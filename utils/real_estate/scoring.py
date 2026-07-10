import re
from datetime import datetime
from typing import Dict, Any, List, Tuple
from utils.real_estate.models import (
    PropertyListing, FinancialInputs, CashFlowResult, MortgageResult, ROIResult,
    AppreciationResult, ComparableSalesResult, DevelopmentResult, TransitResult,
    SchoolResult, RentalDemandResult, PropertyConditionResult, RiskResult
)
from utils.real_estate.data_source import (
    detect_municipality, MUNICIPALITIES_DATA, get_geographic_coords, 
    SKYTRAIN_STATIONS, calculate_haversine_distance
)

def evaluate_comparable_sales(listing: PropertyListing) -> ComparableSalesResult:
    """Generates deterministic comparable sales to compute average/median pricing metrics"""
    municipality = detect_municipality(listing.address)
    m_data = MUNICIPALITIES_DATA.get(municipality, {})
    comp_ref = m_data.get("comp_price_per_sqft", {"Condo": 700, "Townhouse": 600, "Detached House": 1000})
    
    # Base comparable price per sqft for this property type in this city
    base_comp_sqft_price = comp_ref.get(listing.property_type, 650)
    
    # Generate 3 realistic comparable properties in the same sub-area
    coords = get_geographic_coords(listing.address)
    
    # Comparable 1: 4% cheaper per sqft, slightly smaller
    sqft_1 = int(listing.sqft * 0.95) if listing.sqft > 0 else 800
    price_1 = sqft_1 * base_comp_sqft_price * 0.96
    
    # Comparable 2: 3% more expensive per sqft, slightly larger
    sqft_2 = int(listing.sqft * 1.05) if listing.sqft > 0 else 900
    price_2 = sqft_2 * base_comp_sqft_price * 1.03
    
    # Comparable 3: Same size, at baseline market price per sqft
    sqft_3 = listing.sqft if listing.sqft > 0 else 850
    price_3 = sqft_3 * base_comp_sqft_price * 1.00
    
    comps = [
        {"address": f"Comp 1 - Near {listing.address.split()[-2] if len(listing.address.split()) > 2 else 'MLS'}", "price": price_1, "sqft": sqft_1, "price_per_sqft": base_comp_sqft_price * 0.96, "distance_km": 0.4},
        {"address": f"Comp 2 - Near {listing.address.split()[-2] if len(listing.address.split()) > 2 else 'MLS'}", "price": price_2, "sqft": sqft_2, "price_per_sqft": base_comp_sqft_price * 1.03, "distance_km": 0.8},
        {"address": f"Comp 3 - Near {listing.address.split()[-2] if len(listing.address.split()) > 2 else 'MLS'}", "price": price_3, "sqft": sqft_3, "price_per_sqft": base_comp_sqft_price * 1.00, "distance_km": 0.5}
    ]
    
    avg_price_sqft = (comps[0]["price_per_sqft"] + comps[1]["price_per_sqft"] + comps[2]["price_per_sqft"]) / 3
    median_price_sqft = comps[2]["price_per_sqft"] # middle element
    
    # Listing price per sqft
    listing_price_per_sqft = listing.price / listing.sqft if listing.sqft > 0 else base_comp_sqft_price
    
    # Compare listing price per sqft vs average comps
    price_discount_pct = ((avg_price_sqft - listing_price_per_sqft) / avg_price_sqft) * 100
    is_below_market = listing_price_per_sqft < avg_price_sqft
    
    if price_discount_pct >= 8.0:
        opportunity = "Excellent"
    elif price_discount_pct >= 2.0:
        opportunity = "Good"
    elif price_discount_pct >= -3.0:
        opportunity = "Fair"
    else:
        opportunity = "Overpriced"
        
    avg_comp_price = avg_price_sqft * (listing.sqft if listing.sqft > 0 else 850)
    median_comp_price = median_price_sqft * (listing.sqft if listing.sqft > 0 else 850)
    
    return ComparableSalesResult(
        average_comp_price=round(avg_comp_price, 2),
        median_comp_price=round(median_comp_price, 2),
        comp_price_per_sqft=round(avg_price_sqft, 2),
        listing_price_per_sqft=round(listing_price_per_sqft, 2),
        price_discount_pct=round(price_discount_pct, 2),
        is_below_market=is_below_market,
        opportunity_rating=opportunity,
        comparable_listings=comps
    )

