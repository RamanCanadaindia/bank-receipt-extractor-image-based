import numpy as np
from typing import Dict, Any, List, Tuple
from utils.real_estate.models import (
    PropertyListing, FinancialInputs, MortgageResult, 
    CashFlowResult, AppreciationResult, ROIResult, ScenarioResult
)
from utils.real_estate.data_source import detect_municipality, MUNICIPALITIES_DATA

def calculate_mortgage_details(
    principal: float, 
    annual_rate: float, 
    years: int, 
    frequency: str = "Monthly",
    is_variable: bool = False
) -> MortgageResult:
    """
    Calculates Canadian mortgage payments and balances.
    Canadian fixed mortgages compound semi-annually. Variable compounds monthly.
    """
    if principal <= 0 or annual_rate <= 0 or years <= 0:
        return MortgageResult(0, 0, 0, 0, 0, 0, 0)
        
    # Canadian compounding rule
    if is_variable:
        r_comp = annual_rate / 100 / 12
    else:
        # Fixed compounds semi-annually: (1 + r_semi/2)^2 = (1 + r_monthly)^12
        r_comp = (1 + (annual_rate / 100 / 2))**(2/12) - 1

    # Payment frequency mapping
    freq_map = {
        "Monthly": 12,
        "Semi-Monthly": 24,
        "Bi-Weekly": 26,
        "Weekly": 52
    }
    n_payments_per_year = freq_map.get(frequency, 12)
    r_payment = (1 + r_comp)**(12 / n_payments_per_year) - 1
    total_payments = years * n_payments_per_year
    
    # Amortization payment formula
    pmt = principal * (r_payment * (1 + r_payment)**total_payments) / ((1 + r_payment)**total_payments - 1)
    
    # Yearly amortization table details
    balance = principal
    interest_paid_y1 = 0.0
    principal_paid_y1 = 0.0
    interest_paid_total_10y = 0.0
    principal_paid_total_10y = 0.0
    balance_y5 = principal
    balance_y10 = principal
    
    for payment_idx in range(1, total_payments + 1):
        interest_payment = balance * r_payment
        principal_payment = pmt - interest_payment
        balance = max(0.0, balance - principal_payment)
        
        # Track Year 1 totals
        if payment_idx <= n_payments_per_year:
            interest_paid_y1 += interest_payment
            principal_paid_y1 += principal_payment
            
        # Track Year 5 balance
        if payment_idx == n_payments_per_year * 5:
            balance_y5 = balance
            
        # Track Year 10 balance
        if payment_idx == n_payments_per_year * 10:
            balance_y10 = balance
            
        # Track 10 Year totals
        if payment_idx <= n_payments_per_year * 10:
            interest_paid_total_10y += interest_payment
            principal_paid_total_10y += principal_payment
            
    # Monthly payment equivalent to display
    monthly_equivalent = pmt * (n_payments_per_year / 12)
    
    return MortgageResult(
        monthly_payment=round(monthly_equivalent, 2),
        interest_paid_y1=round(interest_paid_y1, 2),
        principal_paid_y1=round(principal_paid_y1, 2),
        remaining_balance_y5=round(balance_y5, 2),
        remaining_balance_y10=round(balance_y10, 2),
        interest_paid_total_10y=round(interest_paid_total_10y, 2),
        principal_paid_total_10y=round(principal_paid_total_10y, 2)
    )

