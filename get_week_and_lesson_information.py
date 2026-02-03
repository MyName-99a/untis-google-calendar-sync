import login
import requests
from pprint import pprint
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

#
# ----------------------------------------------------------------------------------------------------
#

today = datetime.today().strftime('%Y-%m-%d')
current_week_monday = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime('%Y-%m-%d')
current_week_friday = (datetime.now() - timedelta(days=datetime.now().weekday()) + timedelta(days=4)).strftime('%Y-%m-%d')

base_url = login.server
username = login.user
password = login.password

#
# ----------------------------------------------------------------------------------------------------
#

def get_cookies_and_bearer_token():
    auth_data = {"cookies": {}, "bearer_token": None}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        def intercept_headers(request):
            headers = request.headers
            if "authorization" in headers and "Bearer" in headers["authorization"]:
                auth_data["bearer_token"] = headers["authorization"]

        page.on("request", intercept_headers)
        page.goto(f"https://{base_url}/WebUntis")
        page.locator('input[type="text"]').fill(username)
        page.locator('input[type="password"]').fill(password)
        page.locator('button[type="submit"], input[type="submit"]').click()
        page.wait_for_load_state("networkidle")

        cookies_list = context.cookies()
        auth_data["cookies"] = {c['name']: c['value'] for c in cookies_list}
        if not auth_data["bearer_token"]:
            page.wait_for_timeout(3000)
        browser.close()

        schoolname1 = auth_data["cookies"].get("schoolname")
        tenantid1 = auth_data["cookies"].get("Tenant-Id")
        traceid1 = auth_data["cookies"].get("traceId")
        jsessionid1 = auth_data["cookies"].get("JSESSIONID")
        sleek_session1 = auth_data["cookies"].get("_sleek_session")
        sleek_product1 = auth_data["cookies"].get("_sleek_product")
        bearer_token1 = auth_data.get("bearer_token")

        return (
            schoolname1, tenantid1, traceid1, jsessionid1,
            sleek_session1, sleek_product1, bearer_token1
        )
schoolname, tenant_id, traceid, jsessionid, sleek_session, sleek_product, bearer_token = get_cookies_and_bearer_token()
tenant_id_splited = tenant_id[0].replace('"', '') if tenant_id else "" # Ohne "", weil man die bei den api dingern unten ohne benutzt in den 'headers'

#
# ----------------------------------------------------------------------------------------------------
#

def get_school_year():
    cookies = {
        'schoolname': f'{schoolname}',
        'Tenant-Id': f'{tenant_id}',
        'traceId': f'{traceid}',
        'JSESSIONID': f'{jsessionid}',
        '_sleek_session': f'{sleek_session}',
        '_sleek_product': f'{sleek_product}',
    }

    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'de,de-DE;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'authorization': f'{bearer_token}',
        'priority': 'u=1, i',
        'referer': f'https://{base_url}/timetable/my-student?date={current_week_monday}',
        'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Microsoft Edge";v="144"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0',
    }

    response = requests.get(
        f'https://{base_url}/WebUntis/api/rest/view/v1/schoolyears',
        cookies=cookies,
        headers=headers,
    )

    return response.json()[0].get('id') if response.status_code == 200 and response.json() else False
school_year_id = get_school_year()

def get_student_id():
    cookies = {
        'schoolname': f'{schoolname}',
        'Tenant-Id': f'{tenant_id}',
        'traceId': f'{traceid}',
        'JSESSIONID': f'{jsessionid}',
        '_sleek_session': f'{sleek_session}',
        '_sleek_product': f'{sleek_product}',
    }

    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'de,de-DE;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'authorization': f'{bearer_token}',
        'priority': 'u=1, i',
        'referer': f'https://{base_url}/timetable/my-student',
        'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Microsoft Edge";v="144"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'tenant-id': f'{tenant_id_splited}',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0',
        'x-webuntis-api-school-year-id': f'{school_year_id}',
    }

    params = {
        'resourceType': 'STUDENT',
        'timetableType': 'MY_TIMETABLE',
        'start': f'{current_week_monday}',
        'end': f'{current_week_friday}',
    }

    response = requests.get(
        f'https://{base_url}/WebUntis/api/rest/view/v1/timetable/filter',
        params=params,
        cookies=cookies,
        headers=headers,
    )

    return response.json().get('preSelected', {}).get('id') if response.status_code == 200 else False
student_id = get_student_id()

#
# ----------------------------------------------------------------------------------------------------
#

