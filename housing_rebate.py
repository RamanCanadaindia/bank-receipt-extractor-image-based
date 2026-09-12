"""CRA GST190 (2026) and RC7190-WS (2025) calculation and AcroForm filling.

References: https://www.canada.ca/en/revenue-agency/services/forms-publications/
forms/gst190.html and forms/rc7190-ws.html (verified September 2026).
Eligibility is a separate, explicit user declaration; amounts do not prove eligibility.
"""
from __future__ import annotations

import io
import re
import json
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
from datetime import date

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, BooleanObject, DecodedStreamObject, ArrayObject, FloatObject, DictionaryObject


def money(value):
    number = Decimal(str(value).replace(',', ''))
    if not number.is_finite() or number < 0:
        raise ValueError('Amounts must be finite and non-negative.')
    return number.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def calculate_rebate(price, gst_paid, is_fthb=False, application_type='2',
                     fair_market_value=0, builder_tax_rate='5', provincial_rebate=0,
                     prior_federal=0, prior_provincial=0, prior_ontario_fthb=0):
    p, tax = money(price), money(gst_paid)
    if application_type not in ('1A', '1B', '2', '3', '5'):
        raise ValueError('Select a valid application type.')
    group = 1 if application_type in ('1A', '2') else 3 if application_type == '3' else 2
    section = group + (3 if is_fthb else 0)
    cap = Decimal(50000 if is_fthb else 6300)
    calculation = None
    if group == 1:
        base = min(cap, tax if is_fthb else money(tax * Decimal('.36')))
        lower, upper = (Decimal(1000000), Decimal(1500000)) if is_fthb else (Decimal(350000), Decimal(450000))
        basis = p
        lines = {12: tax, 13: p} if is_fthb else {1: tax, 2: p, 3: base}
        final_line = 14 if is_fthb else 4
    else:
        rates = {'5': ('.0171', '.0477', '1.05', 1), '13': ('.0160', '.0443', '1.13', 2),
                 '14': ('.0158', '.0439', '1.14', 4), '15': ('.0157', '.0435', '1.15', 3)}
        if str(builder_tax_rate) not in rates:
            raise ValueError('Builder tax rate must be 5, 13, 14 or 15 percent.')
        standard_rate, fthb_rate, factor, calculation = rates[str(builder_tax_rate)]
        rate = Decimal(fthb_rate if is_fthb else standard_rate)
        if is_fthb and str(builder_tax_rate) in ('14', '15'):
            calculation = 3 if str(builder_tax_rate) == '14' else 4
        base = min(cap, money(p * rate))
        lower, upper = ((Decimal(1000000), Decimal(1500000)) if is_fthb else (Decimal(350000), Decimal(450000)))
        lower, upper = lower * Decimal(factor), upper * Decimal(factor)
        basis = p if group == 3 else money(fair_market_value)
        if group == 2 and basis <= 0:
            raise ValueError('Enter the fair market value of both house and land for a leased-land application.')
        if group == 2:
            lines = {15: p, 16: basis, 17: base} if is_fthb else {5: p, 6: basis, 7: base}
            final_line = 18 if is_fthb else 8
        else:
            lines = {19: p, 20: base} if is_fthb else {9: p, 10: base}
            final_line = 21 if is_fthb else 11
    rebate = base if basis <= lower else Decimal(0) if basis >= upper else money(base * (upper - basis) / (upper - lower))
    lines[final_line] = rebate
    provincial = money(provincial_rebate)
    deductions = [money(v) for v in (prior_federal, prior_provincial, prior_ontario_fthb)]
    total = rebate + provincial - sum(deductions)
    if total < 0:
        raise ValueError('Previously claimed rebates exceed the calculated total. Review the deductions.')
    gst = ({'a': tax, 'b': p, 'c': rebate, 'd': provincial, 'e': total} if group == 1 else
           {'f': p, 'g': basis, 'h': rebate, 'i': provincial, 'j': total} if group == 2 else
           {'k': p, 'l': rebate, 'm': provincial, 'n': total})
    gst.update(dict(zip(('x1', 'x2', 'x3'), deductions)))
    return {'worksheet_section': section, 'gst_section': group, 'calculation': calculation,
            'tapered': lower < basis < upper, 'rebate_rate': str(rate * 100) if group != 1 else '',
            'worksheet_lines': {str(k): f'{v:.2f}' for k, v in lines.items()},
            'gst_lines': {k: f'{v:.2f}' for k, v in gst.items()}, 'total': f'{total:.2f}',
            'federal_rebate': f'{rebate:.2f}', 'base': f'{base:.2f}'}


