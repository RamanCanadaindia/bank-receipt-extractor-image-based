import re
import json
import urllib.request
import urllib.error

# Exact custom rules mapping from the user's PDF lookup sheet
# (pattern_regex, Category, GIFI_Code, GST_Rate)
CUSTOM_RULES = [
    # Page 1
    (r"acc fee-\s*full serv", "Bank Charges", "8715", "0%"),
    (r"annual cash back credit", "Bank Charges", "8715", "0%"),
    (r"balance fee waiver", "Bank Charges", "8715", "0%"),
    (r"bank fee", "Bank Charges", "8715", "0%"),
    (r"cash advance interest", "Bank Charges", "8715", "0%"),
    (r"draft fee", "Bank Charges", "8715", "0%"),
    (r"installment interest", "Bank Charges", "8715", "0%"),
    (r"interest paid", "Bank Charges", "8715", "0%"),
    (r"monthly fee", "Bank Charges", "8715", "0%"),
    (r"nsf charge", "Bank Charges", "8715", "0%"),
    (r"online banking wire fee", "Bank Charges", "8715", "0%"),
    (r"overdraft interest", "Bank Charges", "8715", "0%"),
    (r"overdraft per item charge", "Bank Charges", "8715", "0%"),
    (r"overdraft s/c", "Bank Charges", "8715", "0%"),
    (r"overlimit fee", "Bank Charges", "8715", "0%"),
    (r"plan fee", "Bank Charges", "8715", "0%"),
    (r"purchase interest", "Bank Charges", "8715", "0%"),
    (r"regular transaction fee", "Bank Charges", "8715", "0%"),
    (r"retail interest", "Bank Charges", "8715", "0%"),
    (r"send e-tfr fee", "Bank Charges", "8715", "0%"),
    (r"service charge", "Bank Charges", "8715", "0%"),
    (r"bc registry", "Business taxes", "8760", "0%"),
    (r"driver services centre", "Business taxes", "8760", "12%"),
    (r"american express regular", "CC Payment", "", "0%"),
    (r"mastercard, rbc", "CC Payment", "", "0%"),
    # Page 2
    (r"mastercard, walmart", "CC Payment", "", "0%"),
    (r"payment - thank you", "CC Payment", "", "0%"),
    (r"individual shareholder", "Due to individual shareholder", "3261", "0%"),
    (r"opening\s*(balance|blanace|bal)", "Due to Related Party", "2860", "0%"),
    (r"icbc", "Insurance expense", "8690", "0%"),
    (r"insurance", "Insurance expense", "8690", "0%"),
    (r"pre-authorized payment, icbc", "Insurance expense", "8690", "0%"),
    (r"worksafebc", "Insurance expense", "8690", "0%"),
    (r"7-eleven store", "Meal", "8523", "0%"),
    (r"a&w", "Meal", "8523", "0%"),
    (r"apna chaat", "Meal", "8523", "0%"),
    (r"booster juice", "Meal", "8523", "0%"),
    (r"burger king", "Meal", "8523", "0%"),
    (r"dhaliwal sweets", "Meal", "8523", "0%"),
    (r"dqoj", "Meal", "8523", "0%"),
    (r"freshslice pizza", "Meal", "8523", "0%"),
    (r"kwantlen pizza", "Meal", "8523", "0%"),
    (r"lepp farm market", "Meal", "8523", "0%"),
    (r"little caesars", "Meal", "8523", "0%"),
    (r"lunch bucket", "Meal", "8523", "0%"),
    (r"mcdonald", "Meal", "8523", "0%"),
    (r"mirch masala", "Meal", "8523", "0%"),
    (r"osmows", "Meal", "8523", "0%"),
    (r"pak punjab sweets", "Meal", "8523", "0%"),
    (r"pizza", "Meal", "8523", "0%"),
    # Page 3
    (r"pizza 64", "Meal", "8523", "0%"),
    (r"rose sweet & tandoori", "Meal", "8523", "0%"),
    (r"starbucks", "Meal", "8523", "0%"),
    (r"subway", "Meal", "8523", "0%"),
    (r"surrey punjab", "Meal", "8523", "0%"),
    (r"sushi nara", "Meal", "8523", "0%"),
    (r"tim horton", "Meal", "8523", "0%"),
    (r"triple o", "Meal", "8523", "0%"),
    (r"zaika tastes of india", "Meal", "8523", "0%"),
    (r"fineprint signs", "Office Expense", "8810", "12%"),
    (r"intuit", "Office Expense", "8810", "12%"),
    (r"intuit \*qbooks payroll", "Office Expense", "8810", "12%"),
    (r"microsoft", "Office Expense", "8810", "12%"),
    (r"rent", "Rent", "8912", ""),
    (r"abc auto & window glass", "Repairs and maintenance", "8962", "12%"),
    (r"sukh auto repair", "Repairs and maintenance", "8962", "12%"),
    (r"salaries and wages", "Salaries and wages", "9060", "0%"),
    (r"subcontract exp", "Subcontract Expense", "9110", "5%"),
    (r"bell mobility", "Telephone Expense", "9225", "12%"),
    (r"freedom mobile", "Telephone Expense", "9225", "12%"),
    (r"rogers", "Telephone Expense", "9225", "12%"),
    (r"telus", "Telephone Expense", "9225", "12%"),
    (r"deposit", "Trade Sales", "8000", "5%"),
    (r"mobile cheque deposit", "Trade Sales", "8000", "5%"),
    (r"mobile deposit", "Trade Sales", "8000", "5%"),
    # Page 4
    (r"uber canada", "Travel Expense", "9200", "5%"),
    (r"bill payment ford credit", "Truck Loan", "", "0%"),
    (r"vehicle asset", "Vehicle Asset", "1742", ""),
    (r"canco petroleum", "Vehicle Expense", "9281", "7%"),
    (r"castle car wash", "Vehicle Expense", "9281", "5%"),
    (r"centex", "Vehicle Expense", "9281", "7%"),
    (r"chevron", "Vehicle Expense", "9281", "7%"),
    (r"chv40268", "Vehicle Expense", "9281", "7%"),
    (r"chv40269", "Vehicle Expense", "9281", "7%"),
    (r"chv43013", "Vehicle Expense", "9281", "7%"),
    (r"chv43014", "Vehicle Expense", "9281", "7%"),
    (r"chv43028", "Vehicle Expense", "9281", "7%"),
    (r"chv43099", "Vehicle Expense", "9281", "7%"),
    (r"chv43126", "Vehicle Expense", "9281", "7%"),
    (r"city of kelowna parking", "Vehicle Expense", "9281", "5%"),
    (r"costco gas", "Vehicle Expense", "9281", "7%"),
    (r"esso", "Vehicle Expense", "9281", "7%"),
    (r"fraser valley aggregat", "Vehicle Expense", "9281", "5%"),
    (r"impark", "Vehicle Expense", "9281", "5%"),
    (r"linterra aggregates", "Vehicle Expense", "9281", "5%"),
    (r"nationwide fuel", "Vehicle Expense", "9281", "7%"),
    (r"peterbilt pacific", "Vehicle Expense", "9281", "5%"),
    (r"petro canada", "Vehicle Expense", "9281", "7%"),
    (r"petro-canada", "Vehicle Expense", "9281", "7%"),
    (r"shell", "Vehicle Expense", "9281", "7%"),
    (r"shine auto wash", "Vehicle Expense", "9281", "5%"),
    (r"speedwash", "Vehicle Expense", "9281", "5%"),
    (r"super save gas", "Vehicle Expense", "9281", "7%"),
    # Page 5
    (r"truck wash", "Vehicle Expense", "9281", "5%"),
    (r"yvr parking", "Vehicle Expense", "9281", "5%"),
    (r"equipment rental/lease", "Equipment rental/lease", "8914", "5%"),
    (r"dumping charges", "Dumping Charges", "9279", "5%"),
    (r"utilities", "Utilities", "9220", "12%")
]

