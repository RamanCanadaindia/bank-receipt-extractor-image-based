import streamlit as st
import pandas as pd
import time
import os
import re
from datetime import datetime
from typing import List, Dict, Tuple, Optional

# Import modular investment engine components
from utils.real_estate.models import PropertyListing, FinancialInputs, PropertyEvaluation
from utils.real_estate.calculator import (
    calculate_mortgage_details, calculate_cash_flow_details, 
    calculate_appreciation_forecast, calculate_roi_details, calculate_scenarios
)
from utils.real_estate.scoring import (
    evaluate_comparable_sales, evaluate_transit_score, 
    evaluate_development_potential, evaluate_schools, 
    evaluate_rental_demand, evaluate_property_condition, 
    evaluate_risk_profile, calculate_norm_score
)
from utils.real_estate.recommender import generate_recommendation
from utils.real_estate.maps import build_property_map
from utils.real_estate.excel_export import export_evaluations_to_excel
from utils.real_estate.pdf_report import generate_property_pdf

# Streamlit-Folium integration
from streamlit_folium import st_folium

from tasks.real_estate_scraper import RealEstateScraperTask
import sheets_helper
import auth

# Force Page Configurations
st.set_page_config(
    page_title="Professional Real Estate Investment Engine",
    page_icon="🏠",
    layout="wide"
)

# Password Protection Check
if not auth.check_password():
    st.stop()

# Initialize session state for properties
if "scraped_properties" not in st.session_state:
    st.session_state.scraped_properties = []

def clean_numeric_price(price_str) -> float:
    try:
        cleaned = re.sub(r'[^\d.]', '', str(price_str))
        return float(cleaned) if cleaned else 0.0
    except:
        return 0.0

st.title("💼 Real Estate Investment Decision Engine")
st.write("Professional residential asset valuation dashboard for Metro Vancouver development and cash flow analysis.")

# Setup layout columns
col_left, col_right = st.columns([4, 8])

with col_left:
    st.subheader("⚙️ Analysis Parameters")
    
    # Paragon Link Input
    listing_url = st.text_input(
        "Paragon MLS Link / GUID URL:",
        placeholder="https://bcres.paragonrels.com/paragonls/publink/view.mvc/?GUID=...",
        help="Paste the Paragon public listing link from your realtor."
    )
    
    # Scraper Action Buttons
    col_sc1, col_sc2 = st.columns(2)
    with col_sc1:
        analyze_btn = st.button("⚡ Scrape Property", use_container_width=True, type="primary")
    with col_sc2:
        clear_btn = st.button("🧹 Clear All Data", use_container_width=True)
        
    if clear_btn:
        st.session_state.scraped_properties = []
        st.rerun()
        
    if analyze_btn:
        if not listing_url:
            st.error("Please enter a valid Paragon listing link.")
        else:
            settings = {"url": listing_url}
            with st.spinner("Scraping listing and reconstructing coordinates..."):
                try:
                    import sys
                    is_headless_env = (sys.platform.startswith("linux") and not os.environ.get("DISPLAY"))
                    with RealEstateScraperTask(settings, headless=is_headless_env) as task:
                        res = task.execute()
                    if res:
                        item = res[0]
                        # De-duplicate check
                        exists = False
                        for p in st.session_state.scraped_properties:
                            if p["Link"] == item["Link"] or p["Address"] == item["Address"]:
                                exists = True
                                break
                        if not exists:
                            st.session_state.scraped_properties.append(item)
                            st.success(f"Added listing: {item['Address']}")
                        else:
                            st.info("Listing already analyzed in this session.")
                    else:
                        st.error("Failed to parse listing details.")
                except Exception as e:
                    st.error(f"Scraper Error: {e}")

    # Granular Financial Assumptions
    with st.expander("💸 Detailed Financial Assumptions", expanded=True):
        down_payment_pct = st.number_input("Down Payment %", min_value=5.0, max_value=100.0, value=20.0, step=5.0)
        interest_rate = st.number_input("Interest Rate %", min_value=1.0, max_value=15.0, value=4.8, step=0.1)
        amortization_years = st.number_input("Amortization (Years)", min_value=5, max_value=30, value=25, step=5)
        
        col_ass1, col_ass2 = st.columns(2)
        with col_ass1:
            mortgage_type = st.selectbox("Mortgage Type", ["Fixed", "Variable"])
            frequency = st.selectbox("Payment Frequency", ["Monthly", "Semi-Monthly", "Bi-Weekly", "Weekly"])
        with col_ass2:
            vacancy_rate_pct = st.number_input("Vacancy Allowance %", min_value=0.0, max_value=20.0, value=3.0, step=0.5)
            maintenance_pct = st.number_input("Maintenance Reserve %", min_value=0.0, max_value=20.0, value=5.0, step=0.5)
            
        insurance_monthly = st.number_input("Monthly Insurance ($)", min_value=0.0, value=80.0, step=10.0)
        prop_management_pct = st.number_input("Property Management %", min_value=0.0, max_value=25.0, value=6.0, step=0.5)
        utilities_monthly = st.number_input("Utilities (Landlord Paid $)", min_value=0.0, value=0.0, step=50.0)
        misc_monthly = st.number_input("Misc / Contingency ($/mo)", min_value=0.0, value=0.0, step=25.0)

    # 10-Factor Scoring Weights
    with st.expander("📊 10-Factor MCDA Weights", expanded=False):
        st.write("Adjust weights (relative percentages dynamically normalize to 100%):")
        w_app = st.slider("📈 Expected Appreciation", 0, 100, 25)
        w_cf = st.slider("💵 Cash Flow", 0, 100, 20)
        w_disc = st.slider("🏷️ Comparable Price Discount", 0, 100, 15)
        w_dev = st.slider("🏗️ Development Potential", 0, 100, 10)
        w_trans = st.slider("🚉 Transit Accessibility", 0, 100, 10)
        w_dem = st.slider("👥 Rental Demand", 0, 100, 5)
        w_sch = st.slider("🏫 School Quality", 0, 100, 5)
        w_safe = st.slider("🛡️ Neighbourhood Safety", 0, 100, 5)
        w_cond = st.slider("🛠️ Property Condition", 0, 100, 3)
        w_risk = st.slider("⚠️ Investment Risk Safety", 0, 100, 2)
        
        # Calculate dynamic normalized weights
        w_sum = w_app + w_cf + w_disc + w_dev + w_trans + w_dem + w_sch + w_safe + w_cond + w_risk
        if w_sum == 0:
            w_sum = 10
            w_app = w_cf = w_disc = w_dev = w_trans = w_dem = w_sch = w_safe = w_cond = w_risk = 1

