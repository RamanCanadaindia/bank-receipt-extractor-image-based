import io
import unittest
from pathlib import Path

from pypdf import PdfReader
from housing_rebate import calculate_rebate, map_housing_fields, fill_housing_pdf


class CalculationTests(unittest.TestCase):
    def test_standard_boundaries(self):
        for price, expected in [(350000, '6300.00'), (400000, '3150.00'), (450000, '0.00')]:
            self.assertEqual(calculate_rebate(price, price * .05)['total'], expected)

    def test_fthb_boundaries_and_prior_claim(self):
        for price, expected in [(1000000, '50000.00'), (1202500, '29750.00'), (1500000, '0.00')]:
            self.assertEqual(calculate_rebate(price, price * .05, True)['total'], expected)
        self.assertEqual(calculate_rebate(300000, 15000, True, prior_federal=5400)['total'], '9600.00')

    def test_all_sections_and_rates(self):
        for app, group in [('1A', 1), ('2', 1), ('1B', 2), ('5', 2), ('3', 3)]:
            for first in (False, True):
                for tax_rate in ('5', '13', '14', '15'):
                    result = calculate_rebate(300000, 15000, first, app, 350000, tax_rate)
                    self.assertEqual(result['worksheet_section'], group + 3 * first)
                    self.assertEqual(result['gst_section'], group)
                    self.assertNotIn('12' if not first else '1', result['worksheet_lines'])

    def test_invalid_input(self):
        for amount in (-1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                calculate_rebate(amount, 1)
        with self.assertRaises(ValueError):
            calculate_rebate(300000, 15000, application_type='5')
        with self.assertRaises(ValueError):
            calculate_rebate(300000, 15000, prior_federal=999999)


class OfficialTemplateTests(unittest.TestCase):
    """Download current English CRA fillable templates into tmp/pdfs to run integration tests."""
    @classmethod
    def setUpClass(cls):
        if not all(Path(f'tmp/pdfs/{name}.pdf').exists() for name in ('gst190', 'rc7190')):
            raise unittest.SkipTest('Official templates absent: see docs/housing-rebate.md')

    def test_actual_forms(self):
        data = dict(claimant_name='TEST BUYER', other_purchaser_1='SECOND BUYER', other_purchaser_2='THIRD BUYER',
                    property_address='100 Test Street', city='Vancouver', province='BC', postal_code='V6B 1A1',
                    mailing_address='200 Mailing Road', mailing_city='Victoria', mailing_province='BC',
                    mailing_postal_code='V8W 1A1', builder_name='TEST BUILDER', builder_business_number='123456789RT0001',
                    business_number='987654321RT0002', agreement_date='2026-01-02', closing_date='2026-06-03',
                    possession_date='2026-06-04', construction_start_date='2025-06-01', construction_end_date='2026-06-01',
                    primary_residence='Yes', first_to_occupy='Yes', application_type='2', is_fthb=True)
        for app in ('1A', '1B', '2', '3', '5'):
            for first in (False, True):
                data.update(application_type=app, is_fthb=first)
                calc = calculate_rebate(1202500, 60125, first, app, 1262625)
                for name in ('gst190', 'rc7190'):
                    source = Path(f'tmp/pdfs/{name}.pdf').read_bytes()
                    mapped = map_housing_fields(source, name, data, calc)
                    result = fill_housing_pdf(source, mapped)
                    fields = PdfReader(io.BytesIO(result)).get_fields()
                    self.assertEqual(len(PdfReader(io.BytesIO(result)).pages), 10 if name == 'gst190' else 7)
                    if name == 'gst190':
                        def val(fragment):
                            return next(str(f.get('/V', '')) for k, f in fields.items() if fragment in k and f.get('/FT'))
                        self.assertEqual(val('OtherPurchaser1[0].NameField'), 'SECOND BUYER')
                        self.assertEqual(val('OtherPurchaser2[0].NameField'), 'THIRD BUYER')
                        self.assertEqual(val('Mailing[0].City'), 'Victoria')
                        self.assertEqual(val('PurchaseAgreementDate[0].Date'), '20260102')
                        self.assertEqual(val('PartD[0].BusinessNumber[0].BusinessNumber[0].BusinessNumber_RT1'), '123456789')
                        self.assertEqual(val('PartD[0].BusinessNumber[0].BusinessNumber[0].BusinessNumber_RT2'), '0001')
                    if app == '2' and first:
                        Path(f'tmp/pdfs/{name}-verified.pdf').write_bytes(result)

    def test_wrong_template_rejected(self):
        with self.assertRaises(ValueError):
            map_housing_fields(Path('tmp/pdfs/gst190.pdf').read_bytes(), 'rc7190', {}, {})


if __name__ == '__main__':
    unittest.main()
