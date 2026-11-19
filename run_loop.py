"""
Startet main3.0.py nach Zeitplan (ersetzt Cron) und meldet dem Docker-Healthcheck, ob alles läuft.

    python run_loop.py                 Schleife starten (das ist der Start des Containers)
    python run_loop.py --plan          zeigt den Zeitplan und die nächsten Läufe, startet nichts
    python run_loop.py --healthcheck   Exit-Code 0 = gesund, 1 = ungesund (für Docker HEALTHCHECK)

Einstellungen (siehe config.py): SYNC_INTERVAL_MINUTES, SYNC_WINDOW, SYNC_TIMES, SYNC_DAYS,
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

# Test-Hilfe: mit SYNC_SCRIPT=fake_sync.py lässt sich die Schleife prüfen, ohne den Kalender anzufassen
SYNC_SCRIPT = os.path.join(str(config.BASE_DIR), os.environ.get("SYNC_SCRIPT", "main3.0.py"))
HEALTH_FILE = os.path.join(config.DATA_DIR, "health.json")

EXIT_HANDLED = 3              # Fehler wurde in main3.0.py bereits per ntfy gemeldet
MIN_PAUSE_SECONDS = 30        # mindestens so lange Pause zwischen zwei Läufen
HEALTH_MAX_FAILURES = 3       # so viele Fehlläufe hintereinander = "ungesund"
HEALTH_GRACE_SECONDS = 300    # Toleranz über den geplanten Zeitpunkt hinaus
CRASH_NOTICE_AFTER = 3        # so viele Abstürze hintereinander = ntfy-Meldung
CRASH_NOTICE_EVERY = 24 * 3600

DAY_NAMES = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


# ----------------------------------------------------------------------------------------------------
# Einstellungen lesen
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
    logging.warning(f"SYNC_DAYS={text!r} nicht verständlich (Beispiele: 1-5 oder 1,3,5, 1 = Montag). Es gelten alle Tage.")
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
        logging.warning(f"SYNC_WINDOW={text!r} nicht verständlich (Beispiel: 06:00-19:00, Anfang vor Ende). Es gilt ganztägig.")
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
            logging.warning(f"SYNC_TIMES: {part!r} übersprungen (Beispiel: 06:30,12:00).")
    return sorted(set(result))


def get_timezone():
    try:
        return ZoneInfo(config.TZ)
    except (ZoneInfoNotFoundError, ValueError):
        raise SystemExit(f"Ungültige Zeitzone TZ={config.TZ!r}. Beispiele: Europe/Berlin, Europe/Vienna, Europe/Zurich.")


# ----------------------------------------------------------------------------------------------------
# Zeitplan
# ----------------------------------------------------------------------------------------------------

class Schedule:
    def __init__(self, tz):
        self.tz = tz
        self.days = parse_days(config.SYNC_DAYS)
        self.window = parse_window(config.SYNC_WINDOW)
        self.times = parse_times(config.SYNC_TIMES)
        self.interval = timedelta(minutes=config.SYNC_INTERVAL_MINUTES)
        if config.SYNC_TIMES and not self.times:
            logging.warning("SYNC_TIMES enthält keine gültige Uhrzeit, es gilt das Intervall.")

    def describe(self):
        days = ", ".join(DAY_NAMES[d] for d in sorted(self.days))
        if self.times:
            text = f"Feste Uhrzeiten {', '.join(t.strftime('%H:%M') for t in self.times)}"
            if config.SYNC_WINDOW:
                text += " (SYNC_WINDOW wird ignoriert)"
        else:
            window = (f"{self.window[0].strftime('%H:%M')}-{self.window[1].strftime('%H:%M')}"
                      if self.window else "ganztägig")
            text = f"Alle {config.SYNC_INTERVAL_MINUTES} Minuten, {window}"
        return f"{text}, Tage: {days}, Zeitzone: {config.TZ}"

    def _next_allowed(self, moment):
        # frühester erlaubter Zeitpunkt ab 'moment' (Wochentag und Zeitfenster)
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
        # nächste feste Uhrzeit nach 'after'
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
        return self._next_time(now) if self.times else self._next_allowed(now)

    def next_run(self, started, finished):
        if self.times:
            return self._next_time(finished)
        earliest = max(started + self.interval, finished + timedelta(seconds=MIN_PAUSE_SECONDS))
        return self._next_allowed(earliest)


def fmt(moment):
    return f"{DAY_NAMES[moment.weekday()]} {moment.strftime('%d.%m. %H:%M')}"


# ----------------------------------------------------------------------------------------------------
# Status-Datei für den Healthcheck
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
        logging.warning(f"Statusdatei konnte nicht geschrieben werden: {e}")


def healthcheck():
    try:
        with open(HEALTH_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        print("Keine Statusdatei: Die Schleife läuft nicht.")
        return 1
    if not data.get("ok", False):
        print(f"Die letzten {data.get('failures')} Läufe sind fehlgeschlagen.")
        return 1
    if time.time() > float(data.get("valid_until", 0)):
        print("Statusdatei ist veraltet: Die Schleife reagiert nicht mehr.")
        return 1
    print("OK")
    return 0


# ----------------------------------------------------------------------------------------------------
# Sync starten
# ----------------------------------------------------------------------------------------------------

def _signal_process(proc, sig):
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, sig)   # ganze Prozessgruppe, damit auch Chromium beendet wird
        else:
            proc.terminate()
    except ProcessLookupError:
        pass


def run_sync(state, timeout_seconds):
    """Startet den Sync als eigenen Prozess. Gibt den Exit-Code zurück (None bei Timeout)."""
    proc = subprocess.Popen(
        [sys.executable, SYNC_SCRIPT],
        cwd=str(config.BASE_DIR),
        start_new_session=hasattr(os, "killpg"),
    )
    state["proc"] = proc
    try:
        return proc.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        logging.error(f"Der Sync hängt (länger als {timeout_seconds // 60} Minuten) und wird beendet.")
        _signal_process(proc, getattr(signal, "SIGKILL", signal.SIGTERM))
        proc.wait()
        return None
    finally:
        state["proc"] = None


def notify_crash(reason):
    try:
        import notifications
        notifications.send_error_notification(
            f"Das Sync-Programm bricht wiederholt ab ({reason}). Bitte das Log prüfen: docker compose logs untis-sync"
        )
    except Exception as e:
        logging.warning(f"Absturz-Meldung konnte nicht gesendet werden: {e}")


# ----------------------------------------------------------------------------------------------------
# Hauptschleife
# ----------------------------------------------------------------------------------------------------

def run_loop():
    tz = get_timezone()
    schedule = Schedule(tz)
    timeout_seconds = config.SYNC_TIMEOUT_MINUTES * 60

    stop = threading.Event()
    state = {"proc": None}

    def handle_stop(signum, frame):
        logging.info("Beenden angefordert ...")
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

    logging.info(f"Zeitplan: {schedule.describe()}")
    now = datetime.now(tz)
    next_time = now if config.SYNC_RUN_ON_START else schedule.first_run(now)
    health(now)

    while not stop.is_set():
        wait_seconds = (next_time - datetime.now(tz)).total_seconds()
        if wait_seconds > 1:
            logging.info(f"Nächster Lauf: {fmt(next_time)}")
            health(next_time)
            if stop.wait(wait_seconds):
                break

        started = datetime.now(tz)
        health(started)
        logging.info("Starte Sync ...")
        code = run_sync(state, timeout_seconds)
        finished = datetime.now(tz)
        if stop.is_set():
            break

        duration = int((finished - started).total_seconds())
        if code == 0:
            failures = crashes = 0
            last_success = finished.isoformat(timespec="seconds")
            logging.info(f"Sync erfolgreich ({duration} s).")
        else:
            failures += 1
            reason = "Timeout" if code is None else f"Exit-Code {code}"
            if code == EXIT_HANDLED:
                logging.warning(f"Sync fehlgeschlagen ({reason}), der Fehler wurde bereits gemeldet.")
            else:
                crashes += 1
                logging.error(f"Sync abgestürzt ({reason}), {crashes}. Mal hintereinander.")
                if crashes >= CRASH_NOTICE_AFTER and time.time() - last_notice >= CRASH_NOTICE_EVERY:
                    notify_crash(reason)
                    last_notice = time.time()

        next_time = schedule.next_run(started, finished)
        health(next_time)

    logging.info("Beendet.")


def show_plan(count=8):
    tz = get_timezone()
    schedule = Schedule(tz)
    now = datetime.now(tz)
    print(f"Zeitplan: {schedule.describe()}")
    print(f"Jetzt: {fmt(now)}\n")
    print("Geplante Läufe (angenommen, jeder Lauf dauert 0 Sekunden):")

    moment = now if config.SYNC_RUN_ON_START else schedule.first_run(now)
    for i in range(count):
        label = "  (beim Start, SYNC_RUN_ON_START)" if i == 0 and config.SYNC_RUN_ON_START else ""
        print(f"  {fmt(moment)}{label}")
        moment = schedule.next_run(moment, moment)


if __name__ == "__main__":
    if "--healthcheck" in sys.argv:
        sys.exit(healthcheck())

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - [Zeitplan] %(message)s")
    if "--plan" in sys.argv:
        show_plan()
        sys.exit(0)
    run_loop()