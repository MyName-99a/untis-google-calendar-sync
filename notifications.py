import base64
import logging
import sys
import time
from datetime import date
from itertools import groupby

import requests

import config
import texts
from texts import t

"""
Expected from main3.0.py:

    counts     = {'new': int, 'updated': int, 'skipped': int, 'deleted': int, 'silent': int}
    change_log = list of entries:
        {'type': 'new' | 'deleted', 'date': 'YYYY-MM-DD', 'start': 'YYYY-MM-DDTHH:MM:SS', 'title': str, 'cancelled': bool}
        {'type': 'updated', 'date': ..., 'start': ..., 'title': str, 'cancelled': bool, 'changes': [change, ...]}

    change (comes from changes.diff_fields):
        {'field': str, 'label': str, 'op': 'add' | 'remove' | 'change',
         'old': str | None, 'new': str | None, 'text': str (optional, replaces the whole line), 'high': bool}

All visible texts (weekdays, date format, wording) come from texts.py in the configured LANGUAGE.
"""

NTFY_URL = config.NTFY_URL

SYMBOLS = {'add': '+', 'remove': '−', 'change': '~'}

MAX_TEXT_LEN = 60       # shortening for texts that teachers enter (teaching content, homework, info, ...)
MAX_CHANGE_LEN = 35     # shortening per side for "old → new"
MAX_BYTES = 100000        # per message (ntfy allows about 4 KB)
MAX_MESSAGES = 100        # we do not send more messages than this per sync


# ----------------------------------------------------------------------------------------------------
# Sending
# ----------------------------------------------------------------------------------------------------

def _header(value):
    # HTTP headers must be Latin-1, otherwise encode them as RFC 2047 (UTF-8) like ntfy expects
    try:
        value.encode('latin-1')
        return value
    except UnicodeEncodeError:
        return "=?UTF-8?B?" + base64.b64encode(value.encode('utf-8')).decode('ascii') + "?="


def send_push(message, title="Untis Sync", priority="default"):
    if not NTFY_URL:
        logging.warning("NTFY_TOPIC is not set, the notification is not sent.")
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
        logging.error(f"Push error: {e}")


# ----------------------------------------------------------------------------------------------------
# Formatting
# ----------------------------------------------------------------------------------------------------