def field_info(pdf_bytes):
    fields = PdfReader(io.BytesIO(pdf_bytes)).get_fields() or {}
    return {k: v for k, v in fields.items() if v.get('/FT') in ('/Tx', '/Ch', '/Btn')
            and not int(v.get('/Ff', 0)) & 65536}


def _date(value):
    if not value:
        return ''
    val_str = str(value).strip()
    if not val_str:
        return ''
    try:
        return date.fromisoformat(val_str).strftime('%Y%m%d')
    except Exception:
        pass
    m_ym = re.match(r'^(\d{4})[-/.](\d{1,2})$', val_str)
    if m_ym:
        year, month = int(m_ym.group(1)), int(m_ym.group(2))
        return f'{year:04d}{month:02d}01'
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%B %d, %Y', '%b %d, %Y', '%d-%m-%Y', '%d/%m/%Y', '%Y%m%d'):
        try:
            from datetime import datetime
            return datetime.strptime(val_str, fmt).strftime('%Y%m%d')
        except Exception:
            continue
    digits = re.sub(r'\D', '', val_str)
    if len(digits) == 8:
        return digits
    elif len(digits) == 6:
        return digits + '01'
    elif len(digits) == 4:
        return digits + '0101'
    return ''


def map_housing_fields(pdf_bytes, form, data, calc):
    """Use CRA's scoped field paths and tooltips, never substring name guesses."""
    fields = field_info(pdf_bytes)
    if form == 'gst190':
        required = ('PartF_Section1[0].LineC[0]', 'claim_fthb[0]', 'LineX3[0]')
    elif form == 'rc7190':
        required = ('Section4[0].Line12[0]', 'ApplicationTypeButtons[0]', 'Section6_contd[0]')
    else:
        raise ValueError('Unknown housing form.')
    if any(not any(token in k for k in fields) for token in required):
        raise ValueError('Unsupported or non-fillable template. Use the current English CRA accessible fillable PDF.')
    profile = json.loads((Path(__file__).parent / 'config' / 'housing_form_profiles.json').read_text(encoding='utf-8'))[form]
    actual_schema = {k: [str(v.get('/FT')), str(v.get('/TU', ''))] for k, v in fields.items()}
    if actual_schema != profile:
        raise ValueError('This template differs from the verified CRA version. Use GST190 E (26) or RC7190-WS E (25), English accessible fillable PDFs.')
    values = {}
    yesno = lambda v: '/0' if v in (True, 'Yes') else '/1' if v in (False, 'No') else '/Off'
    app = data['application_type']
    for name, field in fields.items():
        path = re.sub(r'\[\d+\]', '', name).removeprefix('form1.')
        label = str(field.get('/TU', ''))
        value = None
        # Clear old answers in supplied forms; leave fixed read-only text intact.
        if not int(field.get('/Ff', 0)) & 1:
            values[name] = '/Off' if field['/FT'] == '/Btn' else ''
        if form == 'rc7190':
            if path.endswith('ApplicationTypeButtons'):
                value = '/' + str(('1A', '1B', '2', '3', '5').index(app))
            elif path.endswith(('CalculType1', 'CalculType2')):
                active = path.endswith('CalculType2') == bool(data['is_fthb'])
                value = '/' + str(calc['gst_section'] - 1) if active else '/Off'
            else:
                section = re.match(r'Section (\d+)\.', label)
                if section and int(section[1]) == calc['worksheet_section']:
                    line = re.match(r'Section \d+\. Line (\d+)\.', label)
                    operand = re.search(r'Amount from line (\d+)\.', label)
                    branch = re.search(r'Calculation (\d+)\.', label)
                    if line:
                        value = calc['worksheet_lines'].get(line[1])
                    elif 'Rebate rate percentage' in label:
                        value = calc['rebate_rate']
                    elif operand:
                        # Branch operands are needed only in the applicable taper calculation.
                        basic_operand = calc['worksheet_section'] == 1 and operand[1] == '1'
                        applicable = basic_operand or not branch or int(branch[1]) == calc['calculation']
                        taper_operand = (branch is not None and not basic_operand) or 'Line_4_Text' in path or 'Line14_Calcul' in path
                        if applicable and (not taper_operand or calc['tapered']):
                            value = calc['worksheet_lines'].get(operand[1])
                    elif 'Lesser of $50,000 and line 12' in label and calc['tapered']:
                        value = calc['base']
        else:
            line = re.search(r'PartF_Section(\d)\.Line([A-Z]\d?)\.', path)
            if line:
                if int(line[1]) == calc['gst_section']:
                    value = calc['gst_lines'].get(line[2].lower())
            elif '.PartA.' in path:
                mapping = {'ClaimantName.NameField': 'claimant_name', 'SIN.SIN_Comb': 'sin',
                           'DayPhoneNumber.DaytimePhoneNumber': 'daytime_phone', 'DayPhoneNumber.Phone_Ext': 'extension',
                           'HomePhoneNumber': 'home_phone', 'Other.OtherPurchaser1.NameField': 'other_purchaser_1',
                           'Other.OtherPurchaser2.NameField': 'other_purchaser_2', 'Address.PhysicalAddress': 'property_address',
                           'Address.City': 'city', 'Address.Province': 'province', 'Address.PostalCode': 'postal_code',
                           'Mailing.BusinessAddress': 'mailing_address', 'Mailing.City': 'mailing_city',
                           'Mailing.ProvState_DropDown': 'mailing_province', 'Mailing.PostalCode_ZIP': 'mailing_postal_code',
                           'Mailing.Country': 'mailing_country'}
                suffix = path.split('.PartA.')[1]
                if suffix in mapping:
                    value = str(data.get(mapping[suffix]) or '')
                    if suffix in ('SIN.SIN_Comb', 'Address.PostalCode'):
                        value = re.sub(r'[^A-Za-z0-9]', '', value)
                elif 'LanguagePref.' in suffix:
                    value = '/1' if data.get('language') == 'French' else '/0'
                elif 'claim_fthb.' in suffix:
                    value = yesno(data['is_fthb'])
                elif 'Claim_enhr.' in suffix:
                    value = yesno(data.get('is_enhr', False))
                elif 'Claimant_consent.' in suffix:
                    selected = data.get('onhap_assignment')
                    if ('Consent1.' in suffix and selected == 'Assigned to builder') or ('Consent2.' in suffix and selected == 'Not assigned to builder'):
                        value = yesno(data.get('onhap_consent'))
            elif '.PartB.' in path:
                suffix = path.split('.PartB.')[1]
                dates = {'PurchaseDate': 'agreement_date', 'TransferDate': 'closing_date', 'PossessionDate': 'possession_date',
                         'ConstructionDate': 'construction_start_date', 'CompletionDate': 'construction_end_date'}
                if suffix.split('.')[0] in dates:
                    value = _date(data.get(dates[suffix.split('.')[0]]))
                elif suffix.startswith('NHRMainResidence'):
                    value = yesno(data.get('primary_residence'))
                elif suffix.startswith('FTHBMainResidence') and data['is_fthb']:
                    value = yesno(data.get('primary_residence') == 'Yes' and data.get('first_to_occupy') == 'Yes')
                else:
                    key = {'Legaldescr.BusinessAddress': 'lot_number', 'Legaldescr.PlanNumber': 'plan_number',
                           'Legaldescr.Other': 'legal_description', 'Legaldescr.Manufacturer': 'manufacturer',
                           'Legaldescr.Model': 'model', 'Legaldescr.SerialNumber': 'serial_number'}.get(suffix)
                    if key:
                        value = str(data.get(key) or '')
            elif '.PartC.' in path:
                if '.HousingType.' in path:
                    value = '/' + str(data.get('housing_type_index', 0))
                else:
                    kind = re.search(r'\.Type(1A|1B|2|3|5)\.', path)
                    if kind:
                        value = '/' + str(('1A', '1B', '2', '3', '5').index(app) + 1) if kind[1] == app else '/Off'
            elif '.PartD.' in path:
                suffix = path.split('.PartD.')[1]
                mapping = {'LegalName.Name': 'builder_name', 'Address.Address': 'builder_address',
                           'Address.City': 'builder_city', 'Address.ProvinceTerritoryState_DropDown': 'builder_province',
                           'Address.International_PostalCode_ZIP': 'builder_postal_code', 'Address.Country': 'builder_country',
                           'Address.InternationalPhoneNumber.International_PhoneNumber': 'builder_phone',
                           'Address.InternationalPhoneNumber.Extension': 'builder_extension', 'Name': 'builder_official'}
                if suffix in mapping:
                    value = str(data.get(mapping[suffix]) or '')
                elif 'RefoundPayedDirectly' in suffix:
                    value = yesno(data.get('builder_paid'))
                elif 'consent3.' in suffix:
                    value = yesno(data.get('builder_consent'))
                elif suffix.endswith(('FromDate', 'ToDate')):
                    value = _date(data.get('builder_period_from' if suffix.endswith('FromDate') else 'builder_period_to'))
            elif '.PartE.Name' in path:
                value = str(data.get('claimant_name') or '')
            if path.endswith(('BusinessNumber_RT1', 'BusinessNumber_RT2')):
                bn = re.sub(r'[^0-9]', '', str(data.get('builder_business_number' if '.PartD.' in path else 'business_number') or ''))
                if bn and len(bn) not in (9, 13):
                    raise ValueError('Business numbers require 9 digits, optionally followed by RT and 4 digits.')
                value = bn[:9] if path.endswith('RT1') else bn[9:]
        if value is not None:
            values[name] = value
    return values


