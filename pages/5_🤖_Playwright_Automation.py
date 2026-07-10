import os
import json
import time
import glob
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from tasks import TASK_MAPPING
import auth

# Password Check
if not auth.check_password():
    st.stop()

CONFIG_PATH = "config/tasks.json"
RESULTS_PATH = "output/results.xlsx"
ERRORS_DIR = "output/errors"

# Custom premium styling
st.markdown("""
<style>
    .main {
        background-color: #f8f9fa;
    }
    .stButton>button {
        background-color: #4CAF50;
        color: white;
        border-radius: 6px;
        padding: 0.5rem 2rem;
        font-weight: bold;
        border: none;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #45a049;
        transform: translateY(-2px);
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .api-status {
        padding: 10px;
        border-radius: 5px;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

def load_config():
    """Loads tasks.json configuration, creating a default one if missing."""
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        default_config = {
            "active_task": "google_search",
            "tasks": {
                "google_search": {"keyword": "accounting firms Surrey BC", "max_results": 10},
                "website_scraper": {"urls": ["https://example.com"]},
                "competitor_research": {
                    "keyword": "bookkeeping tax services Surrey BC",
                    "max_results": 10,
                    "extract": ["business_name", "website", "services", "phone", "email", "pricing_keywords"]
                },
                "custom_url_task": {
                    "url": "https://example.com",
                    "question": "Summarize this page and extract useful business information"
                },
                "flight_search": {"origin": "YVR", "destination": "LAX", "date": "2026-10-10", "max_results": 5}
            }
        }
        with open(CONFIG_PATH, "w") as f:
            json.dump(default_config, f, indent=2)
        return default_config
    
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Failed to parse config file: {e}")
        return {}

def save_config(config):
    """Saves the current config dict to tasks.json."""
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        st.error(f"Failed to save config: {e}")

def get_latest_screenshot():
    """Finds the most recent screenshot in the output/errors directory."""
    if not os.path.exists(ERRORS_DIR):
        return None
    files = glob.glob(os.path.join(ERRORS_DIR, "*.png"))
    if not files:
        return None
    # Sort files by modification time
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]

def main():
    st.title("🤖 Playwright Web Automation Dashboard")
    st.subheader("Configure, run, and export web crawler scripts interactively.")
    st.write("---")

    config = load_config()
    tasks_config = config.get("tasks", {})

    # Display API Key status
    gemini_key_active = "GEMINI_API_KEY" in os.environ
    if gemini_key_active:
        st.info("🟢 **Gemini AI Engine Status**: Active (GEMINI_API_KEY detected. Intelligent AI parsing is enabled.)")
    else:
        st.warning("🟡 **Gemini AI Engine Status**: Offline Fallback Mode (No API key found in your environment. Tasks will use rule-based local regexes and heuristic summaries.)")

    # Layout with sidebar for selection & main page for inputs/results
    st.sidebar.title("Task Selector")
    
    # Task mapping titles
    task_titles = {
        "google_search": "🔍 Google Search scraper",
        "website_scraper": "🌐 Website Scraper",
        "competitor_research": "🏢 Competitor Research site analyzer",
        "custom_url_task": "❓ Custom URL Q&A",
        "flight_search": "✈️ Google Flights price finder",
        "multi_flight_tracker": "📊 Multi-Site Price Tracker (Skyscanner/Kayak/Google)"
    }
    
    # Inverse map
    inv_task_titles = {v: k for k, v in task_titles.items()}
    
    # Match default index
    default_active = config.get("active_task", "google_search")
    default_active_title = task_titles.get(default_active, "🔍 Google Search scraper")
    
    selected_title = st.sidebar.selectbox(
        "Choose an automation task type:",
        options=list(task_titles.values()),
        index=list(task_titles.keys()).index(default_active) if default_active in task_titles else 0
    )
    
    selected_task = inv_task_titles[selected_title]

    st.write(f"### Configure Settings for: **{selected_title}**")
    
    # Dynamic settings inputs based on the selected task
    settings = {}
    
    if selected_task == "google_search":
        gs_config = tasks_config.get("google_search", {})
        settings["keyword"] = st.text_input(
            "Google Search Keyword:", 
            value=gs_config.get("keyword", "accounting firms Surrey BC"),
            help="Keyword to submit to Google search"
        )
        settings["max_results"] = st.slider(
            "Max Results to extract:", 
            min_value=1, max_value=50, 
            value=gs_config.get("max_results", 10),
            help="Total organic results to scrape across pages"
        )
        
    elif selected_task == "website_scraper":
        ws_config = tasks_config.get("website_scraper", {})
        urls_list = ws_config.get("urls", ["https://example.com"])
        urls_input = st.text_area(
            "Websites to Scrape (one URL per line):",
            value="\n".join(urls_list),
            height=150,
            help="Provide full HTTP/HTTPS web links to parse"
        )
        settings["urls"] = [url.strip() for url in urls_input.split("\n") if url.strip()]
        
    elif selected_task == "competitor_research":
        cr_config = tasks_config.get("competitor_research", {})
        settings["keyword"] = st.text_input(
            "Competitor Niche/Keyword:", 
            value=cr_config.get("keyword", "bookkeeping tax services Surrey BC"),
            help="Search term to discover competitor businesses"
        )
        settings["max_results"] = st.slider(
            "Max Competitors to analyze:", 
            min_value=1, max_value=25, 
            value=cr_config.get("max_results", 10),
            help="Maximum competitor sites to visit and extract details from"
        )
        
        all_fields = ["business_name", "website", "services", "phone", "email", "pricing_keywords"]
        settings["extract"] = st.multiselect(
            "Information Fields to Extract:",
            options=all_fields,
            default=cr_config.get("extract", all_fields),
            help="Specific competitor attributes to extract from homepages"
        )
        
    elif selected_task == "custom_url_task":
        cu_config = tasks_config.get("custom_url_task", {})
        settings["url"] = st.text_input(
            "Target URL Link:", 
            value=cu_config.get("url", "https://example.com"),
            help="Specific page URL to fetch text content from"
        )
        settings["question"] = st.text_area(
            "Your Question about the webpage:", 
            value=cu_config.get("question", "Summarize this page and extract useful business information"),
            height=100,
            help="The question that the local summarizer or Gemini AI will answer using the page text"
        )
        
    elif selected_task in ("flight_search", "multi_flight_tracker"):
        fl_config = tasks_config.get(selected_task, {})
        col1, col2 = st.columns(2)
        
        with col1:
            settings["origin"] = st.text_input(
                "Origin Airport Code:", 
                value=fl_config.get("origin", "YVR"),
                help="E.g. YVR, LAX, LHR"
            ).upper()
        with col2:
            settings["destination"] = st.text_input(
                "Destination Airport Code:", 
                value=fl_config.get("destination", "LAX"),
                help="E.g. LAX, JFK, YVR"
            ).upper()
            
        col3, col4, col5 = st.columns(3)
        with col3:
            trip_type = st.selectbox(
                "Trip Type:",
                options=["One-Way", "Round-Trip"],
                index=0 if fl_config.get("trip_type", "One-Way") == "One-Way" else 1,
                help="Choose one-way travel or round-trip travel"
            )
            settings["trip_type"] = trip_type
            
        with col4:
            default_date_str = fl_config.get("date", "2026-10-10")
            try:
                default_date = datetime.strptime(default_date_str, "%Y-%m-%d").date()
            except:
                default_date = datetime.now().date()
            selected_date = st.date_input(
                "Flight Departure Date:",
                value=default_date,
                help="Date of departure"
            )
            settings["date"] = selected_date.strftime("%Y-%m-%d")
            
        with col5:
            if trip_type == "Round-Trip":
                default_ret_str = fl_config.get("return_date", "2026-10-17")
                try:
                    default_ret = datetime.strptime(default_ret_str, "%Y-%m-%d").date()
                except:
                    default_ret = selected_date + timedelta(days=7)
                selected_return_date = st.date_input(
                    "Flight Return Date:",
                    value=default_ret,
                    min_value=selected_date,
                    help="Date of return travel"
                )
                settings["return_date"] = selected_return_date.strftime("%Y-%m-%d")
            else:
                settings["return_date"] = ""
                
        settings["max_results"] = st.slider(
            "Max flight tickets to list:", 
            min_value=1, max_value=20, 
            value=fl_config.get("max_results", 5)
        )

    # Action layout
    st.write("")
    show_browser = st.sidebar.checkbox(
        "👁️ Show Browser Window", 
        value=False, 
        help="Check this to watch the browser perform typing, clicking, and navigation live."
    )
    run_btn = st.sidebar.button("⚡ Run Automation", use_container_width=True)

    if run_btn:
        # 1. Update config file settings dynamically
        config["active_task"] = selected_task
        config["tasks"][selected_task] = settings
        save_config(config)
        st.sidebar.success("Settings saved to config/tasks.json!")

        # 2. Execute Task
        st.info(f"Launching task '{selected_task}' via Playwright...")
        
        # We fetch the class matching the selected type
        task_class = TASK_MAPPING.get(selected_task)
        if not task_class:
            st.error(f"Task runner mapping for '{selected_task}' was not found.")
            return

        # Place browser runs in a spinner
        start_time = time.time()
        results_list = None
        
        with st.spinner(f"Running '{selected_task}'..."):
            try:
                # Instantiate and run (headless parameter toggled by checkbox)
                with task_class(settings, headless=not show_browser) as task:
                    results_list = task.execute()
                
                duration = time.time() - start_time
                st.success(f"Success! Task finished in {duration:.1f} seconds.")
                
            except Exception as run_err:
                st.error(f"An error occurred during execution: {run_err}")
                
                # Check for failure screenshot to help debug
                latest_screenshot = get_latest_screenshot()
                if latest_screenshot:
                    st.warning(f"Browser screenshot captured at error state: {os.path.basename(latest_screenshot)}")
                    st.image(latest_screenshot, caption="Webpage error state captured by Playwright")
                return

        # 3. Present Results
        if results_list:
            st.write("### Extracted Data Results")
            
            # If flight search, print beautiful recommendation cards first
            if selected_task == "flight_search":
                # Find matching classifications
                best_overall = None
                cheapest = None
                fastest = None
                
                for r in results_list:
                    rec = r.get("Recommendation", "")
                    if "Best Overall" in rec:
                        best_overall = r
                    if "Cheapest" in rec:
                        cheapest = r
                    if "Fastest" in rec:
                        fastest = r
                        
                st.write("#### ✈️ Comet AI Travel Agent Recommendations")
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    if best_overall:
                        st.info(f"""
                        **⭐ Best Overall Flight**
                        - **Airline**: {best_overall['Airline']}
                        - **Price**: {best_overall['Price']}
                        - **Duration**: {best_overall['Duration']} ({best_overall['Stops']})
                        - **Departure/Arrival**: {best_overall['Departure']} - {best_overall['Arrival']}
                        
                        [👉 Book Flight on Google Flights]({best_overall['Booking Link']})
                        """)
                    else:
                        st.info("Best Overall flight details unavailable.")
                        
                with col2:
                    if cheapest:
                        st.success(f"""
                        **💰 Cheapest Option**
                        - **Airline**: {cheapest['Airline']}
                        - **Price**: {cheapest['Price']}
                        - **Duration**: {cheapest['Duration']} ({cheapest['Stops']})
                        - **Departure/Arrival**: {cheapest['Departure']} - {cheapest['Arrival']}
                        
                        [👉 Book Flight on Google Flights]({cheapest['Booking Link']})
                        """)
                    else:
                        st.success("Cheapest flight details unavailable.")
                        
                with col3:
                    if fastest:
                        st.warning(f"""
                        **⚡ Fastest Option**
                        - **Airline**: {fastest['Airline']}
                        - **Price**: {fastest['Price']}
                        - **Duration**: {fastest['Duration']} ({fastest['Stops']})
                        - **Departure/Arrival**: {fastest['Departure']} - {fastest['Arrival']}
                        
                        [👉 Book Flight on Google Flights]({fastest['Booking Link']})
                        """)
                    else:
                        st.warning("Fastest flight details unavailable.")
                st.write("")

            if selected_task == "flight_search":
                # Build custom HTML table matching Comet design (with no leading spaces to avoid markdown code-block parsing)
                html_rows = []
                for r in results_list:
                    rec = r.get("Recommendation", "")
                    price_val = r.get("Price", "")
                    
                    price_label = f"<strong>{price_val}</strong>"
                    if "Best Overall" in rec:
                        price_label += " &nbsp;<span style='color:#0F9D58; font-weight: bold;'>✅ Best</span>"
                    elif "Cheapest" in rec:
                        price_label += " &nbsp;<span style='color:#0F9D58; font-weight: bold;'>✅ Cheapest</span>"
                    elif "Fastest" in rec:
                        price_label += " &nbsp;<span style='color:#F4B400; font-weight: bold;'>⚡ Fastest</span>"
                    
                    airline = r.get("Airline", "Unknown")
                    dep_arr = f"{r.get('Departure', 'Unknown')} &rarr; {r.get('Arrival', 'Unknown')}"
                    duration = r.get("Duration", "Unknown")
                    stops = r.get("Stops", "Unknown")
                    
                    row = (
                        f"<tr>"
                        f"<td style='padding: 12px; border-bottom: 1px solid #e0e0e0; font-weight: bold;'>{airline}</td>"
                        f"<td style='padding: 12px; border-bottom: 1px solid #e0e0e0;'>{dep_arr}</td>"
                        f"<td style='padding: 12px; border-bottom: 1px solid #e0e0e0;'>{duration}</td>"
                        f"<td style='padding: 12px; border-bottom: 1px solid #e0e0e0;'>{stops}</td>"
                        f"<td style='padding: 12px; border-bottom: 1px solid #e0e0e0;'>{price_label}</td>"
                        f"</tr>"
                    )
                    html_rows.append(row)
                    
                table_html = (
                    f"<table style='width: 100%; border-collapse: collapse; font-family: \"Inter\", sans-serif; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border: 1px solid #e0e0e0;'>"
                    f"<thead>"
                    f"<tr style='background-color: #f8f9fa; border-bottom: 2px solid #e0e0e0; text-align: left;'>"
                    f"<th style='padding: 12px; font-weight: bold; color: #5f6368;'>Airline</th>"
                    f"<th style='padding: 12px; font-weight: bold; color: #5f6368;'>Departure &rarr; Arrival</th>"
                    f"<th style='padding: 12px; font-weight: bold; color: #5f6368;'>Duration</th>"
                    f"<th style='padding: 12px; font-weight: bold; color: #5f6368;'>Stops</th>"
                    f"<th style='padding: 12px; font-weight: bold; color: #5f6368;'>Price (CAD)</th>"
                    f"</tr>"
                    f"</thead>"
                    f"<tbody>"
                    f"{''.join(html_rows)}"
                    f"</tbody>"
                    f"</table>"
                )
                st.markdown(table_html, unsafe_allow_html=True)
                st.write("")
                
            elif selected_task == "multi_flight_tracker":
                # Build custom HTML comparison table
                html_rows = []
                # Find the cheapest price to highlight it
                prices = []
                for r in results_list:
                    p_val = r.get("Price", "")
                    try:
                        numeric_p = float(re.sub(r'[^\d.]', '', p_val))
                        prices.append(numeric_p)
                    except:
                        prices.append(float('inf'))
                min_price = min(prices) if prices else float('inf')
                
                for idx, r in enumerate(results_list):
                    source = r.get("Source", "Unknown")
                    route = r.get("Route", "Unknown")
                    f_date = r.get("Flight Date", "Unknown")
                    airline = r.get("Airline", "Unknown")
                    price_val = r.get("Price", "")
                    status = r.get("Status", "Unknown")
                    
                    price_label = f"<strong>{price_val}</strong>"
                    try:
                        numeric_p = float(re.sub(r'[^\d.]', '', price_val))
                        if numeric_p == min_price and min_price != float('inf'):
                            price_label += " &nbsp;<span style='color:#0F9D58; font-weight: bold;'>🏆 Cheapest Deal</span>"
                    except:
                        pass
                        
                    status_style = "color: #0F9D58; font-weight: bold;" if "Success" in status else "color: #D93025; font-weight: bold;"
                    status_label = f"<span style='{status_style}'>{status}</span>"
                    
                    row = (
                        f"<tr>"
                        f"<td style='padding: 12px; border-bottom: 1px solid #e0e0e0; font-weight: bold; color: #1a73e8;'>{source}</td>"
                        f"<td style='padding: 12px; border-bottom: 1px solid #e0e0e0;'>{route}</td>"
                        f"<td style='padding: 12px; border-bottom: 1px solid #e0e0e0;'>{f_date}</td>"
                        f"<td style='padding: 12px; border-bottom: 1px solid #e0e0e0;'>{price_label}</td>"
                        f"<td style='padding: 12px; border-bottom: 1px solid #e0e0e0;'>{airline}</td>"
                        f"<td style='padding: 12px; border-bottom: 1px solid #e0e0e0;'>{status_label}</td>"
                        f"</tr>"
                    )
                    html_rows.append(row)
                    
                table_html = (
                    f"<table style='width: 100%; border-collapse: collapse; font-family: \"Inter\", sans-serif; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border: 1px solid #e0e0e0;'>"
                    f"<thead>"
                    f"<tr style='background-color: #f8f9fa; border-bottom: 2px solid #e0e0e0; text-align: left;'>"
                    f"<th style='padding: 12px; font-weight: bold; color: #5f6368;'>Search Engine</th>"
                    f"<th style='padding: 12px; font-weight: bold; color: #5f6368;'>Route</th>"
                    f"<th style='padding: 12px; font-weight: bold; color: #5f6368;'>Departure Date</th>"
                    f"<th style='padding: 12px; font-weight: bold; color: #5f6368;'>Best Price Found</th>"
                    f"<th style='padding: 12px; font-weight: bold; color: #5f6368;'>Airline / Details</th>"
                    f"<th style='padding: 12px; font-weight: bold; color: #5f6368;'>Status</th>"
                    f"</tr>"
                    f"</thead>"
                    f"<tbody>"
                    f"{''.join(html_rows)}"
                    f"</tbody>"
                    f"</table>"
                )
                st.markdown(table_html, unsafe_allow_html=True)
                st.write("")
                
            else:
                df = pd.DataFrame(results_list)
                st.dataframe(df, use_container_width=True)

            # Export Excel direct link
            if os.path.exists(RESULTS_PATH):
                try:
                    with open(RESULTS_PATH, "rb") as f:
                        excel_data = f.read()
                    st.download_button(
                        label="📥 Download results.xlsx spreadsheet",
                        data=excel_data,
                        file_name="results.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                except Exception as dl_err:
                    st.error(f"Failed to prepare Excel download file: {dl_err}")
        else:
            st.warning("The task finished but did not return any structured result list.")

    # 4. View existing results option if available
    st.write("---")
    st.write("### Manage Output Spreadsheet")
    if os.path.exists(RESULTS_PATH):
        try:
            xl = pd.ExcelFile(RESULTS_PATH)
            st.write(f"Active sheets in existing `{RESULTS_PATH}`: **{', '.join(xl.sheet_names)}**")
            
            # Select sheets to preview
            preview_sheet = st.selectbox("Select sheet tab to preview:", options=xl.sheet_names)
            preview_df = pd.read_excel(RESULTS_PATH, sheet_name=preview_sheet)
            st.dataframe(preview_df, use_container_width=True)
            
            with open(RESULTS_PATH, "rb") as f:
                btn_data = f.read()
            st.download_button(
                label="📥 Download results.xlsx workbook",
                data=btn_data,
                file_name="results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="prev_excel_btn"
            )
        except Exception as sheet_err:
            st.write(f"Results file is empty or cannot be read: {sheet_err}")
    else:
        st.write("No output spreadsheet generated yet. Run a task to create `output/results.xlsx`.")

if __name__ == "__main__":
    main()
