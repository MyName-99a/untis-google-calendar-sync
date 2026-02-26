import os
import json
import hashlib
import logging
import time
from datetime import datetime, date, timedelta

# Google API importe
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Own files
import get_week_and_lesson_information as untis_api
import notifications

# https://emojidb.org/house-emojis?utm_source=user_search - Emojis sind von hier gute seite eig

# pfade und so
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HASH_FILE = os.path.join(BASE_DIR, 'gespeicherte_hashes.json')
TOKEN_PATH = os.path.join(BASE_DIR, 'token.json')
CREDS_PATH = os.path.join(BASE_DIR, 'credentials.json')
LOG_FILE = os.path.join(BASE_DIR, 'sync_log.txt')

SCOPES = ['https://www.googleapis.com/auth/calendar']

FACH_MAP = {
    # LKs
    'BI-LK': 'Biologie LK',
    'CH-LK': 'Chemie LK',
    'EK-LK': 'Erdkunde LK',
    'GE-LK': 'Geschichte LK',
    'KU-LK': 'Kunst LK',
    'PA-LK': 'Pädagogik LK',
    'PH-LK': 'Physik LK',
    'SP-LK': 'Sport LK',
    'SW-LK': 'Sozialwissenschaften LK',

    # LKs kurze Kürzel
    'D-LK': 'Deutsch LK',
    'E-LK': 'Englisch LK',
    'S-LK': 'Spanisch LK',

    # Lange Kürzel
    'EKE': 'Erkunde Englisch',
    'GEE': 'Geschichte Englisch',
    'PJK': 'Projektkurs',

    # Grundkurse
    'BI': 'Biologie',
    'CH': 'Chemie',
    'ER': 'Evangelische Religion',
    'IF': 'Informatik',
    'K0': 'Japanisch',
    'KR': 'Katholische Religion',
    'KU': 'Kunst',
    'MU': 'Musik',
    'PH': 'Physik',
    'PL': 'Praktische Philosophie',
    'SP': 'Sport',
    'SW': 'Sozialwissenschaften',
    'VO': 'Vokalpraxis',
    'GK': 'Gemeinschaftskunde',
    'REV': 'Evangelische Religion',
    # Grundkurse einzelne Kürzel
    'D': 'Deutsch',
    'F': 'Französisch',
    'M': 'Mathematik',
    'S': 'Spanisch',
    'G': 'Geschichte',
    'L': 'Latein',
    'E'; 'Englisch'



 
    # '': '', '': '', '': '',
    # '': '', '': '', '': '',
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)


def log_separator():
    separator = "-" * 50
    logging.info("Ende des Syncs!\n\n" + separator + "\n")


# helpers

def strike(text):
    # wandelt Text in durchgestrichenen Unicode-Text
    return "".join([char + u'\u0336' for char in text])


def get_google_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())
    return build('calendar', 'v3', credentials=creds)


def format_untis_time(untis_date_val, untis_time_val):
    # bereinigt format der zeit für untis und google
    # 1. Nur ziffern extrahieren
    d_raw = "".join(filter(str.isdigit, str(untis_date_val)))
    t_raw = "".join(filter(str.isdigit, str(untis_time_val)))

    # 2. datum auf exakt 8 Stellen begrenzen (YYYYMMDD)
    clean_date = d_raw[:8]

    # 3. Zeit auf exakt 4 Stellen bringen (HHMM)
    clean_time = t_raw.zfill(4)[-4:]

    formatted_date = f"{clean_date[:4]}-{clean_date[4:6]}-{clean_date[6:8]}"
    hours = clean_time[:2]
    minutes = clean_time[2:]

    return f"{formatted_date}T{hours}:{minutes}:00"


def generate_hash(data_dict):
    return hashlib.md5(json.dumps(data_dict, sort_keys=True).encode('utf-8')).hexdigest()


def load_hashes():
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE, 'r') as f: return json.load(f)
    return {}


def save_hashes(hashes):
    heute = date.today()
    gefiltert = {}

    for k, v in hashes.items():
        try:
            # speichern nur wenn das datum nicht älter als 3 tage ist
            item_date = date.fromisoformat(v.get('date'))
            if item_date >= heute - timedelta(days=3):
                gefiltert[k] = v
        except (ValueError, TypeError):
            gefiltert[k] = v

    with open(HASH_FILE, 'w') as f:
        json.dump(gefiltert, f, indent=4)


