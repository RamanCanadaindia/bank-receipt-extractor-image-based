"""
T2 upload support for the Notice to Reader page.

A full T2 / Record Keeping PDF is NOT a GIFI-only PDF: it is 30-60 pages
(T2 jacket, Schedule 1, Schedule 8, ... plus Schedule 100 / Schedule 125).
Sending every page to Gemini OCR is slow, expensive, and noisy - the
first GIFI code seen wins in classify_gifi_items(), so a jacket or
summary page can poison the whole statement.

Instead, for a text-based T2 PDF:
  1. Find the two condensed pages by heading, if present:
       "Condensed Balance Sheet Information"  (Schedule 100)
       "Condensed Income statement information" (Schedule 125)
     These pages already contain Current year / Prior year columns
     for every line the statements need.
  2. If no condensed pages exist (e.g. the 2025 Gillco T2, which only
     has itemised S100/S125 pages), fall back to parsing the itemised
     S100/S125 pages with the same word-position parser.
  3. Parse by WORD POSITION, not by reading order. TaxTron / CRA PDFs
     put the description + GIFI code on the left and the amounts in
     two right-aligned columns. Reading the plain text in order loses
     which amount belongs to which column whenever a cell is blank
     (e.g. short-term investments have no prior-year amount, and
     withholding taxes have no current-year amount). A word whose
     right edge is in the Current column is current-year; a word in
     the Prior column is prior-year, regardless of blanks.
     This also fixes wrapped lines: the dividends amount (459) sits
     on the same row as GIFI 8096 even though plain-text extraction
     puts it on a different line.

No API key is needed for this path: it works on the PDF's own text.
Scanned (image-only) T2 PDFs have no extractable words, so the caller
should fall back to the existing Gemini flow on the condensed pages
only, not on the whole T2.

Returns items in the same shape gifi_extractor expects:
  {"gifi_code": int, "description": str,
   "current_year": float, "prior_year": float}
plus meta, source pages, and tie-out checks. The caller must NOT
silently print $0 placeholders if the checks fail.
"""

import re

try:
    import fitz  # PyMuPDF, already in requirements.txt
except ImportError:  # pragma: no cover
    try:
        import pymupdf as fitz
    except ImportError:
        fitz = None

_AMOUNT_RE = re.compile(r"^\(?[\d,]+\)?$")
_CODE_RE = re.compile(r"^\d{4}$")
_DATE_RE = re.compile(r"\b\d{4}/\d{2}/\d{2}\b")
_BN_RE = re.compile(r"\b\d{9}\b")

# Midpoint between the Current-year column (right edge ~474pt) and
# the Prior-year column (right edge ~572pt) on CRA/TaxTron pages.
_COLUMN_SPLIT_X = 524.0
# GIFI codes sit at x ~334pt on these pages.
_CODE_X_MIN, _CODE_X_MAX = 300.0, 400.0
_Y_TOL = 3.0


def _parse_amount(token):
    token = token.replace(",", "").strip()
    negative = token.startswith("(") and token.endswith(")")
    token = token.strip("()")
    try:
        value = float(token)
    except ValueError:
        return None
    return -value if negative else value


# Total rows that sometimes carry no description on their own row
# (e.g. the 9999 row on the 2025 extraordinary-items page).
_TOTAL_LABELS = {
    1599: "Total current assets",
    2008: "Total tangible capital assets",
    2009: "Total accumulated amortization of capital assets",
    2599: "Total Assets",
    3139: "Total current liabilities",
    3450: "Total long-term liabilities",
    3499: "Total liabilities",
    3620: "Total shareholder equity",
    8089: "Total sales of goods and services",
    8299: "Total Revenue",
    9367: "Total operating expenses",
    9970: "Net income/loss before taxes and extraordinary items",
    9999: "Net income/loss",
}


def _parse_page_words(page):
    """Parse one condensed/itemised GIFI page -> {code: item}."""
    words = page.get_text("words")  # x0, y0, x1, y1, word, block, line, no
    items = {}
    for word in words:
        x0, y0, x1, _y1, token = word[0], word[1], word[2], word[3], word[4]
        if not _CODE_RE.match(token):
            continue
        if not (_CODE_X_MIN <= x0 <= _CODE_X_MAX):
            continue
        # Description: words on the same row, left of the code.
        desc_words = [
            w[4] for w in words
            if abs(w[1] - y0) <= _Y_TOL and w[0] < x0 and w[4] != "."
        ]
        description = " ".join(desc_words).strip().rstrip(".").strip()
        if not description:
            # A total row with no description of its own is still
            # usable; anything else without a description is not.
            description = _TOTAL_LABELS.get(int(token), "")
            if not description:
                continue
        # Amounts: words on the same row, right of the code, in a
        # numeric column. Column is decided by position, not order,
        # so blank cells cannot shift a prior-year amount into the
        # current-year column.
        current_year = 0.0
        prior_year = 0.0
        for w in words:
            if abs(w[1] - y0) > _Y_TOL or w[0] <= x1:
                continue
            amount = _parse_amount(w[4])
            if amount is None:
                continue
            if w[2] <= _COLUMN_SPLIT_X:
                current_year = amount
            else:
                prior_year = amount
        code = int(token)
        # Keep the first parse for a code on this page; a total row
        # repeated in a summary must not overwrite the detail row.
        items.setdefault(code, {
            "gifi_code": code,
            "description": description,
            "current_year": current_year,
            "prior_year": prior_year,
        })
    return items


