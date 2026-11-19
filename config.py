"""
Zentrale Konfiguration.

Alle Einstellungen kommen aus Umgebungsvariablen. Lokal werden sie aus der Datei .env neben dieser
Datei gelesen (Vorlage: .env.example), im Docker-Container kommen sie aus der compose.yaml bzw. .env.
Echte Umgebungsvariablen haben immer Vorrang vor der .env-Datei.
"""

import json
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv ist optional, in Docker reichen echte Umgebungsvariablen
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent

if load_dotenv:
    load_dotenv(BASE_DIR / ".env")


# ----------------------------------------------------------------------------------------------------
# Hilfsfunktionen
# ----------------------------------------------------------------------------------------------------

def _warn(message):
    print(f"[config] Warnung: {message}", file=sys.stderr)


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
        _warn(f"{name}={raw!r} ist keine Zahl, nehme {default}.")
        return default
    if not minimum <= value <= maximum:
        _warn(f"{name}={value} liegt außerhalb von {minimum}-{maximum}, nehme {default}.")
        return default
    return value


def _clean_server(value):
    # "https://schule.webuntis.com/" -> "schule.webuntis.com"
    value = value.strip()
    for prefix in ("https://", "http://"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
    return value.strip("/")


def require(*names):
    """Bricht mit einer verständlichen Meldung ab, wenn Pflicht-Einstellungen fehlen."""
    missing = [name for name in names if not globals().get(name)]
    if missing:
        raise SystemExit(
            "Fehlende Einstellung(en): " + ", ".join(missing) + "\n"
            "Trage sie in die Datei .env ein (Vorlage: .env.example) oder setze sie als Umgebungsvariable."
        )


# ----------------------------------------------------------------------------------------------------
# Ordner für alle Daten (Token, Hashes, Log, fach_map.json). Ohne Angabe: der Projektordner.
# ----------------------------------------------------------------------------------------------------

DATA_DIR = str(Path(_get("DATA_DIR", str(BASE_DIR))).expanduser())
os.makedirs(DATA_DIR, exist_ok=True)


# ----------------------------------------------------------------------------------------------------
# Zeitzone: gilt für Zeitstempel im Log, "heute" im Sync und die Kalendereinträge bei Google.
# Sollte die Zeitzone der Schule sein.
# ----------------------------------------------------------------------------------------------------

TZ = _get("TZ", "Europe/Berlin")
os.environ["TZ"] = TZ
if hasattr(time, "tzset"):
    time.tzset()
try:
    ZoneInfo(TZ)
except (ZoneInfoNotFoundError, ValueError):
    _warn(f"Zeitzone {TZ!r} nicht gefunden. Beispiele für gültige Namen: Europe/Berlin, Europe/Vienna, Europe/Zurich.")


# ----------------------------------------------------------------------------------------------------
# WebUntis
# ----------------------------------------------------------------------------------------------------

UNTIS_SERVER = _clean_server(_get("UNTIS_SERVER"))
UNTIS_USER = _get("UNTIS_USER")
UNTIS_PASSWORD = os.environ.get("UNTIS_PASSWORD", "")  # bewusst nicht gekürzt, Passwörter dürfen Leerzeichen enthalten


# ----------------------------------------------------------------------------------------------------
# Kalender und Zeitraum
# ----------------------------------------------------------------------------------------------------

CALENDAR_ID = _get("CALENDAR_ID", "primary")
SYNC_WEEKS_AHEAD = _get_int("SYNC_WEEKS_AHEAD", 12, minimum=1, maximum=52)

# ----------------------------------------------------------------------------------------------------
# Google (OAuth-Client vom Typ "TVs und Geräte mit eingeschränkter Eingabe", siehe README)
# ----------------------------------------------------------------------------------------------------

GOOGLE_CLIENT_ID = _get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _get("GOOGLE_CLIENT_SECRET")

# ----------------------------------------------------------------------------------------------------
# Zeitsteuerung (wird von run_loop.py ausgewertet)
#
#   SYNC_INTERVAL_MINUTES  Abstand zwischen zwei Läufen (gerechnet vom Start des letzten Laufs)
#   SYNC_WINDOW            nur in diesem Zeitfenster, z. B. 06:00-19:00 (leer = ganztägig)
#   SYNC_TIMES             nur zu festen Uhrzeiten, z. B. 06:30,12:00,17:30 (hat Vorrang, dann werden
#                          Intervall und Zeitfenster ignoriert)
#   SYNC_DAYS              Wochentage, 1 = Montag ... 7 = Sonntag, z. B. 1-5 oder 1,3,5
#   SYNC_RUN_ON_START      beim Start des Containers einmal sofort ausführen
#   SYNC_TIMEOUT_MINUTES   ein hängender Lauf wird nach dieser Zeit beendet
# ----------------------------------------------------------------------------------------------------

SYNC_INTERVAL_MINUTES = _get_int("SYNC_INTERVAL_MINUTES", 4, minimum=1, maximum=1440)
SYNC_WINDOW = _get("SYNC_WINDOW")
SYNC_TIMES = _get("SYNC_TIMES")
SYNC_DAYS = _get("SYNC_DAYS", "1-7")
SYNC_RUN_ON_START = _get("SYNC_RUN_ON_START", "true").lower() not in ("0", "false", "no", "nein")
SYNC_TIMEOUT_MINUTES = _get_int("SYNC_TIMEOUT_MINUTES", 15, minimum=1, maximum=240)


# ----------------------------------------------------------------------------------------------------
# Benachrichtigungen (ntfy). Ohne NTFY_TOPIC werden keine Meldungen verschickt.
# ----------------------------------------------------------------------------------------------------

NTFY_SERVER = _get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = _get("NTFY_TOPIC")
NTFY_URL = f"{NTFY_SERVER}/{NTFY_TOPIC}" if NTFY_TOPIC else None


# ----------------------------------------------------------------------------------------------------
# Fachnamen: fach_map.json im Datenordner überschreibt/ergänzt die Standard-Zuordnung aus main3.0.py.
#
#   Beispiel fach_map.json:  {"M": "Mathe", "E-LK": "Englisch Leistungskurs"}
#
# Eigene Einträge werden zuerst geprüft (der erste passende Anfang gewinnt, daher lange Kürzel vor
# kurzen). FACH_MAP_USE_DEFAULTS=false nutzt NUR die eigene Datei und ignoriert die Standard-Zuordnung.
# ----------------------------------------------------------------------------------------------------

FACH_MAP_FILE = os.path.join(DATA_DIR, "fach_map.json")
FACH_MAP_USE_DEFAULTS = _get("FACH_MAP_USE_DEFAULTS", "true").lower() not in ("0", "false", "no", "nein")


def load_fach_map(default_map):
    custom = {}
    if os.path.exists(FACH_MAP_FILE):
        try:
            with open(FACH_MAP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                custom = {str(k): str(v) for k, v in data.items() if not str(k).startswith("_")}
            else:
                _warn(f"{FACH_MAP_FILE} muss ein JSON-Objekt sein, z. B. {{\"M\": \"Mathematik\"}}.")
        except (OSError, ValueError) as e:
            _warn(f"{FACH_MAP_FILE} konnte nicht gelesen werden: {e}")

    if not FACH_MAP_USE_DEFAULTS:
        if not custom:
            _warn("FACH_MAP_USE_DEFAULTS=false, aber fach_map.json ist leer oder fehlt. Es werden Kürzel angezeigt.")
        return custom

    merged = dict(custom)  # eigene Einträge zuerst
    for key, value in default_map.items():
        merged.setdefault(key, value)
    return merged