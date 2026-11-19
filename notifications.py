import base64
import logging
import sys
import time
from datetime import date
from itertools import groupby

import requests

import config

"""
Erwartet von main3.0.py:

    counts     = {'new': int, 'updated': int, 'skipped': int, 'deleted': int, 'silent': int}
    change_log = Liste von Einträgen:
        {'type': 'new' | 'deleted', 'date': 'YYYY-MM-DD', 'start': 'YYYY-MM-DDTHH:MM:SS', 'title': str, 'cancelled': bool}
        {'type': 'updated', 'date': ..., 'start': ..., 'title': str, 'cancelled': bool, 'changes': [Änderung, ...]}

    Änderung (kommt aus changes.diff_fields):
        {'field': str, 'label': str, 'op': 'add' | 'remove' | 'change',
         'old': str | None, 'new': str | None, 'text': str (optional, überschreibt die ganze Zeile), 'high': bool}
"""

NTFY_URL = config.NTFY_URL

SYMBOLS = {'add': '+', 'remove': '−', 'change': '~'}
WEEKDAYS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']

MAX_TEXT_LEN = 60       # Kürzung für Texte, die Lehrer eintragen (Lehrstoff, Hausaufgaben, Info, ...)
MAX_CHANGE_LEN = 35     # Kürzung pro Seite bei "alt → neu"
MAX_BYTES = 100000        # pro Meldung (ntfy erlaubt rund 4 KB)
MAX_MESSAGES = 100        # mehr Meldungen pro Sync verschicken wir nicht


# ----------------------------------------------------------------------------------------------------
# Senden
# ----------------------------------------------------------------------------------------------------

def _header(value):
    # HTTP-Header müssen Latin-1 sein, sonst ntfy-konform als RFC 2047 (UTF-8) kodieren
    try:
        value.encode('latin-1')
        return value
    except UnicodeEncodeError:
        return "=?UTF-8?B?" + base64.b64encode(value.encode('utf-8')).decode('ascii') + "?="


def send_push(message, title="Untis Sync", priority="default"):
    if not NTFY_URL:
        logging.warning("NTFY_TOPIC ist nicht gesetzt, Meldung wird nicht gesendet.")
        return
    try:
        r = requests.post(
            NTFY_URL,
            data=message.encode('utf-8'),
            headers={
                "Title": _header(title),
                "Priority": priority
            },
            timeout=10
        )
        r.raise_for_status()
    except Exception as e:
        logging.error(f"Push-Fehler: {e}")


# ----------------------------------------------------------------------------------------------------
# Formatierung
# ----------------------------------------------------------------------------------------------------

