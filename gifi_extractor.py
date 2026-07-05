import os
import sys
import json
import re
import urllib.request
import urllib.error
import time

# Ensure we can reuse PDF rendering functions from extract_statement
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    import extract_statement
except ImportError:
    extract_statement = None

def safe_float(val):
    """
    Cleans and converts values to floats. Handles accounting brackets: (100) -> -100.0
    """
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        clean_val = str(val).strip()
        # Handle parentheses representing negative numbers
        if clean_val.startswith("(") and clean_val.endswith(")"):
            clean_val = "-" + clean_val[1:-1]
        
        clean_val = clean_val.replace("$", "").replace(",", "").strip()
        if not clean_val or clean_val.lower() in ('none', 'null', '-', '—'):
            return 0.0
        return float(clean_val)
    except ValueError:
        return 0.0

def extract_gifi_data(api_key, model, base64_image, page_num):
    """
    Calls the Gemini API to extract all GIFI rows on a page as flat JSON data.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    prompt = """Analyze this CRA GIFI (General Index of Financial Information) condensed statement page.
Extract all details and return a JSON object with:
- 'corporation_name': The Name of corporation (e.g. 1386371 B.C. LTD.). Seek this in the header metadata.
- 'business_number': The Business Number (e.g. 791178619).
- 'tax_year_end': The Tax year end in YYYY-MM-DD format (e.g. 2025-06-30).
- 'gifi_items': A list of transaction/account items. Each item must contain:
  * 'gifi_code': The GIFI code as an integer (e.g. 1002, 1599, 1742, 2599, 3600, 8000, 9367).
  * 'description': The name/description of the account (e.g. "Deposits in Canadian banks", "Motor vehicles", "Total Revenue").
  * 'current_year': The numeric value for the current year (or null if blank).
  * 'prior_year': The numeric value for the prior year (or null if blank).

Note: Accounting brackets like '(339)' represent negative values. Keep the negative sign or return as a negative number.
Do not include any markdown wrappers or backticks. Return raw JSON matching this structure."""

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
    
    max_retries = 3
    backoff = 2.0
    
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                
                candidates = res_data.get("candidates", [])
                if not candidates:
                    return {}
                    
                text_response = candidates[0]["content"]["parts"][0]["text"].strip()
                
                # Strip markdown wrappers if present
                if text_response.startswith("```"):
                    text_response = re.sub(r"^```(?:json|JSON)?\n", "", text_response)
                    text_response = re.sub(r"\n```$", "", text_response)
                text_response = text_response.strip()
                
                return json.loads(text_response)
                
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(backoff)
                backoff *= 1.5
            else:
                break
        except Exception:
            break
            
    return {}

def classify_gifi_items(raw_items):
    """
    Groups a flat list of GIFI items into standard financial statement sections
    based on CRA GIFI code ranges.
    """
    classified = {
        "current_assets": [],
        "tangible_assets": [],
        "long_term_assets": [],
        "total_assets_reported": None,
        "current_liabilities": [],
        "long_term_liabilities": [],
        "total_liabilities_reported": None,
        "equity_shares": [],
        "retained_earnings": [],
        "total_equity_reported": None,
        "revenues": [],
        "cost_of_sales": [],
        "expenses": [],
        "net_income_reported": None
    }
    
    seen_codes = set()
    
    for item in raw_items:
        code = item.get("gifi_code")
        if not code:
            continue
            
        try:
            code = int(code)
        except (ValueError, TypeError):
            continue
            
        # Avoid duplicate codes
        if code in seen_codes:
            continue
        seen_codes.add(code)
        
        desc = item.get("description", "").strip()
        curr = safe_float(item.get("current_year"))
        prior = safe_float(item.get("prior_year"))
        
        cleaned_item = {
            "gifi_code": code,
            "description": desc,
            "current_year": curr,
            "prior_year": prior
        }
        
        # Classify based on standard GIFI ranges
        if code == 2599:
            classified["total_assets_reported"] = cleaned_item
        elif code == 3139:
            classified["total_liabilities_reported"] = cleaned_item
        elif code == 3620:
            classified["total_equity_reported"] = cleaned_item
        elif code in (9999, 9970):
            classified["net_income_reported"] = cleaned_item
        elif 1000 <= code <= 1599:
            classified["current_assets"].append(cleaned_item)
        elif 1600 <= code <= 2199:
            classified["tangible_assets"].append(cleaned_item)
        elif 2200 <= code <= 2598:
            classified["long_term_assets"].append(cleaned_item)
        elif 2600 <= code <= 3138:
            classified["current_liabilities"].append(cleaned_item)
        elif 3140 <= code <= 3499:
            classified["long_term_liabilities"].append(cleaned_item)
        elif 3500 <= code <= 3549:
            classified["equity_shares"].append(cleaned_item)
        elif 3550 <= code <= 3849:
            classified["retained_earnings"].append(cleaned_item)
        elif 8000 <= code <= 8299:
            classified["revenues"].append(cleaned_item)
        elif 8300 <= code <= 8519:
            classified["cost_of_sales"].append(cleaned_item)
        elif 8520 <= code <= 9369:
            classified["expenses"].append(cleaned_item)
            
    return classified
