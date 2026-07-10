import pandas as pd
import io
from typing import List
from utils.real_estate.models import PropertyEvaluation

def export_evaluations_to_excel(evaluations: List[PropertyEvaluation]) -> bytes:
    """Exports all property evaluations to a multi-worksheet Excel binary stream"""
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # 1. Dashboard sheet
        dash_data = []
        for idx, ev in enumerate(evaluations):
            dash_data.append({
                "Rank": idx + 1,
                "Address": ev.listing.address,
                "MLS Number": ev.listing.mls_number,
                "Property Type": ev.listing.property_type,
                "Price": ev.listing.price,
                "Beds": ev.listing.beds,
                "Baths": ev.listing.baths,
                "Size (Sqft)": ev.listing.sqft,
                "Overall Score (/10)": ev.composite_score,
                "Net Cash Flow (Monthly)": ev.cash_flow.net_cash_flow_monthly,
                "Cap Rate (%)": ev.cash_flow.cap_rate,
                "Cash-on-Cash Return (%)": ev.cash_flow.cash_on_cash_pct,
                "Year 5 IRR (%)": ev.roi.irr_5y,
                "Opportunity Rating": ev.comparables.opportunity_rating,
                "Risk Rating": ev.risk.risk_level
            })
        pd.DataFrame(dash_data).to_excel(writer, sheet_name="Dashboard", index=False)
        
        # 2. Cash Flow sheet
        cf_data = []
        for ev in evaluations:
            cf = ev.cash_flow
            cf_data.append({
                "Address": ev.listing.address,
                "Gross Rent": cf.gross_rent,
                "Mortgage Payment": cf.mortgage_payment,
                "Property Tax (Monthly)": cf.property_tax_monthly,
                "Insurance (Monthly)": cf.insurance_monthly,
                "Strata Fee (Monthly)": cf.strata_fee_monthly,
                "Vacancy Allowance": cf.vacancy_allowance_monthly,
                "Maintenance Reserve": cf.maintenance_reserve_monthly,
                "Property Management": cf.property_management_monthly,
                "Utilities": cf.utilities_monthly,
                "Misc Expenses": cf.misc_monthly,
                "Net Cash Flow (Monthly)": cf.net_cash_flow_monthly,
                "Net Cash Flow (Annual)": cf.net_cash_flow_annual,
                "Cap Rate (%)": cf.cap_rate,
                "DSCR": cf.dscr
            })
        pd.DataFrame(cf_data).to_excel(writer, sheet_name="Cash Flow", index=False)
        
        # 3. ROI sheet
        roi_data = []
        for ev in evaluations:
            roi = ev.roi
            roi_data.append({
                "Address": ev.listing.address,
                "Year 1 ROI (%)": roi.year_1_roi_pct,
                "Year 5 ROI (%)": roi.year_5_roi_pct,
                "Year 10 ROI (%)": roi.year_10_roi_pct,
                "Equity Growth (5y)": roi.equity_growth_5y,
                "Principal Paydown (5y)": roi.principal_paydown_5y,
                "Expected Appreciation (5y)": roi.expected_appreciation_5y,
                "Total Wealth Created (5y)": roi.total_wealth_created_5y,
                "Annualized Return (5y %)": roi.annualized_return_5y,
                "5y IRR (%)": roi.irr_5y,
                "5y NPV (8% disc)": roi.npv_5y
            })
        pd.DataFrame(roi_data).to_excel(writer, sheet_name="ROI", index=False)
        
        # 4. Mortgage sheet
        mort_data = []
        for ev in evaluations:
            m = ev.mortgage
            mort_data.append({
                "Address": ev.listing.address,
                "Monthly Payment": m.monthly_payment,
                "Interest Paid (Year 1)": m.interest_paid_y1,
                "Principal Paid (Year 1)": m.principal_paid_y1,
                "Interest Paid (10y Total)": m.interest_paid_total_10y,
                "Principal Paid (10y Total)": m.principal_paid_total_10y,
                "Balance Year 5": m.remaining_balance_y5,
                "Balance Year 10": m.remaining_balance_y10
            })
        pd.DataFrame(mort_data).to_excel(writer, sheet_name="Mortgage", index=False)
        
        # 5. Comparable Sales sheet
        comps_data = []
        for ev in evaluations:
            c = ev.comparables
            comps_data.append({
                "Address": ev.listing.address,
                "List Price": ev.listing.price,
                "Avg Comp Price": c.average_comp_price,
                "Median Comp Price": c.median_comp_price,
                "Comps Price/Sqft": c.comp_price_per_sqft,
                "Listing Price/Sqft": c.listing_price_per_sqft,
                "Discount %": c.price_discount_pct,
                "Opportunity Rating": c.opportunity_rating
            })
        pd.DataFrame(comps_data).to_excel(writer, sheet_name="Comparable Sales", index=False)
        
        # 6. Risk sheet
        risk_data = []
        for ev in evaluations:
            r = ev.risk
            risk_data.append({
                "Address": ev.listing.address,
                "Flood Risk": r.flood_risk,
                "Wildfire Risk": r.wildfire_risk,
                "Earthquake Exposure": r.earthquake_exposure,
                "Crime Level": r.crime_rate,
                "Market Volatility": r.market_volatility,
                "Strata Litigation": r.strata_litigation,
                "Leverage Risk": r.leverage_risk,
                "Interest Rate Sensitivity": r.interest_rate_sensitivity,
                "Overall Risk Level": r.risk_level,
                "Risk Score (/10)": r.risk_score
            })
        pd.DataFrame(risk_data).to_excel(writer, sheet_name="Risk", index=False)
        
        # 7. Growth Forecast sheet
        growth_data = []
        for ev in evaluations:
            a = ev.appreciation
            growth_data.append({
                "Address": ev.listing.address,
                "Expected Annual Appreciation (%)": a.expected_annual_appreciation_pct,
                "Appreciation Year 5": a.appreciation_y5,
                "Appreciation Year 10": a.appreciation_y10,
                "Value Year 5": a.property_value_y5,
                "Value Year 10": a.property_value_y10,
                "Forecast Confidence Score (/10)": a.confidence_score
            })
        pd.DataFrame(growth_data).to_excel(writer, sheet_name="Growth Forecast", index=False)
        
        # 8. Rankings sheet
        rank_data = []
        for idx, ev in enumerate(evaluations):
            rank_data.append({
                "Rank": idx + 1,
                "Address": ev.listing.address,
                "Composite Score (/10)": ev.composite_score,
                "Transit Score (/10)": ev.transit.transit_score,
                "Safety Score (/10)": 10.0 - ev.risk.risk_score,
                "School Score (/10)": ev.schools.average_school_rating,
                "Cash Flow Score (/10)": ev.cash_flow.cap_rate,
                "Growth Score (/10)": ev.appreciation.expected_annual_appreciation_pct,
                "Development Score (/10)": ev.development.development_score
            })
        pd.DataFrame(rank_data).to_excel(writer, sheet_name="Rankings", index=False)

    return output.getvalue()
