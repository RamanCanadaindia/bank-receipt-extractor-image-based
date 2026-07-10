import os
import sys
import re
import time
from datetime import datetime
import pandas as pd
from tasks.base_task import BaseTask
from utils.excel_helper import save_to_excel

class MultiFlightTrackerTask(BaseTask):
    """
    Sequentially searches flight prices on Google Flights, Skyscanner, and Kayak.
    Logs results to a history excel sheet and returns comparison data.
    """
    def __init__(self, config_settings, headless=True):
        super().__init__("MultiFlightTracker", config_settings, headless)

    def execute(self):
        origin = self.settings.get("origin", "DEL").upper()
        destination = self.settings.get("destination", "YVR").upper()
        date = self.settings.get("date", "2026-07-25")

        results = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Google Flights
        gf_res = self._run_google_flights(origin, destination, date)
        results.append({
            "Timestamp": timestamp,
            "Source": "Google Flights",
            "Route": f"{origin}-{destination}",
            "Flight Date": date,
            "Airline": gf_res["Airline"],
            "Price": gf_res["Price"],
            "Status": gf_res["Status"]
        })

        # 2. Skyscanner
        ss_res = self._run_skyscanner(origin, destination, date)
        results.append({
            "Timestamp": timestamp,
            "Source": "Skyscanner",
            "Route": f"{origin}-{destination}",
            "Flight Date": date,
            "Airline": ss_res["Airline"],
            "Price": ss_res["Price"],
            "Status": ss_res["Status"]
        })

        # 3. Kayak
        ky_res = self._run_kayak(origin, destination, date)
        results.append({
            "Timestamp": timestamp,
            "Source": "Kayak",
            "Route": f"{origin}-{destination}",
            "Flight Date": date,
            "Airline": ky_res["Airline"],
            "Price": ky_res["Price"],
            "Status": ky_res["Status"]
        })

        # Save to flight_price_history.xlsx
        self._save_to_history(results)

        # Save to current task output spreadsheet (results.xlsx)
        save_to_excel(results, "Multi Flight Tracker")

        return results

    def _clean_price(self, price_str):
        try:
            cleaned = re.sub(r'[^\d.]', '', price_str)
            return float(cleaned) if cleaned else None
        except:
            return None

    def _run_google_flights(self, origin, destination, date):
        print(f"[MultiFlightTracker] Querying Google Flights for {origin} -> {destination} on {date}...")
        try:
            query = f"One-way flights from {origin} to {destination} on {date}"
            target_url = f"https://www.google.com/travel/flights?q={query.replace(' ', '%20')}"
            self.page.goto(target_url, wait_until="load")
            
            # Handle Cookie consent
            try:
                self.page.locator("button:has-text('Accept all'), button:has-text('I agree'), #L2AGLb").first.click(timeout=1500)
                self.page.wait_for_load_state("networkidle")
            except:
                pass

            # Wait for results container
            self.page.wait_for_selector("div.mxvQLc, .mxvQLc, [role='listitem']", timeout=15000)
            time.sleep(2)

            # Click Cheapest tab to sort
            try:
                cheapest_tab = self.page.get_by_role("tab", name=re.compile("Cheapest", re.IGNORECASE)).first
                if cheapest_tab.is_visible(timeout=2000):
                    cheapest_tab.click()
                    self.page.wait_for_load_state("networkidle")
                    time.sleep(2)
            except:
                pass

            # Extract first row text
            first_row = self.page.locator("div.mxvQLc, .mxvQLc, [role='listitem']").first
            card_text = first_row.text_content() or ""
            
            # Parse Price
            price_match = re.search(r'(?:CA\$|US\$|CAD|USD|₹|\$)\s*\d+(?:[\s,]\d+)*', card_text)
            price = price_match.group(0).strip() if price_match else "N/A"
            
            # Parse Airline
            lines = [line.strip() for line in card_text.split("\n") if line.strip()]
            airline = lines[0][:30] if lines else "Unknown Airline"
            
            return {"Airline": airline, "Price": price, "Status": "Success"}
        except Exception as e:
            return {"Airline": "N/A", "Price": "N/A", "Status": f"Failed: {e}"}

    def _run_skyscanner(self, origin, destination, date):
        print(f"[MultiFlightTracker] Querying Skyscanner for {origin} -> {destination} on {date}...")
        try:
            date_obj = datetime.strptime(date, "%Y-%m-%d")
            formatted_date = date_obj.strftime("%y%m%d")
            target_url = f"https://www.skyscanner.ca/transport/flights/{origin.lower()}/{destination.lower()}/{formatted_date}/?adultsv2=1&cabinclass=economy&rtn=0"
            
            self.page.goto(target_url, wait_until="domcontentloaded")
            
            # Give user a brief window to solve any CAPTCHA challenge
            print("[MultiFlightTracker] Loading Skyscanner. Solve any verification screen if prompted.")
            time.sleep(8)
            
            page_text = self.page.locator("body").text_content() or ""
            prices = re.findall(r'(?:CA\$|C\$|\$)\s*\d+(?:[\s,]\d+)*', page_text)
            numeric_prices = []
            for p in prices:
                val = self._clean_price(p)
                if val and val > 100:
                    numeric_prices.append(val)
                    
            if numeric_prices:
                cheapest_val = min(numeric_prices)
                cheapest_price = f"CA${cheapest_val:,.0f}"
                return {"Airline": "Various Options", "Price": cheapest_price, "Status": "Success"}
            else:
                return {"Airline": "N/A", "Price": "N/A", "Status": "No prices found"}
        except Exception as e:
            return {"Airline": "N/A", "Price": "N/A", "Status": f"Failed: {e}"}

    def _run_kayak(self, origin, destination, date):
        print(f"[MultiFlightTracker] Querying Kayak for {origin} -> {destination} on {date}...")
        try:
            target_url = f"https://www.kayak.com/flights/{origin}-{destination}/{date}?sort=price_a"
            self.page.goto(target_url, wait_until="domcontentloaded")
            
            print("[MultiFlightTracker] Loading Kayak. Solve any verification screen if prompted.")
            time.sleep(8)
            
            page_text = self.page.locator("body").text_content() or ""
            prices = re.findall(r'\$\s*\d+(?:[\s,]\d+)*', page_text)
            numeric_prices = []
            for p in prices:
                val = self._clean_price(p)
                if val and val > 100:
                    numeric_prices.append(val)
                    
            if numeric_prices:
                cheapest_val = min(numeric_prices)
                cheapest_price = f"CA${cheapest_val:,.0f}"
                return {"Airline": "Various Options", "Price": cheapest_price, "Status": "Success"}
            else:
                return {"Airline": "N/A", "Price": "N/A", "Status": "No prices found"}
        except Exception as e:
            return {"Airline": "N/A", "Price": "N/A", "Status": f"Failed: {e}"}

    def _save_to_history(self, new_rows):
        history_path = "output/flight_price_history.xlsx"
        new_df = pd.DataFrame(new_rows)
        if os.path.exists(history_path):
            try:
                existing_df = pd.read_excel(history_path)
                combined = pd.concat([existing_df, new_df], ignore_index=True)
            except:
                combined = new_df
        else:
            combined = new_df
        combined.to_excel(history_path, index=False)
