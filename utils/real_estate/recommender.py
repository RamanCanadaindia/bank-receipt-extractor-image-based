import os
from utils.real_estate.models import PropertyEvaluation
from utils.gemini_helper import query_gemini

def generate_recommendation(eval_res: PropertyEvaluation) -> str:
    """Generates a professional written investment recommendation (via Gemini or rules-based fallback)"""
    listing = eval_res.listing
    cf = eval_res.cash_flow
    roi = eval_res.roi
    comps = eval_res.comparables
    transit = eval_res.transit
    risk = eval_res.risk
    dev = eval_res.development
    
    # Check for Gemini API key
    gemini_active = os.environ.get("GEMINI_API_KEY") is not None
    
    if gemini_active:
        prompt = f"""
        You are a commercial real estate investment analyst. Write a professional, concise 3-4 sentence investment summary for the property below.
        
        Address: {listing.address}
        Type: {listing.property_type}
        List Price: ${listing.price:,.0f}
        MLS Number: {listing.mls_number}
        
        Evaluated Metrics:
        - Overall Score: {eval_res.composite_score}/10
        - Monthly Net Cash Flow: ${cf.net_cash_flow_monthly:,.2f}/month
        - Cap Rate: {cf.cap_rate}%
        - Cash-on-Cash Return: {cf.cash_on_cash_pct}%
        - Year 5 IRR: {roi.irr_5y}%
        - Comparable sales: Currently priced {comps.price_discount_pct}% {"below" if comps.price_discount_pct >= 0 else "above"} comparable sales (Opportunity: {comps.opportunity_rating})
        - Transit distance: {transit.walking_distance_meters} meters walk to {transit.nearest_station} Skytrain station
        - Development Potential: Score {dev.development_score}/10 (TOA: {"Yes" if dev.transit_oriented_area else "No"})
        - Risk profile: {risk.risk_level} (Score: {risk.risk_score}/10)
        
        Guidelines:
        1. Keep it strictly fact-based. DO NOT hallucinate any values.
        2. Reference specific numbers from the evaluated metrics list above.
        3. Discuss cash flow, comparable price discount, and transit proximity.
        4. Mention the risk level and main drawbacks (e.g. negative cash flow, older building, or high leverage risk).
        """
        try:
            summary = query_gemini(prompt)
            if summary and len(summary.strip()) > 30:
                return summary.strip()
        except Exception as e:
            print(f"[Recommender] Gemini recommendation generation failed: {e}. Falling back to local rules.")
            
    # Rules-based fallback (extremely high quality)
    recommendation_templates = []
    
    # 1. Opening sentence about Type, Price, and comparable value
    comp_verb = "below" if comps.price_discount_pct >= 0 else "above"
    comp_abs = abs(comps.price_discount_pct)
    recommendation_templates.append(
        f"This {listing.property_type.lower()} at {listing.address} is evaluated as a {comps.opportunity_rating.lower()} investment opportunity, currently priced {comp_abs:.1f}% {comp_verb} comparable neighborhood sales."
    )
    
    # 2. Cash flow details
    if cf.net_cash_flow_monthly >= 0:
        cf_str = f"generates a positive monthly net cash flow of ${cf.net_cash_flow_monthly:,.2f} with a Cap Rate of {cf.cap_rate:.1f}% and a Cash-on-Cash yield of {cf.cash_on_cash_pct:.1f}%."
    else:
        cf_abs = abs(cf.net_cash_flow_monthly)
        cf_str = f"carries a monthly cash flow deficit of -${cf_abs:,.2f} (Cap Rate: {cf.cap_rate:.1f}%), requiring cash injections to cover the monthly mortgage and strata expenses."
    recommendation_templates.append(f"At the base scenario, the property {cf_str}")
    
    # 3. Location, transit, and development
    toa_str = "within a Transit-Oriented Area (TOA) boundary," if dev.transit_oriented_area else "located outside primary transit-oriented areas,"
    recommendation_templates.append(
        f"It is {toa_str} situated {transit.walking_distance_meters:.0f} meters from the {transit.nearest_station} SkyTrain station, giving it a strong Transit score of {transit.transit_score:.1f}/10."
    )
    
    # 4. Risk / draws summary
    drawbacks = []
    if risk.risk_level in ("High", "Very High"):
        drawbacks.append(f"high investment risk profile ({risk.risk_level}) due to flood exposure or interest-rate sensitivities")
    if listing.strata_fee > 400:
        drawbacks.append(f"higher strata fees (${listing.strata_fee:.2f}/mo)")
    if eval_res.condition.age_years > 25:
        drawbacks.append(f"an older structure (built in {listing.year_built}) requiring higher expected maintenance reserves")
        
    drawback_str = " and ".join(drawbacks) if drawbacks else "standard leverage and market volatility parameters"
    recommendation_templates.append(f"Primary risks to consider are {drawback_str}.")
    
    return " ".join(recommendation_templates)
