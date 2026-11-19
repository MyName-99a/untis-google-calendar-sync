import os
import json
import hashlib
import logging
import time
import sys
from datetime import datetime, date, timedelta

# Google API imports
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Own files
import config
import auth
import get_week_and_lesson_information as untis_api
import notifications
import changes
from texts import t

# https://emojidb.org/house-emojis?utm_source=user_search - the emojis are from here, good site

# Paths (everything lives in the data folder, without a setting that is the project folder).
# The file names are German for historical reasons and kept, so that existing installations keep working (see config.HASH_FILE).
DATA_DIR = config.DATA_DIR
HASH_FILE = config.HASH_FILE
LOG_FILE = os.path.join(DATA_DIR, 'sync_log.txt')

# Marker file, so that the "Google login invalid" message does not come every few minutes
# Error messages (notifications.report_error): repeated at most this often while the same error lasts
REPEAT_HOURS_LOGIN = 24    # Google or WebUntis login: the person has to act, once a day is enough
REPEAT_HOURS_SYNC = 6      # all other errors (e.g. WebUntis or Google not reachable)

# Google Calendar colors (colorId)
COLOR_NORMAL = '1'    # Lavender (as before)
COLOR_CANCELLED = '8'  # Grey (wins over exam)
COLOR_EXAM = '11'     # Tomato (exam)

# Fields of the DETAILS block (order = order in the calendar). The names come from texts.py ('field_<key>')
DETAIL_KEYS = ['info', 'text', 'notes', 'substitution']

# Built-in subject names for one German school (the keys are the codes from WebUntis).
# Add your own in data/fach_map.json, or set FACH_MAP_USE_DEFAULTS=false to use only your own file (see README).
FACH_MAP = {
    # Advanced courses (LK)
    'BI-LK': 'Biologie LK',
    'CH-LK': 'Chemie LK',
    'EK-LK': 'Erdkunde LK',
    'GE-LK': 'Geschichte LK',
    'KU-LK': 'Kunst LK',
    'PA-LK': 'Pädagogik LK',
    'PH-LK': 'Physik LK',
    'SP-LK': 'Sport LK',
    'SW-LK': 'Sozialwissenschaften LK',

    # Advanced courses, short codes
    'D-LK': 'Deutsch LK',
    'E-LK': 'Englisch LK',
    'S-LK': 'Spanisch LK',

    # Advanced courses, short codes - new
    'E L': 'Englisch LK',
    'GE L': 'Geschichte LK',
    'E  L': 'Englisch LK',
    'GE  L': 'Geschichte LK',

    # Long codes
    'EKE': 'Erkunde Englisch',
    'GEE': 'Geschichte Englisch',

    # Project course
    'PX': 'Projektkurs',

    # Basic courses
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

    # Basic courses, single-letter codes
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

# own entries from fach_map.json in the data folder come first (see config.load_fach_map)
FACH_MAP = config.load_fach_map(FACH_MAP)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)


def log_separator():
    separator = "-" * 50
    logging.info("End of sync!\n\n" + separator + "\n")


# helpers

def strike(text):
    # turns text into struck-through unicode text
    return "".join([char + u'̶' for char in text])


def is_filled(value):
    # True if a field really has content (not None, empty or "---")
    return bool(value) and str(value).strip() not in ("", "---")


def clean_text(value):
    # returns a cleaned string, or "" if there is nothing useful in it
    return str(value).strip() if is_filled(value) else ""


def exam_summary(exam):
    # turns the exam dict into a short text for the snapshot (name and description, without duplicates)
    if not exam:
        return ""
    parts = []
    for key in ('name', 'description'):
        v = clean_text(exam.get(key))
        if v and v not in parts:
            parts.append(v)
    return " – ".join(parts)


def get_google_service():
    # The login comes from token.json (created with auth.py), details are in auth.py
    creds = auth.get_credentials()

    # Login works (again): the next login error is reported at once
    notifications.clear_error('google')

    return build('calendar', 'v3', credentials=creds, cache_discovery=False)


def http_status(error):
    # HTTP status of a Google API error (404 = not found, 410 = gone)
    return getattr(error, 'status_code', None) or getattr(getattr(error, 'resp', None), 'status', None)


def format_untis_time(untis_date_val, untis_time_val):
    # cleans up the time format for untis and google
    # 1. extract digits only
    d_raw = "".join(filter(str.isdigit, str(untis_date_val)))
    t_raw = "".join(filter(str.isdigit, str(untis_time_val)))

    # 2. limit the date to exactly 8 digits (YYYYMMDD)
    clean_date = d_raw[:8]

    # 3. bring the time to exactly 4 digits (HHMM)
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
    today = date.today()
    filtered = {}

    for k, v in hashes.items():
        try:
            # only keep the entry if its date is not older than 3 days
            item_date = date.fromisoformat(v.get('date'))
            if item_date >= today - timedelta(days=3):
                filtered[k] = v
        except (ValueError, TypeError):
            filtered[k] = v

    with open(HASH_FILE, 'w') as f:
        json.dump(filtered, f, indent=4)


