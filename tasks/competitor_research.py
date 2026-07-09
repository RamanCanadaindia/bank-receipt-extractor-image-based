import re
import os
import sys
import json
import time
from urllib.parse import urlparse
from tasks.base_task import BaseTask
from utils.excel_helper import save_to_excel
from utils.gemini_helper import query_gemini

# List of common directory/social sites that aren't direct competitor businesses
EXCLUDED_DOMAINS = {
    "google.com", "youtube.com", "wikipedia.org", "facebook.com", "twitter.com", 
    "x.com", "linkedin.com", "instagram.com", "yelp.com", "yelp.ca", 
    "yellowpages.ca", "yellowpages.com", "mapquest.com", "tripadvisor.com", 
    "reddit.com", "pinterest.com", "foursquare.com", "groupon.com", "bbb.org"
}

class CompetitorResearchTask(BaseTask):
    """
    Finds competitor websites via Google search and extracts key details 
    (business name, services, phone, email, pricing keywords) from their sites.
    Uses Gemini API if available, otherwise falls back to local heuristic extraction.
    """
    def __init__(self, config_settings, headless=True):
        super().__init__("CompetitorResearch", config_settings, headless)

    def execute(self):
        keyword = self.settings.get("keyword")
        max_results = self.settings.get("max_results", 10)
        extract_fields = self.settings.get("extract", [
            "business_name", "website", "services", "phone", "email", "pricing_keywords"
        ])

        if not keyword:
            raise ValueError("Keyword not specified in configuration.")

        print(f"[CompetitorResearch] Keyword: '{keyword}' (finding up to {max_results} competitors)")

        # 1. Search Google to find competitor domains
        self.page.goto("https://www.google.com")
        self.page.wait_for_load_state("networkidle")

        try:
            # Dismiss cookie consent dialogs
            consent_selectors = [
                "button:has-text('Accept all')",
                "button:has-text('I agree')",
                "button:has-text('Read more')",
                "#L2AGLb"
            ]
            for selector in consent_selectors:
                loc = self.page.locator(selector)
                if loc.is_visible():
                    loc.click()
                    self.page.wait_for_load_state("networkidle")
                    break
        except Exception as e:
            print(f"[CompetitorResearch] Consent check passed: {e}")

        # Input keyword
        search_input = self.page.locator("textarea[name='q'], input[name='q']").first
        search_input.wait_for(state="visible")
        search_input.fill(keyword)
        search_input.press("Enter")
        self.page.wait_for_load_state("networkidle")

        competitor_urls = []
        page_num = 1

        # Retrieve Google organic URLs until we get enough unique, valid competitor sites
        while len(competitor_urls) < max_results:
            print(f"[CompetitorResearch] Extracting organic links from search page {page_num}...")
            self.page.wait_for_selector("div.g, .tF2Cxc", timeout=10000)
            
            result_containers = self.page.locator("div.g, .tF2Cxc").all()
            if not result_containers:
                break

            for container in result_containers:
                if len(competitor_urls) >= max_results:
                    break
                try:
                    link_elem = container.locator("a").first
                    url = link_elem.get_attribute("href")
                    if not url or not url.startswith("http"):
                        continue
                    
                    # Parse domain to filter excluded platforms
                    domain = urlparse(url).netloc.lower()
                    if domain.startswith("www."):
                        domain = domain[4:]
                        
                    # Skip if domain matches exclusion list or is already added
                    if domain in EXCLUDED_DOMAINS or any(domain in u for u in competitor_urls):
                        continue
                        
                    competitor_urls.append(url)
                except:
                    continue

            if len(competitor_urls) >= max_results:
                break

            # Click next
            next_button = self.page.locator("a#pnnext, a:has-text('Next')").first
            if next_button.is_visible():
                next_button.click()
                self.page.wait_for_load_state("networkidle")
                page_num += 1
                time.sleep(2)
            else:
                break

        print(f"[CompetitorResearch] Found {len(competitor_urls)} potential competitor websites to analyze:")
        for idx, u in enumerate(competitor_urls, 1):
            print(f"  {idx}. {u}")

        # 2. Visit each website and extract required fields
        results = []
        for idx, url in enumerate(competitor_urls, 1):
            print(f"[CompetitorResearch] ({idx}/{len(competitor_urls)}) Analyzing website: {url}")
            try:
                self.page.goto(url, wait_until="load")
                self.page.wait_for_load_state("networkidle", timeout=15000)
                
                # Extract text contents
                title = self.page.title()
                body_elem = self.page.locator("body")
                body_text = body_elem.text_content() if body_elem.is_visible() else ""
                
                # Check for Gemini API key
                api_model = query_gemini("test", response_json=False)
                # If we get a response (or can configure Gemini client successfully), query_gemini will return non-None
                # Let's check environment variable directly to decide whether to query Gemini
                gemini_active = os.environ.get("GEMINI_API_KEY") is not None

                if gemini_active:
                    print("[CompetitorResearch] Querying Gemini for detail extraction...")
                    prompt = f"""
                    You are a competitor research bot. Extract information from the competitor website text below.
                    Website URL: {url}
                    Website Title: {title}
                    Website Content:
                    {body_text[:12000]} # Limit to first 12k chars to fit context nicely

                    Extract the following fields based on the user requirements:
                    {extract_fields}

                    Guidelines:
                    - business_name: The company or firm name (often visible in title or headers)
                    - website: {url}
                    - services: Bulleted summary of services they offer (e.g. Tax preparation, payroll, bookkeeping)
                    - phone: The phone number(s) listed on the page
                    - email: The email address(es) listed on the page
                    - pricing_keywords: Mentions of pricing models, costs, packages, fees, or if they offer a free consultation.

                    Format the output strictly as a JSON object with keys corresponding to the fields:
                    {{
                        "business_name": "...",
                        "website": "{url}",
                        "services": "...",
                        "phone": "...",
                        "email": "...",
                        "pricing_keywords": "..."
                    }}
                    Only output valid JSON, no markdown code blocks or extra text.
                    """
                    gemini_response = query_gemini(prompt, response_json=True)
                    if gemini_response:
                        try:
                            # Clean response if markdown blocks leaked
                            cleaned_response = gemini_response.strip()
                            if cleaned_response.startswith("```json"):
                                cleaned_response = cleaned_response[7:]
                            if cleaned_response.endswith("```"):
                                cleaned_response = cleaned_response[:-3]
                            
                            data = json.loads(cleaned_response.strip())
                            
                            # Filter keys based on active extraction config
                            row = {field: data.get(field, "") for field in extract_fields}
                            # Ensure website is populated
                            if "website" in extract_fields:
                                row["website"] = url
                            results.append(row)
                            print("[CompetitorResearch] Extracted details via Gemini.")
                            continue
                        except Exception as json_err:
                            print(f"[CompetitorResearch] Failed to parse Gemini JSON output: {json_err}. Falling back to local rules.")

                # Fallback to local heuristic parsing
                print("[CompetitorResearch] Extracting details via local heuristics fallback...")
                data = self._local_heuristic_extraction(url, title, body_text)
                row = {field: data.get(field, "") for field in extract_fields}
                if "website" in extract_fields:
                    row["website"] = url
                results.append(row)

            except Exception as e:
                print(f"[CompetitorResearch] Error visiting competitor site {url}: {e}", file=sys.stderr)
                # Save screenshot of failure
                clean_url = url.replace("https://", "").replace("http://", "").replace("/", "_")[:50]
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                os.makedirs("output/errors", exist_ok=True)
                screenshot_path = f"output/errors/fail_competitor_{clean_url}_{timestamp}.png"
                try:
                    self.page.screenshot(path=screenshot_path)
                except:
                    pass
                
                # Fill row with error details
                row = {field: "Error visiting page" for field in extract_fields}
                if "website" in extract_fields:
                    row["website"] = url
                results.append(row)

        # Save to excel
        save_to_excel(results, "Competitor Research")
        return results

    def _local_heuristic_extraction(self, url, title, body_text):
        """Helper to do heuristic/regex-based extraction of details from text."""
        # 1. Business name (use Title or extract before separator)
        business_name = title.split("|")[0].split("-")[0].split("•")[0].strip()
        if not business_name or business_name.lower() in ["home", "welcome", "website"]:
            # fallback to domain name capitalized
            domain = urlparse(url).netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            business_name = domain.split(".")[0].capitalize()

        # Clean text for search
        clean_text = " ".join(body_text.split())

        # 2. Email Address regex search
        emails = re.findall(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b', clean_text)
        # Filter out common false-positive image extensions or formats if needed
        email_str = ", ".join(list(set(emails))[:2]) if emails else "Not found"

        # 3. Phone Number regex search
        phones = re.findall(r'\(?\b[0-9]{3}\)?[-. ]?[0-9]{3}[-. ]?[0-9]{4}\b', clean_text)
        phone_str = ", ".join(list(set(phones))[:2]) if phones else "Not found"

        # 4. Services Offered keyword matching
        service_keywords = [
            "bookkeeping", "tax preparation", "payroll", "accounting", "corporate tax", 
            "personal tax", "financial statements", "consulting", "cfo", "gst", "audit"
        ]
        found_services = []
        for kw in service_keywords:
            if kw in clean_text.lower():
                found_services.append(kw.capitalize())
        services_str = ", ".join(found_services[:5]) if found_services else "General services"

        # 5. Pricing Keywords matching
        pricing_terms = ["price", "pricing", "cost", "fee", "rate", "packages", "quote", "free consultation"]
        found_pricing = []
        # Look for sentences containing pricing keywords
        sentences = re.split(r'[.!?]', clean_text)
        for sentence in sentences:
            if len(found_pricing) >= 3:
                break
            for term in pricing_terms:
                if re.search(r'\b' + re.escape(term) + r'\b', sentence.lower()):
                    found_pricing.append(sentence.strip())
                    break
        pricing_str = " | ".join(found_pricing) if found_pricing else "No pricing info listed. Contact for details."

        return {
            "business_name": business_name,
            "website": url,
            "services": services_str,
            "phone": phone_str,
            "email": email_str,
            "pricing_keywords": pricing_str[:300]  # Cap length for cell
        }