def format_title(lesson):
    abk = "---"
    # Versuche das Fach zu finden in den positions die möglich sind
    for key in ['LESSON', 'SUBJECT', 'UNKNOWN']:
        if lesson.get(key) and isinstance(lesson[key], list) and len(lesson[key]) > 0:
            val = lesson[key][0].strip()
            if val and val != "---":
                # Macht aus GE-LK1 (GE-LK1) -> GE-LK1, weil im display name bei untis das so doppelt ist
                abk = val.split('(')[0].strip()
                break

    # wenn kein Fach da ist, also '---', Info als Fallback nutzen
    if abk == "---":
        details = lesson.get('details', {})
        for detail_key in ['info', 'substitution', 'text']:
            detail_val = details.get(detail_key)
            if detail_val and detail_val.strip() and detail_val.strip() != "---":
                res = detail_val.strip()
                return res[:50] + "..." if len(res) > 50 else res
        return "Sondertermin"

    # fach map anwenden, die oben definiert wurde. falls dächer fehlen hinzufpgne!
    found_long = None
    for k, v in FACH_MAP.items():
        if abk.startswith(k):
            found_long = v
            break

    if found_long:
        if abk.lower() in found_long.lower():
            return found_long
        return f"{found_long} ({abk})"

    return abk


def build_description(lesson, homeworks, teacher_list_formatted):
    details = lesson.get('details', {})
    lines = []

    # HAUSAUFGABEN immer anzeigen
    lines.append("--- HAUSAUFGABEN ---")
    if homeworks:
        for text, start, due in homeworks:
            lines.append(f"{text}")
    else:
        lines.append("Keine Hausis")
    lines.append("------------------------")
    lines.append("")

    # 2. DETAILS, alles in einem Block, für schön
    detail_lines = []
    for k, v in details.items():
        if v and str(v).strip() and str(v).strip() != "---":
            detail_lines.append(f"{k.capitalize()}: {v}\n")

    if detail_lines:
        lines.append("-------- DETAILS -------")
        lines.extend(detail_lines)
        lines.append("------------------------")
        lines.append("")

    # 3. LEHRER, ohne Block, unter allen anderen sachen
    if teacher_list_formatted:
        lines.append(f"Lehrer: {', '.join(teacher_list_formatted)}")
        lines.append("")

    return "\n".join(lines)


def cleanup_old_logs(days=7):
    if not os.path.exists(LOG_FILE):
        return

    cutoff = datetime.now() - timedelta(days=days)
    new_lines = []
    deleted_count = 0

    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for line in lines:
            parts = line.split(' - ')
            if len(parts) > 1:
                try:
                    log_date_str = parts[0]
                    log_date = datetime.strptime(log_date_str, '%Y-%m-%d %H:%M:%S,%f')
                    if log_date > cutoff:
                        new_lines.append(line)
                    else:
                        deleted_count += 1
                    continue
                except ValueError:
                    pass
            new_lines.append(line)

        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        if deleted_count > 0:
            logging.info(f"Log-Cleanup: {deleted_count} alte Zeilen entfernt.")

    except Exception as e:
        print(f"Fehler beim Log-Cleanup: {e}")
        logging.error(f"Fehler beim Log-Cleanup: {e}")