# Process evaluations if listings exist
evaluations: List[PropertyEvaluation] = []
if st.session_state.scraped_properties:
    for idx, p in enumerate(st.session_state.scraped_properties):
        price_val = clean_numeric_price(p.get("Price", 0.0))
        
        # Allow rent override via numeric input
        default_rent = float(p.get("Est Rent", 2200))
        est_rent = st.sidebar.number_input(
            f"Rent Override: {p.get('Address', 'Listing')[:18]}...",
            min_value=500.0, max_value=25000.0, value=default_rent, step=100.0,
            key=f"rent_override_val_{idx}"
        )
        
        # Setup dataclass structures
        listing_model = PropertyListing(
            address=p.get("Address", "Unknown Address"),
            price=price_val,
            beds=int(p.get("Bedrooms", 1)),
            baths=int(p.get("Bathrooms", 1)),
            sqft=int(p.get("Sqft", 800)),
            strata_fee=float(p.get("Strata Fee", 0.0)),
            property_tax=float(p.get("Property Tax", 0.0)),
            year_built=int(p.get("Year Built", 2000)),
            property_type=p.get("Property Type", "Condo"),
            mls_number=p.get("MLS Number", "N/A"),
            link=p.get("Link", ""),
            timestamp=p.get("Timestamp", "")
        )
        
        financials_model = FinancialInputs(
            down_payment_pct=down_payment_pct,
            interest_rate=interest_rate,
            amortization_years=amortization_years,
            mortgage_type=mortgage_type,
            payment_frequency=frequency,
            insurance_monthly=insurance_monthly,
            vacancy_rate_pct=vacancy_rate_pct,
            maintenance_pct=maintenance_pct,
            property_management_pct=prop_management_pct,
            utilities_landlord_paid=utilities_monthly,
            misc_expenses_monthly=misc_monthly,
            est_rent=est_rent
        )
        
        # 1. Mortgage Payment Calcs
        principal_mortgage = price_val * (1 - (down_payment_pct / 100))
        mort_res = calculate_mortgage_details(
            principal_mortgage, interest_rate, amortization_years, 
            frequency, mortgage_type == "Variable"
        )
        
        # 2. Yield & Cash Flow Calcs
        cf_res = calculate_cash_flow_details(listing_model, financials_model, mort_res.monthly_payment)
        
        # 3. Appreciation Forecast
        app_res = calculate_appreciation_forecast(listing_model)
        
        # 4. ROI Metrics
        roi_res = calculate_roi_details(listing_model, financials_model, mort_res, cf_res, app_res)
        
        # 5. Comparable Sales
        comp_res = evaluate_comparable_sales(listing_model)
        
        # 6. Transit Accessibility
        transit_res = evaluate_transit_score(listing_model)
        
        # 7. Development Potential
        dev_res = evaluate_development_potential(listing_model, transit_res)
        
        # 8. Schools Catchment
        school_res = evaluate_schools(listing_model)
        
        # 9. Rental Demand
        demand_res = evaluate_rental_demand(listing_model)
        
        # 10. Property Condition
        cond_res = evaluate_property_condition(listing_model)
        
        # 11. Risk Profile
        risk_res = evaluate_risk_profile(listing_model, financials_model, cond_res)
        
        # 12. Scenarios compares (Optimistic / Base / Pessimistic)
        scenario_res = calculate_scenarios(listing_model, financials_model)
        
        # 13. Sub-scores Normalization (1 to 10 scale)
        # expected annual appreciation: range 3.0 to 8.0%
        score_app = calculate_norm_score(app_res.expected_annual_appreciation_pct, 3.0, 8.0)
        # cash on cash: range -2% to 6%
        score_cf = calculate_norm_score(cf_res.cash_on_cash_pct, -2.0, 6.0)
        # comparable discount: range -10% to 15%
        score_disc = calculate_norm_score(comp_res.price_discount_pct, -10.0, 15.0)
        
        score_dev = dev_res.development_score
        score_trans = transit_res.transit_score
        score_dem = demand_res.rental_demand_score
        score_sch = school_res.average_school_rating
        
        # safety (higher safety = better = lower crime)
        from utils.real_estate.data_source import detect_municipality, MUNICIPALITIES_DATA
        m_name = detect_municipality(listing_model.address)
        score_safe = MUNICIPALITIES_DATA.get(m_name, {}).get("safety_score", 7.0)
        
        score_cond = cond_res.condition_score
        score_risk = 10.0 - risk_res.risk_score # low risk = high score
        
        # Dynamic weighted score (normalizes to 100%)
        weighted_val = (
            (w_app * score_app) +
            (w_cf * score_cf) +
            (w_disc * score_disc) +
            (w_dev * score_dev) +
            (w_trans * score_trans) +
            (w_dem * score_dem) +
            (w_sch * score_sch) +
            (w_safe * score_safe) +
            (w_cond * score_cond) +
            (w_risk * score_risk)
        ) / w_sum
        
        composite_score = round(weighted_val * 10.0, 1) # Normalize to 100 scale
        
        eval_obj = PropertyEvaluation(
            listing=listing_model,
            financials=financials_model,
            mortgage=mort_res,
            cash_flow=cf_res,
            appreciation=app_res,
            comparables=comp_res,
            development=dev_res,
            transit=transit_res,
            schools=school_res,
            demand=demand_res,
            condition=cond_res,
            risk=risk_res,
            roi=roi_res,
            scenarios=scenario_res,
            composite_score=composite_score
        )
        # Generate written brochure recommendations
        eval_obj.ai_recommendation = generate_recommendation(eval_obj)
        evaluations.append(eval_obj)

    # Sort evaluations by score descending
    evaluations.sort(key=lambda x: x.composite_score, reverse=True)
    # Assign ranks
    for r_idx, ev in enumerate(evaluations):
        ev.overall_rank = r_idx + 1