def format_title(lesson):
    abbr = "---"
    # try to find the subject in the possible positions
    for key in ['LESSON', 'SUBJECT', 'UNKNOWN']:
        if lesson.get(key) and isinstance(lesson[key], list) and len(lesson[key]) > 0:
            val = lesson[key][0].strip()
            if val and val != "---":
                # turns GE-LK1 (GE-LK1) -> GE-LK1, because untis shows it twice in the display name
                abbr = val.split('(')[0].strip()
                break

    # if there is no subject, i.e. '---', use info as a fallback
    if abbr == "---":
        details = lesson.get('details', {})
        for detail_key in ['info', 'substitution', 'text']:
            detail_val = details.get(detail_key)
            if detail_val and detail_val.strip() and detail_val.strip() != "---":
                res = detail_val.strip()
                return res[:50] + "..." if len(res) > 50 else res
        return t('special_event')

    # apply the fach map (subject names) defined above. if codes are missing, add them!
    found_long = None
    for k, v in FACH_MAP.items():
        if abbr.startswith(k):
            found_long = v
            break

    if found_long:
        if abbr.lower() in found_long.lower():
            return found_long
        return f"{found_long} ({abbr})"

    return abbr


def build_exam_block(exam):
    # builds the EXAM block. Returns a list of lines (empty if there is nothing useful)
    if not exam:
        return []

    name = str(exam.get('name') or '').strip()
    description = str(exam.get('description') or '').strip()
    exam_type = str(exam.get('type_long_name') or '').strip()

    parts = []
    if name and description and name == description:
        # exactly the same -> show only once
        parts.append(t('exam_name_and_description', value=name))
    else:
        if name:
            parts.append(t('exam_name', value=name))
        if description:
            parts.append(t('exam_description', value=description))
    if exam_type:
        parts.append(t('exam_type', value=exam_type))

    if not parts:
        return []

    lines = [t('exam_header')]
    lines.append("\n\n".join(parts))
    lines.append("------------------------")
    lines.append("")
    return lines


def build_description(lesson, homeworks, teacher_list_formatted, teaching_content=None, exam=None):
    details = lesson.get('details', {})
    lines = []

    # 1. HOMEWORK is always shown
    lines.append(t('homework_header'))
    if homeworks:
        for text, start, due in homeworks:
            lines.append(f"{text}")
    else:
        lines.append(t('no_homework'))
    lines.append("------------------------")
    lines.append("")

    # 2. EXAM, own block directly below the homework (only if there is an exam)
    lines.extend(build_exam_block(exam))

    # 3. DETAILS, everything in one block, looks nicer (the teaching content is at the end of the block)
    detail_lines = []
    for key in DETAIL_KEYS:
        v = details.get(key)
        if is_filled(v):
            detail_lines.append(f"{t('field_' + key)}: {v}")
    if is_filled(teaching_content):
        detail_lines.append(f"{t('field_teaching_content')}: {str(teaching_content).strip()}")

    if detail_lines:
        lines.append(t('details_header'))
        lines.append("\n\n".join(detail_lines))
        lines.append("------------------------")
        lines.append("")

    # 4. TEACHER, without a block, below everything else
    if teacher_list_formatted:
        lines.append(f"{t('field_teacher')}: {', '.join(teacher_list_formatted)}")
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
            logging.info(f"Log cleanup: {deleted_count} old lines removed.")

    except Exception as e:
        print(f"Error during log cleanup: {e}")
        logging.error(f"Error during log cleanup: {e}")