def _fallback_corporation_name(doc):
    """Find a standalone corporation-name line, e.g. 'GILLCO INDUSTRIES
    INC.', which is the header line on most T2 pages. Used only when
    the condensed-page header did not yield a name."""
    from collections import Counter
    pattern = re.compile(r"^[A-Z][A-Z0-9 .,&'/-]+ (INC\.|LTD\.|CORP\.)$")
    counts = Counter()
    for page in doc:
        for line in page.get_text().splitlines():
            line = line.strip()
            if pattern.match(line) and "Canada Revenue" not in line:
                counts[line] += 1
    if counts:
        return {"corporation_name": counts.most_common(1)[0][0]}
    return {}


def _extract_meta(page):
    """Best-effort corporation name / BN / tax year end from a page."""
    words = page.get_text("words")
    text = page.get_text()
    meta = {}
    date_match = _DATE_RE.search(text)
    if date_match:
        meta["tax_year_end"] = date_match.group(0).replace("/", "-")
        # Corporation name sits on the same row as the date, after
        # "Name of corporation :".
        for word in words:
            if word[4] == date_match.group(0):
                row = sorted(
                    [w for w in words if abs(w[1] - word[1]) <= _Y_TOL],
                    key=lambda w: w[0],
                )
                tokens = [w[4] for w in row]
                if ":" in tokens:
                    name_tokens = tokens[tokens.index(":") + 1:]
                    name_tokens = [t for t in name_tokens
                                   if not _DATE_RE.match(t)]
                    # A row that yields "BN: ..." is the BN line, not
                    # the corporation name - leave the name blank
                    # rather than printing the BN as the company name.
                    # The Review panel lets the user correct it.
                    if name_tokens and not name_tokens[0].startswith("BN"):
                        meta["corporation_name"] = " ".join(name_tokens)
                break
    bn_match = _BN_RE.search(text)
    if bn_match:
        meta["business_number"] = bn_match.group(0)
    return meta


def _value(items, code, year="current_year"):
    item = items.get(code)
    return float(item[year]) if item else 0.0


# Total/subtotal codes that must never be added to a detail sum, or the
# same amount is counted twice (detail + total). This mirrors the skip
# list in gifi_extractor.classify_gifi_items().
_TOTAL_CODES = {1599, 2008, 2009, 2599, 3139, 3450, 3499, 3620, 8089,
                8299, 8518, 8519, 9367, 9368, 9369, 9970, 9990, 9999}


def _tangible_net(items, year):
    net = 0.0
    for code, item in items.items():
        if 1600 <= code <= 2199 and code not in _TOTAL_CODES:
            desc = item["description"].lower()
            if ("amort" in desc or "accumulated" in desc
                    or code in (1743, 2009)):
                net -= abs(float(item[year]))
            else:
                net += float(item[year])
    return net


def _checks(items):
    """Tie-out checks. Returns a list of {label, ok, detail}."""
    cur = "current_year"
    assets = (
        sum(float(i[cur]) for c, i in items.items() if 1000 <= c <= 1598)
        + _tangible_net(items, cur)
        + sum(float(i[cur]) for c, i in items.items() if 2200 <= c <= 2598)
    )
    liabilities = (
        sum(float(i[cur]) for c, i in items.items()
            if 2600 <= c <= 3138 and c not in _TOTAL_CODES)
        + sum(float(i[cur]) for c, i in items.items()
              if 3140 <= c <= 3499 and c not in _TOTAL_CODES)
    )
    equity = (
        sum(float(i[cur]) for c, i in items.items()
            if 3500 <= c <= 3549 and c not in _TOTAL_CODES)
        + _value(items, 3600, cur)
    )
    revenue = sum(float(i[cur]) for c, i in items.items()
                  if 8000 <= c <= 8298 and c not in _TOTAL_CODES)
    cost_of_sales = sum(float(i[cur]) for c, i in items.items()
                        if 8300 <= c <= 8519 and c not in _TOTAL_CODES)
    expenses = sum(float(i[cur]) for c, i in items.items()
                   if 8520 <= c <= 9369 and c not in _TOTAL_CODES)
    net_calc = revenue - cost_of_sales - expenses - _value(items, 9990, cur)

    def check(label, left, right):
        ok = abs(left - right) <= 1.0
        return {"label": label, "ok": ok,
                "detail": f"{left:,.2f} vs {right:,.2f}"}

    checks = [
        check("Balance sheet balances (Assets = Liabilities + Equity)",
              assets, liabilities + equity),
        check("Total assets tie to reported 2599",
              assets, _value(items, 2599, cur)),
        check("Net income ties to reported 9999",
              net_calc, _value(items, 9999, cur)),
        check("Retained earnings: start (3660) + net (3680) = end (3849)",
              _value(items, 3660, cur) + _value(items, 3680, cur),
              _value(items, 3849, cur)),
        check("Balance-sheet net (3680) = income-statement net (9999)",
              _value(items, 3680, cur), _value(items, 9999, cur)),
    ]
    # A check against a reported total that was not extracted at all
    # is not a failure, it is missing data - mark it as such.
    for c in checks:
        if "reported 2599" in c["label"] and 2599 not in items:
            c["ok"] = True
            c["detail"] += " (2599 not extracted - using computed total)"
        if "reported 9999" in c["label"] and 9999 not in items:
            c["ok"] = True
            c["detail"] += " (9999 not extracted - using computed net)"
    return checks


