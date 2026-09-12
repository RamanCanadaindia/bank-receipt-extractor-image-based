import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path('tmp/ui-test-deps').resolve()))
from streamlit.testing.v1 import AppTest
from housing_drafts import encode_draft

page = next(Path('pages').glob('5_*')).resolve()
# Inject only uploads, which AppTest cannot set; all inputs, buttons and reruns are real Streamlit.
script = '''
import io
from pathlib import Path
from unittest.mock import patch
import streamlit as st
class Upload(io.BytesIO):
    def __init__(self, data, name):
        super().__init__(data)
        self.name = name
def upload(label, **kwargs):
    if 'GST190 (PDF)' in label:
        return Upload(Path('tmp/pdfs/gst190.pdf').read_bytes(), 'gst190-fill-26e.pdf')
    if 'RC7190-WS (PDF)' in label:
        return Upload(Path('tmp/pdfs/rc7190.pdf').read_bytes(), 'rc7190-ws-fill-25e.pdf')
    if '.json' in label and 'test_draft_bytes' in st.session_state:
        return Upload(st.session_state['test_draft_bytes'], 'draft.json')
    return None
st.session_state['password_correct'] = True
page = Path(PAGE_PATH)
source = page.read_text(encoding='utf-8').replace('    ensure_storage()', '    pass # no production storage in tests')
with patch('streamlit.file_uploader', side_effect=upload):
    exec(compile(source, str(page), 'exec'), {'__name__': '__main__', '__file__': str(page)})
'''.replace('PAGE_PATH', repr(str(page)))

app = AppTest.from_string(script, default_timeout=30).run()
assert not app.exception, app.exception
fields = dict(claimant='Saved Buyer', addr='100 Example St', city_val='Vancouver', prov_val='BC',
              postal_val='V6B 1A1', builder='Test Builder', price_val=1202500.0, gst_val=60125.0,
              agree_date='2026-01-02', comp_date='2026-06-03', poss_date='2026-06-04',
              is_fthb_claim=True, construction_start='', construction_end='', lang_pref='French')
app.session_state['test_draft_bytes'] = encode_draft(fields)
app.run()
next(b for b in app.button if b.label == 'Load saved information').click().run()
assert not app.exception, app.exception
assert app.text_input(key='housing_input_claimant').value == 'Saved Buyer'
assert app.number_input(key='housing_input_price_val').value == 1202500
assert app.radio(key='housing_input_lang_pref').value == 'French'
assert app.button(key='generate_gst190').disabled
app.checkbox(key='housing_allow_draft').check()
app.checkbox(key='housing_reviewed').check().run()
assert not app.button(key='generate_gst190').disabled
app.button(key='generate_gst190').click().run()
assert not app.exception, app.exception
assert any('draft generated' in x.value for x in app.success), [x.value for x in app.error]
app.button(key='generate_rc7190').click().run()
assert not app.exception, app.exception
assert any('draft generated' in x.value for x in app.success), [x.value for x in app.error]
app.text_input(key='housing_input_claimant').set_value('Edited Buyer').run()
assert app.session_state['housing_saved_fields']['claimant'] == 'Edited Buyer'
app.text_input(key='housing_input_construction_start').set_value('invalid-date').run()
assert app.button(key='generate_gst190').disabled
assert not app.exception, app.exception
print('PASS: load, restore all input types, both draft PDFs, autosave, invalid date blocking')