def calculate_cash_flow_details(
    listing: PropertyListing,
    financials: FinancialInputs,
    mortgage_payment: float
) -> CashFlowResult:
    """Calculates granular monthly cash flow and investment yields"""
    gross_rent = financials.est_rent
    
    # Monthly expenses
    property_tax_monthly = listing.property_tax / 12
    strata_fee_monthly = listing.strata_fee
    
    vacancy_allowance = gross_rent * (financials.vacancy_rate_pct / 100)
    maintenance_reserve = gross_rent * (financials.maintenance_pct / 100)
    prop_management = gross_rent * (financials.property_management_pct / 100)
    
    total_expenses_monthly = (
        mortgage_payment +
        property_tax_monthly +
        strata_fee_monthly +
        financials.insurance_monthly +
        vacancy_allowance +
        maintenance_reserve +
        prop_management +
        financials.utilities_landlord_paid +
        financials.misc_expenses_monthly
    )
    
    net_cash_flow_monthly = gross_rent - total_expenses_monthly
    net_cash_flow_annual = net_cash_flow_monthly * 12
    
    # Cap Rate = NOI / Price
    # NOI = Rent - expenses (excluding mortgage)
    noi_monthly = gross_rent - (total_expenses_monthly - mortgage_payment)
    noi_annual = noi_monthly * 12
    cap_rate = (noi_annual / listing.price) * 100 if listing.price > 0 else 0.0
    
    # Cash-on-Cash Return = Cash Flow / Initial Equity Invested
    initial_equity = listing.price * (financials.down_payment_pct / 100)
    # Include estimated closing costs (e.g. 1.5% of price)
    initial_investment = initial_equity + (listing.price * 0.015)
    cash_on_cash = (net_cash_flow_annual / initial_investment) * 100 if initial_investment > 0 else 0.0
    
    # Debt Service Coverage Ratio (DSCR) = NOI / Debt Service (Mortgage)
    annual_mortgage = mortgage_payment * 12
    dscr = noi_annual / annual_mortgage if annual_mortgage > 0 else 99.0
    
    return CashFlowResult(
        gross_rent=round(gross_rent, 2),
        mortgage_payment=round(mortgage_payment, 2),
        property_tax_monthly=round(property_tax_monthly, 2),
        insurance_monthly=round(financials.insurance_monthly, 2),
        strata_fee_monthly=round(strata_fee_monthly, 2),
        vacancy_allowance_monthly=round(vacancy_allowance, 2),
        maintenance_reserve_monthly=round(maintenance_reserve, 2),
        property_management_monthly=round(prop_management, 2),
        utilities_monthly=round(financials.utilities_landlord_paid, 2),
        misc_monthly=round(financials.misc_expenses_monthly, 2),
        net_cash_flow_monthly=round(net_cash_flow_monthly, 2),
        net_cash_flow_annual=round(net_cash_flow_annual, 2),
        cap_rate=round(cap_rate, 2),
        cash_on_cash_pct=round(cash_on_cash, 2),
        dscr=round(dscr, 2)
    )

def calculate_appreciation_forecast(
    listing: PropertyListing
) -> AppreciationResult:
    """Forecasts appreciation values based on historical trends"""
    municipality = detect_municipality(listing.address)
    m_data = MUNICIPALITIES_DATA.get(municipality, {"historical_appreciation_pct": 5.5, "population_growth_score": 6.0})
    
    annual_appreciation_pct = m_data.get("historical_appreciation_pct", 5.5)
    
    # Compound appreciation y5 & y10
    v0 = listing.price
    v5 = v0 * (1 + annual_appreciation_pct / 100)**5
    v10 = v0 * (1 + annual_appreciation_pct / 100)**10
    
    app_y5 = v5 - v0
    app_y10 = v10 - v0
    
    # Confidence score calculation
    pop_growth = m_data.get("population_growth_score", 6.0)
    safety = m_data.get("safety_score", 7.0)
    confidence = (pop_growth + safety) / 2.0
    
    return AppreciationResult(
        expected_annual_appreciation_pct=annual_appreciation_pct,
        appreciation_y5=round(app_y5, 2),
        appreciation_y10=round(app_y10, 2),
        property_value_y5=round(v5, 2),
        property_value_y10=round(v10, 2),
        confidence_score=round(confidence, 1)
    )

