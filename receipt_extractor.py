import base64
import json
import urllib.request
import urllib.error
import re
import time
import io
import sys

# Optional dependency imports
try:
    import pypdfium2
except ImportError:
    pypdfium2 = None

try:
    from PIL import Image
except ImportError:
    Image = None

def convert_pdf_to_image_base64(pdf_path):
    """
    Renders the first page of a PDF receipt to a base64 encoded PNG string.
    """
    if pypdfium2 is None or Image is None:
        raise ImportError("pypdfium2 and pillow are required for PDF rendering.")
        
    doc = pypdfium2.PdfDocument(pdf_path)
    try:
        # Receipts are almost always 1 page, render first page (index 0)
        page = doc[0]
        bitmap = page.render(scale=2)  # High-quality render
        pil_img = bitmap.to_pil()
        
        buffered = io.BytesIO()
        pil_img.save(buffered, format="PNG")
        img_bytes = buffered.getvalue()
        
        return base64.b64encode(img_bytes).decode("utf-8")
    finally:
        doc.close()

def extract_receipt_data(api_key, model, base64_image):
    """
    Calls Gemini API with the receipt image base64 data to extract structured receipt fields.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    prompt = """Extract receipt data. Analyze the receipt image and return a JSON object with:
- 'merchant': Name of the store or vendor (e.g. Walmart, Starbucks, Shell). Keep it short and clean.
- 'date': The purchase date in 'YYYY-MM-DD' format. If no year is present, assume 2026.
- 'invoice_number': The invoice or receipt number as a string (or null if not present).
- 'total': The grand total amount as a float (do not include currency symbols or commas).
- 'tax': The total sales tax amount as a float, or null if not specified.
- 'gst': The GST/HST tax amount as a float (or null if not specified).
- 'tip': The tip or gratuity amount as a float, or null if not specified.
- 'payment_method': The payment method used (e.g. Visa, Mastercard, Cash, Debit), or null if not clear.
- 'category': Categorize the expense into one of these standard Wave accounting categories:
  * Meals & Entertainment (restaurants, cafes, coffee shops)
  * Office Supplies (software, paper, tech accessories)
  * Travel & Lodging (hotels, flights, Uber, rideshare)
  * Automobile Expenses (gas, parking, vehicle maintenance)
  * Professional Services (subscriptions, legal, consulting)
  * Utilities (phone bill, internet, electricity)
  * General Expenses (misc purchases, groceries, household)
- 'items': A list of itemized purchase items. Each object should have 'name' (description of item), 'price' (unit price or item total), and 'qty' (quantity).

Do not include markdown wrappers or backticks. Return raw JSON matching this structure.
"""

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
    
    max_retries = 5
    backoff = 30.0
    
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                
                # Extract text response
                candidates = res_data.get("candidates", [])
                if not candidates:
                    print(f"  Warning: No content returned for receipt on attempt {attempt+1}")
                    return None
                    
                text_response = candidates[0]["content"]["parts"][0]["text"]
                
                # Clean up markdown code block wrappers
                text_response = text_response.strip()
                if text_response.startswith("```"):
                    text_response = re.sub(r"^```(?:json|JSON)?\n", "", text_response)
                    text_response = re.sub(r"\n```$", "", text_response)
                text_response = text_response.strip()
                
                return json.loads(text_response)
                
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"  Rate limited (429) on receipt processing. Waiting {backoff}s... (Attempt {attempt+1}/{max_retries})")
                time.sleep(backoff)
                backoff *= 1.5
            else:
                print(f"Error: API request failed with status {e.code}")
                try:
                    print(e.read().decode("utf-8"))
                except Exception:
                    pass
                break
        except Exception as e:
            print(f"Error calling API on attempt {attempt+1}: {e}")
            break
            
    return None