def fill_housing_pdf(pdf_bytes, values):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as layout:
        page_lines = [page.lines for page in layout.pages]
    reader = PdfReader(io.BytesIO(pdf_bytes))
    if any(f.get('/FT') == '/Sig' and f.get('/V') for f in (reader.get_fields() or {}).values()):
        raise ValueError('Use an unsigned template; existing signatures cannot survive form changes.')
    # CRA's Reader usage-rights signature contains malformed encrypted strings.
    # It is not a claimant signature and becomes invalid on any edit anyway.
    reader.root_object.pop(NameObject('/Perms'), None)
    reader.root_object['/AcroForm'].pop(NameObject('/XFA'), None)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    fields = writer.get_fields() or {}
    if set(values) - set(fields):
        raise ValueError('Some mapped fields are missing from the template.')
    acro = writer.root_object['/AcroForm']
    # Hybrid XFA contains separate stale values. Use the existing AcroForm and its appearances.
    acro.pop(NameObject('/XFA'), None)
    acro.pop(NameObject('/CO'), None)
    for field in fields.values():
        field.pop(NameObject('/AA'), None)
    for page in writer.pages:
        for ref in page.get('/Annots', []):
            ref.get_object().pop(NameObject('/AA'), None)
    writer.update_page_form_field_values(None, values, auto_regenerate=False)
    # CRA radio widgets also carry their own /V; pypdf updates only their parent.
    for page_index, page in enumerate(writer.pages):
        for ref in page.get('/Annots', []):
            widget = ref.get_object()
            if widget.get('/Subtype') == '/Widget':
                node, parts = widget, []
                while node is not None:
                    if '/T' in node:
                        parts.insert(0, str(node['/T']))
                    node = node['/Parent'] if '/Parent' in node else None
                key = '.'.join(parts)
                if key in values and widget.get('/T') == 'Amount[0]' and re.fullmatch(r'\d+\.\d{2}', values[key]):
                    rect = [float(v) for v in widget['/Rect']]
                    dividers = [line['x0'] - rect[0] for line in page_lines[page_index]
                                if abs(line['x0'] - line['x1']) < .1
                                and rect[0] + 5 < line['x0'] < rect[2] - 5
                                and abs(line['y0'] - rect[1]) < 2 and line['y1'] <= rect[3]]
                    if dividers:
                        divider = max(dividers)
                        dollars, cents = values[key].split('.')
                        width, height = rect[2] - rect[0], rect[3] - rect[1]
                        size = min(9, (divider - 6) / (len(dollars) * .556))
                        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
                        stream = DecodedStreamObject()
                        stream[NameObject('/Type')] = NameObject('/XObject')
                        stream[NameObject('/Subtype')] = NameObject('/Form')
                        stream[NameObject('/BBox')] = ArrayObject([FloatObject(x) for x in (0, 0, width, height)])
                        stream[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/FMoney'): font})})
                        stream.set_data((f'q BT /FMoney {size} Tf 0 0 0 rg 1 0 0 1 {divider-3-len(dollars)*size*.556} 3 Tm ({dollars}) Tj '
                                         f'1 0 0 1 {width-3-2*size*.556} 3 Tm ({cents}) Tj ET Q').encode('ascii'))
                        widget['/AP'][NameObject('/N')] = writer._add_object(stream)
                if key in values and fields[key].get('/FT') == '/Btn':
                    value = values[key]
                    widget[NameObject('/V')] = NameObject(value)
                    # Vector marks avoid the CRA's non-embedded ZapfDingbats font,
                    # which can otherwise render selected boxes as empty.
                    normal = widget['/AP']['/N']
                    rect = widget['/Rect']
                    width, height = float(rect[2] - rect[0]), float(rect[3] - rect[1])
                    for state in list(normal) + ([NameObject('/Off')] if '/Off' not in normal else []):
                        stream = DecodedStreamObject()
                        stream[NameObject('/Type')] = NameObject('/XObject')
                        stream[NameObject('/Subtype')] = NameObject('/Form')
                        stream[NameObject('/BBox')] = ArrayObject([FloatObject(x) for x in (0, 0, width, height)])
                        stream[NameObject('/Resources')] = DictionaryObject()
                        draw = 'q Q' if state == '/Off' else f'q 0 0 0 RG 1.2 w 2 2 m {width-2} {height-2} l S 2 {height-2} m {width-2} 2 l S Q'
                        stream.set_data(draw.encode('ascii'))
                        normal[NameObject(state)] = writer._add_object(stream)
    acro[NameObject('/NeedAppearances')] = BooleanObject(False)
    output = io.BytesIO()
    writer.write(output)
    result = output.getvalue()
    check = PdfReader(io.BytesIO(result))
    actual = check.get_fields() or {}
    for key, expected in values.items():
        if key not in actual or str(actual[key].get('/V', '')) != expected:
            raise ValueError(f'PDF value did not persist: {key}')
    widget_counts = dict.fromkeys(values, 0)
    for page in check.pages:
        for ref in page.get('/Annots', []):
            widget = ref.get_object()
            if widget.get('/Subtype') != '/Widget':
                continue
            node, parts, effective = widget, [], None
            while node is not None:
                if '/T' in node:
                    parts.insert(0, str(node['/T']))
                if effective is None and '/V' in node:
                    effective = str(node['/V'])
                node = node['/Parent'] if '/Parent' in node else None
            key = '.'.join(parts)
            if key in values:
                widget_counts[key] += 1
                if effective != values[key]:
                    raise ValueError(f'Widget disagrees with field value: {key}')
                appearance = widget.get('/AP', {}).get('/N')
                if appearance is None:
                    raise ValueError(f'Missing field appearance: {key}')
                if actual[key].get('/FT') == '/Btn':
                    state = str(widget.get('/AS', '/Off'))
                    expected_state = values[key] if values[key] in appearance else '/Off'
                    if state != expected_state:
                        raise ValueError(f'Incorrect checkbox appearance: {key}')
                elif not appearance.get_object().get_data():
                    raise ValueError(f'Empty field appearance: {key}')
    if any(count == 0 for count in widget_counts.values()):
        raise ValueError('Template has fields without corresponding page widgets.')
    return result