def _shorten(text, limit=MAX_TEXT_LEN):
    # remove line breaks and shorten to limit characters
    text = " ".join(str(text if text not in (None, "") else "–").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _format_day(date_str):
    # "Fri 13 Nov" (with the year only if it is not the current one)
    try:
        d = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return str(date_str)
    date_format = texts.raw('date_short') if d.year == date.today().year else texts.raw('date_full')
    return f"{texts.raw('weekdays')[d.weekday()]} {d.strftime(date_format)}"


def _format_time(start_iso):
    return start_iso[11:16] if start_iso and len(start_iso) >= 16 else ""


def _format_when(entry):
    return f"{_format_day(entry.get('date'))} {_format_time(entry.get('start'))}".strip()


def _title_with_flag(entry):
    title = entry.get('title', '')
    return t('cancelled_title', title=title) if entry.get('cancelled') else title


def _format_change(change):
    # one line per change, the same for all fields
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
    # groups entries per day (entries must be sorted by date)
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
    # order: changed lessons, new lessons, deleted lessons
    sort_key = lambda c: (c.get('date') or '', c.get('start') or '')

    updated = sorted([c for c in change_log if c.get('type') == 'updated'], key=sort_key)
    new = sorted([c for c in change_log if c.get('type') == 'new'], key=sort_key)
    deleted = sorted([c for c in change_log if c.get('type') == 'deleted'], key=sort_key)

    blocks = []
    for c in updated:
        lines = [f"{_format_when(c)} · {c.get('title', '')}"]
        lines += [f"  {_format_change(ch)}" for ch in c.get('changes', [])]
        blocks.append("\n".join(lines))

    blocks += _day_blocks(new, t('new_lesson'), t('new_lessons'), SYMBOLS['add'])
    blocks += _day_blocks(deleted, t('deleted_lesson'), t('deleted_lessons'), SYMBOLS['remove'])

    # high priority for important changes (see 'high' in changes.py) or new cancellations
    high = (any(ch.get('high') for c in updated for ch in c.get('changes', []))
            or any(c.get('cancelled') for c in new))
    return blocks, high


def _pack_blocks(blocks, max_bytes=MAX_BYTES):
    # packs blocks into messages without cutting a block apart
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
        parts.append(t('stat_new', n=counts['new']))
    if counts.get('updated'):
        parts.append(t('stat_updated', n=counts['updated']))
    if counts.get('deleted'):
        parts.append(t('stat_deleted', n=counts['deleted']))
    return "Untis: " + " · ".join(parts)


def build_messages(counts, change_log):
    # returns a list of (title, text, priority), sends nothing
    if not (counts.get('new') or counts.get('updated') or counts.get('deleted')):
        return []

    blocks, high = _build_blocks(change_log)
    if not blocks:
        blocks = [t('no_details')]

    chunks = _pack_blocks(blocks)
    if len(chunks) > MAX_MESSAGES:
        omitted = sum(len(c) for c in chunks[MAX_MESSAGES:])
        chunks = chunks[:MAX_MESSAGES]
        chunks[-1].append(t('more_entries', n=omitted))

    if counts.get('skipped'):
        chunks[-1].append(t('unchanged', n=counts['skipped']))

    base_title = _stats_title(counts)
    total = len(chunks)
    messages = []
    for i, chunk in enumerate(chunks, start=1):
        title = base_title if total == 1 else f"{base_title} ({i}/{total})"
        priority = "high" if (high and i == 1) else "default"
        messages.append((title, _limit_bytes("\n\n".join(chunk), MAX_BYTES + 500), priority))
    return messages


# ----------------------------------------------------------------------------------------------------
# Public functions (called by main3.0.py)
# ----------------------------------------------------------------------------------------------------

def send_update_notification(counts, change_log):
    for i, (title, body, priority) in enumerate(build_messages(counts, change_log)):
        if i:
            time.sleep(0.5)  # keeps the order right on the phone
        send_push(body, title=title, priority=priority)


def send_error_notification(error):
    send_push(error, title=t('error_title'))


# ----------------------------------------------------------------------------------------------------
# Test: shows example messages (without sending). With --send they are really sent to ntfy.
#   python notifications.py              uses LANGUAGE from .env
#   LANGUAGE=de python notifications.py
# ----------------------------------------------------------------------------------------------------

if __name__ == "__main__":
    demo_counts = {'new': 2, 'updated': 2, 'skipped': 160, 'deleted': 1, 'silent': 0}
    demo_log = [
        {'type': 'updated', 'date': '2026-11-13', 'start': '2026-11-13T08:00:00',
         'title': 'English (E L2)', 'cancelled': True, 'changes': [
            {'field': 'cancelled', 'label': t('field_cancelled'), 'op': 'add', 'old': None, 'new': None,
             'text': t('cancelled_on'), 'high': True},
            {'field': 'teaching_content', 'label': t('field_teaching_content'), 'op': 'add', 'old': None,
             'new': 'Causes and course of the war, with a long text that gets shortened in the notification (p. 318-330)',
             'high': False},
            {'field': 'room', 'label': t('field_room'), 'op': 'change', 'old': 'A101', 'new': 'B202', 'high': True},
        ]},
        {'type': 'updated', 'date': '2026-11-18', 'start': '2026-11-18T09:45:00',
         'title': 'History (H L1)', 'cancelled': False, 'changes': [
            {'field': 'homework', 'label': t('field_homework'), 'op': 'add', 'old': None,
             'new': 'Watch the film if you were absent on Wednesday', 'high': True},
            {'field': 'exam', 'label': t('field_exam'), 'op': 'add', 'old': None,
             'new': 'Grade 11; Grade 12 retake', 'high': True},
        ]},
        {'type': 'new', 'date': '2027-02-05', 'start': '2027-02-05T08:00:00', 'title': 'History (H L1)', 'cancelled': False},
        {'type': 'new', 'date': '2027-02-05', 'start': '2027-02-05T09:45:00', 'title': 'English (E L2)', 'cancelled': False},
        {'type': 'deleted', 'date': '2026-11-23', 'start': '2026-11-23T11:30:00', 'title': 'Biology (B G1)'},
    ]

    messages = build_messages(demo_counts, demo_log)
    for title, body, priority in messages:
        print(f"=== {title}  [priority: {priority}] ===")
        print(body)
        print()

    if "--send" in sys.argv:
        for title, body, priority in messages:
            send_push(body, title=title, priority=priority)
        print("Sent to ntfy.")