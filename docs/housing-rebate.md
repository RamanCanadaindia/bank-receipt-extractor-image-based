# Housing rebate form filler

Verified against CRA's English accessible fillable **GST190 E (26)** and
**RC7190-WS E (25)**, downloaded September 11, 2026:

- https://www.canada.ca/en/revenue-agency/services/forms-publications/forms/gst190.html
- https://www.canada.ca/en/revenue-agency/services/forms-publications/forms/rc7190-ws.html

The housing workflow uses `housing_rebate.py`; the universal PDF workflow remains
separate. `config/housing_form_profiles.json` stores the verified field names,
types and tooltips. A different schema is rejected instead of guessed. Recheck
the form and update the profile when CRA publishes a new version. French forms
and older templates are not supported by this mapping.

All application types (1A, 1B, 2, 3, 5) route to their own calculation sections.
Only the selected standard or FTHB worksheet section is populated. Decimal
arithmetic rounds money to cents. Leased-land/co-op calculations require the
builder's actual tax rate; leased-land applications also require fair market
value. Provincial schedule results and applicable prior rebates are entered
explicitly, not inferred. The software does not establish eligibility or compute
the separate Ontario schedule or ONHAP payment.

Completed forms remain editable. Existing answers are cleared, fixed read-only
text is retained, XFA is removed to prevent conflicting values, and checkbox
appearances are drawn without font dependencies. Every written value is checked
against both the field tree and page widgets. Signatures and signing dates must
be completed by the signers; the builder must review and complete Part D.

## Verification

### Save and resume

Inputs automatically survive reruns within the same session. Use **Save my
information for later** to download a JSON draft before closing the browser.
Use **Open saved information** and **Load saved information** to restore it in
a later session. Files include entered personal information and must be kept
private. Source documents and PDF templates are not included. No shared server
database of client drafts is created.

Missing dates or identity details can be left blank by explicitly choosing
**Generate an editable draft with the missing details left blank**. These
downloads are named `DRAFT_...pdf` and a missing-information checklist is offered.
They are incomplete and must be completed before filing. Invalid dates,
inconsistent eligibility facts and calculation errors still block generation.

Run `python -m unittest test_housing_drafts -v` for save/load validation and
`python tests/housing_ui_check.py` for the Streamlit interaction test (requires
Streamlit and the official PDFs described below).

Run `python -m unittest test_housing_rebate -v`.
For the official-form integration tests, download the accessible PDFs above as
`tmp/pdfs/gst190.pdf` and `tmp/pdfs/rc7190.pdf`. The test fills and reopens both
forms for every application type and both rebate modes, and produces two
synthetic Type 2 FTHB examples in `tmp/pdfs/*-verified.pdf` for rendering.
Without these templates, the integration tests explicitly skip.

Render examples with `pdftoppm -png` and inspect identity, date, checkbox and
amount fields. Tests do not file claims or send source documents anywhere.
The existing optional Gemini extraction sends uploaded source documents only
when the user runs that extraction action. Review extracted facts before filling.
