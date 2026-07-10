import math
from typing import Dict, Any, List

# Regional dataset mapping municipalities to historical and geographical parameters
MUNICIPALITIES_DATA: Dict[str, Dict[str, Any]] = {
    "surrey": {
        "name": "Surrey",
        "historical_appreciation_pct": 6.1,
        "population_growth_score": 8.5,
        "safety_score": 7.0,
        "vacancy_rate_pct": 1.2,
        "annual_rent_growth_pct": 4.2,
        "comp_price_per_sqft": {"Condo": 680, "Townhouse": 580, "Detached House": 890},
        "schools": {
            "elementary": "Frost Road Elementary",
            "elementary_rating": 7.8,
            "dist_elementary_km": 0.6,
            "secondary": "Holy Cross Secondary",
            "secondary_rating": 8.1,
            "dist_secondary_km": 1.2,
            "catchment": "Fleetwood District SD36"
        },
        "crime_level": "Medium",
        "volatility_level": "Medium",
        "transit_bus_frequency": "High"
    },
    "langley": {
        "name": "Langley",
        "historical_appreciation_pct": 6.3,
        "population_growth_score": 9.0,
        "safety_score": 8.5,
        "vacancy_rate_pct": 1.5,
        "annual_rent_growth_pct": 4.0,
        "comp_price_per_sqft": {"Condo": 620, "Townhouse": 540, "Detached House": 820},
        "schools": {
            "elementary": "Alex Hope Elementary",
            "elementary_rating": 7.4,
            "dist_elementary_km": 0.8,
            "secondary": "Walnut Grove Secondary",
            "secondary_rating": 7.9,
            "dist_secondary_km": 1.5,
            "catchment": "Walnut Grove SD35"
        },
        "crime_level": "Low",
        "volatility_level": "Low",
        "transit_bus_frequency": "Medium"
    },
    "burnaby": {
        "name": "Burnaby",
        "historical_appreciation_pct": 5.8,
        "population_growth_score": 7.0,
        "safety_score": 8.0,
        "vacancy_rate_pct": 1.1,
        "annual_rent_growth_pct": 4.5,
        "comp_price_per_sqft": {"Condo": 920, "Townhouse": 810, "Detached House": 1250},
        "schools": {
            "elementary": "Marlborough Elementary",
            "elementary_rating": 7.5,
            "dist_elementary_km": 0.5,
            "secondary": "Moscrop Secondary",
            "secondary_rating": 8.0,
            "dist_secondary_km": 1.1,
            "catchment": "Central Burnaby SD41"
        },
        "crime_level": "Low",
        "volatility_level": "Medium",
        "transit_bus_frequency": "High"
    },
    "delta": {
        "name": "Delta",
        "historical_appreciation_pct": 5.4,
        "population_growth_score": 4.5,
        "safety_score": 8.8,
        "vacancy_rate_pct": 1.3,
        "annual_rent_growth_pct": 3.8,
        "comp_price_per_sqft": {"Condo": 590, "Townhouse": 520, "Detached House": 780},
        "schools": {
            "elementary": "Sunshine Hills Elementary",
            "elementary_rating": 7.9,
            "dist_elementary_km": 0.7,
            "secondary": "Seaquam Secondary",
            "secondary_rating": 8.2,
            "dist_secondary_km": 1.3,
            "catchment": "Sunshine Hills SD37"
        },
        "crime_level": "Low",
        "volatility_level": "Low",
        "transit_bus_frequency": "Low"
    },
    "coquitlam": {
        "name": "Coquitlam",
        "historical_appreciation_pct": 5.7,
        "population_growth_score": 6.5,
        "safety_score": 8.2,
        "vacancy_rate_pct": 1.0,
        "annual_rent_growth_pct": 4.1,
        "comp_price_per_sqft": {"Condo": 760, "Townhouse": 680, "Detached House": 1050},
        "schools": {
            "elementary": "Glen Elementary",
            "elementary_rating": 7.2,
            "dist_elementary_km": 0.9,
            "secondary": "Pinetree Secondary",
            "secondary_rating": 7.8,
            "dist_secondary_km": 1.7,
            "catchment": "Town Centre SD43"
        },
        "crime_level": "Low",
        "volatility_level": "Medium",
        "transit_bus_frequency": "High"
    },
    "richmond": {
        "name": "Richmond",
        "historical_appreciation_pct": 5.2,
        "population_growth_score": 5.0,
        "safety_score": 7.8,
        "vacancy_rate_pct": 1.4,
        "annual_rent_growth_pct": 3.9,
        "comp_price_per_sqft": {"Condo": 820, "Townhouse": 730, "Detached House": 1180},
        "schools": {
            "elementary": "Spul'u'kwuks Elementary",
            "elementary_rating": 8.0,
            "dist_elementary_km": 0.4,
            "secondary": "Richmond Secondary",
            "secondary_rating": 7.5,
            "dist_secondary_km": 1.4,
            "catchment": "Richmond Centre SD38"
        },
        "crime_level": "Low",
        "volatility_level": "High",
        "transit_bus_frequency": "High"
    },
    "new_westminster": {
        "name": "New Westminster",
        "historical_appreciation_pct": 5.5,
        "population_growth_score": 5.8,
        "safety_score": 7.5,
        "vacancy_rate_pct": 1.1,
        "annual_rent_growth_pct": 4.3,
        "comp_price_per_sqft": {"Condo": 720, "Townhouse": 640, "Detached House": 960},
        "schools": {
            "elementary": "Herbert Spencer Elementary",
            "elementary_rating": 7.3,
            "dist_elementary_km": 0.6,
            "secondary": "New Westminster Secondary",
            "secondary_rating": 7.2,
            "dist_secondary_km": 1.0,
            "catchment": "New West SD40"
        },
        "crime_level": "Medium",
        "volatility_level": "Medium",
        "transit_bus_frequency": "High"
    },
    "abbotsford": {
        "name": "Abbotsford",
        "historical_appreciation_pct": 6.5,
        "population_growth_score": 7.5,
        "safety_score": 6.5,
        "vacancy_rate_pct": 1.8,
        "annual_rent_growth_pct": 3.5,
        "comp_price_per_sqft": {"Condo": 490, "Townhouse": 440, "Detached House": 690},
        "schools": {
            "elementary": "Auguston Traditional Elementary",
            "elementary_rating": 7.6,
            "dist_elementary_km": 1.1,
            "secondary": "Abbotsford Traditional Secondary",
            "secondary_rating": 7.1,
            "dist_secondary_km": 2.1,
            "catchment": "East Abbotsford SD34"
        },
        "crime_level": "Medium",
        "volatility_level": "Low",
        "transit_bus_frequency": "Medium"
    },
    "maple_ridge": {
        "name": "Maple Ridge",
        "historical_appreciation_pct": 6.0,
        "population_growth_score": 6.8,
        "safety_score": 7.2,
        "vacancy_rate_pct": 1.6,
        "annual_rent_growth_pct": 3.7,
        "comp_price_per_sqft": {"Condo": 520, "Townhouse": 480, "Detached House": 740},
        "schools": {
            "elementary": "Kanaka Creek Elementary",
            "elementary_rating": 7.0,
            "dist_elementary_km": 0.8,
            "secondary": "Maple Ridge Secondary",
            "secondary_rating": 6.8,
            "dist_secondary_km": 1.8,
            "catchment": "Kanaka Creek SD42"
        },
        "crime_level": "Medium",
        "volatility_level": "Low",
        "transit_bus_frequency": "Low"
    }
}

