"""
Central configuration.

All settings come from environment variables. Locally they are read from the .env file next to this file
(template: .env.example), in the Docker container they come from compose.yaml or .env.
Real environment variables always win over the .env file.
"""

import json
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional, real environment variables are enough in Docker
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent

if load_dotenv:
    load_dotenv(BASE_DIR / ".env")

FALSE_VALUES = ("0", "false", "no", "off")


# ----------------------------------------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------------------------------------

def _warn(message):
    print(f"[config] Warning: {message}", file=sys.stderr)


def _get(name, default=""):
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _get_int(name, default, minimum=1, maximum=1000):
    raw = _get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        _warn(f"{name}={raw!r} is not a number, using {default}.")
        return default
    if not minimum <= value <= maximum:
        _warn(f"{name}={value} is outside {minimum}-{maximum}, using {default}.")
        return default
    return value


def _get_bool(name, default=True):
    raw = _get(name)
    if not raw:
        return default
    return raw.lower() not in FALSE_VALUES


def _clean_server(value):
    # "https://school.webuntis.com/" -> "school.webuntis.com"
    value = value.strip()
    for prefix in ("https://", "http://"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
    return value.strip("/")


def require(*names):
    """Stops with a clear message if required settings are missing."""
    missing = [name for name in names if not globals().get(name)]
    if missing:
        raise SystemExit(
            "Missing setting(s): " + ", ".join(missing) + "\n"
            "Add them to the .env file (template: .env.example) or set them as environment variables."
        )


# ----------------------------------------------------------------------------------------------------
# Folder for all data (token, hashes, log, fach_map.json). Without a value: the project folder.
# ----------------------------------------------------------------------------------------------------

DATA_DIR = str(Path(_get("DATA_DIR", str(BASE_DIR))).expanduser())
os.makedirs(DATA_DIR, exist_ok=True)

# Saved hashes of the synced events. The German file name is kept, so that existing installations keep working.
HASH_FILE = os.path.join(DATA_DIR, "gespeicherte_hashes.json")


# ----------------------------------------------------------------------------------------------------
# Language of everything the calendar and the push notifications show (texts.py).
# Logs and console output are always English.
# ----------------------------------------------------------------------------------------------------

SUPPORTED_LANGUAGES = ("en", "de")

LANGUAGE = _get("LANGUAGE", "en").lower()
if LANGUAGE not in SUPPORTED_LANGUAGES:
    _warn(f"LANGUAGE={LANGUAGE!r} is not supported (use one of: {', '.join(SUPPORTED_LANGUAGES)}), using 'en'.")
    LANGUAGE = "en"


# ----------------------------------------------------------------------------------------------------
# Time zone: used for timestamps in the log, "today" in the sync and the calendar events at Google.
# Should be the time zone of the school.
# ----------------------------------------------------------------------------------------------------

TZ = _get("TZ", "Europe/Berlin")
os.environ["TZ"] = TZ
if hasattr(time, "tzset"):
    time.tzset()
try:
    ZoneInfo(TZ)
except (ZoneInfoNotFoundError, ValueError):
    _warn(f"Time zone {TZ!r} not found. Examples of valid names: Europe/Berlin, Europe/Vienna, Europe/Zurich.")


# ----------------------------------------------------------------------------------------------------
# WebUntis
# ----------------------------------------------------------------------------------------------------

UNTIS_SERVER = _clean_server(_get("UNTIS_SERVER"))
UNTIS_USER = _get("UNTIS_USER")
UNTIS_PASSWORD = os.environ.get("UNTIS_PASSWORD", "")  # deliberately not stripped, passwords may contain spaces


# ----------------------------------------------------------------------------------------------------
# Calendar and time range
# ----------------------------------------------------------------------------------------------------

CALENDAR_ID = _get("CALENDAR_ID", "primary")
SYNC_WEEKS_AHEAD = _get_int("SYNC_WEEKS_AHEAD", 12, minimum=1, maximum=52)

# ----------------------------------------------------------------------------------------------------
# Google (OAuth client of type "TVs and Limited Input devices", see README)
# ----------------------------------------------------------------------------------------------------

GOOGLE_CLIENT_ID = _get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _get("GOOGLE_CLIENT_SECRET")

# ----------------------------------------------------------------------------------------------------
# Schedule (evaluated by run_loop.py)
#
#   SYNC_INTERVAL_MINUTES  time between two runs (counted from the start of the last run), 0 = no interval.
#                          Default: 5, but 0 if SYNC_TIMES is set (so SYNC_TIMES alone means "only at these times")
#   SYNC_WINDOW            the interval runs only inside this window, e.g. 06:00-19:00 (empty = all day)
#   SYNC_TIMES             additional runs at fixed times, e.g. 21:00,21:30,22:00. They run even outside the
#                          window and can be combined with the interval
#   SYNC_DAYS              weekdays for interval and fixed times, 1 = Monday ... 7 = Sunday, e.g. 1-5 or 1,3,5
#   SYNC_RUN_ON_START      run once immediately when the container starts
#   SYNC_TIMEOUT_MINUTES   a hanging run is stopped after this time
#
# Without interval and without fixed times nothing runs automatically (only on start, if SYNC_RUN_ON_START
# is true). A single manual run: python run_loop.py --once
# ----------------------------------------------------------------------------------------------------

SYNC_WINDOW = _get("SYNC_WINDOW")
SYNC_TIMES = _get("SYNC_TIMES")
SYNC_INTERVAL_MINUTES = _get_int("SYNC_INTERVAL_MINUTES", 0 if SYNC_TIMES else 5, minimum=0, maximum=1440)
SYNC_DAYS = _get("SYNC_DAYS", "1-7")
SYNC_RUN_ON_START = _get_bool("SYNC_RUN_ON_START", True)
SYNC_TIMEOUT_MINUTES = _get_int("SYNC_TIMEOUT_MINUTES", 15, minimum=1, maximum=240)


# ----------------------------------------------------------------------------------------------------
# Notifications (ntfy). Without NTFY_TOPIC no messages are sent.
# ----------------------------------------------------------------------------------------------------

NTFY_SERVER = _get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = _get("NTFY_TOPIC")
NTFY_URL = f"{NTFY_SERVER}/{NTFY_TOPIC}" if NTFY_TOPIC else None


# ----------------------------------------------------------------------------------------------------
# Cancelled lessons: besides the status CANCELLED, a lesson also counts as cancelled when one of its info
# texts (info, text, notes, substitution) contains one of these phrases (comma separated, not case
# sensitive). Some schools do not mark a cancelled lesson as cancelled but write a phrase like this
# into the substitution text. The default is the phrase of the author's (German) school.
# ----------------------------------------------------------------------------------------------------

CANCEL_KEYWORDS = [
    keyword.strip().lower()
    for keyword in _get("CANCEL_KEYWORDS", "eigenverantwortliches arbeiten").split(",")
    if keyword.strip()
]


# ----------------------------------------------------------------------------------------------------
# Subject names: fach_map.json in the data folder overrides/extends the built-in table from main3.0.py
# (the built-in table is for one German school).
#
#   Example fach_map.json:  {"M": "Maths", "E-LK": "English advanced course"}
#
# Your own entries are checked first (the first matching beginning wins, so list long codes before short
# ones). FACH_MAP_USE_DEFAULTS=false uses ONLY your own file and ignores the built-in table. Do this if your
# school is not the one the built-in table was made for, otherwise a code like "M" or "E" could be turned
# into a German name.
# ----------------------------------------------------------------------------------------------------

FACH_MAP_FILE = os.path.join(DATA_DIR, "fach_map.json")
FACH_MAP_USE_DEFAULTS = _get_bool("FACH_MAP_USE_DEFAULTS", True)


def load_fach_map(default_map):
    custom = {}
    if os.path.exists(FACH_MAP_FILE):
        try:
            with open(FACH_MAP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                custom = {str(k): str(v) for k, v in data.items() if not str(k).startswith("_")}
            else:
                _warn(f"{FACH_MAP_FILE} must be a JSON object, e.g. {{\"M\": \"Maths\"}}.")
        except (OSError, ValueError) as e:
            _warn(f"{FACH_MAP_FILE} could not be read: {e}")

    if not FACH_MAP_USE_DEFAULTS:
        if not custom:
            _warn("FACH_MAP_USE_DEFAULTS=false, but fach_map.json is empty or missing. Subject codes will be shown as they are.")
        return custom

    merged = dict(custom)  # own entries first
    for key, value in default_map.items():
        merged.setdefault(key, value)
    return merged