def calculate_roi_details(
    listing: PropertyListing,
    financials: FinancialInputs,
    mortgage: MortgageResult,
    cash_flow: CashFlowResult,
    appreciation: AppreciationResult
) -> ROIResult:
    """Calculates standard real estate ROI metrics including IRR and NPV"""
    initial_equity = listing.price * (financials.down_payment_pct / 100)
    initial_investment = initial_equity + (listing.price * 0.015) # + closing costs
    
    # Year 1 ROI
    principal_paydown_y1 = mortgage.principal_paid_y1
    appreciation_y1 = listing.price * (appreciation.expected_annual_appreciation_pct / 100)
    y1_wealth_created = cash_flow.net_cash_flow_annual + principal_paydown_y1 + appreciation_y1
    year_1_roi = (y1_wealth_created / initial_investment) * 100 if initial_investment > 0 else 0.0
    
    # Year 5 ROI
    expected_app_5y = appreciation.appreciation_y5
    principal_paydown_5y = listing.price - (listing.price * (financials.down_payment_pct / 100)) - mortgage.remaining_balance_y5
    total_wealth_created_5y = (cash_flow.net_cash_flow_annual * 5) + principal_paydown_5y + expected_app_5y
    year_5_roi = (total_wealth_created_5y / initial_investment) * 100 if initial_investment > 0 else 0.0
    
    # Annualized Return 5y
    annualized_return_5y = ((total_wealth_created_5y + initial_investment) / initial_investment)**(1/5) - 1
    
    # Year 10 ROI
    expected_app_10y = appreciation.appreciation_y10
    principal_paydown_10y = listing.price - (listing.price * (financials.down_payment_pct / 100)) - mortgage.remaining_balance_y10
    total_wealth_created_10y = (cash_flow.net_cash_flow_annual * 10) + principal_paydown_10y + expected_app_10y
    year_10_roi = (total_wealth_created_10y / initial_investment) * 100 if initial_investment > 0 else 0.0
    
    # Internal Rate of Return (IRR) 5y: Cash flows [Initial Investment, CF1, CF2, CF3, CF4, CF5 + Sale Equity]
    # Sale Equity = Value y5 - remaining balance
    sale_equity_5y = appreciation.property_value_y5 - mortgage.remaining_balance_y5
    cash_flows_5y = [-initial_investment] + [cash_flow.net_cash_flow_annual] * 4 + [cash_flow.net_cash_flow_annual + sale_equity_5y]
    
    try:
        irr_val = np.irr(cash_flows_5y) if hasattr(np, 'irr') else 0.0
        if not irr_val or np.isnan(irr_val):
            # Fallback numpy financial package
            import numpy_financial as npf
            irr_val = npf.irr(cash_flows_5y)
    except:
        irr_val = 0.0
        
    irr_5y = float(irr_val) * 100 if irr_val else 0.0
    
    # Net Present Value (NPV) 5y using 8.0% standard discount rate
    discount_rate = 0.08
    try:
        npv_val = np.npv(discount_rate, cash_flows_5y) if hasattr(np, 'npv') else 0.0
        if not npv_val or np.isnan(npv_val):
            import numpy_financial as npf
            npv_val = npf.npv(discount_rate, cash_flows_5y)
    except:
        npv_val = 0.0
        
    return ROIResult(
        year_1_roi_pct=round(year_1_roi, 2),
        year_5_roi_pct=round(year_5_roi, 2),
        year_10_roi_pct=round(year_10_roi, 2),
        equity_growth_5y=round(sale_equity_5y - initial_equity, 2),
        principal_paydown_5y=round(principal_paydown_5y, 2),
        expected_appreciation_5y=round(expected_app_5y, 2),
        total_wealth_created_5y=round(total_wealth_created_5y, 2),
        total_wealth_created_10y=round(total_wealth_created_10y, 2),
        annualized_return_5y=round(annualized_return_5y * 100, 2),
        irr_5y=round(irr_5y, 2),
        npv_5y=round(npv_val, 2)
    )

