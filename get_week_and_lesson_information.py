import logging
from datetime import datetime, timedelta

import config
import texts
import untis_login
from untis_login import UntisLoginError   # noqa: F401  (main3.0.py catches it as untis_api.UntisLoginError)

#
# ----------------------------------------------------------------------------------------------------
#

today = datetime.today().strftime('%Y-%m-%d')
current_week_monday = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime('%Y-%m-%d')
current_week_friday = (datetime.now() - timedelta(days=datetime.now().weekday()) + timedelta(days=4)).strftime('%Y-%m-%d')

config.require("UNTIS_SERVER", "UNTIS_USER", "UNTIS_PASSWORD")

# Filled by _ensure_ready() when the first data is requested (not when this file is imported),
# so a failed login is reported by the sync like every other error.
_auth = None
school_year_id = None
student_id = None

#
# ----------------------------------------------------------------------------------------------------
#

BASE_HEADERS = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'de,de-DE;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
    'priority': 'u=1, i',
    'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Microsoft Edge";v="144"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': untis_login.USER_AGENT,
}


def _get(path, params=None, referer="/", with_context=True):
    """
    GET request to WebUntis with the login of the session. If WebUntis says the session has ended,
    the program logs in again and repeats the request once.
    with_context=False leaves out the Tenant-Id and school year headers (not needed to find the school year).
    """
    url = f"{untis_login.origin()}{path}"
    for attempt in (1, 2):
        headers = dict(BASE_HEADERS)
        headers['authorization'] = _auth.bearer()
        headers['referer'] = f"{untis_login.origin()}{referer}"
        if with_context:
            headers['tenant-id'] = _auth.tenant_id
            headers['x-webuntis-api-school-year-id'] = str(school_year_id)

        response = _auth.get(url, params, headers)
        if attempt == 1 and _auth.session_lost(response):
            logging.warning(f"WebUntis answered {response.status_code} for {path}, logging in again")
            _auth.login()
            continue
        return response


def _ensure_ready():
    """Logs in once and reads the school year and the student ID (the first call of the sync does it)."""
    global _auth, school_year_id, student_id
    if _auth is not None:
        return
    auth = untis_login.create()
    _auth = auth
    try:
        school_year_id = get_school_year()
        student_id = get_student_id()
        if not school_year_id or not student_id:
            raise RuntimeError("WebUntis did not deliver the school year or the student ID "
                               f"(school year: {bool(school_year_id)}, student: {bool(student_id)})")
    except Exception:
        _auth = None      # the next call starts from the beginning
        raise

#
# ----------------------------------------------------------------------------------------------------
#

def get_school_year():
    response = _get('/WebUntis/api/rest/view/v1/schoolyears',
                    referer=f'/timetable/my-student?date={current_week_monday}', with_context=False)
    if response.status_code != 200:
        return False
    years = response.json()
    if not years:
        return False
    for year in years:    # the school year that contains today, otherwise the first one (as before)
        date_range = year.get('dateRange') or {}
        if date_range.get('start') and date_range.get('end') and date_range['start'] <= today <= date_range['end']:
            return year.get('id')
    return years[0].get('id')


def get_student_id():
    params = {
        'resourceType': 'STUDENT',
        'timetableType': 'MY_TIMETABLE',
        'start': f'{current_week_monday}',
        'end': f'{current_week_friday}',
    }
    response = _get('/WebUntis/api/rest/view/v1/timetable/filter', params, referer='/timetable/my-student')
    return response.json().get('preSelected', {}).get('id') if response.status_code == 200 else False

#
# ----------------------------------------------------------------------------------------------------
#

