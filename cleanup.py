"""
Removes the events this program created from your calendar (or only the duplicates).

Use it to start over, to remove duplicates after something went wrong, or to remove everything when you
do not want to use the sync any more. Without options it only SHOWS what it would delete (dry run).

    python cleanup.py                          dry run: list the synced events from today on
    python cleanup.py --delete                 delete them (asks for confirmation)
    python cleanup.py --duplicates             dry run: list duplicates only (the same lesson more than once)
    python cleanup.py --duplicates --delete    delete the duplicates and keep one event per lesson
    python cleanup.py --all --delete           delete every event the sync ever created, including past ones

Docker:  docker compose stop
         docker compose run --rm untis-sync python cleanup.py --delete
         docker compose start

Options:
    --weeks N       look N weeks ahead (default 52)
    --past-days N   also look N days into the past
    --all           no time limit at all (past and future), also removes the saved hashes
    --yes           do not ask for confirmation (needed when there is no terminal)

How the events are recognized: future events carry the line "Untis-Sync-ID: <id>" in their description.
When a lesson is over, the sync removes that line and adds a closing line instead ("Lesson over" or the
German "Stunde vergangen"). Past events are recognized by that closing line together with the homework
header, so only events that were created by this program are touched. Nothing else in the calendar is deleted.

Deleting events also removes their entries from the saved hashes, so the next sync can create them again.
Stop the sync before you delete (docker compose stop), otherwise it can recreate events while you clean up.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import auth
import config
import texts

MARKER_RE = re.compile(r"Untis-Sync-ID:\s*(\S+)")
DEFAULT_WEEKS = 52
EXAMPLES_SHOWN = 10
RUNNING_WARNING_MINUTES = 15


# ----------------------------------------------------------------------------------------------------
# Recognizing synced events
# ----------------------------------------------------------------------------------------------------

def sync_id(description):
    """The Untis id from the marker line, or None."""
    match = MARKER_RE.search(description or "")
    return match.group(1) if match else None


def is_finished_sync_event(description):
    """True for an event of a lesson that is over: no marker any more, but the closing line of the sync."""
    text = (description or "").rstrip()
    headers = [texts.TEXTS[lang]['homework_header'] for lang in texts.TEXTS]
    endings = [texts.TEXTS[lang]['lesson_over'] for lang in texts.TEXTS]
    return any(h in text for h in headers) and any(text.endswith(e) for e in endings)


def pick_duplicates(events, hashes):
    """Events that belong to the same lesson more than once. Per lesson one event is kept: the one the saved
    hashes point to, otherwise the one that was updated last. Returns the events to remove."""
    groups = {}
    for event in events:
        lesson_id = sync_id(event.get('description'))
        if lesson_id:
            groups.setdefault(lesson_id, []).append(event)

    remove = []
    for lesson_id, group in groups.items():
        if len(group) < 2:
            continue
        wanted = (hashes.get(lesson_id) or {}).get('google_id')
        keep = next((e for e in group if e.get('id') == wanted), None)
        if keep is None:
            keep = max(group, key=lambda e: e.get('updated', ''))
        remove.extend(e for e in group if e is not keep)
    return remove


def describe(event):
    start = event.get('start', {})
    when = start.get('dateTime') or start.get('date') or "?"
    return f"{when[:16].replace('T', ' ')}  {event.get('summary', '(no title)')}"


# ----------------------------------------------------------------------------------------------------
# Saved hashes
# ----------------------------------------------------------------------------------------------------

def load_hashes():
    try:
        with open(config.HASH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_hashes(hashes):
    tmp_path = config.HASH_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(hashes, f, indent=4)
    os.replace(tmp_path, config.HASH_FILE)


def forget_hashes(deleted_google_ids, everything):
    """Removes the entries of deleted events (or the whole file). Returns a short text for the output."""
    if everything:
        if os.path.exists(config.HASH_FILE):
            os.remove(config.HASH_FILE)
            return f"Removed {config.HASH_FILE}"
        return "No saved hashes found"
    hashes = load_hashes()
    kept = {k: v for k, v in hashes.items() if v.get('google_id') not in deleted_google_ids}
    if len(kept) != len(hashes):
        save_hashes(kept)
    return f"Removed {len(hashes) - len(kept)} entries from the saved hashes"


# ----------------------------------------------------------------------------------------------------
# Google Calendar
# ----------------------------------------------------------------------------------------------------

def list_events(service, time_min, time_max):
    """All events of the calendar in the range (all pages)."""
    page_token = None
    while True:
        params = {'calendarId': config.CALENDAR_ID, 'singleEvents': True, 'maxResults': 2500}
        if time_min:
            params['timeMin'] = time_min
        if time_max:
            params['timeMax'] = time_max
        if page_token:
            params['pageToken'] = page_token
        response = service.events().list(**params).execute()
        yield from response.get('items', [])
        page_token = response.get('nextPageToken')
        if not page_token:
            break


def status_of(error):
    return getattr(error, 'status_code', None) or getattr(getattr(error, 'resp', None), 'status', None)


def delete_events(service, events):
    """Deletes the events. Returns (deleted google ids, failed count)."""
    deleted, failed = set(), 0
    for number, event in enumerate(events, start=1):
        try:
            service.events().delete(calendarId=config.CALENDAR_ID, eventId=event['id']).execute()
            deleted.add(event['id'])
        except HttpError as e:
            if status_of(e) in (404, 410):
                deleted.add(event['id'])  # already gone, so it counts as removed
            else:
                failed += 1
                print(f"  Could not delete {describe(event)}: {e}", file=sys.stderr)
        if number % 25 == 0 or number == len(events):
            print(f"  {number}/{len(events)} processed", flush=True)
        time.sleep(0.3)  # stay below the Google API rate limit
    return deleted, failed


# ----------------------------------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------------------------------

def sync_seems_running():
    """Minutes since the sync loop last wrote its status file, or None if it looks stopped."""
    try:
        with open(os.path.join(config.DATA_DIR, "health.json"), encoding="utf-8") as f:
            updated = datetime.fromisoformat(json.load(f)["updated"])
        age = (datetime.now(updated.tzinfo) - updated).total_seconds() / 60
        return int(age) if age < RUNNING_WARNING_MINUTES else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Remove the events created by the sync from your calendar. Dry run unless --delete is given.")
    parser.add_argument("--delete", action="store_true", help="really delete (without it only a list is shown)")
    parser.add_argument("--duplicates", action="store_true", help="only the duplicates, keep one event per lesson")
    parser.add_argument("--weeks", type=int, default=None, help=f"weeks ahead to look at (default {DEFAULT_WEEKS})")
    parser.add_argument("--past-days", type=int, default=0, help="also look this many days into the past")
    parser.add_argument("--all", action="store_true", help="no time limit: past and future, also resets the saved hashes")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args(argv)
    if args.all and (args.weeks is not None or args.past_days):
        parser.error("--all cannot be combined with --weeks or --past-days")
    if args.all and args.duplicates:
        parser.error("--all cannot be combined with --duplicates")
    if (args.weeks is not None and args.weeks < 1) or args.past_days < 0:
        parser.error("--weeks must be 1 or more and --past-days 0 or more")
    return args


def time_range(args):
    """(timeMin, timeMax) as RFC 3339 with the time zone offset, None = open."""
    if args.all:
        return None, None
    tz = ZoneInfo(config.TZ)
    today = date.today()
    start = datetime.combine(today - timedelta(days=args.past_days), dtime.min, tzinfo=tz)
    end = datetime.combine(today + timedelta(weeks=args.weeks or DEFAULT_WEEKS), dtime.max, tzinfo=tz)
    return start.isoformat(), end.isoformat()


def collect(service, args):
    """Returns the events that would be deleted."""
    time_min, time_max = time_range(args)
    include_past = args.all or args.past_days > 0

    events = list(list_events(service, time_min, time_max))
    if args.duplicates:
        return pick_duplicates(events, load_hashes())

    found = []
    for event in events:
        description = event.get('description')
        if sync_id(description) or (include_past and is_finished_sync_event(description)):
            found.append(event)
    return found


def run(argv):
    args = parse_args(argv)

    try:
        creds = auth.get_credentials()
    except auth.GoogleAuthError as e:
        print(f"Google login problem: {e}")
        return 1
    service = build('calendar', 'v3', credentials=creds, cache_discovery=False)

    try:
        calendar = service.calendars().get(calendarId=config.CALENDAR_ID).execute()
        print(f"Calendar: {calendar.get('summary', config.CALENDAR_ID)}")
        found = collect(service, args)
    except HttpError as e:
        print(f"Google Calendar error: {e}")
        return 1

    time_min, time_max = time_range(args)
    scope = "all time" if args.all else f"{time_min[:10]} to {time_max[:10]}"
    kind = "duplicate events" if args.duplicates else "events created by the sync"
    print(f"Range: {scope}")
    print(f"Found {len(found)} {kind}.")

    if not found:
        return 0

    found.sort(key=lambda e: e.get('start', {}).get('dateTime') or e.get('start', {}).get('date') or "")
    for event in found[:EXAMPLES_SHOWN]:
        print(f"  {describe(event)}")
    if len(found) > EXAMPLES_SHOWN:
        print(f"  ... and {len(found) - EXAMPLES_SHOWN} more")

    if not args.delete:
        print("\nDry run: nothing was deleted. Run it again with --delete to delete these events.")
        return 0

    running = sync_seems_running()
    if running is not None:
        print(f"\nWarning: the sync seems to be running (status updated {running} min ago). Stop it first "
              f"(docker compose stop), otherwise it can recreate events while you clean up.")

    if not args.yes:
        if not sys.stdin.isatty():
            print("\nNo terminal for the confirmation. Run it again with --yes.")
            return 1
        answer = input(f"\nDelete {len(found)} events from this calendar? Type 'yes' to continue: ")
        if answer.strip().lower() != "yes":
            print("Cancelled, nothing was deleted.")
            return 0

    print("Deleting ...")
    deleted, failed = delete_events(service, found)
    print(f"Deleted {len(deleted)} events" + (f", {failed} failed" if failed else "") + ".")

    # With failures keep the hashes of the events that still exist: only forget what is really gone
    print(forget_hashes(deleted, everything=args.all and not failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