# main function
def sync():
    try:
        service = get_google_service()
        local_hashes = load_hashes()
        new_hashes = {}
        change_log = []  # structured changes for the notification
        c_new, c_upd, c_skip, c_del, c_silent = 0, 0, 0, 0, 0

        # --------------------------------------------------
        # TIME RANGE: always keep exactly ONE of the two variants active

        # Variant A (normal): today until 12 weeks ahead
        start_date = date.today()
        end_date = start_date + timedelta(weeks=config.SYNC_WEEKS_AHEAD)

        # Variant B (test): fixed range (to test, comment out A and activate B)
        # start_date = date.fromisoformat("2026-11-09")
        # end_date = date.fromisoformat("2026-11-13")
        # --------------------------------------------------

        logging.info(f"Fetching data for {start_date} to {end_date}")
        week_data = untis_api.get_week_data_from_api(start_date.isoformat(), end_date.isoformat())

        # WebUntis login works (again): the next login error is reported at once
        notifications.clear_error('login')

        for day in week_data:
            untis_date = day['date']  # Format: YYYYMMDD
            d_raw = "".join(filter(str.isdigit, str(untis_date)))[:8]
            fmt_date = f"{d_raw[:4]}-{d_raw[4:6]}-{d_raw[6:8]}"

            for lesson in day['lessons']:
                u_id = lesson['ids'][0] if lesson['ids'] else None
                if not u_id: continue

                details = lesson.get('details', {})

                # check cancellation: status CANCELLED, or an info text with one of the CANCEL_KEYWORDS
                sub_text = ""
                for val in details.values():
                    if val and any(keyword in str(val).lower() for keyword in config.CANCEL_KEYWORDS):
                        sub_text = str(val)
                        break
                is_cancelled = (lesson.get('status') == 'CANCELLED') or (sub_text != "")

                # format the time
                start_iso = format_untis_time(untis_date, lesson['start'])
                end_iso = format_untis_time(untis_date, lesson['end'])

                # fetch detail data: homework, teaching content and exam (one request per lesson)
                detail = {'homeworks': [], 'teaching_content': None, 'exam': None}
                try:
                    detail = untis_api.get_lesson_detail(u_id, start_iso, end_iso)
                except Exception as hw_e:
                    logging.warning(f"Detail data for ID {u_id} failed: {hw_e}")

                hw = detail.get('homeworks') or []
                teaching_content = detail.get('teaching_content')
                exam = detail.get('exam')

                # get teachers
                current_teachers = lesson.get('TEACHER', [])
                removed_teachers = lesson.get('REMOVED_TEACHER', [])
                teacher_parts = []
                for teacher in current_teachers:
                    if teacher and teacher.strip() != "---":
                        # Hopefully fixed: if cancelled, also strike through the current teacher. This was not done before. The teacher was not struck through despite the cancellation.
                        if is_cancelled:
                            teacher_parts.append(strike(teacher))
                        else:
                            teacher_parts.append(teacher)
                for teacher in removed_teachers:
                    if teacher and teacher.strip() != "---":
                        striked_t = strike(teacher)
                        if striked_t not in teacher_parts:
                            teacher_parts.append(striked_t)
                valid_teachers = teacher_parts

                # get rooms
                current_rooms = lesson.get('ROOM', [])
                removed_rooms = lesson.get('REMOVED_ROOM', [])
                room_parts = []
                for r in current_rooms:
                    if r and r.strip() != "---":
                        # same as with the teachers above
                        if is_cancelled:
                            room_parts.append(strike(r))
                        else:
                            room_parts.append(r)
                for r in removed_rooms:
                    if r and r.strip() != "---":
                        striked_r = strike(r)
                        if striked_r not in room_parts:
                            room_parts.append(striked_r)

                room_base = ", ".join(room_parts) if room_parts else t('no_room')

                # for icons (ℹ always comes before 🏠︎, if both are there)
                # Teaching content and exam deliberately do NOT count for the ⚠️, only info/text/notes/substitution
                has_details = any(is_filled(v) for v in details.values())
                has_hw = len(hw) > 0

                indicators = []
                if has_details:
                    indicators.append("⚠️")  # ⚠️
                if has_hw:
                    indicators.append("\U0001f3e0")    # 🏠

                # join with an invisible tag-character separator in between (U+E006F, bullet, U+E004F x2)
                separator = " \U000e006f•\U000e004f\U000e004f "
                if indicators:
                    room = f"{room_base}{separator}{separator.join(indicators)}"
                else:
                    room = room_base

                # build the title for a cancellation (base_title without prefix is needed for the snapshot)
                base_title = format_title(lesson)
                title = t('cancelled_title', title=base_title) if is_cancelled else base_title

                # color: cancelled (grey) wins over exam (red)
                if is_cancelled:
                    color_id = COLOR_CANCELLED
                elif exam:
                    color_id = COLOR_EXAM
                else:
                    color_id = COLOR_NORMAL

                description = build_description(lesson, hw, valid_teachers, teaching_content, exam)

                # snapshot of every single field, so that changes can be compared exactly.
                # new fields = add an entry here (and in changes.py the field list)
                fields = {
                    'title': base_title,
                    'start': start_iso,
                    'end': end_iso,
                    'room': [r.strip() for r in current_rooms if is_filled(r)],
                    'teacher': [x.strip() for x in current_teachers if is_filled(x)],
                    'cancelled': is_cancelled,
                    'homework': [clean_text(text) for text, _, _ in hw if is_filled(text)],
                    'teaching_content': clean_text(teaching_content),
                    'exam': exam_summary(exam),
                    'info': clean_text(details.get('info')),
                    'text': clean_text(details.get('text')),
                    'notes': clean_text(details.get('notes')),
                    'substitution': clean_text(details.get('substitution')),
                }

                event_data = {
                    'summary': title,
                    'location': room,
                    'start': start_iso,
                    'end': end_iso,
                    'description': description,
                    'colorId': color_id
                }

                current_hash = generate_hash(event_data)
                logging.info(f"Checking event: {title} on {start_iso}")

                # 5. Google event body
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
                            # Event unchanged, only gets the snapshot added (once, after the switch)
                            new_hashes[u_id]['fields'] = fields
                    else:
                        try:
                            service.events().patch(calendarId=config.CALENDAR_ID, eventId=g_id, body=event_body).execute()
                        except HttpError as patch_error:
                            if http_status(patch_error) not in (404, 410):
                                raise
                            # the event was deleted in the calendar (e.g. by hand): create it again
                            logging.warning(f"Event {g_id} no longer exists in the calendar, creating it again: {title}")
                            g_id = service.events().insert(calendarId=config.CALENDAR_ID, body=event_body).execute()['id']

                        # what exactly changed? (without an old snapshot no comparison is possible)
                        diff = changes.diff_fields(old_fields, fields) if old_fields else []
                        if diff:
                            c_upd += 1
                            change_log.append({
                                'type': 'updated',
                                'date': fmt_date,
                                'start': start_iso,
                                'title': base_title,
                                'cancelled': is_cancelled,
                                'changes': diff,
                            })
                        else:
                            # description/format is new, but nothing worth a notification changed in content
                            c_silent += 1

                        new_hashes[u_id] = {'hash': current_hash, 'google_id': g_id, 'date': fmt_date,
                                            'summary': title, 'fields': fields}
                    del local_hashes[u_id]
                else:
                    created = service.events().insert(calendarId=config.CALENDAR_ID, body=event_body).execute()
                    c_new += 1
                    change_log.append({
                        'type': 'new',
                        'date': fmt_date,
                        'start': start_iso,
                        'title': base_title,
                        'cancelled': is_cancelled,
                    })
                    new_hashes[u_id] = {'hash': current_hash, 'google_id': created['id'], 'date': fmt_date,
                                        'summary': title, 'fields': fields}

                time.sleep(0.2)  # for the google api, otherwise timeout

        # remove the ids from the google events, so that they become invisible to the program in case they are also removed from the hashes after 3 days
        today_str = date.today().isoformat()
        for u_id, data in local_hashes.items():
            g_id = data.get('google_id')
            old_fields = data.get('fields') or {}
            if data['date'] < today_str:
                # keep the history, do not delete
                try:
                    event = service.events().get(calendarId=config.CALENDAR_ID, eventId=g_id).execute()
                    new_desc = event.get('description', '').split('\n\nUntis-Sync-ID:')[0] + "\n\n" + t('lesson_over')
                    service.events().patch(calendarId=config.CALENDAR_ID, eventId=g_id, body={'description': new_desc}).execute()
                except:
                    pass
            else:
                # delete future ones, if they changed (only this counts as "deleted")
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
                    logging.warning(f"Deleting {g_id} failed: {del_e}")

        save_hashes(new_hashes)
        counts = {'new': c_new, 'updated': c_upd, 'skipped': c_skip, 'deleted': c_del, 'silent': c_silent}
        notifications.send_recovery()    # only if an error message was sent before
        notifications.send_update_notification(counts, change_log)
        logging.info(f"Done! New: {c_new}, updated: {c_upd}, unchanged: {c_skip}, deleted: {c_del}, silently updated: {c_silent}")
        log_separator()
        return True

    except auth.GoogleAuthError as e:
        logging.error(f"Google login: {e}")
        notifications.report_error('google', t('auth_invalid', error=str(e)), every_hours=REPEAT_HOURS_LOGIN)
        log_separator()
        return False

    except untis_api.UntisLoginError as e:
        logging.error(f"WebUntis login: {e}")
        notifications.report_error('login', t('login_invalid', error=str(e)), every_hours=REPEAT_HOURS_LOGIN)
        log_separator()
        return False

    except Exception as e:
        logging.error(f"Error in sync: {e}", exc_info=True)
        notifications.report_error('sync', t('sync_error', error=str(e)), every_hours=REPEAT_HOURS_SYNC)
        log_separator()
        return False


if __name__ == "__main__":
    cleanup_old_logs(days=7)
    ok = sync()
    sys.exit(0 if ok else 3)  # 3 = error was already reported (see run_loop.py)
