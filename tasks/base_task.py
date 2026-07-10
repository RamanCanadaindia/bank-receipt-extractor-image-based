import os
import sys
from datetime import datetime
from playwright.sync_api import sync_playwright

class BaseTask:
    """
    Base class for Playwright automation tasks.
    Manages browser lifecycle, default configuration, error screenshots, and cleanup.
    """
    def __init__(self, task_name, config_settings, headless=True):
        self.task_name = task_name
        self.settings = config_settings
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def __enter__(self):
        self.start_browser()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            # An error occurred, capture a screenshot
            self.handle_error(exc_val)
        self.close_browser()

    def start_browser(self):
        """Launches the Playwright browser and sets up context/page."""
        print(f"[{self.task_name}] Starting Chromium browser (headless={self.headless})...")
        self.playwright = sync_playwright().start()
        try:
            self.browser = self.playwright.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"]  # Help avoid simple bot detection
            )
        except Exception as launch_err:
            err_str = str(launch_err).lower()
            if "executable" in err_str or "not installed" in err_str or "find" in err_str or "playwright install" in err_str:
                print(f"[{self.task_name}] Playwright chromium not found. Installing chromium browser binaries...")
                import subprocess
                installed_ok = False
                # Try system command first
                try:
                    subprocess.run(["playwright", "install", "chromium"], check=True)
                    installed_ok = True
                except Exception as e1:
                    print(f"[{self.task_name}] System playwright install failed ({e1}). Trying via python module...")
                    
                # Try python module fallback
                if not installed_ok:
                    try:
                        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                        installed_ok = True
                    except Exception as e2:
                        print(f"[{self.task_name}] Python module playwright install failed ({e2}).")
                
                if installed_ok:
                    try:
                        self.browser = self.playwright.chromium.launch(
                            headless=self.headless,
                            args=["--disable-blink-features=AutomationControlled"]
                        )
                    except Exception as launch_retry_err:
                        print(f"[{self.task_name}] Failed to launch browser even after installation attempt: {launch_retry_err}")
                        raise launch_err
                else:
                    raise launch_err
            else:
                raise launch_err
        # Set a realistic user agent and viewport size
        self.context = self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        self.page = self.context.new_page()
        # Set default timeout (30 seconds)
        self.page.set_default_timeout(30000)

    def close_browser(self):
        """Safely closes the page, context, browser, and playwright instance."""
        if self.page:
            try:
                self.page.close()
            except:
                pass
        if self.context:
            try:
                self.context.close()
            except:
                pass
        if self.browser:
            try:
                self.browser.close()
            except:
                pass
        if self.playwright:
            try:
                self.playwright.stop()
            except:
                pass
        print(f"[{self.task_name}] Browser successfully closed.")

    def handle_error(self, exception):
        """Captures a screenshot on error and saves it to output/errors/."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        error_dir = "output/errors"
        os.makedirs(error_dir, exist_ok=True)
        screenshot_path = os.path.join(error_dir, f"error_{self.task_name}_{timestamp}.png")
        
        print(f"[{self.task_name}] ERROR: {exception}", file=sys.stderr)
        
        if self.page:
            try:
                self.page.screenshot(path=screenshot_path, full_page=True)
                print(f"[{self.task_name}] Error screenshot saved to: {screenshot_path}", file=sys.stderr)
            except Exception as e:
                print(f"[{self.task_name}] Failed to capture error screenshot: {e}", file=sys.stderr)
        else:
            print(f"[{self.task_name}] Browser page was not initialized, screenshot skipped.", file=sys.stderr)

    def execute(self):
        """To be overridden by subclasses."""
        raise NotImplementedError("Subclasses must implement the execute method.")
