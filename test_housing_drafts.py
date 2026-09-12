import unittest
from housing_drafts import encode_draft, decode_draft, restore_draft, remember_fields


class DraftTests(unittest.TestCase):
    def test_round_trip(self):
        fields = dict(claimant='Test Buyer', price_val=1202500.0, is_fthb_claim=True,
                      construction_start='', lang_pref='French', prior_federal=123.45,
                      app_type='Type 5 (Directly with CRA - Lease land)')
        self.assertEqual(decode_draft(encode_draft(fields)), fields)

    def test_restore_replaces_client_and_clears_review(self):
        state = {'housing_input_sin_val': '999999999', 'extracted_soa': {'claimant_name': 'Old'},
                 'housing_gst190_old': b'old-pdf', 'housing_reviewed': True}
        restore_draft(state, {'claimant': 'New'})
        self.assertNotIn('housing_input_sin_val', state)
        self.assertNotIn('extracted_soa', state)
        self.assertNotIn('housing_gst190_old', state)
        self.assertFalse(state['housing_reviewed'])
        self.assertEqual(remember_fields(state), {'claimant': 'New'})

    def test_reject_invalid_without_modifying_session(self):
        for raw in (b'{}', b'null', b'not json', b'{"format":"housing-rebate-draft","version":1,"fields":{"price_val":-1}}'):
            with self.assertRaises(ValueError):
                decode_draft(raw)
        state = {'housing_input_claimant': 'Keep'}
        with self.assertRaises(ValueError):
            restore_draft(state, {'unexpected': 'value'})
        self.assertEqual(state, {'housing_input_claimant': 'Keep'})

    def test_hidden_fields_survive(self):
        state = {'housing_saved_fields': {'manufacturer': 'Test Factory'}, 'housing_input_claimant': 'Buyer'}
        self.assertEqual(remember_fields(state)['manufacturer'], 'Test Factory')


if __name__ == '__main__':
    unittest.main()
