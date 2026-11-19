"""
Starts main3.0.py on a schedule (replaces cron) and tells the Docker healthcheck whether everything runs.

    python run_loop.py                 start the loop (this is what the container runs)
    python run_loop.py --once          one sync right now, then exit (ignores the schedule)
    python run_loop.py --plan          shows the schedule and the next runs, starts nothing
    python run_loop.py --healthcheck   exit code 0 = healthy, 1 = unhealthy (for the Docker HEALTHCHECK)

The schedule can combine an interval (SYNC_INTERVAL_MINUTES, inside SYNC_WINDOW) and fixed times (SYNC_TIMES).
Both are optional. With neither of them nothing runs automatically, use --once.

Settings (see config.py): SYNC_INTERVAL_MINUTES, SYNC_WINDOW, SYNC_TIMES, SYNC_DAYS,
SYNC_RUN_ON_START, SYNC_TIMEOUT_MINUTES, TZ.
"""

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import config

# Test helper: with SYNC_SCRIPT=fake_sync.py the loop can be tested without touching the calendar
SYNC_SCRIPT = os.path.join(str(config.BASE_DIR), os.environ.get("SYNC_SCRIPT", "main3.0.py"))
HEALTH_FILE = os.path.join(config.DATA_DIR, "health.json")

EXIT_HANDLED = 3              # the error was already reported via ntfy in main3.0.py
MIN_PAUSE_SECONDS = 30        # minimum pause between two runs
HEALTH_MAX_FAILURES = 3       # this many failed runs in a row = "unhealthy"
HEALTH_GRACE_SECONDS = 300    # tolerance beyond the planned time
CRASH_NOTICE_AFTER = 3        # this many crashes in a row = ntfy message
CRASH_NOTICE_EVERY = 24 * 3600

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]  # logs are always English


# ----------------------------------------------------------------------------------------------------
# Read settings
# ----------------------------------------------------------------------------------------------------

def parse_time(text):
    return datetime.strptime(text.strip(), "%H:%M").time()


def parse_days(text):
    try:
        days = set()
        for part in text.replace(" ", "").split(","):
            if not part:
                continue
            if "-" in part:
                first, last = (int(x) for x in part.split("-", 1))
            else:
                first = last = int(part)
            if not 1 <= first <= last <= 7:
                raise ValueError(part)
            days.update(range(first - 1, last))
        if days:
            return days
    except ValueError:
        pass
    logging.warning(f"SYNC_DAYS={text!r} not understood (examples: 1-5 or 1,3,5, 1 = Monday). Using all days.")
    return set(range(7))


def parse_window(text):
    if not text:
        return None
    try:
        first, last = text.split("-", 1)
        start, end = parse_time(first), parse_time(last)
        if start >= end:
            raise ValueError(text)
        return start, end
    except ValueError:
        logging.warning(f"SYNC_WINDOW={text!r} not understood (example: 06:00-19:00, start before end). Running all day.")
        return None


def parse_times(text):
    result = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(parse_time(part))
        except ValueError:
            logging.warning(f"SYNC_TIMES: {part!r} skipped (example: 06:30,12:00).")
    return sorted(set(result))


def get_timezone():
    try:
        return ZoneInfo(config.TZ)
    except (ZoneInfoNotFoundError, ValueError):
        raise SystemExit(f"Invalid time zone TZ={config.TZ!r}. Examples: Europe/Berlin, Europe/Vienna, Europe/Zurich.")


# ----------------------------------------------------------------------------------------------------
# Schedule
# ----------------------------------------------------------------------------------------------------