# Standard category-to-meta mappings for fallback/AI classifications
CATEGORY_META = {
    "Accounting Fees": {"gifi": "8862", "gst": "5%"},
    "Advertising Expense": {"gifi": "8521", "gst": "12%"},
    "Bank Charges": {"gifi": "8715", "gst": "0%"},
    "Business taxes": {"gifi": "8760", "gst": "0%"},
    "CC Payment": {"gifi": "", "gst": "0%"},
    "CRA Payment": {"gifi": "", "gst": "0%"},
    "Due to individual shareholder": {"gifi": "3261", "gst": "0%"},
    "Due to Related Party": {"gifi": "2860", "gst": "0%"},
    "Insurance expense": {"gifi": "8690", "gst": "0%"},
    "Meal": {"gifi": "8523", "gst": "0%"},
    "Office Expense": {"gifi": "8810", "gst": "12%"},
    "Office Supplies": {"gifi": "8811", "gst": "12%"},
    "Rent": {"gifi": "8912", "gst": "0%"},
    "Repairs and maintenance": {"gifi": "8962", "gst": "12%"},
    "Salaries and wages": {"gifi": "9060", "gst": "0%"},
    "Subcontract Expense": {"gifi": "9110", "gst": "5%"},
    "Telephone Expense": {"gifi": "9225", "gst": "12%"},
    "Trade Sales": {"gifi": "8000", "gst": "5%"},
    "Travel Expense": {"gifi": "9200", "gst": "5%"},
    "Truck Loan": {"gifi": "", "gst": "0%"},
    "Vehicle Asset": {"gifi": "1742", "gst": "0%"},
    "Vehicle Expense": {"gifi": "9281", "gst": "5%"},
    "Equipment rental/lease": {"gifi": "8914", "gst": "5%"},
    "Dumping Charges": {"gifi": "9279", "gst": "5%"},
    "Utilities": {"gifi": "9220", "gst": "12%"},
    "Other Expenses": {"gifi": "", "gst": "0%"},
    "Revenue / Deposits": {"gifi": "8000", "gst": "5%"}
}