SKYTRAIN_STATIONS: List[Dict[str, Any]] = [
    {"name": "Surrey Central", "lat": 49.1895, "lon": -122.8480, "line": "Expo Line"},
    {"name": "King George", "lat": 49.1828, "lon": -122.8447, "line": "Expo Line"},
    {"name": "Gateway", "lat": 49.1994, "lon": -122.8505, "line": "Expo Line"},
    {"name": "Metrotown", "lat": 49.2257, "lon": -123.0039, "line": "Expo Line"},
    {"name": "Lougheed Town Centre", "lat": 49.2526, "lon": -122.8967, "line": "Expo/Millennium Line"},
    {"name": "Coquitlam Central", "lat": 49.2740, "lon": -122.7993, "line": "Millennium Line"},
    {"name": "Richmond-Brighouse", "lat": 49.1681, "lon": -123.1362, "line": "Canada Line"},
    {"name": "New Westminster", "lat": 49.2014, "lon": -122.9126, "line": "Expo Line"},
    {"name": "Braid", "lat": 49.2243, "lon": -122.8831, "line": "Expo Line"},
    {"name": "Columbia", "lat": 49.2048, "lon": -122.9061, "line": "Expo Line"},
    {"name": "Lafarge Lake-Douglas", "lat": 49.2863, "lon": -122.7919, "line": "Millennium Line"}
]

# Coordinate database of neighborhoods to calculate proximity
NEIGHBORHOOD_COORDS: Dict[str, tuple] = {
    "fleetwood": (49.1728, -122.8122),
    "whalley": (49.1912, -122.8465),
    "guildford": (49.1925, -122.8023),
    "cloverdale": (49.1172, -122.7314),
    "metrotown": (49.2248, -123.0012),
    "walnut grove": (49.1868, -122.6288),
    "willoughby": (49.1345, -122.6467),
    "coquitlam central": (49.2743, -122.8010),
    "brighouse": (49.1685, -123.1382),
    "queensborough": (49.1915, -122.9465),
    "abbotsford east": (49.0494, -122.2514),
    "haney": (49.2201, -122.5975)
}

def detect_municipality(address: str) -> str:
    addr_lower = address.lower()
    for key in MUNICIPALITIES_DATA.keys():
        name = MUNICIPALITIES_DATA[key]["name"].lower()
        if name in addr_lower:
            return key
    # Default to surrey if undefined
    return "surrey"

def detect_neighborhood(address: str) -> str:
    addr_lower = address.lower()
    for name in NEIGHBORHOOD_COORDS.keys():
        if name in addr_lower:
            return name
    return "fleetwood"

def get_geographic_coords(address: str) -> tuple:
    """Estimates lat/lon based on matching neighborhood and street digits to generate mock coordinates"""
    neighborhood = detect_neighborhood(address)
    base_coords = NEIGHBORHOOD_COORDS.get(neighborhood, (49.1728, -122.8122))
    
    # Generate deterministic slight offset based on address string length
    offset_lat = (len(address) % 50) * 0.0001
    offset_lon = (len(address) % 40) * 0.0001
    return (base_coords[0] + offset_lat, base_coords[1] - offset_lon)

def calculate_haversine_distance(coord1: tuple, coord2: tuple) -> float:
    """Calculates great-circle distance between two coordinates in kilometers"""
    R = 6371.0 # earth radius
    lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
    lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])
    
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c
