import os
import sys
import re
import time
from datetime import datetime
import pandas as pd
from playwright.sync_api import sync_playwright

# Append path to ensure imports work correctly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Define output directory
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)
HISTORY_FILE = os.path.join(OUTPUT_DIR, "flight_price_history.xlsx")

def clean_price(price_str):
    """Extracts numeric price from string."""
    try:
        cleaned = re.sub(r'[^\d.]', '', price_str)
        return float(cleaned) if cleaned else None
    except:
        return None

def run_google_flights(playwright, origin, destination, date):
    """Runs Google Flights search silently (headless)."""
    print("\n[Google Flights] Initiating background search...")
    browser = playwright.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"]
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800}
    )
    page = context.new_page()
    page.set_default_timeout(30000)

    try:
        # Build search URL
        query = f"One-way flights from {origin} to {destination} on {date}"
        target_url = f"https://www.google.com/travel/flights?q={query.replace(' ', '%20')}"
        page.goto(target_url, wait_until="load")
        
        # Handle Cookie consent
        try:
            page.locator("button:has-text('Accept all'), button:has-text('I agree'), #L2AGLb").first.click(timeout=2000)
            page.wait_for_load_state("networkidle")
        except:
            pass

        # Wait for results
        page.wait_for_selector("[role='listitem']", timeout=15000)
        
        # Click Cheapest tab to sort
        try:
            cheapest_tab = page.get_by_role("tab", name=re.compile("Cheapest", re.IGNORECASE)).first
            if cheapest_tab.is_visible(timeout=2000):
                cheapest_tab.click()
                page.wait_for_load_state("networkidle")
                time.sleep(2)
        except:
            pass

        # Extract visible text from first row
        first_row = page.locator("[role='listitem']").first
        card_text = first_row.text_content() or ""
        
        # Parse price
        price_match = re.search(r'(?:CA\$|US\$|CAD|USD|₹|\$)\s*\d+(?:[\s,]\d+)*', card_text)
        price = price_match.group(0).strip() if price_match else "N/A"
        
        # Parse Airline
        lines = [line.strip() for line in card_text.split("\n") if line.strip()]
        airline = lines[0][:30] if lines else "Unknown Airline"
        
        print(f"[Google Flights] Found Cheapest: {price} on {airline}")
        return {"Airline": airline, "Price": price, "Status": "Success"}
    except Exception as e:
        print(f"[Google Flights] Error: {e}")
        return {"Airline": "N/A", "Price": "N/A", "Status": f"Failed: {e}"}
    finally:
        browser.close()

def run_skyscanner(playwright, origin, destination, date):
    """Runs Skyscanner search briefly (headed for CAPTCHA bypass)."""
    print("\n[Skyscanner] Initiating headed search (browser window will open)...")
    browser = playwright.chromium.launch(
        headless=False,  # Headed so user can solve CAPTCHAs if triggered
        args=["--disable-blink-features=AutomationControlled"]
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800}
    )
    page = context.new_page()
    page.set_default_timeout(45000)

    try:
        # Build direct Skyscanner flight URL
        # Format: del/yvr/yymmdd
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        formatted_date = date_obj.strftime("%y%m%d")
        target_url = f"https://www.skyscanner.ca/transport/flights/{origin.lower()}/{destination.lower()}/{formatted_date}/?adultsv2=1&cabinclass=economy&rtn=0"
        
        print(f"[Skyscanner] Opening URL: {target_url}")
        page.goto(target_url, wait_until="domcontentloaded")
        
        # Give user time to solve CAPTCHA if needed
        print("[Skyscanner] Loading page... If you see a verification/CAPTCHA screen, please click it now.")
        time.sleep(10)
        
        # Extract page text to parse price list
        page_text = page.locator("body").text_content() or ""
        
        # Extract prices
        prices = re.findall(r'(?:CA\$|C\$|\$)\s*\d+(?:[\s,]\d+)*', page_text)
        numeric_prices = []
        for p in prices:
            val = clean_price(p)
            if val and val > 100:  # Ignore small numbers / filters
                numeric_prices.append(val)
                
        if numeric_prices:
            cheapest_val = min(numeric_prices)
            cheapest_price = f"CA${cheapest_val:,.0f}"
            print(f"[Skyscanner] Found Cheapest Price: {cheapest_price}")
            return {"Airline": "Various Options", "Price": cheapest_price, "Status": "Success"}
        else:
            print("[Skyscanner] No flight prices could be extracted.")
            return {"Airline": "N/A", "Price": "N/A", "Status": "No prices found"}
    except Exception as e:
        print(f"[Skyscanner] Error: {e}")
        return {"Airline": "N/A", "Price": "N/A", "Status": f"Failed: {e}"}
    finally:
        browser.close()

