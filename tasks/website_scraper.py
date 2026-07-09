import os
import sys
from datetime import datetime
from tasks.base_task import BaseTask
from utils.excel_helper import save_to_excel

class WebsiteScraperTask(BaseTask):
    """
    Scrapes basic metadata and content summary for a list of URLs.
    """
    def __init__(self, config_settings, headless=True):
        super().__init__("WebsiteScraper", config_settings, headless)

    def execute(self):
        urls = self.settings.get("urls", [])
        if not urls:
            raise ValueError("No URLs specified in configuration.")

        print(f"[WebsiteScraper] Scraping {len(urls)} URLs...")
        results = []

        for idx, url in enumerate(urls, 1):
            print(f"[WebsiteScraper] ({idx}/{len(urls)}) Scraping URL: {url}")
            
            try:
                # Navigate to the page
                self.page.goto(url, wait_until="load")
                self.page.wait_for_load_state("networkidle", timeout=10000)
                
                # Title
                title = self.page.title()
                
                # Meta description
                meta_desc = ""
                meta_desc_elem = self.page.locator("meta[name='description'], meta[property='og:description']").first
                if meta_desc_elem.is_visible(timeout=500):
                    meta_desc = meta_desc_elem.get_attribute("content") or ""
                
                # Main Heading (H1)
                h1_text = ""
                h1_elem = self.page.locator("h1").first
                if h1_elem.is_visible(timeout=500):
                    h1_text = h1_elem.text_content().strip()
                
                # Page Body Summary (first 1000 characters)
                body_text = self.page.locator("body").text_content() or ""
                # Clean up multiple whitespaces/newlines
                body_text_clean = " ".join(body_text.split())
                body_summary = body_text_clean[:1000] + ("..." if len(body_text_clean) > 1000 else "")
                
                results.append({
                    "URL": url,
                    "Title": title,
                    "Meta Description": meta_desc.strip(),
                    "Main Heading (H1)": h1_text,
                    "Body Summary": body_summary,
                    "Status": "Success",
                    "Scrape Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                
            except Exception as e:
                print(f"[WebsiteScraper] Error scraping {url}: {e}", file=sys.stderr)
                
                # Capture screenshot specifically for this URL failure
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                error_dir = "output/errors"
                os.makedirs(error_dir, exist_ok=True)
                # Clean url for filename
                clean_url = url.replace("https://", "").replace("http://", "").replace("/", "_").replace("?", "_")[:50]
                screenshot_path = os.path.join(error_dir, f"fail_{clean_url}_{timestamp}.png")
                
                try:
                    self.page.screenshot(path=screenshot_path)
                    print(f"[WebsiteScraper] Error screenshot saved to: {screenshot_path}", file=sys.stderr)
                except Exception as ex:
                    print(f"[WebsiteScraper] Could not save screenshot: {ex}", file=sys.stderr)
                
                results.append({
                    "URL": url,
                    "Title": "ERROR",
                    "Meta Description": str(e),
                    "Main Heading (H1)": "ERROR",
                    "Body Summary": "Navigation or parsing failed.",
                    "Status": "Failed",
                    "Scrape Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })

        print(f"[WebsiteScraper] Scraping completed. Scraped {len(results)} pages.")
        
        # Save results to Excel
        save_to_excel(results, "Website Scraper")
        return results