def evaluate_transit_score(listing: PropertyListing) -> TransitResult:
    """Calculates geographical distance to SkyTrain stations and maps transit metrics"""
    coords = get_geographic_coords(listing.address)
    
    # Find nearest station
    min_dist = 999.0
    nearest_station_name = "Unknown Transit Hub"
    for station in SKYTRAIN_STATIONS:
        dist = calculate_haversine_distance(coords, (station["lat"], station["lon"]))
        if dist < min_dist:
            min_dist = dist
            nearest_station_name = station["name"]
            
    # Commute details
    municipality = detect_municipality(listing.address)
    m_data = MUNICIPALITIES_DATA.get(municipality, {})
    bus_freq = m_data.get("transit_bus_frequency", "Medium")
    
    # Estimated commute to Downtown Vancouver based on municipality
    commute_times = {
        "surrey": 42,
        "langley": 55,
        "burnaby": 20,
        "delta": 45,
        "coquitlam": 38,
        "richmond": 25,
        "new_westminster": 30,
        "abbotsford": 75,
        "maple_ridge": 60
    }
    commute_time = commute_times.get(municipality, 40)
    
    # Walk score calculation: under 800m is close, 800m-1.5km moderate, 1.5km+ distant
    walk_dist_meters = min_dist * 1000
    
    # SkyTrain Transit Score: 800m = 10, linearly decaying to 2 at 4km
    if walk_dist_meters <= 800:
        transit_score = 10.0
    elif walk_dist_meters >= 4000:
        transit_score = 2.0
    else:
        transit_score = 10.0 - ((walk_dist_meters - 800) / 3200) * 8.0
        
    # Boost if future project nearby (Langley / Surrey extension projects)
    future_station = False
    if municipality in ("langley", "surrey") and walk_dist_meters > 2000:
        future_station = True
        transit_score = min(10.0, transit_score + 1.5)
        
    highway_access = "Moderate" if municipality in ("surrey", "coquitlam", "richmond") else ("Quick" if municipality in ("langley", "delta", "burnaby", "abbotsford") else "Distant")
    
    return TransitResult(
        walking_distance_meters=round(walk_dist_meters, 0),
        bus_frequency=bus_freq,
        skytrain_distance_km=round(min_dist, 2),
        nearest_station=nearest_station_name,
        future_station_nearby=future_station,
        highway_access=highway_access,
        commute_time_vancouver_min=commute_time,
        transit_score=round(transit_score, 1)
    )

def evaluate_development_potential(
    listing: PropertyListing, 
    transit: TransitResult
) -> DevelopmentResult:
    """Evaluates development potential based on regional housing legislation (Bill 44, SSMUH)"""
    municipality = detect_municipality(listing.address)
    
    # Transit-Oriented Area (TOA) triggers if within 800m of a Skytrain station
    toa = transit.walking_distance_meters <= 800
    
    # SSMUH (Small Scale Multi-Unit Housing) / Multiplex eligibility
    # Single-family / duplex lots are eligible. Townhouse/Condo are stratified.
    ssmuh = listing.property_type == "Detached House"
    multiplex = listing.property_type == "Detached House"
    
    # Subdivision potential is typically corner lots or large lots (e.g. length of address offset)
    is_corner = (len(listing.address) % 7) == 0
    has_lane = (len(listing.address) % 5) != 0
    subdivision = listing.property_type == "Detached House" and is_corner
    
    # Development Score
    if listing.property_type == "Detached House":
        base_score = 7.0
        if toa: base_score += 2.0
        if is_corner: base_score += 0.5
        if has_lane: base_score += 0.5
    elif listing.property_type == "Townhouse":
        base_score = 4.0
        if toa: base_score += 2.0
    else:
        base_score = 2.0
        if toa: base_score += 1.0
        
    rezoning = "High" if (toa and listing.property_type == "Detached House") else ("Medium" if listing.property_type == "Detached House" else "Low")
    
    return DevelopmentResult(
        transit_oriented_area=toa,
        skytrain_proximity_score=transit.transit_score,
        ftda_eligible=toa,
        ocp_designation="Transit Corridor Residential" if toa else "Low Density Residential",
        ssmu_eligible=ssmuh,
        multiplex_eligible=multiplex,
        subdivision_potential=subdivision,
        corner_lot=is_corner,
        lane_access=has_lane,
        rezoning_likelihood=rezoning,
        development_score=round(base_score, 1)
    )

def evaluate_schools(listing: PropertyListing) -> SchoolResult:
    """Looks up school catchments from regional database"""
    municipality = detect_municipality(listing.address)
    m_data = MUNICIPALITIES_DATA.get(municipality, {})
    s_info = m_data.get("schools", {
        "elementary": "Public School", "elementary_rating": 6.0, "dist_elementary_km": 1.2,
        "secondary": "Public High", "secondary_rating": 6.2, "dist_secondary_km": 2.0,
        "catchment": "District catchment"
    })
    
    avg_rating = (s_info["elementary_rating"] + s_info["secondary_rating"]) / 2.0
    
    return SchoolResult(
        elementary_school=s_info["elementary"],
        elementary_rating=s_info["elementary_rating"],
        secondary_school=s_info["secondary"],
        secondary_rating=s_info["secondary_rating"],
        average_school_rating=round(avg_rating, 1),
        dist_elementary_km=s_info["dist_elementary_km"],
        dist_secondary_km=s_info["dist_secondary_km"],
        catchment_info=s_info["catchment"]
    )