def get_week_data_from_api(start_date_of_week_iso, end_date_of_week_iso):
    cookies = {
        'schoolname': f'{schoolname}',
        'Tenant-Id': f'{tenant_id}',
        'traceId': f'{traceid}',
        'JSESSIONID': f'{jsessionid}',
        '_sleek_session': f'{sleek_session}',
        '_sleek_product': f'{sleek_product}',
    }

    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'de,de-DE;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'authorization': f'{bearer_token}',
        'priority': 'u=1, i',
        'referer': f'https://{base_url}/timetable/my-student?date={start_date_of_week_iso}',
        'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Microsoft Edge";v="144"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'tenant-Id': f'{tenant_id}',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0',
        'x-webuntis-api-school-year-id': f'{school_year_id}',
    }

    params = {
        'start': f'{start_date_of_week_iso}',
        'end': f'{end_date_of_week_iso}',
        'format': '1', # kp was 1 heißt
        'resourceType': 'STUDENT',
        'resources': f'{student_id}',
        'periodTypes': '',
        'timetableType': 'MY_TIMETABLE',
        'layout': 'START_TIME',
    }

    response = requests.get(
        f'https://{base_url}/WebUntis/api/rest/view/v1/timetable/entries',
        params=params,
        cookies=cookies,
        headers=headers,
    )

    week_entries = []
    # 1. definierung von hilfsfunktion, um die posititonen zu ermiteln. (sind werte, die sich ändern können. also könnte alles drinstehen vom type her)
    def process_positions(lesson_data, current_lesson_dict):
        # es gibt mehr als drei aber beim lfg werden meist nur 3 benutzt. es gibt 1 - 7
        for p_key in ['position1', 'position2', 'position3']:
            pos_list = lesson_data.get(p_key)
            if not pos_list:
                continue

            for entry in pos_list:
                curr = entry.get('current')
                rem = entry.get('removed')

                # typ bestimmen der position
                detected_type = None
                if curr:
                    detected_type = curr.get('type')
                elif rem:
                    detected_type = rem.get('type')

                if not detected_type:
                    continue

                if detected_type not in current_lesson_dict:
                    current_lesson_dict[detected_type] = []

                # für gelöschte einträge "removed"
                rem_key = f"REMOVED_{detected_type}"
                if rem_key not in current_lesson_dict:
                    current_lesson_dict[rem_key] = []

                if curr and curr.get('displayName'):
                    current_lesson_dict[detected_type].append(curr.get('displayName'))

                if rem and rem.get('displayName'):
                    current_lesson_dict[rem_key].append(rem.get('displayName'))

    # 2. in ein dic alles zusammenführen
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

def get_homework_information(id_der_stunde, start_zeit_in_iso, end_zeit_in_iso):
    cookies = {
        'schoolname': f'{schoolname}',
        'Tenant-Id': f'{tenant_id}',
        'traceId': f'{traceid}',
        'JSESSIONID': f'{jsessionid}',
        '_sleek_session': f'{sleek_session}',
        '_sleek_product': f'{sleek_product}',
    }

    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'de,de-DE;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'authorization': f'{bearer_token}',
        'priority': 'u=1, i',
        'referer': f'https://{base_url}/timetable/my-student/lessonDetails/{id_der_stunde}/{student_id}/5/{start_zeit_in_iso}/{end_zeit_in_iso}/true?date={current_week_monday}&entityId={student_id}', # /5/ steht für schüler
        'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Microsoft Edge";v="144"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'tenant-id': f'{tenant_id_splited}',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0',
        'x-webuntis-api-school-year-id': f'{school_year_id}',
    }

    params = {
        'elementId': f'{student_id}',
        'elementType': '5', # Hier steht 5 auch wieder für Schüler?
        'endDateTime': f'{end_zeit_in_iso}',
        'homeworkOption': 'DUE',
        'startDateTime': f'{start_zeit_in_iso}',
    }

    response = requests.get(
        f'https://{base_url}/WebUntis/api/rest/view/v2/calendar-entry/detail',
        params=params,
        cookies=cookies,
        headers=headers,
    )

    all_homeworks = []

    try:
        data = response.json()
        # Sicherstellen, dass calendarEntries existiert und nicht leer ist
        entries = data.get('calendarEntries', [])

        if entries and len(entries) > 0:
            # Sicherstellen, dass homeworks existiert (kann None sein, wenn keine HA da sind)
            homeworks_list = entries[0].get('homeworks')

            if homeworks_list:
                for hw in homeworks_list:
                    text_from_hw = hw.get('text', 'Kein Text vorhanden')
                    date_time_from_hw = hw.get('dateTime')
                    due_date_time_from_hw = hw.get('dueDateTime')

                    all_homeworks.append((text_from_hw, date_time_from_hw, due_date_time_from_hw))

    except Exception as e:
        # Falls das JSON-Parsing fehlschlägt oder die Struktur völlig anders ist
        print(f"Fehler beim Parsen der Hausaufgaben für ID {id_der_stunde}: {e}")
        return []

    return all_homeworks

#
# ----------------------------------------------------------------------------------------------------
#