"""
Vergleicht zwei Snapshots ('fields') einer Stunde und liefert eine Liste von Änderungen.

Jede Änderung ist ein Dictionary:
    {'field': 'room', 'label': 'Raum', 'op': 'change', 'old': 'A101', 'new': 'B202', 'high': True}
    optional zusätzlich 'text' (ersetzt die ganze Zeile in der Meldung, z. B. "Ausfall eingetragen")

    op:   'add'    = vorher leer, jetzt gefüllt
          'remove' = vorher gefüllt, jetzt leer
          'change' = vorher und jetzt gefüllt, aber anders
    high: True = wichtige Änderung (löst in notifications.py die hohe ntfy-Priorität aus)

Neues Feld ergänzen:
    1. in main3.0.py im 'fields'-Dictionary einen Eintrag hinzufügen
    2. unten in FIELD_DEFS einen Eintrag hinzufügen (key, label, kind, high). Fertig.

kind:
    'text'         einfacher Text (alt -> neu)
    'list_joined'  Liste, die als ein Text mit Komma angezeigt wird (z. B. Raum, Lehrer)
    'list_items'   Liste, bei der jeder Eintrag einzeln hinzugefügt/entfernt wird (z. B. Hausaufgaben)
    'bool'         Ja/Nein mit festen Texten 'on' / 'off' (z. B. Ausfall)
"""

from collections import Counter

# Reihenfolge = Reihenfolge der Zeilen in der Meldung
FIELD_DEFS = [
    {'key': 'cancelled', 'label': 'Ausfall', 'kind': 'bool',
     'on': 'Ausfall eingetragen', 'off': 'Ausfall aufgehoben', 'high': True},
    {'key': 'time', 'label': 'Zeit', 'kind': 'text', 'high': False},
    {'key': 'title', 'label': 'Fach', 'kind': 'text', 'high': False},
    {'key': 'room', 'label': 'Raum', 'kind': 'list_joined', 'high': True},
    {'key': 'teacher', 'label': 'Lehrer', 'kind': 'list_joined', 'high': True},
    {'key': 'exam', 'label': 'Klausur', 'kind': 'text', 'high': True},
    {'key': 'homework', 'label': 'Hausaufgabe', 'kind': 'list_items', 'high': True},
    {'key': 'teaching_content', 'label': 'Lehrstoff', 'kind': 'text', 'high': False},
    {'key': 'info', 'label': 'Info', 'kind': 'text', 'high': False},
    {'key': 'text', 'label': 'Text', 'kind': 'text', 'high': False},
    {'key': 'notes', 'label': 'Notes', 'kind': 'text', 'high': False},
    {'key': 'substitution', 'label': 'Vertretung', 'kind': 'text', 'high': False},
]


# ----------------------------------------------------------------------------------------------------
# Hilfsfunktionen
# ----------------------------------------------------------------------------------------------------

def _clean(value):
    # Text normalisieren (Whitespace und Zeilenumbrüche vereinheitlichen), damit nur echte Änderungen zählen
    if value is None:
        return ""
    return " ".join(str(value).split())


def _clean_list(values):
    return [c for c in (_clean(v) for v in (values or [])) if c]


def _make(spec, op, old=None, new=None, text=None):
    change = {
        'field': spec['key'],
        'label': spec['label'],
        'op': op,
        'old': old,
        'new': new,
        'high': spec.get('high', False),
    }
    if text:
        change['text'] = text
    return change


def _view(fields):
    # Snapshot um abgeleitete Werte ergänzen (z. B. 'time' aus start und end)
    view = dict(fields)
    start = fields.get('start') or ''
    end = fields.get('end') or ''
    view['time'] = f"{start[11:16]}–{end[11:16]}" if start and end else ""
    return view


# ----------------------------------------------------------------------------------------------------
# Vergleich je Feldart
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
    for item in old_items:                      # Reihenfolge wie im Original beibehalten
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
        return [_make(spec, 'add', text=spec['on'])]
    return [_make(spec, 'remove', text=spec['off'])]


_HANDLERS = {
    'text': _diff_text,
    'list_joined': _diff_list_joined,
    'list_items': _diff_list_items,
    'bool': _diff_bool,
}


# ----------------------------------------------------------------------------------------------------
# Öffentliche Funktion (wird von main3.0.py aufgerufen)
# ----------------------------------------------------------------------------------------------------

def diff_fields(old_fields, new_fields):
    """Gibt eine Liste von Änderungen zurück (leer, wenn nichts anders ist oder kein alter Snapshot da ist)."""
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
        'title': 'Englisch LK (E  L2)', 'start': '2026-11-13T08:00:00', 'end': '2026-11-13T08:45:00',
        'room': ['A101'], 'teacher': ['DRK (Druschke)'], 'cancelled': False,
        'homework': ['Seite 12 lesen'], 'teaching_content': '', 'exam': '',
        'info': '', 'text': '', 'notes': '', 'substitution': '',
    }
    new = dict(old)
    new.update({
        'cancelled': True,
        'room': ['B202'],
        'homework': ['Seite 12 lesen', 'Film anschauen'],
        'teaching_content': 'Etappen der Entrechtung (S. 318-330)',
        'exam': 'EF; Q1; Q2 Nachschreiber',
        'end': '2026-11-13T09:00:00',
    })

    for c in diff_fields(old, new):
        print(c)

    # einfache Prüfungen
    assert diff_fields(old, old) == []
    assert diff_fields(None, new) == []
    fields_changed = {c['field'] for c in diff_fields(old, new)}
    assert fields_changed == {'cancelled', 'room', 'homework', 'teaching_content', 'exam', 'time'}, fields_changed
    assert [c['op'] for c in diff_fields(new, old) if c['field'] == 'cancelled'] == ['remove']
    print("\nAlle Tests bestanden.")