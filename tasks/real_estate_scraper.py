import os
import sys
import re
import json
import time
from datetime import datetime
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
        
        # Wait for detail frame element to load in parent page DOM to prevent race conditions
        try:
            self.page.wait_for_selector('frame[name="fraDetail"]', timeout=15000)
        except Exception as e:
            print(f"[RealEstateScraper] Frame element wait timed out: {e}")
            
        # Extract content from detail frame 'fraDetail' if present, otherwise main body
        title = self.page.title()
        detail_frame = self.page.frame(name="fraDetail")
        body_text = ""
        
        if detail_frame:
            print("[RealEstateScraper] Accessing detail frame 'fraDetail' with coordinate reconstruction...")
            try:
                detail_frame.wait_for_selector("body", timeout=12000)
                js_code = """
                () => {
                    const elements = Array.from(document.querySelectorAll('div, span, td, th, a'));
                    const data = [];
                    elements.forEach(el => {
                        const text = Array.from(el.childNodes)
                            .filter(n => n.nodeType === 3) // Node.TEXT_NODE
                            .map(n => n.nodeValue.trim())
                            .join(' ')
                            .trim();
                        if (text) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                data.push({
                                    text: text,
                                    top: Math.round(rect.top),
                                    left: Math.round(rect.left)
                                });
                            }
                        }
                    });

                    // Sort by top, then left
                    data.sort((a, b) => a.top - b.top || a.left - b.left);
                    const lines = [];
                    let currentLine = [];
                    let currentTop = -100;
                    data.forEach(item => {
                        if (item.top - currentTop > 6) {
                            if (currentLine.length > 0) {
                                lines.push(currentLine.map(x => x.text).join('  |  '));
                            }
                            currentLine = [item];
                            currentTop = item.top;
                        } else {
                            currentLine.push(item);
                        }
                    });
                    if (currentLine.length > 0) {
                        lines.push(currentLine.map(x => x.text).join('  |  '));
                    }
                    return lines.join('\\n');
                }
                """
                body_text = detail_frame.evaluate(js_code) or ""
            except Exception as fe:
                print(f"[RealEstateScraper] Coordinate JS execution timed out/failed: {fe}. Fallback to plain inner_text.")
                try:
                    body_text = detail_frame.locator("body").inner_text() or ""
                except:
                    body_text = ""
        else:
            print("[RealEstateScraper] Detail frame not found, extracting from main page body...")
            body_elem = self.page.locator("body")
            body_text = body_elem.inner_text() if body_elem.is_visible() else ""
            
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
            - property_type: The property type (e.g. "Townhouse", "Condo", "Detached House")
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
                "property_type": "Townhouse",
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
                        "Property Type": data.get("property_type", "Condo"),
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
        # Address
        address_match = re.search(r'(\d+[\w\s]{2,50}?\b(?:STREET|ST|AVENUE|AVE|AV|ROAD|RD|DRIVE|DR|COURT|CRT|PLACE|PL|WAY|BOULEVARD|BLVD|CRESCENT|CRES)\b)', text, re.IGNORECASE)
        address = address_match.group(1).strip() if address_match else "Scraped MLS Listing Address"
        
        # Price (e.g. 699,000 or $699,000)
        price_match = re.search(r'\$?(\d{3},\d{3})\b', text)
        price = f"${price_match.group(1)}" if price_match else "Check Listing"
        
        # Strata fee (e.g. Maint Fee:  |  $521.54)
        strata_match = re.search(r'(?:Maint Fee|Strata Fee|Maintenance Fee|Maint\. Fee)[\s:|]*(\$?[\d,]+\.?\d*)', text, re.IGNORECASE)
        strata_fee_str = strata_match.group(1) if strata_match else "0"
        try:
            strata_fee = float(re.sub(r'[^\d.]', '', strata_fee_str))
        except:
            strata_fee = 0.0
            
        # Property Tax (e.g. Gross Taxes:  |  $2,887.55)
        tax_match = re.search(r'(?:Gross Taxes|Property Tax|Taxes|Tax)[\s:|]*(\$?[\d,]+\.?\d*)', text, re.IGNORECASE)
        tax_str = tax_match.group(1) if tax_match else "0"
        try:
            property_tax = float(re.sub(r'[^\d.]', '', tax_str))
        except:
            property_tax = 0.0
            
        # MLS Number (e.g. R3134407)
        mls_match = re.search(r'\b[R|M|V]\d{7}\b', text)
        mls_num = mls_match.group(0) if mls_match else "N/A"
        
        # Beds and Baths
        bed_match = re.search(r'(?:Bedrooms|Beds)[\s:|]*(\d+)', text, re.IGNORECASE)
        beds = int(bed_match.group(1)) if bed_match else 1
        
        bath_match = re.search(r'(?:Bathrooms|Baths)[\s:|]*(\d+)', text, re.IGNORECASE)
        baths = int(bath_match.group(1)) if bath_match else 1
        
        # Sqft (e.g. Finished Floor (Total):  |  1,411)
        sqft_match = re.search(r'(?:Finished Floor \(Total\)|Finished Floor Total|Sqft|Square\s*Feet)[\s:|]*([\d,]+)', text, re.IGNORECASE)
        if sqft_match:
            try:
                sqft = int(re.sub(r'[^\d]', '', sqft_match.group(1)))
            except:
                sqft = 800
        else:
            sqft = 800
            
        # Year Built
        year_match = re.search(r'(?:Approx\.\s*Year\s*Built|Year\s*Built|Yr\s*Built)[\s:|]*(\d{4})', text, re.IGNORECASE)
        year_built = int(year_match.group(1)) if year_match else 2000
        
        # Property Type
        prop_type = "Condo"
        if "townhouse" in text.lower() or "row house" in text.lower():
            prop_type = "Townhouse"
        elif "detached" in text.lower() or "single family" in text.lower() or "house" in text.lower():
            prop_type = "Detached House"

        return [{
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Address": address,
            "Price": price,
            "Bedrooms": beds,
            "Bathrooms": baths,
            "Sqft": sqft,
            "Strata Fee": strata_fee,
            "Property Tax": property_tax,
            "Year Built": year_built,
            "Property Type": prop_type,
            "MLS Number": mls_num,
            "Transit Walk Min": 10,
            "Nearest Station": "Nearest Station Hub",
            "Est Rent": 2200,
            "Growth Score": 6,
            "Link": url
        }]