def _shorten(text, limit=MAX_TEXT_LEN):
    # Zeilenumbrüche entfernen und auf limit Zeichen kürzen
    text = " ".join(str(text if text not in (None, "") else "–").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _format_day(date_str):
    # "Fr 13.11." (Jahr nur, wenn es nicht das aktuelle ist)
    try:
        d = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return str(date_str)
    result = f"{WEEKDAYS[d.weekday()]} {d.strftime('%d.%m.')}"
    if d.year != date.today().year:
        result += str(d.year)
    return result


def _format_time(start_iso):
    return start_iso[11:16] if start_iso and len(start_iso) >= 16 else ""


def _format_when(entry):
    return f"{_format_day(entry.get('date'))} {_format_time(entry.get('start'))}".strip()


def _title_with_flag(entry):
    title = entry.get('title', '')
    return f"AUSFALL: {title}" if entry.get('cancelled') else title


def _format_change(change):
    # eine Zeile pro Änderung, einheitlich für alle Felder
    op = change.get('op', 'change')
    symbol = SYMBOLS.get(op, '~')

    if change.get('text'):
        return f"{symbol} {_shorten(change['text'])}"

    label = change.get('label') or change.get('field', '')
    if op == 'add':
        return f"{symbol} {label}: {_shorten(change.get('new'))}"
    if op == 'remove':
        return f"{symbol} {label}: {_shorten(change.get('old'))}"
    return (f"{symbol} {label}: {_shorten(change.get('old'), MAX_CHANGE_LEN)}"
            f" → {_shorten(change.get('new'), MAX_CHANGE_LEN)}")


def _day_blocks(entries, singular, plural, symbol):
    # fasst Einträge pro Tag zusammen (entries muss nach Datum sortiert sein)
    blocks = []
    for day, group in groupby(entries, key=lambda c: c.get('date')):
        group = list(group)
        n = len(group)
        lines = [f"{_format_day(day)} · {n} {singular if n == 1 else plural}"]
        for c in group:
            lines.append(f"  {symbol} {_title_with_flag(c)} {_format_time(c.get('start'))}".rstrip())
        blocks.append("\n".join(lines))
    return blocks


def _build_blocks(change_log):
    # Reihenfolge: geänderte Stunden, neue Stunden, gelöschte Stunden
    sort_key = lambda c: (c.get('date') or '', c.get('start') or '')

    updated = sorted([c for c in change_log if c.get('type') == 'updated'], key=sort_key)
    new = sorted([c for c in change_log if c.get('type') == 'new'], key=sort_key)
    deleted = sorted([c for c in change_log if c.get('type') == 'deleted'], key=sort_key)

    blocks = []
    for c in updated:
        lines = [f"{_format_when(c)} · {c.get('title', '')}"]
        lines += [f"  {_format_change(ch)}" for ch in c.get('changes', [])]
        blocks.append("\n".join(lines))

    blocks += _day_blocks(new, "neue Stunde", "neue Stunden", SYMBOLS['add'])
    blocks += _day_blocks(deleted, "Stunde gelöscht", "Stunden gelöscht", SYMBOLS['remove'])

    # high bei wichtigen Änderungen (siehe 'high' in changes.py) oder neuen Ausfällen
    high = (any(ch.get('high') for c in updated for ch in c.get('changes', []))
            or any(c.get('cancelled') for c in new))
    return blocks, high


def _pack_blocks(blocks, max_bytes=MAX_BYTES):
    # packt Blöcke in Meldungen, ohne einen Block zu zerschneiden
    chunks, current, size = [], [], 0
    for block in blocks:
        block_size = len(block.encode('utf-8')) + 2
        if current and size + block_size > max_bytes:
            chunks.append(current)
            current, size = [], 0
        current.append(block)
        size += block_size
    if current:
        chunks.append(current)
    return chunks


def _limit_bytes(text, max_bytes=4000):
    return text.encode('utf-8')[:max_bytes].decode('utf-8', errors='ignore')


def _stats_title(counts):
    parts = []
    if counts.get('new'):
        parts.append(f"{counts['new']} neu")
    if counts.get('updated'):
        parts.append(f"{counts['updated']} geändert")
    if counts.get('deleted'):
        parts.append(f"{counts['deleted']} gelöscht")
    return "Untis: " + " · ".join(parts)


def build_messages(counts, change_log):
    # gibt eine Liste von (Titel, Text, Priorität) zurück, sendet nichts
    if not (counts.get('new') or counts.get('updated') or counts.get('deleted')):
        return []

    blocks, high = _build_blocks(change_log)
    if not blocks:
        blocks = ["Änderungen erkannt (keine Details verfügbar)"]

    chunks = _pack_blocks(blocks)
    if len(chunks) > MAX_MESSAGES:
        omitted = sum(len(c) for c in chunks[MAX_MESSAGES:])
        chunks = chunks[:MAX_MESSAGES]
        chunks[-1].append(f"… und {omitted} weitere Einträge (siehe Kalender und Log)")

    if counts.get('skipped'):
        chunks[-1].append(f"Unverändert: {counts['skipped']}")

    base_title = _stats_title(counts)
    total = len(chunks)
    messages = []
    for i, chunk in enumerate(chunks, start=1):
        title = base_title if total == 1 else f"{base_title} ({i}/{total})"
        priority = "high" if (high and i == 1) else "default"
        messages.append((title, _limit_bytes("\n\n".join(chunk), MAX_BYTES + 500), priority))
    return messages


# ----------------------------------------------------------------------------------------------------
# Öffentliche Funktionen (werden von main3.0.py aufgerufen)
# ----------------------------------------------------------------------------------------------------

def send_update_notification(counts, change_log):
    for i, (title, body, priority) in enumerate(build_messages(counts, change_log)):
        if i:
            time.sleep(0.5)  # damit die Reihenfolge auf dem Handy stimmt
        send_push(body, title=title, priority=priority)


def send_error_notification(error):
    send_push(error, title="Error-Sync")


# ----------------------------------------------------------------------------------------------------
# Test: zeigt Beispielmeldungen an (ohne zu senden). Mit --send wird wirklich an ntfy geschickt.
# ----------------------------------------------------------------------------------------------------

if __name__ == "__main__":
    demo_counts = {'new': 2, 'updated': 2, 'skipped': 160, 'deleted': 1, 'silent': 0}
    demo_log = [
        {'type': 'updated', 'date': '2026-11-13', 'start': '2026-11-13T08:00:00',
         'title': 'Englisch LK (E  L2)', 'cancelled': True, 'changes': [
            {'field': 'cancelled', 'label': 'Ausfall', 'op': 'add', 'old': None, 'new': None,
             'text': 'Ausfall eingetragen', 'high': True},
            {'field': 'teaching_content', 'label': 'Lehrstoff', 'op': 'add', 'old': None,
             'new': 'Etappen der Entrechtung, Verfolgung und Vernichtung der jüdischen Bevölkerung im NS-Staat (S. 318-330)',
             'high': False},
            {'field': 'room', 'label': 'Raum', 'op': 'change', 'old': 'A101', 'new': 'B202', 'high': True},
        ]},
        {'type': 'updated', 'date': '2026-11-18', 'start': '2026-11-18T09:45:00',
         'title': 'Geschichte LK (GE L1)', 'cancelled': False, 'changes': [
            {'field': 'homework', 'label': 'Hausaufgabe', 'op': 'add', 'old': None,
             'new': 'Film anschauen, falls man am Mittwoch nicht anwesend war', 'high': True},
            {'field': 'exam', 'label': 'Klausur', 'op': 'add', 'old': None,
             'new': 'EF; Q1; Q2 Nachschreiber', 'high': True},
        ]},
        {'type': 'new', 'date': '2027-02-05', 'start': '2027-02-05T08:00:00', 'title': 'Geschichte LK (GE L1)', 'cancelled': False},
        {'type': 'new', 'date': '2027-02-05', 'start': '2027-02-05T09:45:00', 'title': 'Englisch LK (E  L2)', 'cancelled': False},
        {'type': 'deleted', 'date': '2026-11-23', 'start': '2026-11-23T11:30:00', 'title': 'Biologie (BI G1)'},
    ]

    messages = build_messages(demo_counts, demo_log)
    for title, body, priority in messages:
        print(f"=== {title}  [Priorität: {priority}] ===")
        print(body)
        print()

    if "--send" in sys.argv:
        for title, body, priority in messages:
            send_push(body, title=title, priority=priority)
        print("An ntfy gesendet.")