import datetime
import os.path
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_google_service():
    creds = None
    if os.path.exists('../token.json'):
        creds = Credentials.from_authorized_user_file('../token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('../credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('../token.json', 'w') as token:
            token.write(creds.to_json())
    return build('calendar', 'v3', credentials=creds)


def cleanup_calendar():
    service = get_google_service()

    # Zeitraum festlegen: Ab heute für die nächsten 24 Wochen (sicherheitsweise etwas mehr)
    start_date = datetime.date.today()
    end_date = start_date + datetime.timedelta(weeks=24)

    t_start = datetime.datetime.combine(start_date, datetime.time.min).isoformat() + "Z"
    t_end = datetime.datetime.combine(end_date, datetime.time.max).isoformat() + "Z"

    print(f"Suche nach Untis-Terminen vom {start_date} bis {end_date}...")

    events_result = service.events().list(
        calendarId='primary', timeMin=t_start, timeMax=t_end, singleEvents=True
    ).execute()
    events = events_result.get('items', [])

    deleted_count = 0
    for event in events:
        time.sleep(0.3)
        desc = event.get('description', '')
        # Alles löschen, was nh Untis code enthält
        if "Untis-Sync-ID" in desc:
            print(f"Lösche: {event.get('summary')} am {event.get('start', {}).get('dateTime')}")
            service.events().delete(calendarId='primary', eventId=event['id']).execute()
            time.sleep(0.5)
            deleted_count += 1

    print(f"\nFertig! Es wurden {deleted_count} doppelte/alte Termine gelöscht.")


if __name__ == "__main__":
    cleanup_calendar()