def run_kayak(playwright, origin, destination, date):
    """Runs Kayak search briefly (headed for CAPTCHA bypass)."""
    print("\n[Kayak] Initiating headed search (browser window will open)...")
    browser = playwright.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"]
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800}
    )
    page = context.new_page()
    page.set_default_timeout(45000)

    try:
        # Build direct Kayak URL
        # Format: DEL-YVR/YYYY-MM-DD
        target_url = f"https://www.kayak.com/flights/{origin.upper()}-{destination.upper()}/{date}?sort=price_a"
        
        print(f"[Kayak] Opening URL: {target_url}")
        page.goto(target_url, wait_until="domcontentloaded")
        
        print("[Kayak] Loading page... Solve any verification screen if prompted.")
        time.sleep(10)
        
        # Parse price list
        page_text = page.locator("body").text_content() or ""
        prices = re.findall(r'\$\s*\d+(?:[\s,]\d+)*', page_text)
        numeric_prices = []
        for p in prices:
            val = clean_price(p)
            if val and val > 100:
                numeric_prices.append(val)
                
        if numeric_prices:
            cheapest_val = min(numeric_prices)
            cheapest_price = f"CA${cheapest_val:,.0f}"
            print(f"[Kayak] Found Cheapest Price: {cheapest_price}")
            return {"Airline": "Various Options", "Price": cheapest_price, "Status": "Success"}
        else:
            print("[Kayak] No flight prices could be extracted.")
            return {"Airline": "N/A", "Price": "N/A", "Status": "No prices found"}
    except Exception as e:
        print(f"[Kayak] Error: {e}")
        return {"Airline": "N/A", "Price": "N/A", "Status": f"Failed: {e}"}
    finally:
        browser.close()

def save_to_history(data_rows):
    """Appends data rows to flight_price_history.xlsx sheet."""
    new_df = pd.DataFrame(data_rows)
    
    if os.path.exists(HISTORY_FILE):
        try:
            existing_df = pd.read_excel(HISTORY_FILE)
            combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        except Exception as e:
            print(f"[History] Could not read existing history excel, creating fresh: {e}")
            combined_df = new_df
    else:
        combined_df = new_df
        
    combined_df.to_excel(HISTORY_FILE, index=False)
    print(f"\n[History] Flight price log successfully written to: {HISTORY_FILE}")

def main():
    # --- TASK CONFIGURATION ---
    ORIGIN = "DEL"
    DESTINATION = "YVR"
    DATE = "2026-07-25"  # Format YYYY-MM-DD
    # --------------------------
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print(f" Flight Price Tracker Run: {timestamp}")
    print(f" Route: {ORIGIN} -> {DESTINATION} | Date: {DATE}")
    print("=" * 60)
    
    results = []
    with sync_playwright() as playwright:
        # 1. Run Google Flights (Headless/Silent)
        gf_res = run_google_flights(playwright, ORIGIN, DESTINATION, DATE)
        results.append({
            "Timestamp": timestamp,
            "Source": "Google Flights",
            "Route": f"{ORIGIN}-{DESTINATION}",
            "Flight Date": DATE,
            "Airline": gf_res["Airline"],
            "Price": gf_res["Price"],
            "Status": gf_res["Status"]
        })
        
        # 2. Run Skyscanner (Headed)
        ss_res = run_skyscanner(playwright, ORIGIN, DESTINATION, DATE)
        results.append({
            "Timestamp": timestamp,
            "Source": "Skyscanner",
            "Route": f"{ORIGIN}-{DESTINATION}",
            "Flight Date": DATE,
            "Airline": ss_res["Airline"],
            "Price": ss_res["Price"],
            "Status": ss_res["Status"]
        })
        
        # 3. Run Kayak (Headed)
        ky_res = run_kayak(playwright, ORIGIN, DESTINATION, DATE)
        results.append({
            "Timestamp": timestamp,
            "Source": "Kayak",
            "Route": f"{ORIGIN}-{DESTINATION}",
            "Flight Date": DATE,
            "Airline": ky_res["Airline"],
            "Price": ky_res["Price"],
            "Status": ky_res["Status"]
        })
        
    # Write to Excel log sheet
    save_to_history(results)
    
    print("\nPrice tracker completed successfully!")

if __name__ == "__main__":
    main()
