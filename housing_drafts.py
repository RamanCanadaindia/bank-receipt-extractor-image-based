"""Portable, user-controlled housing drafts; never store client data in a shared database."""
import json
import math
from pathlib import Path

SPECS = json.loads((Path(__file__).parent / 'config' / 'housing_draft_fields.json').read_text(encoding='utf-8'))
PREFIX = 'housing_input_'


def validate_fields(fields):
    if not isinstance(fields, dict) or set(fields) - set(SPECS):
        raise ValueError('This draft contains unrecognized fields.')
    result = {}
    for key, value in fields.items():
        spec = SPECS[key]
        if spec['type'] == 'number_input':
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f'Invalid amount in {key}.')
            value = float(value)
        elif spec['type'] == 'checkbox':
            if not isinstance(value, bool):
                raise ValueError(f'Invalid selection in {key}.')
        elif not isinstance(value, str) or len(value) > 20000:
            raise ValueError(f'Invalid text in {key}.')
        if 'options' in spec and value not in spec['options']:
            raise ValueError(f'Unrecognized selection in {key}.')
        result[key] = value
    return result


def encode_draft(fields):
    return json.dumps({'format': 'housing-rebate-draft', 'version': 1,
                       'fields': validate_fields(fields)}, indent=2, ensure_ascii=False).encode('utf-8')


def decode_draft(raw):
    if len(raw) > 2_000_000:
        raise ValueError('Draft file is too large.')
    try:
        draft = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Choose a valid housing draft JSON file.') from exc
    if not isinstance(draft, dict) or draft.get('format') != 'housing-rebate-draft' or draft.get('version') != 1:
        raise ValueError('Choose a housing draft saved by this form filler.')
    return validate_fields(draft.get('fields'))


def restore_draft(state, fields):
    """Call before rendering any input widgets. Replace, rather than merge, clients."""
    fields = validate_fields(fields)
    for key in SPECS:
        state.pop(PREFIX + key, None)
    state['housing_saved_fields'] = fields.copy()
    state.pop('extracted_soa', None)
    for key in list(state):
        if key.startswith(('housing_gst190_', 'housing_rc7190_')):
            del state[key]
    state['housing_reviewed'] = False
    state['housing_allow_draft'] = False
    for key, value in fields.items():
        state[PREFIX + key] = value


def remember_fields(state):
    fields = dict(state.get('housing_saved_fields', {}))
    for key in SPECS:
        if PREFIX + key in state:
            fields[key] = state[PREFIX + key]
    state['housing_saved_fields'] = validate_fields(fields)
    return fields
