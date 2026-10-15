#!/usr/bin/env python3
import os
import sys
import json
import csv
import re
import argparse
import base64
from io import BytesIO
import urllib.request
import urllib.error

# Try importing PDF libraries
try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None

try:
    from PIL import Image
except ImportError:
    Image = None

def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract transactions from bank statements (supports digital text extraction and Gemini-powered OCR for scanned PDFs)."
    )
    parser.add_argument("input_pdf", help="Path to the bank statement PDF file.")
    parser.add_argument(
        "-o", "--output", default="extracted_transactions.csv",
        help="Path to the output CSV file (default: extracted_transactions.csv)."
    )
    parser.add_argument(
        "--api-key", help="Gemini API Key. If not provided, the script looks for the GEMINI_API_KEY environment variable."
    )
    parser.add_argument(
        "--model", default="gemini-2.5-flash",
        help="Gemini model to use for OCR (default: gemini-2.5-flash)."
    )
    parser.add_argument(
        "--force-ocr", action="store_true",
        help="Force OCR mode even if the PDF contains extractable digital text."
    )
    return parser.parse_args()

def check_dependencies(ocr_needed=False):
    missing = []
    if ocr_needed:
        if pdfium is None:
            missing.append("pypdfium2")
        if Image is None:
            missing.append("pillow")
    else:
        if pypdf is None and pdfplumber is None:
            missing.append("pypdf or pdfplumber")
            
    if missing:
        print(f"Error: Missing required python libraries: {', '.join(missing)}")
        print("Please install them using:")
        print(f"  pip install {' '.join(missing)}")
        sys.exit(1)