def evaluate_rental_demand(listing: PropertyListing) -> RentalDemandResult:
    """Computes rental demand scores based on municipal vacancy rates and metrics"""
    municipality = detect_municipality(listing.address)
    m_data = MUNICIPALITIES_DATA.get(municipality, {})
    
    vacancy = m_data.get("vacancy_rate_pct", 1.5)
    pop_growth = m_data.get("population_growth_score", 6.0)
    rent_growth = m_data.get("annual_rent_growth_pct", 4.0)
    
    # Proximity score based on type (Condos/Townhouses usually closer to amenities)
    amenities = 8.0 if listing.property_type in ("Condo", "Townhouse") else 6.0
    
    # Rental Demand Score: vacancy rate below 1.5% is strong
    v_score = 10.0 if vacancy <= 1.0 else (8.0 if vacancy <= 1.5 else 6.0)
    
    demand_score = (v_score + pop_growth + amenities) / 3.0
    
    return RentalDemandResult(
        vacancy_rate_pct=vacancy,
        population_growth_score=pop_growth,
        employment_growth_score=pop_growth - 0.5,
        nearby_amenities_score=amenities,
        est_rent_growth_annual_pct=rent_growth,
        rental_demand_score=round(demand_score, 1)
    )

def evaluate_property_condition(listing: PropertyListing) -> PropertyConditionResult:
    """Evaluates building parameters and contingency reserves to output a condition score"""
    # Calculate age
    current_year = datetime.now().year if 'datetime' in globals() else 2026
    age = max(0, current_year - listing.year_built)
    
    # Maintenance / assessments risks are higher for older structures
    if age <= 5:
        roof = "Good"
        hvac = "Excellent"
        expected_maint = listing.price * 0.005 # 0.5% of price
        special_risk = "Low"
        contingency = "Healthy"
        score = 9.5
    elif age <= 15:
        roof = "Good"
        hvac = "Good"
        expected_maint = listing.price * 0.008
        special_risk = "Low"
        contingency = "Healthy"
        score = 8.0
    elif age <= 25:
        roof = "Fair"
        hvac = "Fair"
        expected_maint = listing.price * 0.012
        special_risk = "Medium"
        contingency = "Moderate"
        score = 6.0
    else:
        roof = "Needs Replacement"
        hvac = "Needs Replacement"
        expected_maint = listing.price * 0.020
        special_risk = "High"
        contingency = "Low"
        score = 4.0
        
    if listing.property_type == "Detached House":
        contingency = "N/A" # No strata fund for detached houses
        
    return PropertyConditionResult(
        age_years=age,
        roof_condition=roof,
        hvac_system=hvac,
        expected_maintenance_y1_to_y5=round(expected_maint, 2),
        special_assessments_risk=special_risk,
        strata_contingency_fund_level=contingency,
        condition_score=round(score, 1)
    )

def evaluate_risk_profile(
    listing: PropertyListing,
    financials: FinancialInputs,
    condition: PropertyConditionResult
) -> RiskResult:
    """Calculates investment risk profile metrics"""
    municipality = detect_municipality(listing.address)
    m_data = MUNICIPALITIES_DATA.get(municipality, {})
    
    # Natural risks based on geography
    flood = "High" if municipality in ("delta", "abbotsford", "maple_ridge") else "Low"
    wildfire = "Medium" if municipality in ("maple_ridge", "langley") else "Low"
    earthquake = "Medium" if municipality in ("richmond", "delta") else "Low"
    
    # Safety stats
    crime = m_data.get("crime_level", "Medium")
    volatility = m_data.get("volatility_level", "Medium")
    
    # Financial risks
    leverage = "High" if financials.down_payment_pct <= 10.0 else "Medium"
    sensitivity = "High" if financials.mortgage_type == "Variable" else "Medium"
    
    # Composite Risk score (1-10, higher is riskier)
    base_risk = 3.0
    if flood == "High": base_risk += 1.5
    if crime == "Medium": base_risk += 1.0
    if leverage == "High": base_risk += 1.5
    if sensitivity == "High": base_risk += 1.0
    if condition.special_assessments_risk == "High": base_risk += 2.0
    
    risk_score = min(10.0, base_risk)
    
    if risk_score <= 4.0:
        level = "Low"
    elif risk_score <= 6.0:
        level = "Medium"
    elif risk_score <= 8.0:
        level = "High"
    else:
        level = "Very High"
        
    return RiskResult(
        flood_risk=flood,
        wildfire_risk=wildfire,
        earthquake_exposure=earthquake,
        crime_rate=crime,
        market_volatility=volatility,
        strata_litigation=False,
        leverage_risk=leverage,
        interest_rate_sensitivity=sensitivity,
        risk_level=level,
        risk_score=round(risk_score, 1)
    )

def calculate_norm_score(value: float, min_val: float, max_val: float, invert: bool = False) -> float:
    """Helper to normalize values onto a 1-10 scale"""
    if max_val == min_val:
        return 5.0
    val_norm = (value - min_val) / (max_val - min_val)
    score = 1.0 + val_norm * 9.0
    score = max(1.0, min(10.0, score))
    return 11.0 - score if invert else score