def lookup_by_rules(desc):
    """
    Looks up a transaction description in the custom rules sheet.
    Returns (category, gifi_code, gst_rate) or (None, None, None).
    """
    desc_lower = str(desc).lower()
    for pattern, category, gifi, gst in CUSTOM_RULES:
        if re.search(pattern, desc_lower):
            return category, gifi, gst
    return None, None, None

def save_user_rule(desc, category, gifi_code, gst_rate):
    """
    Saves a manual category change to user_rules.json for persistent learning.
    """
    import os
    user_rules_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_rules.json")
    user_rules = {}
    if os.path.exists(user_rules_path):
        try:
            with open(user_rules_path, "r", encoding="utf-8") as f:
                user_rules = json.load(f)
        except Exception:
            pass
            
    user_rules[str(desc).strip()] = {
        "category": category,
        "gifi_code": gifi_code,
        "gst_rate": gst_rate
    }
    
    try:
        with open(user_rules_path, "w", encoding="utf-8") as f:
            json.dump(user_rules, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving user rule: {e}")
        return False

def categorize_transactions(api_key, transactions):
    """
    Categorize a list of transaction dictionaries using hybrid rules + AI.
    Returns transaction dicts with 'category', 'gifi_code', and 'gst_rate' added.
    """
    if not transactions:
        return []
        
    # Load persistent user-defined overrides first
    import os
    user_rules = {}
    user_rules_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_rules.json")
    if os.path.exists(user_rules_path):
        try:
            with open(user_rules_path, "r", encoding="utf-8") as f:
                user_rules = json.load(f)
        except Exception as e:
            print(f"Error loading user_rules.json: {e}")
        
    # Phase 1: Local lookup search (0ms, 100% accurate)
    unresolved_descs = []
    lookup_results = {}
    
    for t in transactions:
        desc = t.get("description", "")
        if not desc:
            continue
            
        # Check user-defined overrides first
        if desc in user_rules:
            cat = user_rules[desc].get("category")
            gifi = user_rules[desc].get("gifi_code", "")
            gst = user_rules[desc].get("gst_rate", "0%")
            lookup_results[desc] = (cat, gifi, gst)
            continue
            
        # Check default custom rules sheet
        cat, gifi, gst = lookup_by_rules(desc)
        if cat:
            lookup_results[desc] = (cat, gifi, gst)
        else:
            unresolved_descs.append(desc)
            
    # Phase 2: Call Gemini for remaining/unknown descriptions
    unresolved_descs = list(set(unresolved_descs))
    gemini_map = {}
    if api_key and unresolved_descs:
        gemini_map = categorize_with_gemini(api_key, unresolved_descs)
        
    # Phase 3: Assemble results with fallback logic
    categorized_txs = []
    for tx in transactions:
        desc = tx.get("description", "")
        is_credit = tx.get("credit") is not None and tx.get("credit") > 0
        
        category = None
        gifi_code = ""
        gst_rate = "0%"
        
        # Check user rules or default lookup rules
        if desc in lookup_results:
            category, gifi_code, gst_rate = lookup_results[desc]
        # Check Gemini response second
        elif desc in gemini_map:
            category = gemini_map[desc]
            meta = CATEGORY_META.get(category, {"gifi": "", "gst": "0%"})
            gifi_code = meta["gifi"]
            gst_rate = meta["gst"]
            
        # Standard default fallbacks
        if not category:
            if is_credit:
                category = "Trade Sales"
                gifi_code = "8000"
                gst_rate = "5%"
            else:
                category = "Other Expenses"
                gifi_code = ""
                gst_rate = "0%"
                
        new_tx = tx.copy()
        new_tx["category"] = category
        new_tx["gifi_code"] = gifi_code
        new_tx["gst_rate"] = gst_rate
        categorized_txs.append(new_tx)
        
    return categorized_txs

def categorize_with_gemini(api_key, descriptions):
    """
    Calls the Gemini API to classify unique descriptions in batch.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    
    categories_list = list(CATEGORY_META.keys())
    prompt = f"""Analyze the following transaction descriptions and assign each one of them to EXACTLY one of these standard business categories:
{json.dumps(categories_list)}

Return a raw JSON object mapping each description key directly to its category value. Do not wrap in markdown or backticks.
Descriptions to categorize:
""" + json.dumps(descriptions)

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
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            candidates = res_data.get("candidates", [])
            if not candidates:
                return {}
            text_response = candidates[0]["content"]["parts"][0]["text"].strip()
            
            # Robust JSON parsing
            start_idx = text_response.find("{")
            end_idx = text_response.rfind("}")
            if start_idx != -1 and end_idx != -1:
                return json.loads(text_response[start_idx:end_idx+1])
    except Exception as e:
        print(f"Error calling Gemini for batch transaction categorization: {e}")
        
    return {}

def get_user_rules():
    """
    Returns the dictionary of saved user overrides from user_rules.json.
    """
    import os
    user_rules_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_rules.json")
    if os.path.exists(user_rules_path):
        try:
            with open(user_rules_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}
