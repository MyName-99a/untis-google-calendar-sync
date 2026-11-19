"""
Google-Anmeldung für den Kalender (Device-Flow, es wird kein Browser auf dem Server gebraucht).

Einmalig ausführen:
    python auth.py            (Docker: docker compose run --rm untis-sync python auth.py)
    python auth.py --force    (eine vorhandene token.json ersetzen)

Das Programm zeigt einen Code an. Den gibst du auf https://www.google.com/device an einem beliebigen
Gerät ein (Handy, PC), meldest dich mit deinem Google-Konto an und bestätigst. Danach liegt token.json
im Datenordner. Es erneuert sich ab dann automatisch.

Der restliche Code nutzt nur get_credentials() und GoogleAuthError.
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

import config

SCOPES = ['https://www.googleapis.com/auth/calendar']
DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
TOKEN_PATH = os.path.join(config.DATA_DIR, 'token.json')


class GoogleAuthError(Exception):
    """Die Anmeldung fehlt oder ist ungültig. Dann muss auth.py (erneut) ausgeführt werden."""


# ----------------------------------------------------------------------------------------------------
# Für den Sync: gültige Zugangsdaten holen und bei Bedarf automatisch erneuern
# ----------------------------------------------------------------------------------------------------

def _save_token(creds):
    # erst in eine temporäre Datei schreiben, dann ersetzen (verhindert eine kaputte token.json)
    tmp_path = TOKEN_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    os.replace(tmp_path, TOKEN_PATH)


def get_credentials():
    if not os.path.exists(TOKEN_PATH):
        raise GoogleAuthError("token.json fehlt. Einmalig 'python auth.py' ausführen (siehe README).")

    try:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    except (ValueError, OSError) as e:
        raise GoogleAuthError(f"token.json ist unbrauchbar ({e}). 'python auth.py --force' ausführen.") from e

    if not creds.valid:
        if not creds.refresh_token:
            raise GoogleAuthError("token.json enthält keinen Refresh-Token. 'python auth.py --force' ausführen.")
        try:
            creds.refresh(Request())
        except RefreshError as e:
            if getattr(e, "retryable", False):
                raise  # vorübergehendes Problem bei Google, das ist kein Fall für eine neue Anmeldung
            raise GoogleAuthError(
                f"Google-Anmeldung abgelaufen oder widerrufen ({e}). 'python auth.py --force' ausführen."
            ) from e
        _save_token(creds)

    return creds


# ----------------------------------------------------------------------------------------------------
# Einmalige Anmeldung (Device-Flow)
# ----------------------------------------------------------------------------------------------------

def _json(response):
    try:
        return response.json()
    except ValueError:
        return {"error": f"HTTP {response.status_code}", "error_description": response.text[:200]}


def _check_calendar(creds):
    # kleiner Test, ob Anmeldung, Kalender-API und CALENDAR_ID zusammenpassen
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    try:
        service = build('calendar', 'v3', credentials=creds)
        calendar = service.calendars().get(calendarId=config.CALENDAR_ID).execute()
        print(f"Verbunden mit Kalender: {calendar.get('summary', config.CALENDAR_ID)}", flush=True)
    except HttpError as e:
        print(f"Die Anmeldung ist gespeichert, aber der Kalender '{config.CALENDAR_ID}' ist nicht erreichbar: {e}")
        print("→ CALENDAR_ID prüfen (für den Hauptkalender: primary) und ob die Google Calendar API aktiviert ist.")
        sys.exit(1)


def run_device_flow(force=False):
    config.require("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")

    if os.path.exists(TOKEN_PATH) and not force:
        print(f"{TOKEN_PATH} existiert bereits. Mit 'python auth.py --force' wird sie ersetzt.")
        sys.exit(1)

    # 1. Code anfordern
    response = requests.post(
        DEVICE_CODE_URL,
        data={"client_id": config.GOOGLE_CLIENT_ID, "scope": " ".join(SCOPES)},
        timeout=15,
    )
    data = _json(response)
    if response.status_code != 200 or "device_code" not in data:
        error = data.get("error", "unbekannt")
        print(f"Google hat die Anfrage abgelehnt: {error} {data.get('error_description', '')}")
        if error == "invalid_client":
            print("→ Client-ID prüfen. Der Client muss vom Typ 'TVs und Geräte mit eingeschränkter Eingabe' sein.")
        elif error == "invalid_scope":
            print("→ Google erlaubt den Kalender-Zugriff in diesem Verfahren nicht (bitte melde das dem Entwickler).")
        sys.exit(1)

    url = data.get("verification_url") or data.get("verification_uri") or "https://www.google.com/device"
    print("", flush=True)
    print("1. Öffne auf einem beliebigen Gerät (Handy oder PC):", flush=True)
    print(f"     {url}", flush=True)
    print("2. Gib diesen Code ein:", flush=True)
    print(f"     {data['user_code']}", flush=True)
    print("3. Melde dich mit dem Google-Konto an, in dem der Kalender liegt, und bestätige den Zugriff.", flush=True)
    print("   Bei der Warnung 'Google hat diese App nicht überprüft' auf 'Erweitert' und dann 'Weiter' klicken.", flush=True)
    print("   Das ist bei einem eigenen Projekt normal und gewollt.", flush=True)
    print("\nWarte auf deine Bestätigung ...", flush=True)

    # 2. warten, bis bestätigt wurde
    interval = int(data.get("interval", 5))
    deadline = time.time() + int(data.get("expires_in", 1800))
    tokens = None

    while time.time() < deadline:
        time.sleep(interval)
        try:
            poll = requests.post(
                TOKEN_URL,
                data={
                    "client_id": config.GOOGLE_CLIENT_ID,
                    "client_secret": config.GOOGLE_CLIENT_SECRET,
                    "device_code": data["device_code"],
                    "grant_type": DEVICE_GRANT_TYPE,
                },
                timeout=15,
            )
        except requests.RequestException as e:
            print(f"Netzwerkproblem ({e}), versuche es weiter ...", flush=True)
            continue

        result = _json(poll)
        if "access_token" in result:
            tokens = result
            break

        error = result.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error == "access_denied":
            print("Der Zugriff wurde abgelehnt. Starte auth.py neu, falls das ein Versehen war.")
            sys.exit(1)
        print(f"Fehler bei der Anmeldung: {error} {result.get('error_description', '')}")
        sys.exit(1)

    if tokens is None:
        print("Der Code ist abgelaufen. Starte auth.py neu.")
        sys.exit(1)

    if SCOPES[0] not in tokens.get("scope", SCOPES[0]):
        print("Der Kalender-Zugriff wurde nicht erteilt. Starte auth.py neu und lasse alle Häkchen gesetzt.")
        sys.exit(1)

    if not tokens.get("refresh_token"):
        print("Google hat keinen Refresh-Token geliefert. Entziehe dem Projekt unter "
              "https://myaccount.google.com/permissions den Zugriff und starte auth.py neu.")
        sys.exit(1)

    # 3. token.json im Format von google-auth speichern
    expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=int(tokens.get("expires_in", 3600)) - 60)
    creds = Credentials(
        token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_uri=TOKEN_URL,
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
        expiry=expiry,
    )
    _save_token(creds)
    print(f"\nAnmeldung gespeichert: {TOKEN_PATH}", flush=True)
    _check_calendar(creds)


if __name__ == "__main__":
    run_device_flow(force="--force" in sys.argv)