# Render Dashboard Right Column
with col_right:
    if not evaluations:
        st.info("⚡ Real Estate Investment Decision Engine ready. Enter a listing URL in the parameters panel and click Scrape to analyze.")
    else:
        # Multi-tab layout for modular analysis
        tab_dashboard, tab_cashflow, tab_comps, tab_compare = st.tabs([
            "🏆 Investment Rankings",
            "💵 Cash Flow & Scenarios",
            "🗺️ Maps & Comparable Sales",
            "👥 Side-by-Side Comparison"
        ])
        
        # ------------------ TAB 1: RANKINGS DASHBOARD ------------------
        with tab_dashboard:
            st.subheader("📊 Property Performance Rankings")
            
            for ev in evaluations:
                listing = ev.listing
                cf = ev.cash_flow
                roi = ev.roi
                risk = ev.risk
                
                with st.container(border=True):
                    col_det1, col_det2 = st.columns([9, 3])
                    
                    with col_det1:
                        st.markdown(f"### #{ev.overall_rank}: **{listing.address}**")
                        st.markdown(
                            f"**MLS®**: `{listing.mls_number}` | **Type**: `{listing.property_type}` | "
                            f"**Built**: `{listing.year_built}` (Age: {ev.condition.age_years} yrs) | **Price**: `${listing.price:,.0f}`"
                        )
                        st.markdown(f"📐 **Size**: {listing.sqft} sqft (${listing.price/listing.sqft:,.2f}/sqft) | **Layout**: {listing.beds} Bed, {listing.baths} Bath")
                        
                        # Yield Metrics Row
                        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                        col_m1.metric("Cap Rate", f"{cf.cap_rate}%")
                        col_m2.metric("Cash-on-Cash Return", f"{cf.cash_on_cash_pct}%")
                        col_m3.metric("5y IRR Projection", f"{roi.irr_5y:.1f}%")
                        
                        cf_color = "green" if cf.net_cash_flow_monthly >= 0 else "red"
                        col_m4.markdown(
                            f"Monthly Cash Flow:<br><span style='color:{cf_color}; font-size:18px; font-weight:bold;'>"
                            f"${cf.net_cash_flow_monthly:,.2f}</span>", 
                            unsafe_allow_html=True
                        )
                        
                        # AI summary brochure card
                        st.markdown(f"📝 **Investment Assessment:**")
                        st.info(ev.ai_recommendation)
                        
                    with col_det2:
                        st.write("")
                        st.metric("Overall Investment Score", f"{ev.composite_score} / 100")
                        st.progress(ev.composite_score / 100.0)
                        
                        st.write(f"⚠️ Risk Profile: **{risk.risk_level}**")
                        st.write(f"🏗️ Development Score: **{ev.development.development_score}/10**")
                        
                        # Exporters Buttons
                        pdf_data = generate_property_pdf(ev)
                        st.download_button(
                            label="📥 Download PDF Report",
                            data=pdf_data,
                            file_name=f"investment_report_{listing.mls_number}.pdf",
                            mime="application/pdf",
                            use_container_width=True,
                            key=f"dl_pdf_btn_{listing.mls_number}"
                        )
                        st.markdown(f"[🔗 Open Listing Link]({listing.link})")
                        
        # ------------------ TAB 2: CASH FLOW & SCENARIOS ------------------
        with tab_cashflow:
            st.subheader("💵 Cash Flow Statements & Scenario Models")
            
            for ev in evaluations:
                listing = ev.listing
                cf = ev.cash_flow
                m = ev.mortgage
                sc = ev.scenarios
                
                with st.expander(f"📊 Financials & Scenario Analysis: {listing.address}", expanded=True):
                    # Side-by-side scenarios comparison table
                    st.markdown("**Side-by-Side Stress-Test Projections (Base vs Optimistic vs Pessimistic)**")
                    
                    scenario_tbl = pd.DataFrame({
                        "Metric": [
                            "Monthly Rent", "Mortgage Payment", "Vacancy Allowance", 
                            "Maintenance Reserve", "Strata Fees", "Property Taxes", 
                            "Net Cash Flow (Monthly)", "Net Cash Flow (Annual)", 
                            "Cap Rate (%)", "Cash-on-Cash Return (%)", "5-Year IRR (%)"
                        ],
                        "Pessimistic Scenario": [
                            f"${sc.pessimistic.gross_rent:,.2f}", f"${sc.pessimistic.mortgage_payment:,.2f}", f"${sc.pessimistic.vacancy_allowance_monthly:,.2f}",
                            f"${sc.pessimistic.maintenance_reserve_monthly:,.2f}", f"${sc.pessimistic.strata_fee_monthly:,.2f}", f"${sc.pessimistic.property_tax_monthly:,.2f}",
                            f"${sc.pessimistic.net_cash_flow_monthly:,.2f}", f"${sc.pessimistic.net_cash_flow_annual:,.2f}",
                            f"{sc.pessimistic.cap_rate}%", f"{sc.pessimistic.cash_on_cash_pct}%", f"{sc.pessimistic_roi.irr_5y:.1f}%"
                        ],
                        "Base Scenario": [
                            f"${sc.base.gross_rent:,.2f}", f"${sc.base.mortgage_payment:,.2f}", f"${sc.base.vacancy_allowance_monthly:,.2f}",
                            f"${sc.base.maintenance_reserve_monthly:,.2f}", f"${sc.base.strata_fee_monthly:,.2f}", f"${sc.base.property_tax_monthly:,.2f}",
                            f"${sc.base.net_cash_flow_monthly:,.2f}", f"${sc.base.net_cash_flow_annual:,.2f}",
                            f"{sc.base.cap_rate}%", f"{sc.base.cash_on_cash_pct}%", f"{sc.base_roi.irr_5y:.1f}%"
                        ],
                        "Optimistic Scenario": [
                            f"${sc.optimistic.gross_rent:,.2f}", f"${sc.optimistic.mortgage_payment:,.2f}", f"${sc.optimistic.vacancy_allowance_monthly:,.2f}",
                            f"${sc.optimistic.maintenance_reserve_monthly:,.2f}", f"${sc.optimistic.strata_fee_monthly:,.2f}", f"${sc.optimistic.property_tax_monthly:,.2f}",
                            f"${sc.optimistic.net_cash_flow_monthly:,.2f}", f"${sc.optimistic.net_cash_flow_annual:,.2f}",
                            f"{sc.optimistic.cap_rate}%", f"{sc.optimistic.cash_on_cash_pct}%", f"{sc.optimistic_roi.irr_5y:.1f}%"
                        ]
                    })
                    st.table(scenario_tbl)
                    
                    # Mortgage specifics card
                    st.markdown("**Mortgage Schedule Breakdown**")
                    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                    col_m1.metric("Monthly Payment", f"${m.monthly_payment:,.2f}")
                    col_m2.metric("Year 1 Interest Paid", f"${m.interest_paid_y1:,.2f}")
                    col_m3.metric("5-Year Balance Forecast", f"${m.remaining_balance_y5:,.2f}")
                    col_m4.metric("10-Year Balance Forecast", f"${m.remaining_balance_y10:,.2f}")

        # ------------------ TAB 3: LOCATION MAPS & COMPS ------------------
        with tab_comps:
            st.subheader("🗺️ Geographic Proximity & Market Valuation")
            
            for ev in evaluations:
                listing = ev.listing
                comps = ev.comparables
                transit = ev.transit
                
                with st.expander(f"📍 Map & Comps Analysis: {listing.address}", expanded=True):
                    # Map section
                    st.markdown("**Interactive Location Map (Subject, Transit Hubs, Schools, & Comps)**")
                    property_map = build_property_map(ev)
                    st_folium(property_map, height=350, width=700, key=f"map_{listing.mls_number}")
                    
                    # Comparable properties table
                    st.markdown("**Comparable Sales Dashboard**")
                    comp_list = []
                    for c_listing in comps.comparable_listings:
                        comp_list.append({
                            "Comparable Address": c_listing["address"],
                            "Sold Price": f"${c_listing['price']:,.0f}",
                            "Size (Sqft)": c_listing["sqft"],
                            "Price/Sqft": f"${c_listing['price_per_sqft']:.2f}",
                            "Distance (km)": f"{c_listing['distance_km']:.2f} km"
                        })
                    st.table(pd.DataFrame(comp_list))
                    
                    # Comps stats
                    st.write(
                        f"📊 Comparable Average: **${comps.average_comp_price:,.2f}** "
                        f"(${comps.comp_price_per_sqft:.2f}/sqft). Discount: **{comps.price_discount_pct}%**."
                    )
                    
                    # School catches card
                    st.markdown("**School Catchment Quality Indicators**")
                    st.write(
                        f"🏫 **Elementary**: `{ev.schools.elementary_school}` (Fraser Score: **{ev.schools.elementary_rating}/10**). "
                        f"🏫 **Secondary**: `{ev.schools.secondary_school}` (Fraser Score: **{ev.schools.secondary_rating}/10**)."
                    )

        # ------------------ TAB 4: PROPERTY COMPARISON GRID ------------------
        with tab_compare:
            st.subheader("👥 Comparative Property Matrix")
            
            # Select properties to compare
            addresses = [ev.listing.address for ev in evaluations]
            selected_addresses = st.multiselect("Select properties to compare:", addresses, default=addresses[:2])
            
            if len(selected_addresses) < 1:
                st.info("Select at least one property to view the comparative matrix.")
            else:
                compare_data = []
                for ev in evaluations:
                    if ev.listing.address in selected_addresses:
                        compare_data.append({
                            "Rank": ev.overall_rank,
                            "Address": ev.listing.address,
                            "Score": f"{ev.composite_score}/100",
                            "Price": f"${ev.listing.price:,.0f}",
                            "Beds/Baths": f"{ev.listing.beds}B / {ev.listing.baths}B",
                            "Monthly Cash Flow": f"${ev.cash_flow.net_cash_flow_monthly:,.2f}",
                            "Cap Rate": f"{ev.cash_flow.cap_rate}%",
                            "Cash-on-Cash": f"{ev.cash_flow.cash_on_cash_pct}%",
                            "IRR (5y)": f"{ev.roi.irr_5y:.1f}%",
                            "Risk Level": ev.risk.risk_level,
                            "Transit Score": f"{ev.transit.transit_score}/10",
                            "School Rating": f"{ev.schools.average_school_rating}/10",
                            "Dev Score": f"{ev.development.development_score}/10"
                        })
                st.table(pd.DataFrame(compare_data))

        # ------------------ SHEET SYNC & EXPORTS SECTION ------------------
        st.write("---")
        st.subheader("📊 Document Exporters & Synchronizations")
        
        col_exp1, col_exp2 = st.columns(2)
        with col_exp1:
            # Excel Multi-sheet download
            excel_bytes = export_evaluations_to_excel(evaluations)
            st.download_button(
                label="📥 Download Multi-Tab Excel Workbook",
                data=excel_bytes,
                file_name="metro_vancouver_investment_matrix.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="dl_excel_btn"
            )
            
        with col_exp2:
            try:
                default_sheet_id = st.secrets.get("google_spreadsheet_id", "")
                if not default_sheet_id:
                    default_sheet_id = st.secrets.get("google_sheets", {}).get("spreadsheet_id", "")
            except Exception:
                default_sheet_id = ""
            spreadsheet_input = st.text_input(
                "Google Sheet Link / URL:",
                value=default_sheet_id,
                placeholder="Paste your shared Google Spreadsheet URL here...",
                key="sheets_url_input"
            )
            
        sync_btn = st.button("📤 Sync Evaluated Listings to Google Sheets", use_container_width=True, type="primary")
        
        if sync_btn:
            if not spreadsheet_input:
                st.error("Please enter a Google Spreadsheet ID/URL.")
            else:
                with st.spinner("Authorizing connection and appending rows..."):
                    client = sheets_helper.get_gspread_client()
                    if client:
                        spreadsheet = sheets_helper.get_spreadsheet(client, spreadsheet_input)
                        if spreadsheet:
                            rows_data = []
                            for ev in evaluations:
                                listing = ev.listing
                                cf = ev.cash_flow
                                roi = ev.roi
                                transit = ev.transit
                                risk = ev.risk
                                
                                rows_data.append({
                                    "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "Address": listing.address,
                                    "Property Type": listing.property_type,
                                    "Year Built": listing.year_built,
                                    "Price": f"${listing.price:,.2f}",
                                    "Bedrooms": listing.beds,
                                    "Bathrooms": listing.baths,
                                    "Sqft": listing.sqft,
                                    "Strata Fee": f"${listing.strata_fee:.2f}",
                                    "Property Tax": f"${listing.property_tax:.2f}",
                                    "Est Rent": f"${cf.gross_rent:.2f}",
                                    "Mortgage": f"${cf.mortgage_payment:.2f}",
                                    "Net Cash Flow": f"${cf.net_cash_flow_monthly:.2f}",
                                    "Cap Rate": f"{cf.cap_rate}%",
                                    "Cash-on-Cash Return": f"{cf.cash_on_cash_pct}%",
                                    "5y IRR": f"{roi.irr_5y:.1f}%",
                                    "Transit Score": f"{transit.transit_score:.1f}/10",
                                    "Schools Catchment": f"{ev.schools.average_school_rating:.1f}/10",
                                    "Risk Score": f"{risk.risk_level}",
                                    "Composite Rank Score": f"{ev.composite_score}/100",
                                    "MLS Number": listing.mls_number,
                                    "Link": listing.link
                                })
                            
                            sync_df = pd.DataFrame(rows_data)
                            sheets_helper.sync_property_listings(spreadsheet, sync_df)
