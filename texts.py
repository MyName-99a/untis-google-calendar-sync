"""
All texts that show up in the calendar events and in the push notifications, in every supported language.

Select the language with LANGUAGE=en or LANGUAGE=de in .env (default: en). Logs and console output are always
English and do not use this file.

    from texts import t
    t("no_room")                      -> "No room" (or "Kein Raum")
    t("stat_new", n=3)                -> "3 new"   (or "3 neu")

Add a new language:
    1. copy the whole 'en' block below, rename it (e.g. 'fr') and translate the values
    2. add the language code to SUPPORTED_LANGUAGES in config.py
    3. run: python texts.py   (checks that every language has the same keys and placeholders)

The 'de' block must keep the exact wording that was used before the language setting existed. A different text
changes the hash of every event and rewrites the whole calendar on the next run.
"""

import re
import sys

import config

TEXTS = {
    'en': {
        # ---- Calendar event description ----
        'homework_header': "--- HOMEWORK ---",
        'no_homework': "No homework",
        'no_homework_text': "No text",
        'exam_header': "--------- EXAM ---------",
        'exam_name_and_description': "Name and description: {value}",
        'exam_name': "Name: {value}",
        'exam_description': "Description: {value}",
        'exam_type': "Type: {value}",
        'details_header': "-------- DETAILS -------",
        'lesson_over': "Lesson over",

        # ---- Calendar event title and location ----
        'cancelled_title': "CANCELLED: {title}",
        'no_room': "No room",
        'special_event': "Special event",

        # ---- Field names (event description and change notifications) ----
        'field_cancelled': "Cancelled",
        'field_time': "Time",
        'field_title': "Subject",
        'field_room': "Room",
        'field_teacher': "Teacher",
        'field_exam': "Exam",
        'field_homework': "Homework",
        'field_teaching_content': "Teaching content",
        'field_info': "Info",
        'field_text': "Text",
        'field_notes': "Notes",
        'field_substitution': "Substitution",
        'cancelled_on': "Marked as cancelled",
        'cancelled_off': "Cancellation removed",

        # ---- Push notifications ----
        'weekdays': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        'date_short': "%d %b",           # shown for the current year, e.g. 13 Nov
        'date_full': "%d %b %Y",         # shown for any other year, e.g. 13 Nov 2027
        'new_lesson': "new lesson",
        'new_lessons': "new lessons",
        'deleted_lesson': "lesson deleted",
        'deleted_lessons': "lessons deleted",
        'stat_new': "{n} new",
        'stat_updated': "{n} changed",
        'stat_deleted': "{n} deleted",
        'no_details': "Changes detected (no details available)",
        'more_entries': "… and {n} more entries (see calendar and log)",
        'unchanged': "Unchanged: {n}",
        'error_title': "Sync error",
        'sync_error': "Sync error: {error}",
        'auth_invalid': "Google login invalid: {error}",
        'login_invalid': "WebUntis login failed: {error}",
        'crash_notice': "The sync program keeps crashing ({reason}). Please check the log: docker compose logs untis-sync",
        'recovered_title': "Sync works again",
        'recovered': "The sync works again. It was interrupted since {since}.",
    },

    'de': {
        # ---- Kalendereintrag: Beschreibung ----
        'homework_header': "--- HAUSAUFGABEN ---",
        'no_homework': "Keine Hausis",
        'no_homework_text': "Kein Text vorhanden",
        'exam_header': "-------- KLAUSUR -------",
        'exam_name_and_description': "Name und Beschreibung: {value}",
        'exam_name': "Name: {value}",
        'exam_description': "Beschreibung: {value}",
        'exam_type': "Typ: {value}",
        'details_header': "-------- DETAILS -------",
        'lesson_over': "Stunde vergangen",

        # ---- Kalendereintrag: Titel und Ort ----
        'cancelled_title': "AUSFALL: {title}",
        'no_room': "Kein Raum",
        'special_event': "Sondertermin",

        # ---- Feldnamen (Beschreibung und Änderungsmeldungen) ----
        'field_cancelled': "Ausfall",
        'field_time': "Zeit",
        'field_title': "Fach",
        'field_room': "Raum",
        'field_teacher': "Lehrer",
        'field_exam': "Klausur",
        'field_homework': "Hausaufgabe",
        'field_teaching_content': "Lehrstoff",
        'field_info': "Info",
        'field_text': "Text",
        'field_notes': "Notes",
        'field_substitution': "Vertretung",
        'cancelled_on': "Ausfall eingetragen",
        'cancelled_off': "Ausfall aufgehoben",

        # ---- Push-Meldungen ----
        'weekdays': ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'],
        'date_short': "%d.%m.",
        'date_full': "%d.%m.%Y",
        'new_lesson': "neue Stunde",
        'new_lessons': "neue Stunden",
        'deleted_lesson': "Stunde gelöscht",
        'deleted_lessons': "Stunden gelöscht",
        'stat_new': "{n} neu",
        'stat_updated': "{n} geändert",
        'stat_deleted': "{n} gelöscht",
        'no_details': "Änderungen erkannt (keine Details verfügbar)",
        'more_entries': "… und {n} weitere Einträge (siehe Kalender und Log)",
        'unchanged': "Unverändert: {n}",
        'error_title': "Error-Sync",
        'sync_error': "Sync Fehler: {error}",
        'auth_invalid': "Google-Anmeldung ungültig: {error}",
        'login_invalid': "WebUntis-Anmeldung fehlgeschlagen: {error}",
        'crash_notice': "Das Sync-Programm bricht wiederholt ab ({reason}). Bitte das Log prüfen: docker compose logs untis-sync",
        'recovered_title': "Sync läuft wieder",
        'recovered': "Der Sync läuft wieder. Er war unterbrochen seit {since}.",
    },
}