class Schedule:
    def __init__(self, tz):
        self.tz = tz
        self.days = parse_days(config.SYNC_DAYS)
        self.window = parse_window(config.SYNC_WINDOW)
        self.times = parse_times(config.SYNC_TIMES)
        self.interval = timedelta(minutes=config.SYNC_INTERVAL_MINUTES) if config.SYNC_INTERVAL_MINUTES > 0 else None
        if config.SYNC_TIMES and not self.times:
            logging.warning("SYNC_TIMES contains no valid time, ignoring it.")
        if self.window and not self.interval:
            logging.warning("SYNC_WINDOW has no effect without SYNC_INTERVAL_MINUTES (the window only applies to the interval).")

    def describe(self):
        days = ", ".join(DAY_NAMES[d] for d in sorted(self.days))
        parts = []
        if self.interval:
            window = (f"{self.window[0].strftime('%H:%M')}-{self.window[1].strftime('%H:%M')}"
                      if self.window else "all day")
            parts.append(f"every {config.SYNC_INTERVAL_MINUTES} minutes, {window}")
        if self.times:
            parts.append(f"fixed times {', '.join(t.strftime('%H:%M') for t in self.times)}")
        if not parts:
            return "no automatic runs (use --once for a manual run)"
        return f"{' + '.join(parts)}, days: {days}, time zone: {config.TZ}"

    def _next_allowed(self, moment):
        # earliest allowed time from 'moment' on (weekday and time window)
        for _ in range(9):
            if moment.weekday() in self.days:
                if not self.window:
                    return moment
                start = moment.replace(hour=self.window[0].hour, minute=self.window[0].minute, second=0, microsecond=0)
                end = moment.replace(hour=self.window[1].hour, minute=self.window[1].minute, second=59, microsecond=999999)
                if moment < start:
                    return start
                if moment <= end:
                    return moment
            moment = (moment + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return moment

    def _next_time(self, after):
        # next fixed time after 'after'
        for offset in range(9):
            day = (after + timedelta(days=offset)).date()
            if day.weekday() not in self.days:
                continue
            for t in self.times:
                candidate = datetime.combine(day, t, tzinfo=self.tz)
                if candidate > after:
                    return candidate
        return after + timedelta(days=1)

    def first_run(self, now):
        candidates = []
        if self.interval:
            candidates.append(self._next_allowed(now))
        if self.times:
            candidates.append(self._next_time(now))
        return min(candidates) if candidates else None

    def next_run(self, started, finished):
        # the earlier of "next interval run" and "next fixed time", None if nothing is scheduled
        candidates = []
        if self.interval:
            earliest = max(started + self.interval, finished + timedelta(seconds=MIN_PAUSE_SECONDS))
            candidates.append(self._next_allowed(earliest))
        if self.times:
            candidates.append(self._next_time(finished))
        return min(candidates) if candidates else None


def fmt(moment):
    return f"{DAY_NAMES[moment.weekday()]} {moment.strftime('%d %b %H:%M')}"


# ----------------------------------------------------------------------------------------------------
# Status file for the healthcheck
# ----------------------------------------------------------------------------------------------------

def write_health(ok, valid_until, failures, last_success, tz):
    data = {
        "ok": ok,
        "valid_until": valid_until.timestamp(),
        "failures": failures,
        "last_success": last_success,
        "updated": datetime.now(tz).isoformat(timespec="seconds"),
    }
    try:
        tmp_path = HEALTH_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_path, HEALTH_FILE)
    except OSError as e:
        logging.warning(f"Status file could not be written: {e}")


def healthcheck():
    try:
        with open(HEALTH_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        print("No status file: the loop is not running.")
        return 1
    if not data.get("ok", False):
        print(f"The last {data.get('failures')} runs failed.")
        return 1
    if time.time() > float(data.get("valid_until", 0)):
        print("Status file is outdated: the loop is not responding.")
        return 1
    print("OK")
    return 0


# ----------------------------------------------------------------------------------------------------
# Start the sync
# ----------------------------------------------------------------------------------------------------

def _signal_process(proc, sig):
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, sig)   # whole process group, so that Chromium is stopped too
        else:
            proc.terminate()
    except ProcessLookupError:
        pass


def run_sync(state, timeout_seconds):
    """Starts the sync as its own process. Returns the exit code (None on timeout)."""
    proc = subprocess.Popen(
        [sys.executable, SYNC_SCRIPT],
        cwd=str(config.BASE_DIR),
        start_new_session=hasattr(os, "killpg"),
    )
    state["proc"] = proc
    try:
        return proc.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        logging.error(f"The sync is stuck (longer than {timeout_seconds // 60} minutes) and is being stopped.")
        _signal_process(proc, getattr(signal, "SIGKILL", signal.SIGTERM))
        proc.wait()
        return None
    finally:
        state["proc"] = None


def notify_crash(reason):
    try:
        import notifications
        from texts import t
        notifications.send_error_notification(t('crash_notice', reason=reason))
    except Exception as e:
        logging.warning(f"Crash notification could not be sent: {e}")


# ----------------------------------------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------------------------------------

