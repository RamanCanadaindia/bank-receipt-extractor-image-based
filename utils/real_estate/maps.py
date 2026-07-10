import folium
from typing import List, Dict, Any
from utils.real_estate.models import PropertyEvaluation
from utils.real_estate.data_source import get_geographic_coords, SKYTRAIN_STATIONS

def build_property_map(eval_res: PropertyEvaluation) -> folium.Map:
    """Builds a Folium interactive map showing the property, SkyTrain stations, schools, and comparable sales"""
    listing = eval_res.listing
    coords = get_geographic_coords(listing.address)
    
    # 1. Initialize Map centered at property coordinates
    m = folium.Map(location=[coords[0], coords[1]], zoom_start=14, control_scale=True)
    
    # 2. Add Target Property Marker
    tooltip_content = f"🏠 <b>{listing.address}</b><br>Price: ${listing.price:,.0f}<br>{listing.beds} Bed, {listing.baths} Bath"
    folium.Marker(
        location=[coords[0], coords[1]],
        popup=folium.Popup(tooltip_content, max_width=300),
        tooltip="Subject Property",
        icon=folium.Icon(color="red", icon="home", prefix="fa")
    ).add_to(m)
    
    # 3. Add SkyTrain Station Markers (within 4km)
    for station in SKYTRAIN_STATIONS:
        # Distance calculation
        from utils.real_estate.data_source import calculate_haversine_distance
        dist = calculate_haversine_distance(coords, (station["lat"], station["lon"]))
        if dist <= 4.0:
            station_tooltip = f"🚉 <b>{station['name']} Station</b><br>{station['line']}<br>Distance: {dist:.2f} km"
            folium.Marker(
                location=[station["lat"], station["lon"]],
                popup=folium.Popup(station_tooltip, max_width=300),
                tooltip=f"SkyTrain: {station['name']}",
                icon=folium.Icon(color="blue", icon="train", prefix="fa")
            ).add_to(m)
            
    # 4. Add School Catchment Markers
    schools = eval_res.schools
    # Estimate school locations based on property offset (simulating real school coords)
    elem_coords = (coords[0] + 0.003, coords[1] - 0.002)
    sec_coords = (coords[0] - 0.004, coords[1] + 0.005)
    
    # Elementary
    elem_tooltip = f"🏫 <b>{schools.elementary_school}</b> (Elementary)<br>Fraser Rating: {schools.elementary_rating}/10<br>Distance: {schools.dist_elementary_km:.1f} km"
    folium.Marker(
        location=[elem_coords[0], elem_coords[1]],
        popup=folium.Popup(elem_tooltip, max_width=300),
        tooltip=f"Elementary School: {schools.elementary_school}",
        icon=folium.Icon(color="green", icon="graduation-cap", prefix="fa")
    ).add_to(m)
    
    # Secondary
    sec_tooltip = f"🏫 <b>{schools.secondary_school}</b> (Secondary)<br>Fraser Rating: {schools.secondary_rating}/10<br>Distance: {schools.dist_secondary_km:.1f} km"
    folium.Marker(
        location=[sec_coords[0], sec_coords[1]],
        popup=folium.Popup(sec_tooltip, max_width=300),
        tooltip=f"High School: {schools.secondary_school}",
        icon=folium.Icon(color="green", icon="graduation-cap", prefix="fa")
    ).add_to(m)
    
    # 5. Add Comparable Sales Markers (orange)
    for idx, comp in enumerate(eval_res.comparables.comparable_listings):
        # Offset coordinates relative to target property to simulate exact geographic locations
        offset_lat = 0.0015 * (idx + 1) * (-1 if idx % 2 == 0 else 1)
        offset_lon = 0.0020 * (idx + 1) * (1 if idx % 3 == 0 else -1)
        comp_coords = (coords[0] + offset_lat, coords[1] + offset_lon)
        
        comp_tooltip = f"🏷️ <b>{comp['address']}</b><br>Sold Price: ${comp['price']:,.0f}<br>Size: {comp['sqft']} Sqft<br>Price/Sqft: ${comp['price_per_sqft']:.2f}"
        folium.Marker(
            location=[comp_coords[0], comp_coords[1]],
            popup=folium.Popup(comp_tooltip, max_width=300),
            tooltip=f"Comparable Sale {idx+1}",
            icon=folium.Icon(color="orange", icon="tag", prefix="fa")
        ).add_to(m)
        
    return m
