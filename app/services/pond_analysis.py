"""
Satellite-based aqua pond analysis.
Uses Sentinel-2 NDWI (water extent), NDVI on water (algae detection),
and weather data (temperature, humidity) to estimate pond health
parameters that matter for aquaculture: dissolved oxygen, temperature,
algae bloom risk, heat stress, and overall mortality risk.
"""


def analyze_pond(
    ndwi: float | None,
    ndwi_previous: float | None,
    ndvi_on_water: float | None,
    weather: dict,
    area_acres: float,
    species: str = "Fish",
) -> dict:
    """
    Returns all pond health parameters from satellite indices + weather.

    NDWI > 0.3 on a pond = open water (healthy, full pond)
    NDWI 0.1-0.3 = partially filled or turbid
    NDWI < 0.1 = very shallow / nearly dry

    NDVI on water surface > 0.2 = algae bloom present
    (healthy water has near-zero NDVI; algae increases it)
    """
    temp = weather.get("temperature", 28.0)
    humidity = weather.get("humidity", 70.0)
    rain_7d = weather.get("rainfall_7d", 0.0)

    # ─── WATER SPREAD ────────────────────────────────────────────────
    if ndwi is not None:
        if ndwi >= 0.4:
            water_spread = 95
            water_trend = "Stable"
        elif ndwi >= 0.3:
            water_spread = 85
            water_trend = "Stable"
        elif ndwi >= 0.2:
            water_spread = 70
            water_trend = "Reducing"
        elif ndwi >= 0.1:
            water_spread = 55
            water_trend = "Reducing"
        else:
            water_spread = 35
            water_trend = "Critically Low"

        if ndwi_previous and ndwi > ndwi_previous + 0.05:
            water_trend = "Increasing"
    else:
        water_spread = 80
        water_trend = "Stable"

    # ─── ALGAE BLOOM ─────────────────────────────────────────────────
    # High temperature + high humidity + calm water = algae favorable
    algae_score = 0
    if ndvi_on_water is not None and ndvi_on_water > 0.15:
        algae_score += 40  # Satellite directly sees greenish water
    if temp > 32:
        algae_score += 20
    if humidity > 80:
        algae_score += 15
    if rain_7d < 5:  # No rain = no mixing, stratified water = algae
        algae_score += 15
    if water_spread < 70:  # Concentrated, shallow water = more algae
        algae_score += 10

    if algae_score >= 60:
        algae_bloom_risk = "High"
    elif algae_score >= 35:
        algae_bloom_risk = "Moderate"
    else:
        algae_bloom_risk = "Low"

    # ─── HEAT STRESS ─────────────────────────────────────────────────
    # Species-specific thresholds
    heat_thresholds = {
        "Shrimp": (28, 32),
        "Prawn": (27, 31),
        "Fish": (30, 35),
        "Rohu": (30, 35),
        "Catla": (30, 36),
        "Tilapia": (32, 38),
    }
    t_comfort, t_stress = heat_thresholds.get(species, (30, 35))

    if temp >= t_stress:
        heat_stress_risk = "High"
    elif temp >= t_comfort:
        heat_stress_risk = "Moderate"
    else:
        heat_stress_risk = "Low"

    # ─── DISSOLVED OXYGEN ESTIMATE ───────────────────────────────────
    # DO decreases with temperature and algae blooms (nighttime crash)
    # DO increases with wind mixing and rain
    # Species-specific base DO (different stocking densities and management)
    species_base_do = {
        "Shrimp": 7.5,   # Shrimp ponds typically more intensively managed
        "Prawn": 7.8,
        "Fish": 8.5,
        "Rohu": 8.2,
        "Catla": 8.0,
        "Tilapia": 8.8,  # Tilapia tolerates lower DO
        "Catfish": 7.0,
    }
    base_do = species_base_do.get(species, 8.5)
    do = base_do
    do -= (temp - 25) * 0.15  # warm water holds less oxygen
    if algae_bloom_risk == "High":
        do -= 1.8  # algae blooms crash DO at night
    elif algae_bloom_risk == "Moderate":
        do -= 0.8
    wind = weather.get("wind_speed", 10)
    do += min(1.0, wind / 20)  # wind mixing adds oxygen
    if rain_7d > 10:
        do += 0.3  # rain mixes water
    do = round(max(2.0, min(12.0, do)), 1)

    # ─── PH ESTIMATE ─────────────────────────────────────────────────
    # Algae blooms raise pH through photosynthesis
    ph = 7.5
    if algae_bloom_risk == "High":
        ph += 0.8
    elif algae_bloom_risk == "Moderate":
        ph += 0.3
    if rain_7d > 20:
        ph -= 0.2  # rain slightly acidifies
    ph = round(max(5.5, min(9.5, ph)), 1)

    # ─── TEMPERATURE ESTIMATE ────────────────────────────────────────
    # Shallow ponds warm faster than air temperature
    pond_temp = round(temp + 1.5, 1)  # ponds ~1.5°C warmer than air

    # ─── MORTALITY RISK ──────────────────────────────────────────────
    risk_score = 0
    if do < 3:
        risk_score += 50  # critical DO
    elif do < 4:
        risk_score += 30
    elif do < 5:
        risk_score += 15
    if algae_bloom_risk == "High":
        risk_score += 25
    elif algae_bloom_risk == "Moderate":
        risk_score += 10
    if heat_stress_risk == "High":
        risk_score += 20
    elif heat_stress_risk == "Moderate":
        risk_score += 8
    if ph < 6.0 or ph > 9.0:
        risk_score += 15
    elif ph < 6.5 or ph > 8.5:
        risk_score += 5
    if water_trend == "Critically Low":
        risk_score += 15

    if risk_score >= 60:
        mortality_risk = "High"
    elif risk_score >= 30:
        mortality_risk = "Moderate"
    else:
        mortality_risk = "Low"

    return {
        "water_spread_percent": water_spread,
        "water_trend": water_trend,
        "algae_bloom_risk": algae_bloom_risk,
        "heat_stress_risk": heat_stress_risk,
        "mortality_risk": mortality_risk,
        "dissolved_oxygen": do,
        "temperature_celsius": pond_temp,
        "ph_level": ph,
        "risk_score": risk_score,
        "do_score": do,
    }