def run_loop():
    tz = get_timezone()
    schedule = Schedule(tz)
    timeout_seconds = config.SYNC_TIMEOUT_MINUTES * 60

    stop = threading.Event()
    state = {"proc": None}

    def handle_stop(signum, frame):
        logging.info("Stop requested ...")
        stop.set()
        proc = state["proc"]
        if proc is not None and proc.poll() is None:
            _signal_process(proc, signal.SIGTERM)

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    failures = 0
    crashes = 0
    last_success = None
    last_notice = 0.0

    def valid_until(moment):
        return moment + timedelta(seconds=timeout_seconds + HEALTH_GRACE_SECONDS)

    def health(moment):
        write_health(failures < HEALTH_MAX_FAILURES, valid_until(moment), failures, last_success, tz)

    logging.info(f"Schedule: {schedule.describe()}")
    now = datetime.now(tz)
    next_time = now if config.SYNC_RUN_ON_START else schedule.first_run(now)
    idle_logged = False
    health(now)

    while not stop.is_set():
        if next_time is None:
            # nothing scheduled: stay alive (and healthy), a manual run is possible with --once
            if not idle_logged:
                logging.info("No automatic runs planned. Waiting (a manual run: python run_loop.py --once).")
                idle_logged = True
            health(datetime.now(tz) + timedelta(minutes=10))
            if stop.wait(300):
                break
            continue

        wait_seconds = (next_time - datetime.now(tz)).total_seconds()
        if wait_seconds > 1:
            logging.info(f"Next run: {fmt(next_time)}")
            health(next_time)
            if stop.wait(wait_seconds):
                break

        started = datetime.now(tz)
        health(started)
        logging.info("Starting sync ...")
        code = run_sync(state, timeout_seconds)
        finished = datetime.now(tz)
        if stop.is_set():
            break

        duration = int((finished - started).total_seconds())
        if code == 0:
            failures = crashes = 0
            last_success = finished.isoformat(timespec="seconds")
            logging.info(f"Sync successful ({duration} s).")
        else:
            failures += 1
            reason = "timeout" if code is None else f"exit code {code}"
            if code == EXIT_HANDLED:
                logging.warning(f"Sync failed ({reason}), the error was already reported.")
            else:
                crashes += 1
                logging.error(f"Sync crashed ({reason}), crash number {crashes} in a row.")
                if crashes >= CRASH_NOTICE_AFTER and time.time() - last_notice >= CRASH_NOTICE_EVERY:
                    notify_crash(reason)
                    last_notice = time.time()

        next_time = schedule.next_run(started, finished)
        health(next_time or finished + timedelta(minutes=10))

    logging.info("Stopped.")


def show_plan(count=8):
    tz = get_timezone()
    schedule = Schedule(tz)
    now = datetime.now(tz)
    print(f"Schedule: {schedule.describe()}")
    print(f"Now: {fmt(now)}\n")
    print("Planned runs (assuming every run takes 0 seconds):")

    moment = now if config.SYNC_RUN_ON_START else schedule.first_run(now)
    for i in range(count):
        if moment is None:
            print("  (no further automatic runs, use --once for a manual run)")
            break
        label = "  (on start, SYNC_RUN_ON_START)" if i == 0 and config.SYNC_RUN_ON_START else ""
        print(f"  {fmt(moment)}{label}")
        moment = schedule.next_run(moment, moment)


def run_once():
    """One sync right now, independent of the schedule. Returns the exit code of the sync (0 = success)."""
    state = {"proc": None}

    def handle_stop(signum, frame):
        proc = state["proc"]
        if proc is not None and proc.poll() is None:
            _signal_process(proc, signal.SIGTERM)

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    logging.info("Starting sync ...")
    started = time.time()
    code = run_sync(state, config.SYNC_TIMEOUT_MINUTES * 60)
    duration = int(time.time() - started)
    if code == 0:
        logging.info(f"Sync successful ({duration} s).")
        return 0
    reason = "timeout" if code is None else f"exit code {code}"
    logging.error(f"Sync failed ({reason}).")
    return code if code and code > 0 else 1


if __name__ == "__main__":
    if "--healthcheck" in sys.argv:
        sys.exit(healthcheck())

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - [Schedule] %(message)s")
    if "--plan" in sys.argv:
        show_plan()
        sys.exit(0)
    if "--once" in sys.argv:
        sys.exit(run_once())
    run_loop()