def extract_digital_text(pdf_path):
    """
    Attempt to extract digital text from the PDF.
    pdf_path can be a string path or a file-like object.
    """
    text_pages = []
    
    # Try pdfplumber first
    if pdfplumber is not None:
        try:
            if hasattr(pdf_path, "seek"):
                pdf_path.seek(0)
            with pdfplumber.open(pdf_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        text_pages.append(text)
                    else:
                        text_pages.append("")
            # If all pages are completely empty, it's scanned
            if any(len(p.strip()) > 0 for p in text_pages):
                return text_pages
        except Exception as e:
            print(f"Warning: Failed to extract text with pdfplumber: {e}")
            
    # Try pypdf next
    if pypdf is not None:
        try:
            if hasattr(pdf_path, "seek"):
                pdf_path.seek(0)
                reader = pypdf.PdfReader(pdf_path)
            else:
                with open(pdf_path, "rb") as f:
                    reader = pypdf.PdfReader(f)
            
            text_pages = []
            for page in reader.pages:
                text = page.extract_text()
                text_pages.append(text if text else "")
            if any(len(p.strip()) > 0 for p in text_pages):
                return text_pages
        except Exception as e:
            print(f"Warning: Failed to extract text with pypdf: {e}")
            
    return []

def parse_digital_text(text_pages):
    """
    Parser for digital bank statements (TD, BMO, RBC, CIBC, etc.).
    Supports full dates ('Jun 30, 2025') and abbreviated dates ('Jan 02') with statement year context.
    """
    transactions = []
    print("Attempting to parse digital text...")
    
    full_text = "\n".join(text_pages)
    months_map = {
        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
        "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
        "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
        "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"
    }
    
    # Detect year from text
    year_match = re.search(r'\b(20\d{2}|19\d{2})\b', full_text)
    detected_year = year_match.group(1) if year_match else "2025"
    
    # Pattern 1: Date with Year (e.g. 'Jun 30, 2025 Description Amount1 Amount2 Balance')
    pattern_full_date = re.compile(
        r"^([A-Z][a-z]{2})\s+(\d{1,2}),\s+(\d{4})\s+(.+?)\s+([\d,]+\.\d{2})?\s*([\d,]+\.\d{2})?\s*(\$?[\d,]+\.\d{2})$"
    )
    # Pattern 2: Date without Year (e.g. 'Jan 02 INTERAC e-Transfer Received 100.00 267.10')
    pattern_short_date = re.compile(
        r"^([A-Za-z]{3})\s+(\d{1,2})\s+(.+?)\s+([\d,]+\.\d{2})?\s*([\d,]+\.\d{2})?\s*(\$?[\d,]+\.\d{2})$"
    )
    # Pattern 3: Credit Card with Trans Date and optional Posting Date, description, amount, and optional CR
    pattern_cc_date = re.compile(
        r"^([A-Za-z]{3,4})\.?\s+(\d{1,2})(?:\s+[A-Za-z]{3,4}\.?\s+\d{1,2})?\s+(.+?)\s+([\d,]+\.\d{2})\s*(CR)?$",
        re.IGNORECASE
    )
    # Pattern 4: Date with slashes/dashes and 4-digit year (e.g. Scotiabank '03/03/2026 CREDIT MEMO 79.00 965.50')
    pattern_slash_date = re.compile(
        r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\s+(.+?)\s+([\d,]+\.\d{2})?\s*([\d,]+\.\d{2})?\s*(\$?[\d,]+\.\d{2})$"
    )

    # Patterns for lines that start with Date but DO NOT have amounts on the same line
    pattern_slash_date_start = re.compile(
        r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\s*(.*)$"
    )
    pattern_full_date_start = re.compile(
        r"^([A-Z][a-z]{2})\s+(\d{1,2}),\s+(\d{4})\s*(.*)$"
    )
    pattern_short_date_start = re.compile(
        r"^([A-Za-z]{3})\s+(\d{1,2})\s*(.*)$"
    )

    # Continuation patterns for trailing amounts
    pattern_trailing_two_amounts = re.compile(
        r"^(.*?)\s*([\d,]+\.\d{2})\s+(\$?[\d,]+\.\d{2})$"
    )
    pattern_trailing_one_amount = re.compile(
        r"^(.*?)\s*([\d,]+\.\d{2})\s*(CR)?$",
        re.IGNORECASE
    )

    from local_extractor import is_disclaimer_or_metadata, extract_statement_period

    start_year, start_month, end_year, end_month = extract_statement_period(full_text)
    detected_year = str(start_year)

    current_tx = None

    def finalize_tx(tx):
        if not tx:
            return
        desc = tx.get("description", "").strip()
        if is_disclaimer_or_metadata(desc):
            return
        desc_clean = desc.lower()
        if any(k in desc_clean for k in ("opening balance", "balance forward", "solde reporté", "closing balance", "closing totals")):
            return
        # Must have at least one valid amount
        if tx.get("debit") is not None or tx.get("credit") is not None or tx.get("balance") is not None:
            tx["description"] = re.sub(r'\s+', ' ', desc).strip()
            tx["statement_order"] = len(transactions)
            transactions.append(tx)

    for page_num, text in enumerate(text_pages, 1):
        lines = text.split("\n")
        for line_idx, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
                
            if is_disclaimer_or_metadata(line):
                finalize_tx(current_tx)
                current_tx = None
                continue

            # Check footer / summary stop markers
            line_lower = line.lower()
            if any(marker in line_lower for marker in [
                "no. of debits", "uncollected fees", "odi owing", "please examine this statement",
                "total service charges", "statement of: service charge", "closing totals", "end of statement"
            ]):
                finalize_tx(current_tx)
                current_tx = None
                continue

            # 1. Try matching lines with Date AND Amount
            m_full = pattern_full_date.match(line)
            m_slash = None
            m_short = None
            m_cc = None
            cr_flag = None
            date = None

            if m_full:
                month_str, day_str, year_str, desc, amount1, amount2, balance_str = m_full.groups()
                month = months_map.get(month_str.capitalize(), "01")
                day = f"{int(day_str):02d}"
                date = f"{year_str}-{month}-{day}"
            else:
                m_slash = pattern_slash_date.match(line)
                if m_slash:
                    p1, p2, yr_str, desc, amount1, amount2, balance_str = m_slash.groups()
                    n1, n2 = int(p1), int(p2)
                    m_num, d_num = (n2, n1) if n1 > 12 else (n1, n2)
                    date = f"{yr_str}-{m_num:02d}-{d_num:02d}"
                else:
                    m_short = pattern_short_date.match(line)
                    if m_short and m_short.group(1).capitalize() in months_map:
                        month_str, day_str, desc, amount1, amount2, balance_str = m_short.groups()
                        month = months_map.get(month_str.capitalize(), "01")
                        day = f"{int(day_str):02d}"
                        m_int = int(month)
                        yr = start_year if (start_month <= end_month or m_int >= start_month) else end_year
                        date = f"{yr}-{month}-{day}"
                    else:
                        m_cc = pattern_cc_date.match(line)
                        if m_cc and m_cc.group(1).capitalize()[:3] in months_map:
                            month_str, day_str, desc, amount1, cr_flag = m_cc.groups()
                            month = months_map[month_str.capitalize()[:3]]
                            day = f"{int(day_str):02d}"
                            m_int = int(month)
                            yr = start_year if (start_month <= end_month or m_int >= start_month) else end_year
                            date = f"{yr}-{month}-{day}"
                            amount2 = None
                            balance_str = None

            if date:
                # We matched a line with date and amounts
                finalize_tx(current_tx)
                current_tx = None

                # Skip opening / balance forward / closing
                desc_clean = desc.lower().strip()
                if any(k in desc_clean for k in ("opening balance", "balance forward", "solde reporté", "closing balance", "closing totals")):
                    continue

                bal_val = float(balance_str.replace("$", "").replace(",", "")) if balance_str else None
                val1 = float(amount1.replace(",", "")) if amount1 else None
                val2 = float(amount2.replace(",", "")) if amount2 else None
                
                debit = None
                credit = None
                if val1 is not None and val2 is not None:
                    debit = val1
                    credit = val2
                elif val1 is not None:
                    if m_cc:
                        if cr_flag or re.search(r'\bcr\b', desc_clean) or any(k in desc_clean for k in ("payment received", "pymt received", "refund", "rebate")):
                            credit = val1
                        else:
                            debit = val1
                    else:
                        is_known_credit = bool(re.search(r'\b(?:deposit|received|rebate|refund|payroll|credit|cr|depot)\b', desc_clean))
                        if is_known_credit:
                            credit = val1
                        else:
                            debit = val1

                current_tx = {
                    "date": date,
                    "description": desc.strip(),
                    "debit": debit,
                    "credit": credit,
                    "balance": bal_val,
                    "page_num": page_num,
                    "row_idx": line_idx
                }
                continue

            # 2. Try matching lines that start with Date but lack amounts
            m_start_slash = pattern_slash_date_start.match(line)
            date_start = None
            desc_start = ""

            if m_start_slash:
                p1, p2, yr_str, desc_start = m_start_slash.groups()
                n1, n2 = int(p1), int(p2)
                m_num, d_num = (n2, n1) if n1 > 12 else (n1, n2)
                date_start = f"{yr_str}-{m_num:02d}-{d_num:02d}"
            else:
                m_start_full = pattern_full_date_start.match(line)
                if m_start_full and m_start_full.group(1).capitalize() in months_map:
                    month_str, day_str, year_str, desc_start = m_start_full.groups()
                    month = months_map[month_str.capitalize()]
                    date_start = f"{year_str}-{month}-{int(day_str):02d}"
                else:
                    m_start_short = pattern_short_date_start.match(line)
                    if m_start_short and m_start_short.group(1).capitalize() in months_map:
                        month_str, day_str, desc_start = m_start_short.groups()
                        month = months_map[month_str.capitalize()]
                        m_int = int(month)
                        yr = start_year if (start_month <= end_month or m_int >= start_month) else end_year
                        date_start = f"{yr}-{month}-{int(day_str):02d}"

            if date_start:
                finalize_tx(current_tx)
                current_tx = {
                    "date": date_start,
                    "description": desc_start.strip(),
                    "debit": None,
                    "credit": None,
                    "balance": None,
                    "page_num": page_num,
                    "row_idx": line_idx
                }
                continue

            # 3. Handle continuation lines (when current_tx exists)
            if current_tx:
                # If current_tx needs amounts, check if this line contains amounts
                if current_tx["debit"] is None and current_tx["credit"] is None and current_tx["balance"] is None:
                    m_two = pattern_trailing_two_amounts.match(line)
                    if m_two:
                        extra_desc, a1, a2 = m_two.groups()
                        if extra_desc.strip():
                            current_tx["description"] += " " + extra_desc.strip()
                        val1 = float(a1.replace(",", ""))
                        bal_val = float(a2.replace("$", "").replace(",", ""))
                        desc_clean = current_tx["description"].lower()
                        if re.search(r'\b(?:deposit|received|rebate|refund|payroll|credit|cr|depot)\b', desc_clean):
                            current_tx["credit"] = val1
                        else:
                            current_tx["debit"] = val1
                        current_tx["balance"] = bal_val
                        continue

                    m_one = pattern_trailing_one_amount.match(line)
                    if m_one:
                        extra_desc, a1, cr_flag = m_one.groups()
                        val1 = float(a1.replace(",", ""))
                        if extra_desc.strip():
                            current_tx["description"] += " " + extra_desc.strip()
                        desc_clean = current_tx["description"].lower()
                        if cr_flag or re.search(r'\b(?:deposit|received|rebate|refund|payroll|credit|cr|depot)\b', desc_clean):
                            current_tx["credit"] = val1
                        else:
                            current_tx["debit"] = val1
                        continue

                # If current_tx already has amounts, check if this line is a new transaction on the same date (e.g. date omitted)
                else:
                    m_two = pattern_trailing_two_amounts.match(line)
                    if m_two and m_two.group(1).strip():
                        extra_desc, a1, a2 = m_two.groups()
                        val1 = float(a1.replace(",", ""))
                        bal_val = float(a2.replace("$", "").replace(",", ""))
                        finalize_tx(current_tx)
                        desc_clean = extra_desc.lower()
                        cred = val1 if re.search(r'\b(?:deposit|received|rebate|refund|payroll|credit|cr|depot)\b', desc_clean) else None
                        deb = val1 if cred is None else None
                        current_tx = {
                            "date": current_tx["date"],
                            "description": extra_desc.strip(),
                            "debit": deb,
                            "credit": cred,
                            "balance": bal_val,
                            "page_num": page_num,
                            "row_idx": line_idx
                        }
                        continue

                # Otherwise, it is text description continuation
                current_tx["description"] += " " + line.strip()

        finalize_tx(current_tx)
        current_tx = None

    return transactions

def render_pdf_pages(pdf_path):
    """
    Renders PDF pages to base64 PNG strings using pypdfium2.
    """
    print("Rendering PDF pages to images for Gemini OCR...")
    check_dependencies(ocr_needed=True)
    
    doc = pdfium.PdfDocument(pdf_path)
    base64_images = []
    
    try:
        for i in range(len(doc)):
            print(f"  Rendering page {i+1}/{len(doc)}...")
            page = doc[i]
            # Render at 2x resolution for good OCR quality
            bitmap = page.render(scale=2)
            pil_img = bitmap.to_pil()
            
            # Convert to PNG bytes
            buffered = BytesIO()
            pil_img.save(buffered, format="PNG")
            img_bytes = buffered.getvalue()
            
            # Encode to Base64
            base64_str = base64.b64encode(img_bytes).decode("utf-8")
            base64_images.append(base64_str)
    finally:
        doc.close()
        
    return base64_images

def call_gemini_api(api_key, model, base64_image, page_num):
    """
    Calls the Gemini API using standard urllib to process the page image.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    prompt = """Extract all transactions from the bank statement image (including all payments, credits, interest charges, fees, and standard purchases/withdrawals). 
Return a JSON object with a single key 'transactions', which is a list of objects. Each transaction object MUST contain:
- 'date': The transaction date in 'YYYY-MM-DD' format. Look at the statement year context (e.g., 'June 2025' or 'July 2025' header) to determine the correct year, and map dates like 'Jun 30' to '2025-06-30'.
- 'description': The exact description text (e.g., 'TD MORTGAGE', 'MOBILE DEPOSIT', 'PAYMENT THANK YOU').
- 'debit': The debit amount as a float (or null if not present). For credit card statements, purchases/charges are debits.
- 'credit': The credit amount as a float (or null if not present). For credit card statements, payments/refunds/credits are credits.
- 'balance': The balance amount as a float (or null if not present).

Do not include any currency symbols or commas in the numeric fields.
Make sure you extract EVERY single transaction row across all sections (including the 'payments and credits' section and the 'new charges' section)."""

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": "image/png",
                            "data": base64_image
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    import time
    
    max_retries = 5
    backoff = 2.0
    
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                
                # Extract JSON text from response structure
                candidates = res_data.get("candidates", [])
                if not candidates:
                    print(f"  Warning: No content returned for page {page_num} on attempt {attempt+1}")
                    return []
                    
                text_response = candidates[0]["content"]["parts"][0]["text"]
                
                # Clean up markdown code block wrappers if present
                text_response = text_response.strip()
                if text_response.startswith("```"):
                    # Strip opening backticks and optional 'json' / 'JSON' identifier
                    text_response = re.sub(r"^```(?:json|JSON)?\n", "", text_response)
                    # Strip closing backticks
                    text_response = re.sub(r"\n```$", "", text_response)
                text_response = text_response.strip()

                page_data = json.loads(text_response)
                return page_data.get("transactions", [])
                
        except urllib.error.HTTPError as e:
            if e.code == 429:
                if backoff < 30.0:
                    backoff = 30.0
                print(f"  Rate limited (429) on page {page_num}. Quota exceeded. Waiting {backoff}s to reset limit window... (Attempt {attempt+1}/{max_retries})")
                time.sleep(backoff)
                backoff *= 1.5
            else:
                print(f"Error: HTTP request to Gemini failed with status {e.code} on page {page_num}")
                try:
                    print(e.read().decode("utf-8"))
                except Exception:
                    pass
                break
        except Exception as e:
            print(f"Error processing page {page_num} on attempt {attempt+1}: {e}")
            break
            
    return []

def call_gemini_api_for_text(api_key, model, full_text):
    """
    Calls the Gemini API to parse the full extracted digital text from a PDF statement.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    prompt = f"""Extract all transaction rows from the following bank statement text (including all payments, credits, fees, interest, and purchases/withdrawals across all sections like 'Your payments' and 'Your new charges').
Return a JSON object with a single key 'transactions', which is a list of objects. Each transaction object MUST contain:
- 'date': The transaction date in 'YYYY-MM-DD' format. Look at the statement year context (e.g. '2026') in the text to determine the correct year.
- 'description': The exact description text (e.g. 'PREAUTHORIZED DEBIT', 'PAYMENT THANK YOU').
- 'debit': The debit amount as a float (or null if not present). For credit card statements, purchases/charges are debits.
- 'credit': The credit amount as a float (or null if not present). For credit card statements, payments/refunds/credits are credits.
- 'balance': The balance amount as a float (or null if not present).

Do not include any currency symbols or commas in the numeric fields.
Make sure you extract EVERY single transaction row across all tables (including the 'Your payments' section).

Bank Statement Text:
{full_text}"""

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    import time
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                candidates = res_data.get("candidates", [])
                if not candidates:
                    return []
                text_response = candidates[0]["content"]["parts"][0]["text"].strip()
                
                if text_response.startswith("```"):
                    text_response = re.sub(r"^```(?:json|JSON)?\n", "", text_response)
                    text_response = re.sub(r"\n```$", "", text_response)
                text_response = text_response.strip()
                
                return json.loads(text_response).get("transactions", [])
        except Exception as e:
            print(f"Text parsing retry attempt {attempt+1}: {e}")
            time.sleep(1)
            
    return []

def safe_float(val):
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        # Strip any currency symbols, commas, or extra whitespace
        clean_val = str(val).replace("$", "").replace(",", "").strip()
        if not clean_val or clean_val.lower() == 'none' or clean_val.lower() == 'null':
            return 0.0
        return float(clean_val)
    except ValueError:
        return 0.0

def validate_and_correct_transactions(transactions, sort_chronologically=True):
    """
    Sorts transactions chronologically, checks balance transitions,
    and warns or fixes any mathematical errors.
    """
    if not transactions:
        return []
        
    # Standardize and clean all numeric values first to avoid TypeErrors
    for tx in transactions:
        tx["balance"] = safe_float(tx.get("balance"))
        
        deb_val = safe_float(tx.get("debit"))
        tx["debit"] = deb_val if deb_val != 0.0 else None
        
        cred_val = safe_float(tx.get("credit"))
        tx["credit"] = cred_val if cred_val != 0.0 else None
        
    # Check if this statement actually has balance column data
    has_balances = any(safe_float(tx.get("balance")) != 0.0 for tx in transactions)
    if not has_balances:
        if sort_chronologically:
            transactions.sort(key=lambda x: x["date"])
        return transactions

    # Store original order index
    for idx, tx in enumerate(transactions):
        tx["original_index"] = idx
        
    # Sort chronologically for validation flow
    transactions.sort(key=lambda x: x["date"])
    
    print("\nValidating balance transitions...")
    errors = 0
    
    for i in range(1, len(transactions)):
        prev = transactions[i-1]
        curr = transactions[i]
        
        prev_bal = prev["balance"]
        curr_bal = curr["balance"]
        
        deb = curr["debit"] if curr["debit"] is not None else 0.0
        cred = curr["credit"] if curr["credit"] is not None else 0.0
        
        expected_bal = round(prev_bal - deb + cred, 2)
        
        if abs(expected_bal - curr_bal) > 0.01:
            # Check if debit and credit were swapped
            expected_swap = round(prev_bal + deb - cred, 2)
            if abs(expected_swap - curr_bal) <= 0.01:
                print(f"  [Auto-Fixed Swap] Swapped debit/credit for {curr['date']} - {curr['description']}")
                curr["debit"], curr["credit"] = curr["credit"], curr["debit"]
            else:
                print(f"  [Mismatch] {curr['date']} - {curr['description']}")
                print(f"    Previous Balance: ${prev_bal:,.2f}")
                print(f"    Transaction values: Debit=${deb:,.2f}, Credit=${cred:,.2f}")
                print(f"    Expected Balance: ${expected_bal:,.2f} | Actual Balance: ${curr_bal:,.2f} (Diff: {round(curr_bal - expected_bal, 2)})")
                errors += 1
                
    if errors == 0:
        print("Success: All balance transitions are mathematically consistent!")
    else:
        print(f"Warning: Found {errors} balance transition mismatch(es). Please review the CSV manually.")
        
    # Restore original statement order if requested
    if not sort_chronologically:
        transactions.sort(key=lambda x: x["original_index"])
        
    # Clean up original_index key
    for tx in transactions:
        tx.pop("original_index", None)
        
    return transactions

def save_to_csv(transactions, output_path):
    with open(output_path, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Description", "Debit", "Credit", "Balance"])
        for tx in transactions:
            deb_str = f"{tx['debit']:.2f}" if tx.get("debit") else ""
            cred_str = f"{tx['credit']:.2f}" if tx.get("credit") else ""
            bal_str = f"{tx['balance']:.2f}"
            writer.writerow([tx["date"], tx["description"], deb_str, cred_str, bal_str])
    print(f"\nSaved {len(transactions)} transactions to {output_path}")

def main():
    args = parse_args()
    
    if not os.path.exists(args.input_pdf):
        print(f"Error: Input file '{args.input_pdf}' does not exist.")
        sys.exit(1)
        
    # Step 1: Attempt digital extraction first unless forced OCR
    text_pages = []
    if not args.force_ocr:
        print("Checking if PDF contains extractable digital text...")
        check_dependencies(ocr_needed=False)
        text_pages = extract_digital_text(args.input_pdf)
        
    transactions = []
    
    if text_pages and not args.force_ocr:
        print(f"Detected digital text in PDF ({len(text_pages)} pages). Extracting...")
        try:
            from local_extractor import detect_bank, extract_digital_pdf
            detected_bank = detect_bank(args.input_pdf)
            local_txs, _ = extract_digital_pdf(args.input_pdf, detected_bank)
            if local_txs:
                transactions = local_txs
        except Exception as e:
            print(f"extract_digital_pdf fallback to parse_digital_text: {e}")
            
        if not transactions:
            transactions = parse_digital_text(text_pages)
    else:
        # Step 2: Fallback to OCR / Image processing
        print("PDF appears to be scanned or force-ocr was enabled.")
        
        # Resolve API key
        api_key = args.api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("\nGemini API key not found.")
            api_key = input("Please enter your Gemini API Key: ").strip()
            if not api_key:
                print("Error: Gemini API Key is required to process scanned statements.")
                sys.exit(1)
                
        base64_images = render_pdf_pages(args.input_pdf)
        
        print("\nProcessing pages using Gemini API...")
        for i, img_b64 in enumerate(base64_images, 1):
            print(f"  Sending page {i}/{len(base64_images)} to Gemini...")
            page_txs = call_gemini_api(api_key, args.model, img_b64, i)
            print(f"    Extracted {len(page_txs)} transactions.")
            transactions.extend(page_txs)
            
    # Step 3: Validate, sort, and save
    if transactions:
        transactions = validate_and_correct_transactions(transactions)
        save_to_csv(transactions, args.output)
    else:
        print("No transactions found or extracted.")

if __name__ == "__main__":
    main()