def get_week_data_from_api(start_date_of_week_iso, end_date_of_week_iso):
    _ensure_ready()

    params = {
        'start': f'{start_date_of_week_iso}',
        'end': f'{end_date_of_week_iso}',
        'format': '1',  # no idea what 1 means
        'resourceType': 'STUDENT',
        'resources': f'{student_id}',
        'periodTypes': '',
        'timetableType': 'MY_TIMETABLE',
        'layout': 'START_TIME',
    }

    response = _get('/WebUntis/api/rest/view/v1/timetable/entries', params,
                    referer=f'/timetable/my-student?date={start_date_of_week_iso}')
    if response.status_code != 200:
        # without this check an error page would look like "no lessons" and the sync would delete the events
        raise RuntimeError(f"WebUntis timetable request failed with HTTP {response.status_code}")

    week_entries = []
    # 1. helper function to find the positions (the values can change, so the type could be anything)
    def process_positions(lesson_data, current_lesson_dict):
        # there are more than three, but only 3 are usually used. there are 1 - 7
        for p_key in ['position1', 'position2', 'position3']:
            pos_list = lesson_data.get(p_key)
            if not pos_list:
                continue

            for entry in pos_list:
                curr = entry.get('current')
                rem = entry.get('removed')

                # determine the type of the position
                detected_type = None
                if curr:
                    detected_type = curr.get('type')
                elif rem:
                    detected_type = rem.get('type')

                if not detected_type:
                    continue

                if detected_type not in current_lesson_dict:
                    current_lesson_dict[detected_type] = []

                # for removed entries ("removed")
                rem_key = f"REMOVED_{detected_type}"
                if rem_key not in current_lesson_dict:
                    current_lesson_dict[rem_key] = []

                if curr and curr.get('displayName'):
                    current_lesson_dict[detected_type].append(curr.get('displayName'))

                if rem and rem.get('displayName'):
                    current_lesson_dict[rem_key].append(rem.get('displayName'))

    # 2. merge everything into one dict
    for day in response.json().get('days', []):
        day_data = {"date": day.get('date'), "lessons": []}

        for lesson in day.get('gridEntries', []):
            lesson_ids = [str(i) for i in lesson.get('ids', [])]

            current_lesson = {
                "ids": lesson_ids,
                "start": lesson.get('duration', {}).get('start'),
                "end": lesson.get('duration', {}).get('end'),
                "status": lesson.get('status'),
                "details": {
                    "info": lesson.get('lessonInfo'),
                    "text": lesson.get('lessonText'),
                    "notes": lesson.get('notesAll'),
                    "substitution": lesson.get('substitutionText')
                }
            }

            process_positions(lesson, current_lesson)

            day_data["lessons"].append(current_lesson)

        week_entries.append(day_data)

    return week_entries

#
# ----------------------------------------------------------------------------------------------------
#

def get_lesson_detail(id_der_stunde, start_zeit_in_iso, end_zeit_in_iso):
    """
    Fetches the detail view of a lesson (one request) and returns:
    {
        "homeworks": [(text, dateTime, dueDateTime), ...],
        "teaching_content": str or None,
        "exam": {"name": ..., "description": ..., "type_long_name": ...} or None
    }
    """
    _ensure_ready()

    params = {
        'elementId': f'{student_id}',
        'elementType': '5',  # 5 stands for student here as well?
        'endDateTime': f'{end_zeit_in_iso}',
        'homeworkOption': 'DUE',
        'startDateTime': f'{start_zeit_in_iso}',
    }

    # /5/ in the referer stands for student
    response = _get('/WebUntis/api/rest/view/v2/calendar-entry/detail', params,
                    referer=f'/timetable/my-student/lessonDetails/{id_der_stunde}/{student_id}/5/{start_zeit_in_iso}/{end_zeit_in_iso}/true?date={current_week_monday}&entityId={student_id}')

    result = {"homeworks": [], "teaching_content": None, "exam": None}

    try:
        data = response.json()
        # make sure calendarEntries exists and is not empty
        entries = data.get('calendarEntries', [])

        if entries and len(entries) > 0:
            entry = entries[0]

            # 1. homework (can be None if there is none)
            homeworks_list = entry.get('homeworks')
            if homeworks_list:
                for hw in homeworks_list:
                    text_from_hw = hw.get('text', texts.t('no_homework_text'))
                    date_time_from_hw = hw.get('dateTime')
                    due_date_time_from_hw = hw.get('dueDateTime')

                    result["homeworks"].append((text_from_hw, date_time_from_hw, due_date_time_from_hw))

            # 2. teaching content (teachingContent), empty or missing -> None
            teaching_content = entry.get('teachingContent')
            if teaching_content and str(teaching_content).strip():
                result["teaching_content"] = str(teaching_content).strip()

            # 3. exam (can be None or missing)
            exam = entry.get('exam')
            if exam:
                exam_data = {
                    "name": exam.get('name'),
                    "description": exam.get('description'),
                    "type_long_name": exam.get('typeLongName'),
                }
                # only keep it if there is really some text in it
                if any(v and str(v).strip() for v in exam_data.values()):
                    result["exam"] = exam_data

    except Exception as e:
        # in case the JSON parsing fails or the structure is completely different
        logging.error(f"Error parsing the detail data for ID {id_der_stunde}: {e}")
        return {"homeworks": [], "teaching_content": None, "exam": None}

    return result

#
# ----------------------------------------------------------------------------------------------------
#
