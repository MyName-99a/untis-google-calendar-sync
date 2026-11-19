"""
Google login for the calendar (device flow, no browser is needed on the server).

Run once:
    python auth.py            (Docker: docker compose run --rm untis-sync python auth.py)
    python auth.py --force    (replace an existing token.json)

The program shows a code. Enter it at https://www.google.com/device on any device (phone, PC),
sign in with your Google account and confirm. Afterwards token.json is in the data folder.
It renews itself automatically from then on.

The rest of the code only uses get_credentials() and GoogleAuthError.
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
    """The login is missing or invalid. auth.py has to be run (again)."""


# ----------------------------------------------------------------------------------------------------
# For the sync: get valid credentials and renew them automatically when needed
# ----------------------------------------------------------------------------------------------------

def _save_token(creds):
    # write to a temporary file first, then replace (prevents a broken token.json)
    tmp_path = TOKEN_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    os.replace(tmp_path, TOKEN_PATH)


def get_credentials():
    if not os.path.exists(TOKEN_PATH):
        raise GoogleAuthError("token.json is missing. Run 'python auth.py' once (see README).")

    try:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    except (ValueError, OSError) as e:
        raise GoogleAuthError(f"token.json is unusable ({e}). Run 'python auth.py --force'.") from e

    if not creds.valid:
        if not creds.refresh_token:
            raise GoogleAuthError("token.json contains no refresh token. Run 'python auth.py --force'.")
        try:
            creds.refresh(Request())
        except RefreshError as e:
            if getattr(e, "retryable", False):
                raise  # temporary problem at Google, not a case for a new login
            raise GoogleAuthError(
                f"Google login expired or revoked ({e}). Run 'python auth.py --force'."
            ) from e
        _save_token(creds)

    return creds


# ----------------------------------------------------------------------------------------------------
# One-time login (device flow)
# ----------------------------------------------------------------------------------------------------

def _json(response):
    try:
        return response.json()
    except ValueError:
        return {"error": f"HTTP {response.status_code}", "error_description": response.text[:200]}


def _check_calendar(creds):
    # small test whether login, Calendar API and CALENDAR_ID fit together
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    try:
        service = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        calendar = service.calendars().get(calendarId=config.CALENDAR_ID).execute()
        print(f"Connected to calendar: {calendar.get('summary', config.CALENDAR_ID)}", flush=True)
    except HttpError as e:
        print(f"The login is saved, but the calendar '{config.CALENDAR_ID}' cannot be reached: {e}")
        print("→ Check CALENDAR_ID (for the main calendar: primary) and whether the Google Calendar API is enabled.")
        sys.exit(1)


def run_device_flow(force=False):
    config.require("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")

    if os.path.exists(TOKEN_PATH) and not force:
        print(f"{TOKEN_PATH} already exists. Use 'python auth.py --force' to replace it.")
        sys.exit(1)

    # 1. request a code
    response = requests.post(
        DEVICE_CODE_URL,
        data={"client_id": config.GOOGLE_CLIENT_ID, "scope": " ".join(SCOPES)},
        timeout=15,
    )
    data = _json(response)
    if response.status_code != 200 or "device_code" not in data:
        error = data.get("error", "unknown")
        print(f"Google rejected the request: {error} {data.get('error_description', '')}")
        if error == "invalid_client":
            print("→ Check the client ID. The client must be of type 'TVs and Limited Input devices'.")
        elif error == "invalid_scope":
            print("→ Google does not allow calendar access with this flow (please report this to the developer).")
        sys.exit(1)

    url = data.get("verification_url") or data.get("verification_uri") or "https://www.google.com/device"
    print("", flush=True)
    print("1. On any device (phone or PC) open:", flush=True)
    print(f"     {url}", flush=True)
    print("2. Enter this code:", flush=True)
    print(f"     {data['user_code']}", flush=True)
    print("3. Sign in with the Google account that owns the calendar and confirm the access.", flush=True)
    print("   At the warning 'Google hasn't verified this app' click 'Advanced' and then 'Continue'.", flush=True)
    print("   This is normal and expected for your own project.", flush=True)
    print("\nWaiting for your confirmation ...", flush=True)

    # 2. wait until it is confirmed
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
            print(f"Network problem ({e}), trying again ...", flush=True)
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
            print("Access was denied. Start auth.py again if that was a mistake.")
            sys.exit(1)
        print(f"Login error: {error} {result.get('error_description', '')}")
        sys.exit(1)

    if tokens is None:
        print("The code has expired. Start auth.py again.")
        sys.exit(1)

    if SCOPES[0] not in tokens.get("scope", SCOPES[0]):
        print("Calendar access was not granted. Start auth.py again and leave all checkboxes ticked.")
        sys.exit(1)

    if not tokens.get("refresh_token"):
        print("Google did not return a refresh token. Remove the project's access at "
              "https://myaccount.google.com/permissions and start auth.py again.")
        sys.exit(1)

    # 3. save token.json in the format of google-auth
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
    print(f"\nLogin saved: {TOKEN_PATH}", flush=True)
    _check_calendar(creds)


if __name__ == "__main__":
    run_device_flow(force="--force" in sys.argv)