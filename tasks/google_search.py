import time
from tasks.base_task import BaseTask
from utils.excel_helper import save_to_excel

class GoogleSearchTask(BaseTask):
    """
    Scrapes Google search results for a specific keyword up to max_results.
    """
    def __init__(self, config_settings, headless=True):
        super().__init__("GoogleSearch", config_settings, headless)

    def execute(self):
        keyword = self.settings.get("keyword")
        max_results = self.settings.get("max_results", 10)
        
        if not keyword:
            raise ValueError("Keyword not specified in configuration.")

        print(f"[GoogleSearch] Searching for: '{keyword}' (max results: {max_results})")
        
        # Navigate to Google
        self.page.goto("https://www.google.com")
        self.page.wait_for_load_state("networkidle")

        # Handle cookies/consent modal if it appears
        try:
            # Common Google consent buttons: "Accept all", "I agree", "Read more"
            consent_selectors = [
                "button:has-text('Accept all')",
                "button:has-text('I agree')",
                "button:has-text('Read more')",
                "#L2AGLb"  # Europe Accept All button ID
            ]
            for selector in consent_selectors:
                loc = self.page.locator(selector)
                if loc.is_visible():
                    print("[GoogleSearch] Clicking consent button...")
                    loc.click()
                    self.page.wait_for_load_state("networkidle")
                    break
        except Exception as e:
            print(f"[GoogleSearch] Check for consent modal failed (likely none appeared): {e}")

        # Locate search input, fill and submit
        search_input = self.page.locator("textarea[name='q'], input[name='q']").first
        search_input.wait_for(state="visible")
        search_input.fill(keyword)
        search_input.press("Enter")
        
        # Wait for search results
        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception as e:
            pass
        
        results = []
        page_num = 1
        
        while len(results) < max_results:
            print(f"[GoogleSearch] Scraping page {page_num}...")
            
            # Wait for search result items (typically class 'g' or search container)
            self.page.wait_for_selector("div.g, .tF2Cxc", timeout=10000)
            
            # Find all result containers
            result_containers = self.page.locator("div.g, .tF2Cxc").all()
            
            if not result_containers:
                print("[GoogleSearch] No result containers found on page.")
                break

            for container in result_containers:
                if len(results) >= max_results:
                    break
                
                try:
                    # Title
                    title_elem = container.locator("h3").first
                    if not title_elem.is_visible(timeout=500):
                        continue
                    title = title_elem.text_content()
                    
                    # URL
                    link_elem = container.locator("a").first
                    url = link_elem.get_attribute("href")
                    
                    if not url or not url.startswith("http"):
                        continue
                        
                    # Snippet (Description)
                    # Snippets are usually in div.VwiC3b, div.yD755b, etc.
                    # We can use a general locator looking for text elements inside the result card
                    snippet = ""
                    snippet_candidates = [
                        container.locator("div.VwiC3b"),
                        container.locator("span.aCOpRe"),
                        container.locator("div.yD755b")
                    ]
                    for candidate in snippet_candidates:
                        if candidate.is_visible(timeout=500):
                            snippet = candidate.text_content()
                            break
                    
                    # If snippet candidates fail, extract descriptive text from the container omitting the title
                    if not snippet:
                        snippet = container.text_content().replace(title, "").strip()[:200]
                    
                    results.append({
                        "Keyword": keyword,
                        "Position": len(results) + 1,
                        "Title": title,
                        "URL": url,
                        "Snippet": snippet
                    })
                except Exception as ex:
                    # Skip problematic search result cards
                    continue

            print(f"[GoogleSearch] Total results scraped so far: {len(results)}")

            if len(results) >= max_results:
                break
                
            # Check for next page
            next_button = self.page.locator("a#pnnext, a:has-text('Next')").first
            if next_button.is_visible():
                print("[GoogleSearch] Navigating to next search page...")
                next_button.click()
                self.page.wait_for_load_state("networkidle")
                page_num += 1
                time.sleep(2)  # Avoid fast pagination detection
            else:
                print("[GoogleSearch] No next page button found. Stopping.")
                break

        print(f"[GoogleSearch] Scraping completed. Found {len(results)} results.")
        
        # Save results to Excel
        save_to_excel(results, "Google Search")
        return results