def t(key, **values):
    """Text in the configured language. With keyword arguments the {placeholders} are filled in."""
    text = TEXTS[config.LANGUAGE][key]
    return text.format(**values) if values else text


def raw(key):
    """Value without any formatting (lists and date formats)."""
    return TEXTS[config.LANGUAGE][key]


def check():
    """Returns a list of problems (empty = all languages have the same keys and placeholders)."""
    problems = []
    reference = TEXTS['en']

    if set(TEXTS) != set(config.SUPPORTED_LANGUAGES):
        problems.append(f"TEXTS has {sorted(TEXTS)}, but config.SUPPORTED_LANGUAGES is {sorted(config.SUPPORTED_LANGUAGES)}")

    for lang, texts in TEXTS.items():
        missing = sorted(set(reference) - set(texts))
        extra = sorted(set(texts) - set(reference))
        if missing:
            problems.append(f"{lang}: missing keys {missing}")
        if extra:
            problems.append(f"{lang}: unknown keys {extra}")

        for key in sorted(set(reference) & set(texts)):
            ref_value, value = reference[key], texts[key]
            if isinstance(ref_value, list):
                if not isinstance(value, list) or len(value) != len(ref_value):
                    problems.append(f"{lang}.{key}: must be a list with {len(ref_value)} entries")
            elif isinstance(ref_value, str):
                if not isinstance(value, str):
                    problems.append(f"{lang}.{key}: must be a string")
                elif set(re.findall(r"\{(\w*)\}", ref_value)) != set(re.findall(r"\{(\w*)\}", value)):
                    problems.append(f"{lang}.{key}: placeholders differ from 'en'")
    return problems


if __name__ == "__main__":
    found = check()
    if found:
        print("Problems in texts.py:")
        for problem in found:
            print(f"  - {problem}")
        sys.exit(1)
    print(f"texts.py OK: {len(TEXTS['en'])} keys in {', '.join(sorted(TEXTS))}")
