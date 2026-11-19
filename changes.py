"""
Compares two snapshots ('fields') of a lesson and returns a list of changes.

Every change is a dictionary:
    {'field': 'room', 'label': 'Room', 'op': 'change', 'old': 'A101', 'new': 'B202', 'high': True}
    optionally also 'text' (replaces the whole line in the notification, e.g. "Marked as cancelled")

    op:   'add'    = was empty, now filled
          'remove' = was filled, now empty
          'change' = was filled and is filled, but different
    high: True = important change (triggers the high ntfy priority in notifications.py)

The label and the fixed texts come from texts.py in the configured LANGUAGE.

Add a new field:
    1. add an entry to the 'fields' dictionary in main3.0.py
    2. add an entry to FIELD_DEFS below (key, label_key, kind, high) and the label ('field_<key>') to every
       language in texts.py. Done.

kind:
    'text'         simple text (old -> new)
    'list_joined'  list that is shown as one text with commas (e.g. room, teacher)
    'list_items'   list where every entry is added/removed on its own (e.g. homework)
    'bool'         yes/no with fixed texts on_key / off_key (e.g. cancelled)
"""

from collections import Counter

import texts

# Order = order of the lines in the notification
FIELD_DEFS = [
    {'key': 'cancelled', 'label_key': 'field_cancelled', 'kind': 'bool',
     'on_key': 'cancelled_on', 'off_key': 'cancelled_off', 'high': True},
    {'key': 'time', 'label_key': 'field_time', 'kind': 'text', 'high': False},
    {'key': 'title', 'label_key': 'field_title', 'kind': 'text', 'high': False},
    {'key': 'room', 'label_key': 'field_room', 'kind': 'list_joined', 'high': True},
    {'key': 'teacher', 'label_key': 'field_teacher', 'kind': 'list_joined', 'high': True},
    {'key': 'exam', 'label_key': 'field_exam', 'kind': 'text', 'high': True},
    {'key': 'homework', 'label_key': 'field_homework', 'kind': 'list_items', 'high': True},
    {'key': 'teaching_content', 'label_key': 'field_teaching_content', 'kind': 'text', 'high': False},
    {'key': 'info', 'label_key': 'field_info', 'kind': 'text', 'high': False},
    {'key': 'text', 'label_key': 'field_text', 'kind': 'text', 'high': False},
    {'key': 'notes', 'label_key': 'field_notes', 'kind': 'text', 'high': False},
    {'key': 'substitution', 'label_key': 'field_substitution', 'kind': 'text', 'high': False},
]


# ----------------------------------------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------------------------------------

def _clean(value):
    # normalize text (unify whitespace and line breaks) so that only real changes count
    if value is None:
        return ""
    return " ".join(str(value).split())


def _clean_list(values):
    return [c for c in (_clean(v) for v in (values or [])) if c]


def _make(spec, op, old=None, new=None, text=None):
    change = {
        'field': spec['key'],
        'label': texts.t(spec['label_key']),
        'op': op,
        'old': old,
        'new': new,
        'high': spec.get('high', False),
    }
    if text:
        change['text'] = text
    return change


def _view(fields):
    # add derived values to the snapshot (e.g. 'time' from start and end)
    view = dict(fields)
    start = fields.get('start') or ''
    end = fields.get('end') or ''
    view['time'] = f"{start[11:16]}–{end[11:16]}" if start and end else ""
    return view


# ----------------------------------------------------------------------------------------------------
# Comparison per kind of field
# ----------------------------------------------------------------------------------------------------

def _diff_text(spec, old, new):
    o, n = _clean(old), _clean(new)
    if o == n:
        return []
    if not o:
        return [_make(spec, 'add', None, n)]
    if not n:
        return [_make(spec, 'remove', o, None)]
    return [_make(spec, 'change', o, n)]


def _diff_list_joined(spec, old, new):
    return _diff_text(spec, ", ".join(_clean_list(old)), ", ".join(_clean_list(new)))


def _diff_list_items(spec, old, new):
    old_items = _clean_list(old)
    new_items = _clean_list(new)
    removed = Counter(old_items) - Counter(new_items)
    added = Counter(new_items) - Counter(old_items)

    result = []
    for item in old_items:                      # keep the original order
        if removed[item] > 0:
            removed[item] -= 1
            result.append(_make(spec, 'remove', item, None))
    for item in new_items:
        if added[item] > 0:
            added[item] -= 1
            result.append(_make(spec, 'add', None, item))
    return result


def _diff_bool(spec, old, new):
    o, n = bool(old), bool(new)
    if o == n:
        return []
    if n:
        return [_make(spec, 'add', text=texts.t(spec['on_key']))]
    return [_make(spec, 'remove', text=texts.t(spec['off_key']))]


_HANDLERS = {
    'text': _diff_text,
    'list_joined': _diff_list_joined,
    'list_items': _diff_list_items,
    'bool': _diff_bool,
}


# ----------------------------------------------------------------------------------------------------
# Public function (called by main3.0.py)
# ----------------------------------------------------------------------------------------------------

def diff_fields(old_fields, new_fields):
    """Returns a list of changes (empty if nothing differs or there is no old snapshot)."""
    if not old_fields or new_fields is None:
        return []

    old_view = _view(old_fields)
    new_view = _view(new_fields)

    result = []
    for spec in FIELD_DEFS:
        handler = _HANDLERS[spec['kind']]
        result.extend(handler(spec, old_view.get(spec['key']), new_view.get(spec['key'])))
    return result


# ----------------------------------------------------------------------------------------------------
# Test: python changes.py
# ----------------------------------------------------------------------------------------------------

if __name__ == "__main__":
    old = {
        'title': 'English (E L2)', 'start': '2026-11-13T08:00:00', 'end': '2026-11-13T08:45:00',
        'room': ['A101'], 'teacher': ['DRK (Druschke)'], 'cancelled': False,
        'homework': ['Read page 12'], 'teaching_content': '', 'exam': '',
        'info': '', 'text': '', 'notes': '', 'substitution': '',
    }
    new = dict(old)
    new.update({
        'cancelled': True,
        'room': ['B202'],
        'homework': ['Read page 12', 'Watch the film'],
        'teaching_content': 'Causes of the war (p. 318-330)',
        'exam': 'Grade 11; Grade 12 retake',
        'end': '2026-11-13T09:00:00',
    })

    for c in diff_fields(old, new):
        print(c)

    # simple checks
    assert diff_fields(old, old) == []
    assert diff_fields(None, new) == []
    fields_changed = {c['field'] for c in diff_fields(old, new)}
    assert fields_changed == {'cancelled', 'room', 'homework', 'teaching_content', 'exam', 'time'}, fields_changed
    assert [c['op'] for c in diff_fields(new, old) if c['field'] == 'cancelled'] == ['remove']
    print("\nAll tests passed.")