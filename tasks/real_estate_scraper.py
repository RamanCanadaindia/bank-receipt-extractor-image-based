import os
import sys
import re
import json
import time
from tasks.base_task import BaseTask
from utils.excel_helper import save_to_excel
from utils.gemini_helper import query_gemini

class RealEstateScraperTask(BaseTask):
    """
    Visits a Paragon MLS listing link, extracts key property parameters,
    uses Gemini to estimate proximity scores (Skytrain walk times, growth potential, rent range),
    and logs them.
    """
    def __init__(self, config_settings, headless=True):
        super().__init__("RealEstateScraper", config_settings, headless)

    def execute(self):
        url = self.settings.get("url")
        if not url:
            raise ValueError("Real estate scraper requires a listing 'url' to be configured.")

        print(f"[RealEstateScraper] Navigating to: {url}")
        self.page.goto(url, wait_until="load")
        
        # Wait for content to settle (Paragon pages often load inside frames or dynamically load detail grids)
        time.sleep(5)

        # Extract title and entire visible text
        title = self.page.title()
        body_elem = self.page.locator("body")
        body_text = body_elem.text_content() if body_elem.is_visible() else ""
        
        # Clean text
        clean_text = " ".join(body_text.split())

        # Check for Gemini API key
        gemini_active = os.environ.get("GEMINI_API_KEY") is not None
        results = []

        if gemini_active:
            print("[RealEstateScraper] Querying Gemini to extract and analyze property parameters...")
            prompt = f"""
            You are a real estate research assistant. Parse the property listing details from the webpage text below.
            URL: {url}
            Webpage Title: {title}
            Webpage Content:
            {clean_text[:15000]}  # Limit content size

            Extract the following parameters:
            - address: The full property address (including street, unit number, city, and province/postal code if available)
            - price: The list price as a number or string (e.g. 750000 or "$750,000")
            - beds: Number of bedrooms (integer or float, e.g. 2)
            - baths: Number of bathrooms (integer or float, e.g. 2)
            - sqft: Total square footage (integer, e.g. 850)
            - strata_fee: Monthly maintenance/strata fee as a number (e.g. 350.00. Set 0 if no strata/maintenance fee is present)
            - property_tax: Annual property tax as a number (e.g. 2100.00. Set 0 if not listed)
            - year_built: Year the property was built (integer, e.g. 2018)
            - mls_number: The MLS number if listed (e.g. R2891321)

            Also, estimate the following research parameters based on your geography knowledge of Metro Vancouver (if the address is in British Columbia):
            - skytrain_walk_minutes: Estimated walking time to the nearest Skytrain station in minutes (integer, e.g. 8. If detached house far from station, estimate walking time to transit hub).
            - skytrain_station: Name of the nearest Skytrain station (e.g. Surrey Central, Metrotown, Lougheed).
            - est_rent: Estimated monthly market rent for this property type, beds/baths, and city (integer, e.g. 2500)
            - growth_score: Estimated long-term capital growth potential score from 1 to 10 (integer, e.g. 8. Detached land = 9/10, Surrey/Burnaby development hubs = 8/10, older woodframe condos = 5/10)

            Format your response strictly as a JSON object:
            {{
                "address": "...",
                "price": "...",
                "beds": 2,
                "baths": 2,
                "sqft": 850,
                "strata_fee": 350.00,
                "property_tax": 2100.00,
                "year_built": 2018,
                "mls_number": "...",
                "skytrain_walk_minutes": 8,
                "skytrain_station": "...",
                "est_rent": 2500,
                "growth_score": 8
            }}
            Do not include markdown code blocks or any other explanation. Only return valid JSON.
            """
            gemini_response = query_gemini(prompt, response_json=True)
            if gemini_response:
                try:
                    cleaned_response = gemini_response.strip()
                    if cleaned_response.startswith("```json"):
                        cleaned_response = cleaned_response[7:]
                    if cleaned_response.endswith("```"):
                        cleaned_response = cleaned_response[:-3]
                        
                    data = json.loads(cleaned_response.strip())
                    
                    results.append({
                        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Address": data.get("address", "Unknown Address"),
                        "Price": data.get("price", "0"),
                        "Bedrooms": data.get("beds", 0),
                        "Bathrooms": data.get("baths", 0),
                        "Sqft": data.get("sqft", 0),
                        "Strata Fee": data.get("strata_fee", 0.0),
                        "Property Tax": data.get("property_tax", 0.0),
                        "Year Built": data.get("year_built", 0),
                        "MLS Number": data.get("mls_number", "N/A"),
                        "Transit Walk Min": data.get("skytrain_walk_minutes", 15),
                        "Nearest Station": data.get("skytrain_station", "Unknown Transit"),
                        "Est Rent": data.get("est_rent", 2000),
                        "Growth Score": data.get("growth_score", 5),
                        "Link": url
                    })
                    print(f"[RealEstateScraper] Successfully extracted property listing via Gemini.")
                except Exception as json_err:
                    print(f"[RealEstateScraper] Failed to parse Gemini response: {json_err}. Falling back to local rules.")

        if not results:
            print("[RealEstateScraper] Running local text-parsing heuristics fallback...")
            results = self._local_heuristic_parse(clean_text, url)

        # Save to local active task spreadsheet
        save_to_excel(results, "Real Estate Listings")
        return results

    def _local_heuristic_parse(self, text, url):
        # Fallback regexes
        price_match = re.search(r'\$\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})?', text)
        price = price_match.group(0) if price_match else "Check Listing"
        
        strata_match = re.search(r'(?:Strata Fee|Maintenance Fee|Maint\. Fee)\s*(?::|\$)?\s*(\d+(?:\.\d{2})?)', text, re.IGNORECASE)
        strata_fee = float(strata_match.group(1)) if strata_match else 0.0
        
        tax_match = re.search(r'(?:Property Tax|Taxes|Tax)\s*(?::|\$)?\s*(\d+(?:\.\d{2})?)', text, re.IGNORECASE)
        property_tax = float(tax_match.group(1)) if tax_match else 0.0
        
        mls_match = re.search(r'\b[R|M|V]\d{7}\b', text)
        mls_num = mls_match.group(0) if mls_match else "N/A"
        
        bed_match = re.search(r'(\d+)\s*(?:Bedrooms|Bed|Beds)', text, re.IGNORECASE)
        beds = int(bed_match.group(1)) if bed_match else 1
        
        bath_match = re.search(r'(\d+)\s*(?:Bathrooms|Bath|Baths)', text, re.IGNORECASE)
        baths = int(bath_match.group(1)) if bath_match else 1
        
        sqft_match = re.search(r'(\d{3,4})\s*(?:Sqft|Sq\. Ft\.|Square Feet)', text, re.IGNORECASE)
        sqft = int(sqft_match.group(1)) if sqft_match else 800

        # Create basic result row
        return [{
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Address": "Scraped MLS Listing Address",
            "Price": price,
            "Bedrooms": beds,
            "Bathrooms": baths,
            "Sqft": sqft,
            "Strata Fee": strata_fee,
            "Property Tax": property_tax,
            "Year Built": 2000,
            "MLS Number": mls_num,
            "Transit Walk Min": 15,
            "Nearest Station": "Nearest Station Hub",
            "Est Rent": 2200,
            "Growth Score": 6,
            "Link": url
        }]
