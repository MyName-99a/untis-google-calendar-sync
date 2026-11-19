import os
import json
import hashlib
import logging
import time
import sys
from datetime import datetime, date, timedelta

# Google API importe
from googleapiclient.discovery import build

# Own files
import config
import auth
import get_week_and_lesson_information as untis_api
import notifications
import changes

# https://emojidb.org/house-emojis?utm_source=user_search - Emojis sind von hier gute seite eig

# pfade und so (alles liegt im Datenordner, ohne Angabe ist das der Projektordner)
DATA_DIR = config.DATA_DIR
HASH_FILE = os.path.join(DATA_DIR, 'gespeicherte_hashes.json')
LOG_FILE = os.path.join(DATA_DIR, 'sync_log.txt')

# Merker-Datei, damit die Meldung "Google-Anmeldung ungültig" nicht alle paar Minuten kommt
AUTH_ERROR_MARKER = os.path.join(DATA_DIR, '.google_auth_error_gemeldet')

# Google Kalender Farben (colorId)
COLOR_NORMAL = '1'    # Lavendel (wie bisher)
COLOR_AUSFALL = '8'   # Grau (hat Vorrang vor Klausur)
COLOR_EXAM = '11'     # Tomate (Klausur)

# Anzeigenamen für die Felder im DETAILS-Block (Reihenfolge = Reihenfolge im Kalender)
DETAIL_LABELS = {
    'info': 'Info',
    'text': 'Text',
    'notes': 'Notes',
    'substitution': 'Vertretung',
}

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

    # LKs kurze Kürzel - Neu
    'E L': 'Englisch LK',
    'GE L': 'Geschichte LK',
    'E  L': 'Englisch LK',
    'GE  L': 'Geschichte LK',

    # Lange Kürzel
    'EKE': 'Erkunde Englisch',
    'GEE': 'Geschichte Englisch',

    # Projektkurs
    'PX': 'Projektkurs',

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
    'E': 'Englisch'

    # '': '', '': '', '': '',
    # '': '', '': '', '': '',
}

# eigene Einträge aus fach_map.json im Datenordner kommen zuerst (siehe config.load_fach_map)
FACH_MAP = config.load_fach_map(FACH_MAP)

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


def is_filled(value):
    # True, wenn ein Feld wirklich Inhalt hat (nicht None, leer oder "---")
    return bool(value) and str(value).strip() not in ("", "---")


def clean_text(value):
    # gibt einen bereinigten String zurück, oder "" wenn nichts Sinnvolles drinsteht
    return str(value).strip() if is_filled(value) else ""


def exam_summary(exam):
    # macht aus dem Exam-Dict einen kurzen Text für den Snapshot (Name und Beschreibung, ohne Doppelung)
    if not exam:
        return ""
    parts = []
    for key in ('name', 'description'):
        v = clean_text(exam.get(key))
        if v and v not in parts:
            parts.append(v)
    return " – ".join(parts)


def get_google_service():
    # Die Anmeldung kommt aus token.json (erstellt mit auth.py), Details stehen in auth.py
    creds = auth.get_credentials()

    # Anmeldung funktioniert (wieder): Merker für die Fehlermeldung zurücksetzen
    if os.path.exists(AUTH_ERROR_MARKER):
        os.remove(AUTH_ERROR_MARKER)

    return build('calendar', 'v3', credentials=creds, cache_discovery=False)


def notify_auth_error_once(message, every_hours=24):
    # schickt die Meldung höchstens einmal pro Tag, bis die Anmeldung wieder funktioniert
    try:
        if os.path.exists(AUTH_ERROR_MARKER):
            if time.time() - os.path.getmtime(AUTH_ERROR_MARKER) < every_hours * 3600:
                return
        notifications.send_error_notification(f"Google-Anmeldung ungültig: {message}")
        with open(AUTH_ERROR_MARKER, 'w') as f:
            f.write(datetime.now().isoformat())
    except Exception as e:
        logging.warning(f"Auth-Meldung konnte nicht gesendet werden: {e}")


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


def build_exam_block(exam):
    # baut den KLAUSUR-Block. Gibt eine Liste von Zeilen zurück (leer, wenn nichts Sinnvolles da ist)
    if not exam:
        return []

    name = str(exam.get('name') or '').strip()
    beschreibung = str(exam.get('description') or '').strip()
    typ = str(exam.get('type_long_name') or '').strip()

    parts = []
    if name and beschreibung and name == beschreibung:
        # exakt gleich -> nur einmal anzeigen
        parts.append(f"Name und Beschreibung: {name}")
    else:
        if name:
            parts.append(f"Name: {name}")
        if beschreibung:
            parts.append(f"Beschreibung: {beschreibung}")
    if typ:
        parts.append(f"Typ: {typ}")

    if not parts:
        return []

    lines = ["-------- KLAUSUR -------"]
    lines.append("\n\n".join(parts))
    lines.append("------------------------")
    lines.append("")
    return lines


