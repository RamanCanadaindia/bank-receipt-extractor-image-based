import streamlit as st
import pandas as pd
import time
import os
import re
from datetime import datetime
from tasks.real_estate_scraper import RealEstateScraperTask
import sheets_helper
import auth

# Force Page Configurations
st.set_page_config(
    page_title="Paragon MLS Real Estate Analyzer",
    page_icon="🏠",
    layout="wide"
)

# Check password protection if enabled
if not auth.check_password():
    st.stop()

# Initialize session state for properties
if "scraped_properties" not in st.session_state:
    st.session_state.scraped_properties = []

def clean_numeric_price(price_str):
    try:
        cleaned = re.sub(r'[^\d.]', '', str(price_str))
        return float(cleaned) if cleaned else 0.0
    except:
        return 0.0

def calculate_mortgage(principal, annual_rate, years):
    if annual_rate <= 0 or principal <= 0 or years <= 0:
        return 0.0
    monthly_rate = (annual_rate / 100) / 12
    months = years * 12
    try:
        mortgage = principal * (monthly_rate * (1 + monthly_rate)**months) / ((1 + monthly_rate)**months - 1)
        return round(mortgage, 2)
    except:
        return 0.0

st.title("🏠 Paragon MLS Real Estate Analyzer")
st.write("Extract listing specifications from realtor links, evaluate investment viability, and sync to Google Sheets.")

# Setup Two Columns layout for inputs and results
col_left, col_right = st.columns([5, 7])

with col_left:
    st.subheader("🔍 Scraper Parameters")
    
    # URL Input
    listing_url = st.text_input(
        "Paragon MLS Link / GUID URL:",
        placeholder="https://bcres.paragonrels.com/paragonls/publink/view.mvc/?GUID=...",
        help="Paste the public Paragon listing link emailed to you by your realtor."
    )
    
    # Financial parameters card
    with st.container(border=True):
        st.markdown("**Financial Assumptions**")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            down_payment_pct = st.number_input("Down Payment %", min_value=5.0, max_value=100.0, value=20.0, step=5.0)
            amortization_years = st.number_input("Amortization (Years)", min_value=5, max_value=30, value=25, step=5)
        with col_f2:
            interest_rate = st.number_input("Interest Rate %", min_value=1.0, max_value=15.0, value=4.8, step=0.1)
            contingency_pct = st.slider("Contingency / Maintenance (% of Rent)", min_value=0.0, max_value=15.0, value=5.0, step=0.5)

    # Ranking Weights card
    with st.container(border=True):
        st.markdown("**Importance Scoring Weights**")
        st.write("Adjust weights to change the property composite rankings:")
        weight_transit = st.slider("🚉 Proximity to Skytrain / Transit", 0, 100, 40)
        weight_cash_flow = st.slider("💵 Monthly Net Cash Flow", 0, 100, 40)
        weight_growth = st.slider("📈 Long-Term Capital Growth", 0, 100, 20)

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        analyze_btn = st.button("⚡ Scrape & Analyze Listing", use_container_width=True, type="primary")
    with col_btn2:
        clear_btn = st.button("🧹 Clear Scraped Data", use_container_width=True)

    if clear_btn:
        st.session_state.scraped_properties = []
        st.rerun()

    if analyze_btn:
        if not listing_url:
            st.error("Please enter a valid Paragon listing link.")
        else:
            # Instantiate task settings
            settings = {"url": listing_url}
            
            with st.spinner("Accessing Paragon MLS and analyzing layout..."):
                try:
                    # Run headed/headless depending on environment
                    import sys
                    is_headless_env = (sys.platform.startswith("linux") and not os.environ.get("DISPLAY"))
                    
                    with RealEstateScraperTask(settings, headless=is_headless_env) as task:
                        res = task.execute()
                        
                    if res:
                        item = res[0]
                        # Verify we don't add duplicates
                        exists = False
                        for p in st.session_state.scraped_properties:
                            if p["Link"] == item["Link"] or p["Address"] == item["Address"]:
                                exists = True
                                break
                        if not exists:
                            st.session_state.scraped_properties.append(item)
                            st.success(f"Successfully scraped: {item['Address']}")
                        else:
                            st.info("Listing already analyzed and present in your session.")
                    else:
                        st.error("Failed to parse listing page.")
                except Exception as e:
                    st.error(f"Error executing scraper: {e}")