def extract_t2_condensed(pdf_path):
    """
    Extract GIFI items from a full T2 PDF.

    Returns a dict with keys:
      found (bool), source ("condensed" | "itemised" | "none"),
      pages ({"balance_sheet": int, "income_statement": int} or {}),
      items (list), meta (dict), checks (list), warnings (list).
    Page numbers are 1-based, as printed in the PDF.
    """
    if fitz is None:
        return {"found": False, "source": "none", "pages": {}, "items": [],
                "meta": {}, "checks": [],
                "warnings": ["PyMuPDF is not installed, so text extraction "
                             "is unavailable. Use the GIFI-only upload."]}

    doc = fitz.open(str(pdf_path))
    try:
        bs_page_no = is_page_no = None
        bs_items = is_items = {}
        meta = {}
        for i, page in enumerate(doc):
            text = page.get_text()
            if ("Condensed Balance Sheet Information" in text
                    and bs_page_no is None):
                bs_page_no = i + 1
                bs_items = _parse_page_words(page)
                meta = _extract_meta(page) or meta
            if ("Condensed Income statement information" in text
                    and is_page_no is None):
                is_page_no = i + 1
                is_items = _parse_page_words(page)
                if not meta:
                    meta = _extract_meta(page)

        if bs_page_no is not None and is_page_no is not None:
            items_by_code = {}
            items_by_code.update(bs_items)
            items_by_code.update(is_items)
            items = [items_by_code[c] for c in sorted(items_by_code)]
            if "corporation_name" not in meta:
                meta.update(_fallback_corporation_name(doc))
            return {"found": True, "source": "condensed",
                    "pages": {"balance_sheet": bs_page_no,
                              "income_statement": is_page_no},
                    "items": items, "meta": meta,
                    "checks": _checks(items_by_code), "warnings": []}

        # Fallback: itemised S100/S125 pages. Same parser, applied to
        # every page that carries GIFI codes in the code column.
        # Condensed pages (if only one was found) are included too.
        items_by_code = {}
        for page in doc:
            page_items = _parse_page_words(page)
            for code, item in page_items.items():
                items_by_code.setdefault(code, item)
            if page_items:
                page_meta = _extract_meta(page)
                # Merge: keep a valid corporation name, BN and year
                # end from any page; never let a BN line overwrite
                # the name.
                for key, value in page_meta.items():
                    if value and key not in meta:
                        meta[key] = value
        # A usable itemised set needs the core of both statements.
        # Reported totals 2599 / 9999 are not required: the 2025
        # Gillco file's detail pages do not print a 2599 code, but
        # the computed totals still tie out (see _checks).
        if items_by_code and 1000 in items_by_code \
                and 3600 in items_by_code and 8000 in items_by_code \
                and 9367 in items_by_code:
            items = [items_by_code[c] for c in sorted(items_by_code)]
            if "corporation_name" not in meta:
                meta.update(_fallback_corporation_name(doc))
            return {"found": True, "source": "itemised", "pages": {},
                    "items": items, "meta": meta,
                    "checks": _checks(items_by_code),
                    "warnings": [
                        "No pages headed 'Condensed Balance Sheet / "
                        "Condensed Income statement' were found, so the "
                        "itemised Schedule 100 / Schedule 125 pages were "
                        "used instead. Check the totals before printing."]}
        return {"found": False, "source": "none", "pages": {}, "items": [],
                "meta": meta, "checks": [],
                "warnings": [
                    "No Condensed Balance Sheet / Condensed Income "
                    "statement pages and no usable Schedule 100 / 125 "
                    "items were found in this PDF. It may be a scanned "
                    "PDF - use the GIFI-only upload (Gemini OCR) instead, "
                    "or upload the GIFI condensed statement on its own."]}
    finally:
        doc.close()