# main function
def sync():
    try:
        service = get_google_service()
        local_hashes = load_hashes()
        new_hashes = {}
        change_details = []
        c_new, c_upd, c_skip = 0, 0, 0

        # das zeitfenster: heute bis in X Wochen
        start_date = date.today()
        end_date = start_date + timedelta(weeks=12)

        logging.info(f"Hole Daten für {start_date} bis {end_date}")
        week_data = untis_api.get_week_data_from_api(start_date.isoformat(), end_date.isoformat())

        for day in week_data:
            untis_date = day['date']  # Format: YYYYMMDD
            d_raw = "".join(filter(str.isdigit, str(untis_date)))[:8]
            fmt_date = f"{d_raw[:4]}-{d_raw[4:6]}-{d_raw[6:8]}"

            for lesson in day['lessons']:
                u_id = lesson['ids'][0] if lesson['ids'] else None
                if not u_id: continue

                details = lesson.get('details', {})

                # check ausfall
                sub_text = ""
                for val in details.values():
                    if val and "eigenverantwortliches arbeiten" in str(val).lower():
                        sub_text = str(val)
                        break
                is_ausfall = (lesson.get('status') == 'CANCELLED') or (sub_text != "")

                # formatieren der zeit
                start_iso = format_untis_time(untis_date, lesson['start'])
                end_iso = format_untis_time(untis_date, lesson['end'])

                # daten holen
                details = lesson.get('details', {})
                hw = []
                try:
                    hw = untis_api.get_homework_information(u_id, start_iso, end_iso)
                except Exception as hw_e:
                    logging.warning(f"Hausaufgaben für ID {u_id} fehlgeschlagen: {hw_e}")

                # lehrer holen
                current_teachers = lesson.get('TEACHER', [])
                removed_teachers = lesson.get('REMOVED_TEACHER', [])
                teacher_parts = []
                for t in current_teachers:
                    if t and t.strip() != "---":
                        # Hoffelntlich error behoben: Wenn Ausfall, dann auch current_teacher streichen. Wurde nicht geamcht vorher. Trotz ausfall wurde der lehrer nicht durchgestrichen.
                        if is_ausfall:
                            teacher_parts.append(strike(t))
                        else:
                            teacher_parts.append(t)
                for t in removed_teachers:
                    if t and t.strip() != "---":
                        striked_t = strike(t)
                        if striked_t not in teacher_parts:
                            teacher_parts.append(striked_t)
                valid_teachers = teacher_parts

                # raum holen
                current_rooms = lesson.get('ROOM', [])
                removed_rooms = lesson.get('REMOVED_ROOM', [])
                room_parts = []
                for r in current_rooms:
                    if r and r.strip() != "---":
                        # Hier das gleiche wie mit den lehrern oben
                        if is_ausfall:
                            room_parts.append(strike(r))
                        else:
                            room_parts.append(r)
                for r in removed_rooms:
                    if r and r.strip() != "---":
                        striked_r = strike(r)
                        if striked_r not in room_parts:
                            room_parts.append(striked_r)

                room_base = ", ".join(room_parts) if room_parts else "Kein Raum"

                # für icons (ℹ steht immer vor 🏠︎, falls beides da ist)
                has_details = any(v and str(v).strip() and str(v).strip() != "---" for v in details.values())
                has_hw = len(hw) > 0

                indicators = []
                if has_details:
                    indicators.append("⚠️")
                if has_hw:
                    indicators.append("🏠")

                # zusammenführen mit "󠁯•󠁏󠁏" dazwischen
                separator = " 󠁯•󠁏󠁏 "
                if indicators:
                    room = f"{room_base}{separator}{separator.join(indicators)}"
                else:
                    room = room_base

                # titel machen für ausfall
                titel = format_title(lesson)
                if is_ausfall:
                    titel = f"AUSFALL: {titel}"

                description = build_description(lesson, hw, valid_teachers)

                event_data = {
                    'summary': titel,
                    'location': room,
                    'start': start_iso,
                    'end': end_iso,
                    'description': description
                }

                current_hash = generate_hash(event_data)
                logging.info(f"Prüfe Termin: {titel} am {start_iso}")

                # 5. Google Event Body
                event_body = {
                    'summary': event_data['summary'],
                    'location': event_data['location'],
                    'description': (
                            description +
                            "\n------------------------\n\n" +
                            f"Untis-Sync-ID: {u_id}" +
                            "\n\nMade by MyName99a ✧₊⁺⋆.˚୨ৎ"
                    ),
                    'colorId': '8' if is_ausfall else '1',
                    'start': {'dateTime': start_iso, 'timeZone': 'Europe/Berlin'},
                    'end': {'dateTime': end_iso, 'timeZone': 'Europe/Berlin'},
                    'reminders': {
                        'useDefault': False,
                        'overrides': [],
                    },
                }

                if u_id in local_hashes:
                    g_id = local_hashes[u_id]['google_id']
                    if local_hashes[u_id]['hash'] == current_hash:
                        c_skip += 1
                        new_hashes[u_id] = local_hashes[u_id]
                    else:
                        change_details.append(f"{fmt_date}: '{local_hashes[u_id].get('summary')}' -> '{titel}'")
                        service.events().patch(calendarId='primary', eventId=g_id, body=event_body).execute()
                        c_upd += 1
                        new_hashes[u_id] = {'hash': current_hash, 'google_id': g_id, 'date': fmt_date, 'summary': titel}
                    del local_hashes[u_id]
                else:
                    change_details.append(f"Neu am {fmt_date}: {titel}")
                    created = service.events().insert(calendarId='primary', body=event_body).execute()
                    c_new += 1
                    new_hashes[u_id] = {'hash': current_hash, 'google_id': created['id'], 'date': fmt_date,
                                        'summary': titel}

                time.sleep(0.2)  # für google api, sonst timeout

        # ids in google einträgen löschen, damit die für das programm unsichtbar werden, falls sie auch aus den hashes gelöscht werden nach 3 tagen
        heute_str = date.today().isoformat()
        for u_id, data in local_hashes.items():
            g_id = data.get('google_id')
            if data['date'] < heute_str:
                # Historie bewahren, nicht löschen
                try:
                    event = service.events().get(calendarId='primary', eventId=g_id).execute()
                    new_desc = event.get('description', '').split('\n\nUntis-Sync-ID:')[0] + "\n\nStunde vergangen"
                    service.events().patch(calendarId='primary', eventId=g_id, body={'description': new_desc}).execute()
                except:
                    pass
            else:
                # Zukünftiges löschen, falls aktualisirt
                try:
                    service.events().delete(calendarId='primary', eventId=g_id).execute()
                except:
                    pass

        save_hashes(new_hashes)
        notifications.send_update_notification(c_new, c_upd, c_skip, len(local_hashes), change_details)
        logging.info(f"Fertig! Neu: {c_new}, Updates: {c_upd}, Unverändert: {c_skip}, Gelöscht: {len(local_hashes)}")
        log_separator()

    except Exception as e:
        logging.error(f"Fehler im Sync: {e}", exc_info=True)
        notifications.send_error_notification(f"Sync Fehler: {str(e)}")
        log_separator()


if __name__ == "__main__":
    cleanup_old_logs(days=7)
    sync()