def build_description(lesson, homeworks, teacher_list_formatted, teaching_content=None, exam=None):
    details = lesson.get('details', {})
    lines = []

    # 1. HAUSAUFGABEN immer anzeigen
    lines.append("--- HAUSAUFGABEN ---")
    if homeworks:
        for text, start, due in homeworks:
            lines.append(f"{text}")
    else:
        lines.append("Keine Hausis")
    lines.append("------------------------")
    lines.append("")

    # 2. KLAUSUR, eigener Block direkt unter den Hausaufgaben (nur wenn ein Exam da ist)
    lines.extend(build_exam_block(exam))

    # 3. DETAILS, alles in einem Block, für schön (Lehrstoff steht am Ende des Blocks)
    detail_lines = []
    for key, label in DETAIL_LABELS.items():
        v = details.get(key)
        if is_filled(v):
            detail_lines.append(f"{label}: {v}")
    if is_filled(teaching_content):
        detail_lines.append(f"Lehrstoff: {str(teaching_content).strip()}")

    if detail_lines:
        lines.append("-------- DETAILS -------")
        lines.append("\n\n".join(detail_lines))
        lines.append("------------------------")
        lines.append("")

    # 4. LEHRER, ohne Block, unter allen anderen sachen
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
        change_log = []  # strukturierte Änderungen für die Benachrichtigung
        c_new, c_upd, c_skip, c_del, c_silent = 0, 0, 0, 0, 0

        # --------------------------------------------------
        # ZEITFENSTER: immer genau EINE der beiden Varianten aktiv lassen

        # Variante A (normal): heute bis in 12 Wochen
        start_date = date.today()
        end_date = start_date + timedelta(weeks=config.SYNC_WEEKS_AHEAD)

        # Variante B (Test): fester Zeitraum (zum Testen A auskommentieren und B aktivieren)
        # start_date = date.fromisoformat("2026-11-09")
        # end_date = date.fromisoformat("2026-11-13")
        # --------------------------------------------------

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

                # detaildaten holen: hausaufgaben, lehrstoff und exam (ein request pro stunde)
                detail = {'homeworks': [], 'teaching_content': None, 'exam': None}
                try:
                    detail = untis_api.get_lesson_detail(u_id, start_iso, end_iso)
                except Exception as hw_e:
                    logging.warning(f"Detaildaten für ID {u_id} fehlgeschlagen: {hw_e}")

                hw = detail.get('homeworks') or []
                teaching_content = detail.get('teaching_content')
                exam = detail.get('exam')

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
                # Lehrstoff und Exam zählen bewusst NICHT für das ⚠️, nur Info/Text/Notes/Vertretung
                has_details = any(is_filled(v) for v in details.values())
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

                # titel machen für ausfall (base_title ohne Präfix wird für den Snapshot gebraucht)
                base_title = format_title(lesson)
                titel = f"AUSFALL: {base_title}" if is_ausfall else base_title

                # farbe: ausfall (grau) gewinnt vor klausur (rot)
                if is_ausfall:
                    color_id = COLOR_AUSFALL
                elif exam:
                    color_id = COLOR_EXAM
                else:
                    color_id = COLOR_NORMAL

                description = build_description(lesson, hw, valid_teachers, teaching_content, exam)

                # snapshot aller einzelnen felder, damit man bei änderungen genau vergleichen kann.
                # neue felder = hier einen eintrag ergänzen (und in changes.py die Feldliste)
                fields = {
                    'title': base_title,
                    'start': start_iso,
                    'end': end_iso,
                    'room': [r.strip() for r in current_rooms if is_filled(r)],
                    'teacher': [t.strip() for t in current_teachers if is_filled(t)],
                    'cancelled': is_ausfall,
                    'homework': [clean_text(text) for text, _, _ in hw if is_filled(text)],
                    'teaching_content': clean_text(teaching_content),
                    'exam': exam_summary(exam),
                    'info': clean_text(details.get('info')),
                    'text': clean_text(details.get('text')),
                    'notes': clean_text(details.get('notes')),
                    'substitution': clean_text(details.get('substitution')),
                }

                event_data = {
                    'summary': titel,
                    'location': room,
                    'start': start_iso,
                    'end': end_iso,
                    'description': description,
                    'colorId': color_id
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
                    'colorId': color_id,
                    'start': {'dateTime': start_iso, 'timeZone': config.TZ},
                    'end': {'dateTime': end_iso, 'timeZone': config.TZ},
                    'reminders': {
                        'useDefault': False,
                        'overrides': [],
                    },
                }

                if u_id in local_hashes:
                    old = local_hashes[u_id]
                    g_id = old['google_id']
                    old_fields = old.get('fields')

                    if old['hash'] == current_hash:
                        c_skip += 1
                        new_hashes[u_id] = dict(old)
                        if old_fields is None:
                            # Termin unverändert, bekommt nur den Snapshot nachgetragen (einmalig nach der Umstellung)
                            new_hashes[u_id]['fields'] = fields
                    else:
                        service.events().patch(calendarId=config.CALENDAR_ID, eventId=g_id, body=event_body).execute()

                        # was genau hat sich geändert? (ohne alten Snapshot ist kein Vergleich möglich)
                        diff = changes.diff_fields(old_fields, fields) if old_fields else []
                        if diff:
                            c_upd += 1
                            change_log.append({
                                'type': 'updated',
                                'date': fmt_date,
                                'start': start_iso,
                                'title': base_title,
                                'cancelled': is_ausfall,
                                'changes': diff,
                            })
                        else:
                            # Beschreibung/Format neu, aber inhaltlich nichts, was eine Meldung wert ist
                            c_silent += 1

                        new_hashes[u_id] = {'hash': current_hash, 'google_id': g_id, 'date': fmt_date,
                                            'summary': titel, 'fields': fields}
                    del local_hashes[u_id]
                else:
                    created = service.events().insert(calendarId=config.CALENDAR_ID, body=event_body).execute()
                    c_new += 1
                    change_log.append({
                        'type': 'new',
                        'date': fmt_date,
                        'start': start_iso,
                        'title': base_title,
                        'cancelled': is_ausfall,
                    })
                    new_hashes[u_id] = {'hash': current_hash, 'google_id': created['id'], 'date': fmt_date,
                                        'summary': titel, 'fields': fields}

                time.sleep(0.2)  # für google api, sonst timeout

        # ids in google einträgen löschen, damit die für das programm unsichtbar werden, falls sie auch aus den hashes gelöscht werden nach 3 tagen
        heute_str = date.today().isoformat()
        for u_id, data in local_hashes.items():
            g_id = data.get('google_id')
            old_fields = data.get('fields') or {}
            if data['date'] < heute_str:
                # Historie bewahren, nicht löschen
                try:
                    event = service.events().get(calendarId=config.CALENDAR_ID, eventId=g_id).execute()
                    new_desc = event.get('description', '').split('\n\nUntis-Sync-ID:')[0] + "\n\nStunde vergangen"
                    service.events().patch(calendarId=config.CALENDAR_ID, eventId=g_id, body={'description': new_desc}).execute()
                except:
                    pass
            else:
                # Zukünftiges löschen, falls aktualisirt (nur das zählt als "gelöscht")
                try:
                    service.events().delete(calendarId=config.CALENDAR_ID, eventId=g_id).execute()
                    c_del += 1
                    change_log.append({
                        'type': 'deleted',
                        'date': data['date'],
                        'start': old_fields.get('start', ''),
                        'title': old_fields.get('title') or data.get('summary', ''),
                    })
                except Exception as del_e:
                    logging.warning(f"Löschen von {g_id} fehlgeschlagen: {del_e}")

        save_hashes(new_hashes)
        counts = {'new': c_new, 'updated': c_upd, 'skipped': c_skip, 'deleted': c_del, 'silent': c_silent}
        notifications.send_update_notification(counts, change_log)
        logging.info(f"Fertig! Neu: {c_new}, Updates: {c_upd}, Unverändert: {c_skip}, Gelöscht: {c_del}, Still aktualisiert: {c_silent}")
        log_separator()
        return True

    except auth.GoogleAuthError as e:
        logging.error(f"Google-Anmeldung: {e}")
        notify_auth_error_once(str(e))
        log_separator()
        return False

    except Exception as e:
        logging.error(f"Fehler im Sync: {e}", exc_info=True)
        notifications.send_error_notification(f"Sync Fehler: {str(e)}")
        log_separator()
        return False


if __name__ == "__main__":
    cleanup_old_logs(days=7)
    ok = sync()
    sys.exit(0 if ok else 3)  # 3 = Fehler wurde bereits gemeldet (siehe run_loop.py)