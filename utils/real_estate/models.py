from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

@dataclass
class PropertyListing:
    address: str
    price: float
    beds: int
    baths: int
    sqft: int
    strata_fee: float
    property_tax: float
    year_built: int
    property_type: str  # Condo, Townhouse, Detached House
    mls_number: str = "N/A"
    link: str = ""
    timestamp: str = ""

@dataclass
class FinancialInputs:
    down_payment_pct: float = 20.0
    interest_rate: float = 4.8
    amortization_years: int = 25
    mortgage_type: str = "Fixed"  # Fixed or Variable
    payment_frequency: str = "Monthly"  # Monthly, Semi-Monthly, Bi-Weekly, Weekly
    insurance_monthly: float = 80.0
    vacancy_rate_pct: float = 3.0
    maintenance_pct: float = 5.0
    property_management_pct: float = 6.0
    utilities_landlord_paid: float = 0.0
    misc_expenses_monthly: float = 0.0
    est_rent: float = 2500.0

@dataclass
class MortgageResult:
    monthly_payment: float
    interest_paid_y1: float
    principal_paid_y1: float
    remaining_balance_y5: float
    remaining_balance_y10: float
    interest_paid_total_10y: float
    principal_paid_total_10y: float

@dataclass
class CashFlowResult:
    gross_rent: float
    mortgage_payment: float
    property_tax_monthly: float
    insurance_monthly: float
    strata_fee_monthly: float
    vacancy_allowance_monthly: float
    maintenance_reserve_monthly: float
    property_management_monthly: float
    utilities_monthly: float
    misc_monthly: float
    net_cash_flow_monthly: float
    net_cash_flow_annual: float
    cap_rate: float
    cash_on_cash_pct: float
    dscr: float

@dataclass
class AppreciationResult:
    expected_annual_appreciation_pct: float
    appreciation_y5: float
    appreciation_y10: float
    property_value_y5: float
    property_value_y10: float
    confidence_score: float  # 1 to 10

@dataclass
class ComparableSalesResult:
    average_comp_price: float
    median_comp_price: float
    comp_price_per_sqft: float
    listing_price_per_sqft: float
    price_discount_pct: float  # positive means discount, negative means premium
    is_below_market: bool
    opportunity_rating: str  # Excellent, Good, Fair, Overpriced
    comparable_listings: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class DevelopmentResult:
    transit_oriented_area: bool
    skytrain_proximity_score: float  # 1-10
    ftda_eligible: bool
    ocp_designation: str
    ssmu_eligible: bool
    multiplex_eligible: bool
    subdivision_potential: bool
    corner_lot: bool
    lane_access: bool
    rezoning_likelihood: str  # High, Medium, Low
    development_score: float  # 1 to 10

@dataclass
class TransitResult:
    walking_distance_meters: float
    bus_frequency: str  # High, Medium, Low
    skytrain_distance_km: float
    nearest_station: str
    future_station_nearby: bool
    highway_access: str  # Quick, Moderate, Distant
    commute_time_vancouver_min: float
    transit_score: float  # 1 to 10

@dataclass
class SchoolResult:
    elementary_school: str
    elementary_rating: float  # 1-10 Fraser Institute
    secondary_school: str
    secondary_rating: float  # 1-10 Fraser Institute
    average_school_rating: float
    dist_elementary_km: float
    dist_secondary_km: float
    catchment_info: str

@dataclass
class RentalDemandResult:
    vacancy_rate_pct: float
    population_growth_score: float  # 1-10
    employment_growth_score: float  # 1-10
    nearby_amenities_score: float  # 1-10
    est_rent_growth_annual_pct: float
    rental_demand_score: float  # 1 to 10

@dataclass
class PropertyConditionResult:
    age_years: int
    roof_condition: str  # New, Good, Fair, Needs Replacement
    hvac_system: str
    expected_maintenance_y1_to_y5: float  # annual dollar estimate
    special_assessments_risk: str  # Low, Medium, High
    strata_contingency_fund_level: str  # Healthy, Moderate, Low, N/A
    condition_score: float  # 1 to 10

@dataclass
class RiskResult:
    flood_risk: str  # Low, Medium, High
    wildfire_risk: str  # Low, Medium, High
    earthquake_exposure: str  # Low, Medium, High
    crime_rate: str  # Low, Medium, High
    market_volatility: str  # Low, Medium, High
    strata_litigation: bool
    leverage_risk: str  # Low, Medium, High
    interest_rate_sensitivity: str  # Low, Medium, High
    risk_level: str  # Low, Medium, High, Very High
    risk_score: float  # 1 to 10 (higher is riskier)

@dataclass
class ROIResult:
    year_1_roi_pct: float
    year_5_roi_pct: float
    year_10_roi_pct: float
    equity_growth_5y: float
    principal_paydown_5y: float
    expected_appreciation_5y: float
    total_wealth_created_5y: float
    total_wealth_created_10y: float
    annualized_return_5y: float
    irr_5y: float
    npv_5y: float

@dataclass
class ScenarioResult:
    optimistic: CashFlowResult
    base: CashFlowResult
    pessimistic: CashFlowResult
    optimistic_roi: ROIResult
    base_roi: ROIResult
    pessimistic_roi: ROIResult

@dataclass
class PropertyEvaluation:
    listing: PropertyListing
    financials: FinancialInputs
    mortgage: MortgageResult
    cash_flow: CashFlowResult
    appreciation: AppreciationResult
    comparables: ComparableSalesResult
    development: DevelopmentResult
    transit: TransitResult
    schools: SchoolResult
    demand: RentalDemandResult
    condition: PropertyConditionResult
    risk: RiskResult
    roi: ROIResult
    scenarios: ScenarioResult
    composite_score: float = 0.0  # 1 to 10
    overall_rank: int = 999
    ai_recommendation: str = ""