# Process and Render properties list in the right column
with col_right:
    st.subheader("🏆 Ranked Property Evaluation Dashboard")
    
    if not st.session_state.scraped_properties:
        st.info("No properties analyzed yet. Paste a listing link in the left panel to begin!")
    else:
        # We calculate financial rankings dynamically based on assumptions
        evaluated_properties = []
        
        for idx, p in enumerate(st.session_state.scraped_properties):
            # Price
            price_val = clean_numeric_price(p["Price"])
            
            # Rent override check
            key_rent = f"rent_override_{idx}"
            default_rent = int(p.get("Est Rent", 2200))
            est_rent = st.number_input(f"Monthly Rent for: {p['Address']}", min_value=500, max_value=15000, value=default_rent, step=100, key=key_rent)
            
            # Strata fee and property tax
            strata_fee = float(p.get("Strata Fee", 0.0))
            annual_tax = float(p.get("Property Tax", 0.0))
            monthly_tax = annual_tax / 12
            
            # Mortgage calculations
            principal = price_val * (1 - (down_payment_pct / 100))
            monthly_mortgage = calculate_mortgage(principal, interest_rate, amortization_years)
            
            # Maintenance / contingency
            monthly_contingency = est_rent * (contingency_pct / 100)
            
            # Net Cash Flow
            net_cash_flow = est_rent - strata_fee - monthly_tax - monthly_mortgage - monthly_contingency
            
            # Score Sub-Components (1-10 Scale)
            # 🚉 Transit Score: 10 mins walk = 0, 0 mins walk = 10
            walk_min = p.get("Transit Walk Min", 15)
            score_transit = max(1.0, 10.0 - (walk_min / 2.0))
            
            # 💵 Cash Flow Score: >= $500/mo = 10, <= -$500/mo = 1
            if net_cash_flow >= 500:
                score_cash_flow = 10.0
            elif net_cash_flow <= -500:
                score_cash_flow = 1.0
            else:
                score_cash_flow = 5.5 + (net_cash_flow / 100) # linear interpolation
                
            # 📈 Growth Score
            score_growth = float(p.get("Growth Score", 6.0))
            
            # Composite Scoring math
            total_weight = weight_transit + weight_cash_flow + weight_growth
            if total_weight > 0:
                composite_score = (
                    (weight_transit * score_transit) + 
                    (weight_cash_flow * score_cash_flow) + 
                    (weight_growth * score_growth)
                ) / total_weight
            else:
                composite_score = 5.0
                
            evaluated_properties.append({
                "Address": p["Address"],
                "Price": price_val,
                "Beds": p["Bedrooms"],
                "Baths": p["Bathrooms"],
                "Sqft": p["Sqft"],
                "Strata Fee": strata_fee,
                "Property Tax": annual_tax,
                "Year Built": int(p.get("Year Built", 2000)),
                "Property Type": p.get("Property Type", "Condo"),
                "Est Rent": est_rent,
                "Mortgage": monthly_mortgage,
                "Net Cash Flow": net_cash_flow,
                "Transit Score": score_transit,
                "Nearest Station": p.get("Nearest Station", "Unknown Station"),
                "Growth Score": score_growth,
                "Composite Score": round(composite_score, 2),
                "MLS Number": p["MLS Number"],
                "Link": p["Link"]
            })
            
        # Sort by Composite Score descending
        ranked_properties = sorted(evaluated_properties, key=lambda x: x["Composite Score"], reverse=True)
        
        # Display each property card
        for rank, p in enumerate(ranked_properties):
            with st.container(border=True):
                col_c1, col_c2 = st.columns([8, 4])
                
                with col_c1:
                    st.markdown(f"### #{rank+1}: **{p['Address']}**")
                    st.markdown(f"**MLS®**: {p['MLS Number']} | **Type**: {p['Property Type']} | **Built**: {p['Year Built']} | **Price**: ${p['Price']:,.0f}")
                    st.markdown(f"**Layout**: {p['Beds']} Bed, {p['Baths']} Bath ({p['Sqft']} Sqft)")
                    
                    # Renders metric results
                    st.markdown(f"🚉 **Transit**: Near `{p['Nearest Station']}`. Transit Score: **{p['Transit Score']:.1f}/10**")
                    st.markdown(f"📈 **Long-Term Growth Score**: **{p['Growth Score']:.0f}/10**")
                    
                    # Cash flow details
                    cf_color = "green" if p['Net Cash Flow'] >= 0 else "red"
                    st.markdown(f"💵 **Net Cash Flow**: <span style='color:{cf_color}; font-weight:bold;'>${p['Net Cash Flow']:,.2f}/month</span>", unsafe_allow_html=True)
                    st.write(f"(Rent: ${p['Est Rent']}/mo | Strata: ${p['Strata Fee']}/mo | Tax: ${p['Property Tax']/12:,.1f}/mo | Mortgage: ${p['Mortgage']}/mo)")
                    
                with col_c2:
                    st.write("")
                    st.metric("Overall Rank Score", f"{p['Composite Score']}/10")
                    st.progress(p["Composite Score"] / 10.0)
                    st.write("")
                    st.markdown(f"[🔗 Open Listing Link]({p['Link']})")
                    
        # ------------------ GOOGLE SHEETS SYNC SECTION ------------------
        st.write("---")
        st.subheader("📊 Google Sheets Synchronization")
        
        # Default spreadsheet config
        default_sheet_id = st.secrets.get("google_spreadsheet_id", "")
        spreadsheet_input = st.text_input(
            "Google Spreadsheet ID or Full URL Link:",
            value=default_sheet_id,
            placeholder="Paste your shared Google Spreadsheet URL link here...",
            help="Your service account must have 'Editor' access to this Google sheet."
        )
        
        sync_btn = st.button("📤 Sync Ranked Properties to Google Sheets", use_container_width=True, type="primary")
        
        if sync_btn:
            if not spreadsheet_input:
                st.error("Please enter a Google Spreadsheet ID/URL.")
            else:
                with st.spinner("Authorizing connection and appending rows..."):
                    client = sheets_helper.get_gspread_client()
                    if client:
                        spreadsheet = sheets_helper.get_spreadsheet(client, spreadsheet_input)
                        if spreadsheet:
                            # Build dataframe matching sheet schema
                            rows_data = []
                            for p in ranked_properties:
                                rows_data.append({
                                    "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "Address": p["Address"],
                                    "Property Type": p["Property Type"],
                                    "Year Built": p["Year Built"],
                                    "Price": f"${p['Price']:,.2f}",
                                    "Bedrooms": p["Beds"],
                                    "Bathrooms": p["Baths"],
                                    "Sqft": p["Sqft"],
                                    "Strata Fee": f"${p['Strata Fee']:.2f}",
                                    "Property Tax": f"${p['Property Tax']:.2f}",
                                    "Est Rent": f"${p['Est Rent']:.2f}",
                                    "Mortgage": f"${p['Mortgage']:.2f}",
                                    "Net Cash Flow": f"${p['Net Cash Flow']:.2f}",
                                    "Transit Score": f"{p['Transit Score']:.1f}/10",
                                    "Growth Score": f"{p['Growth Score']:.0f}/10",
                                    "Composite Rank": f"{p['Composite Score']}/10",
                                    "MLS Number": p["MLS Number"],
                                    "Link": p["Link"]
                                })
                            
                            sync_df = pd.DataFrame(rows_data)
                            sheets_helper.sync_property_listings(spreadsheet, sync_df)
