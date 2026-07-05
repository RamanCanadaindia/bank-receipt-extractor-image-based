import re
import json
import urllib.request
import urllib.error

# Heuristic rules for common transaction types
KEYWORDS_MAP = {
    r"shell|petro|esso|chevron|gas|fuel|husky|co-op|coop": "Automotive & Travel",
    r"starbucks|tim\s*horton|mcdonald|restaurant|pub|grill|cafe|subway|pizza|uber\s*eats|skip\s*the|doordash|tim\s*bit": "Meals & Entertainment",
    r"walmart|loblaws|sobeys|safeway|costco|grocer|metro|no\s*frills|superstore|grocery": "Groceries",
    r"amazon|staples|indigo|ink|paper|software|adobe|microsoft|google|github|aws|zoom|domain|host": "Office Expenses",
    r"rent|lease|landlord|realty|mortgage": "Rent & Utilities",
    r"rogers|bell|telus|shaw|fido|koodo|internet|hydro|power|water|energy": "Rent & Utilities",
    r"fee|service\s*charge|nsf|monthly\s*fee|interest\s*charge|bank\s*card|chg|overdraft": "Bank Fees & Interest",
    r"insurance|intact|aviva|co-operators|td\s*insurance|desjardins": "Insurance",
    r"payroll|salary|wage|bonus|direct\s*deposit|subcontract|employee": "Subcontractors & Labor",
    r"revenue|invoice|deposit|e-transfer\s*receive|etransfer\s*rec|payment\s*received|square\s*inc|stripe|wire\s*transfer": "Revenue / Deposits",
    r"advertising|marketing|facebook|adwords|meta\s*ad|ad\s*spend": "Advertising & Marketing",
    r"legal|law|cpa|accountant|notary|counsel|audit": "Professional Fees",
    r"cra|tax|revenue\s*agency|gst|hst|corporate\s*tax": "Taxes & Licenses"
}

def categorize_by_rules(desc, is_credit=False):
    desc_lower = str(desc).lower()
    
    # Check keyword patterns
    for pattern, category in KEYWORDS_MAP.items():
        if re.search(pattern, desc_lower):
            return category
            
    # Default fallbacks
    if is_credit:
        return "Revenue / Deposits"
    else:
        return "Other Expenses"

def categorize_transactions(api_key, transactions):
    """
    Categorize a list of transaction dictionaries.
    Uses Gemini if api_key is provided, falling back to local rule-based heuristics.
    """
    if not transactions:
        return []
        
    # Extract unique descriptions to optimize API payload size
    unique_descriptions = list(set(
        t["description"] for t in transactions if t.get("description")
    ))
    
    gemini_map = {}
    if api_key:
        gemini_map = categorize_with_gemini(api_key, unique_descriptions)
        
    # Map back to transactions
    categorized_txs = []
    for tx in transactions:
        desc = tx.get("description", "")
        is_credit = tx.get("credit") is not None and tx.get("credit") > 0
        
        # Check Gemini response first
        category = gemini_map.get(desc)
        
        # Verify it mapped to a valid category, otherwise fallback to rules
        valid_categories = {
            "Advertising & Marketing", "Automotive & Travel", "Office Expenses",
            "Meals & Entertainment", "Professional Fees", "Rent & Utilities",
            "Insurance", "Subcontractors & Labor", "Bank Fees & Interest",
            "Taxes & Licenses", "Revenue / Deposits", "Groceries", "Other Expenses"
        }
        if not category or category not in valid_categories:
            category = categorize_by_rules(desc, is_credit)
            
        new_tx = tx.copy()
        new_tx["category"] = category
        categorized_txs.append(new_tx)
        
    return categorized_txs

def categorize_with_gemini(api_key, descriptions):
    """
    Calls the Gemini API to classify unique descriptions in batch.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    
    prompt = """Analyze the following transaction descriptions and assign each one of them to EXACTLY one of these standard business categories:
- Advertising & Marketing
- Automotive & Travel
- Office Expenses
- Meals & Entertainment
- Professional Fees
- Rent & Utilities
- Insurance
- Subcontractors & Labor
- Bank Fees & Interest
- Taxes & Licenses
- Revenue / Deposits
- Groceries
- Other Expenses

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