def calculate_scenarios(
    listing: PropertyListing,
    financials: FinancialInputs
) -> ScenarioResult:
    """Calculates Cash Flow and ROI under Base, Optimistic, and Pessimistic scenarios"""
    
    # 1. Base Scenario (Inputs as is)
    mortgage_base = calculate_mortgage_details(
        listing.price * (1 - financials.down_payment_pct/100),
        financials.interest_rate,
        financials.amortization_years,
        financials.payment_frequency,
        financials.mortgage_type == "Variable"
    )
    cf_base = calculate_cash_flow_details(listing, financials, mortgage_base.monthly_payment)
    app_base = calculate_appreciation_forecast(listing)
    roi_base = calculate_roi_details(listing, financials, mortgage_base, cf_base, app_base)
    
    # 2. Optimistic Scenario (Rent +10%, Vacancy -1%, Appreciation +1.5%, Interest -0.5%)
    opt_fin = FinancialInputs(
        down_payment_pct=financials.down_payment_pct,
        interest_rate=max(1.0, financials.interest_rate - 0.5),
        amortization_years=financials.amortization_years,
        mortgage_type=financials.mortgage_type,
        payment_frequency=financials.payment_frequency,
        insurance_monthly=financials.insurance_monthly,
        vacancy_rate_pct=max(0.0, financials.vacancy_rate_pct - 1.0),
        maintenance_pct=financials.maintenance_pct,
        property_management_pct=financials.property_management_pct,
        utilities_landlord_paid=financials.utilities_landlord_paid,
        misc_expenses_monthly=financials.misc_expenses_monthly,
        est_rent=financials.est_rent * 1.10
    )
    mortgage_opt = calculate_mortgage_details(
        listing.price * (1 - opt_fin.down_payment_pct/100),
        opt_fin.interest_rate,
        opt_fin.amortization_years,
        opt_fin.payment_frequency,
        opt_fin.mortgage_type == "Variable"
    )
    cf_opt = calculate_cash_flow_details(listing, opt_fin, mortgage_opt.monthly_payment)
    # Adjust appreciation for opt
    app_opt = calculate_appreciation_forecast(listing)
    app_opt.expected_annual_appreciation_pct += 1.5
    v5_opt = listing.price * (1 + app_opt.expected_annual_appreciation_pct / 100)**5
    v10_opt = listing.price * (1 + app_opt.expected_annual_appreciation_pct / 100)**10
    app_opt.appreciation_y5 = v5_opt - listing.price
    app_opt.appreciation_y10 = v10_opt - listing.price
    app_opt.property_value_y5 = v5_opt
    app_opt.property_value_y10 = v10_opt
    
    roi_opt = calculate_roi_details(listing, opt_fin, mortgage_opt, cf_opt, app_opt)
    
    # 3. Pessimistic Scenario (Rent -10%, Vacancy +2%, Appreciation -2.0%, Interest +1.0%)
    pess_fin = FinancialInputs(
        down_payment_pct=financials.down_payment_pct,
        interest_rate=financials.interest_rate + 1.0,
        amortization_years=financials.amortization_years,
        mortgage_type=financials.mortgage_type,
        payment_frequency=financials.payment_frequency,
        insurance_monthly=financials.insurance_monthly,
        vacancy_rate_pct=financials.vacancy_rate_pct + 2.0,
        maintenance_pct=financials.maintenance_pct,
        property_management_pct=financials.property_management_pct,
        utilities_landlord_paid=financials.utilities_landlord_paid,
        misc_expenses_monthly=financials.misc_expenses_monthly,
        est_rent=financials.est_rent * 0.90
    )
    mortgage_pess = calculate_mortgage_details(
        listing.price * (1 - pess_fin.down_payment_pct/100),
        pess_fin.interest_rate,
        pess_fin.amortization_years,
        pess_fin.payment_frequency,
        pess_fin.mortgage_type == "Variable"
    )
    cf_pess = calculate_cash_flow_details(listing, pess_fin, mortgage_pess.monthly_payment)
    # Adjust appreciation for pess
    app_pess = calculate_appreciation_forecast(listing)
    app_pess.expected_annual_appreciation_pct = max(0.5, app_pess.expected_annual_appreciation_pct - 2.0)
    v5_pess = listing.price * (1 + app_pess.expected_annual_appreciation_pct / 100)**5
    v10_pess = listing.price * (1 + app_pess.expected_annual_appreciation_pct / 100)**10
    app_pess.appreciation_y5 = v5_pess - listing.price
    app_pess.appreciation_y10 = v10_pess - listing.price
    app_pess.property_value_y5 = v5_pess
    app_pess.property_value_y10 = v10_pess
    
    roi_pess = calculate_roi_details(listing, pess_fin, mortgage_pess, cf_pess, app_pess)
    
    return ScenarioResult(
        optimistic=cf_opt,
        base=cf_base,
        pessimistic=cf_pess,
        optimistic_roi=roi_opt,
        base_roi=roi_base,
        pessimistic_roi=roi_pess
    )
