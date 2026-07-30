"""
Crop-specific pest and disease risk engine.
Based on the architecture document: each crop has its own pest/disease
models with specific temperature, humidity, rainfall, and crop stage
thresholds. Satellites detect stress signatures; weather + crop stage
determine which pest/disease is most likely causing it.
"""
from datetime import datetime


# ─── CROP-SPECIFIC PEST MODELS ────────────────────────────────────────────────
PEST_MODELS = {
    "Rice": [
        {
            "name": "Brown Plant Hopper",
            "telugu": "గోధుమ మొక్కజొన్న పురుగు",
            "temp_range": (25, 35),
            "humidity_min": 80,
            "rain_favorable": True,
            "standing_water": True,
            "crop_stage_days": (20, 80),
            "ndvi_drop_threshold": 0.05,
            "weight": 1.0,
        },
        {
            "name": "Stem Borer",
            "telugu": "కాండం తొలిచే పురుగు",
            "temp_range": (26, 36),
            "humidity_min": 70,
            "rain_favorable": False,
            "standing_water": False,
            "crop_stage_days": (15, 60),
            "ndvi_drop_threshold": 0.04,
            "weight": 0.9,
        },
        {
            "name": "Leaf Folder",
            "telugu": "ఆకు మడత పురుగు",
            "temp_range": (28, 38),
            "humidity_min": 75,
            "rain_favorable": True,
            "standing_water": False,
            "crop_stage_days": (25, 70),
            "ndvi_drop_threshold": 0.03,
            "weight": 0.8,
        },
    ],
    "Cotton": [
        {
            "name": "Pink Bollworm",
            "telugu": "గులాబీ కాయ తొలిచే పురుగు",
            "temp_range": (27, 38),
            "humidity_min": 60,
            "rain_favorable": False,
            "standing_water": False,
            "crop_stage_days": (60, 150),
            "ndvi_drop_threshold": 0.06,
            "weight": 1.0,
        },
        {
            "name": "Whitefly",
            "telugu": "తెల్ల దోమ",
            "temp_range": (28, 40),
            "humidity_min": 55,
            "rain_favorable": False,
            "standing_water": False,
            "crop_stage_days": (20, 120),
            "ndvi_drop_threshold": 0.04,
            "weight": 0.9,
        },
        {
            "name": "Jassid",
            "telugu": "జాసిడ్",
            "temp_range": (25, 38),
            "humidity_min": 50,
            "rain_favorable": False,
            "standing_water": False,
            "crop_stage_days": (15, 90),
            "ndvi_drop_threshold": 0.03,
            "weight": 0.85,
        },
    ],
    "Chilli": [
        {
            "name": "Thrips",
            "telugu": "తెల్ల పురుగు",
            "temp_range": (25, 35),
            "humidity_min": 55,
            "rain_favorable": False,
            "standing_water": False,
            "crop_stage_days": (20, 90),
            "ndvi_drop_threshold": 0.04,
            "weight": 1.0,
        },
        {
            "name": "Mites",
            "telugu": "పేలు",
            "temp_range": (28, 42),
            "humidity_min": 40,
            "rain_favorable": False,
            "standing_water": False,
            "crop_stage_days": (25, 100),
            "ndvi_drop_threshold": 0.05,
            "weight": 0.9,
        },
    ],
    "Maize": [
        {
            "name": "Fall Armyworm",
            "telugu": "శరద్ కాల సైనిక పురుగు",
            "temp_range": (20, 35),
            "humidity_min": 60,
            "rain_favorable": True,
            "standing_water": False,
            "crop_stage_days": (10, 70),
            "ndvi_drop_threshold": 0.06,
            "weight": 1.0,
        },
    ],
    "Wheat": [
        {
            "name": "Aphid",
            "telugu": "పేలు",
            "temp_range": (15, 28),
            "humidity_min": 65,
            "rain_favorable": False,
            "standing_water": False,
            "crop_stage_days": (30, 90),
            "ndvi_drop_threshold": 0.04,
            "weight": 1.0,
        },
    ],
}

# ─── CROP-SPECIFIC DISEASE MODELS ─────────────────────────────────────────────
DISEASE_MODELS = {
    "Rice": [
        {
            "name": "Rice Blast",
            "telugu": "వరి బ్లాస్ట్",
            "temp_range": (22, 28),
            "humidity_min": 90,
            "rain_required": True,
            "leaf_wetness_hours_min": 6,
            "crop_stage_days": (20, 60),
            "ndvi_drop_threshold": 0.06,
            "ndmi_drop_threshold": 0.04,
            "weight": 1.0,
        },
        {
            "name": "Bacterial Leaf Blight",
            "telugu": "బ్యాక్టీరియల్ లీఫ్ బ్లైట్",
            "temp_range": (25, 34),
            "humidity_min": 85,
            "rain_required": True,
            "leaf_wetness_hours_min": 4,
            "crop_stage_days": (40, 90),
            "ndvi_drop_threshold": 0.05,
            "ndmi_drop_threshold": 0.03,
            "weight": 0.9,
        },
        {
            "name": "Sheath Blight",
            "telugu": "షీత్ బ్లైట్",
            "temp_range": (28, 34),
            "humidity_min": 90,
            "rain_required": True,
            "leaf_wetness_hours_min": 8,
            "crop_stage_days": (45, 85),
            "ndvi_drop_threshold": 0.07,
            "ndmi_drop_threshold": 0.05,
            "weight": 0.85,
        },
    ],
    "Cotton": [
        {
            "name": "Leaf Curl Virus",
            "telugu": "ఆకు మురి వైరస్",
            "temp_range": (26, 36),
            "humidity_min": 60,
            "rain_required": False,
            "leaf_wetness_hours_min": 0,
            "crop_stage_days": (20, 80),
            "ndvi_drop_threshold": 0.06,
            "ndmi_drop_threshold": 0.04,
            "weight": 1.0,
        },
        {
            "name": "Alternaria Leaf Spot",
            "telugu": "ఆల్టర్నేరియా ఆకు మచ్చ",
            "temp_range": (24, 30),
            "humidity_min": 80,
            "rain_required": True,
            "leaf_wetness_hours_min": 5,
            "crop_stage_days": (40, 120),
            "ndvi_drop_threshold": 0.05,
            "ndmi_drop_threshold": 0.03,
            "weight": 0.85,
        },
    ],
    "Chilli": [
        {
            "name": "Anthracnose",
            "telugu": "యాంత్రాక్నోస్",
            "temp_range": (22, 30),
            "humidity_min": 85,
            "rain_required": True,
            "leaf_wetness_hours_min": 6,
            "crop_stage_days": (50, 120),
            "ndvi_drop_threshold": 0.06,
            "ndmi_drop_threshold": 0.04,
            "weight": 1.0,
        },
        {
            "name": "Powdery Mildew",
            "telugu": "పొడి తెగులు",
            "temp_range": (20, 28),
            "humidity_min": 70,
            "rain_required": False,
            "leaf_wetness_hours_min": 2,
            "crop_stage_days": (30, 100),
            "ndvi_drop_threshold": 0.04,
            "ndmi_drop_threshold": 0.03,
            "weight": 0.85,
        },
    ],
    "Maize": [
        {
            "name": "Northern Leaf Blight",
            "telugu": "ఉత్తర ఆకు బ్లైట్",
            "temp_range": (18, 27),
            "humidity_min": 85,
            "rain_required": True,
            "leaf_wetness_hours_min": 6,
            "crop_stage_days": (30, 80),
            "ndvi_drop_threshold": 0.07,
            "ndmi_drop_threshold": 0.05,
            "weight": 1.0,
        },
    ],
    "Wheat": [
        {
            "name": "Yellow Rust",
            "telugu": "పసుపు తుప్పు",
            "temp_range": (10, 20),
            "humidity_min": 90,
            "rain_required": True,
            "leaf_wetness_hours_min": 4,
            "crop_stage_days": (40, 90),
            "ndvi_drop_threshold": 0.05,
            "ndmi_drop_threshold": 0.04,
            "weight": 1.0,
        },
    ],
}

DEFAULT_PESTS = [
    {"name": "General Insect Pest", "telugu": "సాధారణ పురుగు",
     "temp_range": (25, 38), "humidity_min": 60, "rain_favorable": False,
     "standing_water": False, "crop_stage_days": (0, 180),
     "ndvi_drop_threshold": 0.05, "weight": 0.7},
]
DEFAULT_DISEASES = [
    {"name": "General Fungal Disease", "telugu": "సాధారణ శిలీంధ్రం",
     "temp_range": (20, 32), "humidity_min": 75, "rain_required": True,
     "leaf_wetness_hours_min": 4, "crop_stage_days": (0, 180),
     "ndvi_drop_threshold": 0.05, "ndmi_drop_threshold": 0.03, "weight": 0.7},
]


def _crop_age_days(sowing_date_str: str) -> int:
    try:
        sowing = datetime.strptime(sowing_date_str[:10], "%Y-%m-%d").date()
        return (datetime.utcnow().date() - sowing).days
    except Exception:
        return 45  # assume mid-season


def calculate_pest_risk(
    crop_type: str,
    sowing_date: str,
    ndvi_current: float,
    ndvi_previous: float,
    weather: dict,
    waterlogging_severity: str,
) -> dict:
    """
    Returns pest risk score (0-100), level, top pest name, and recommendation.
    """
    pests = PEST_MODELS.get(crop_type, DEFAULT_PESTS)
    crop_age = _crop_age_days(sowing_date)
    ndvi_drop = max(0, (ndvi_previous or ndvi_current) - ndvi_current)

    temp = weather.get("temperature", 30)
    humidity = weather.get("humidity", 65)
    rain_3d = weather.get("rainfall_3d", 0)
    has_standing_water = waterlogging_severity in ("Moderate", "Severe")

    best_score = 0
    top_pest = None

    for pest in pests:
        score = 0
        t_min, t_max = pest["temp_range"]

        # Temperature suitability (0-25 points)
        if t_min <= temp <= t_max:
            score += 25
        elif temp < t_min:
            score += max(0, 25 - (t_min - temp) * 3)
        else:
            score += max(0, 25 - (temp - t_max) * 3)

        # Humidity suitability (0-20 points)
        if humidity >= pest["humidity_min"]:
            score += 20
        else:
            score += max(0, 20 - (pest["humidity_min"] - humidity) * 0.4)

        # Rainfall (0-15 points)
        if pest["rain_favorable"] and rain_3d > 5:
            score += 15
        elif not pest["rain_favorable"] and rain_3d < 2:
            score += 15
        elif pest["rain_favorable"] and rain_3d > 0:
            score += 8

        # Standing water (0-10 points)
        if pest.get("standing_water") and has_standing_water:
            score += 10
        elif not pest.get("standing_water") and not has_standing_water:
            score += 5

        # NDVI drop (satellite stress signature, 0-20 points)
        threshold = pest["ndvi_drop_threshold"]
        if ndvi_drop >= threshold:
            score += 20
        elif ndvi_drop > 0:
            score += int((ndvi_drop / threshold) * 20)

        # Crop stage (0-10 points)
        s_min, s_max = pest["crop_stage_days"]
        if s_min <= crop_age <= s_max:
            score += 10
        else:
            score += 0

        weighted = score * pest["weight"]
        if weighted > best_score:
            best_score = weighted
            top_pest = pest

    risk_percent = min(100, int(best_score))

    if risk_percent >= 70:
        level = "High"
        recommendation = (
            f"High risk of {top_pest['name']} ({top_pest['telugu']}). "
            "Inspect your field within 48 hours. "
            "Consider targeted spray if infestation is confirmed."
        )
    elif risk_percent >= 40:
        level = "Moderate"
        recommendation = (
            f"Moderate risk of {top_pest['name']} ({top_pest['telugu']}). "
            "Monitor closely over the next week. "
            "Check crop edges and low-lying areas first."
        )
    else:
        level = "Low"
        recommendation = "Pest risk is currently low. Continue routine monitoring."

    return {
        "pest_risk_percent": risk_percent,
        "pest_risk_level": level,
        "top_pest_name": top_pest["name"] if top_pest else "None",
        "top_pest_telugu": top_pest["telugu"] if top_pest else "",
        "pest_recommendation": recommendation,
        "crop_age_days": crop_age,
    }


def calculate_disease_risk(
    crop_type: str,
    sowing_date: str,
    ndvi_current: float,
    ndvi_previous: float,
    ndmi_current: float,
    ndmi_previous: float,
    weather: dict,
) -> dict:
    """
    Returns disease risk score (0-100), level, top disease name, and recommendation.
    """
    diseases = DISEASE_MODELS.get(crop_type, DEFAULT_DISEASES)
    crop_age = _crop_age_days(sowing_date)

    ndvi_drop = max(0, (ndvi_previous or ndvi_current) - ndvi_current)
    ndmi_drop = max(0, (ndmi_previous or ndmi_current) - ndmi_current)

    temp = weather.get("temperature", 30)
    humidity = weather.get("humidity", 65)
    rain_3d = weather.get("rainfall_3d", 0)
    leaf_wetness = weather.get("leaf_wetness_hours", 0)

    best_score = 0
    top_disease = None

    for disease in diseases:
        score = 0
        t_min, t_max = disease["temp_range"]

        # Temperature (0-20 points)
        if t_min <= temp <= t_max:
            score += 20
        elif temp < t_min:
            score += max(0, 20 - (t_min - temp) * 3)
        else:
            score += max(0, 20 - (temp - t_max) * 3)

        # Humidity (0-20 points)
        if humidity >= disease["humidity_min"]:
            score += 20
        else:
            score += max(0, 20 - (disease["humidity_min"] - humidity) * 0.5)

        # Rainfall (0-15 points)
        if disease["rain_required"] and rain_3d > 3:
            score += 15
        elif disease["rain_required"] and rain_3d > 0:
            score += 8
        elif not disease["rain_required"]:
            score += 10

        # Leaf wetness (0-15 points) — key disease trigger
        req_lw = disease["leaf_wetness_hours_min"]
        if req_lw == 0:
            score += 10
        elif leaf_wetness >= req_lw:
            score += 15
        elif leaf_wetness > 0:
            score += int((leaf_wetness / req_lw) * 15)

        # NDVI drop (0-15 points)
        if ndvi_drop >= disease["ndvi_drop_threshold"]:
            score += 15
        elif ndvi_drop > 0:
            score += int((ndvi_drop / disease["ndvi_drop_threshold"]) * 15)

        # NDMI drop — moisture stress (0-10 points)
        if ndmi_drop >= disease.get("ndmi_drop_threshold", 0.04):
            score += 10
        elif ndmi_drop > 0:
            score += int((ndmi_drop / max(disease.get("ndmi_drop_threshold", 0.04), 0.01)) * 10)

        # Crop stage (0-5 points)
        s_min, s_max = disease["crop_stage_days"]
        if s_min <= crop_age <= s_max:
            score += 5

        weighted = score * disease["weight"]
        if weighted > best_score:
            best_score = weighted
            top_disease = disease

    risk_percent = min(100, int(best_score))

    if risk_percent >= 70:
        level = "High"
        elevated = True
        recommendation = (
            f"High risk of {top_disease['name']} ({top_disease['telugu']}). "
            "Weather conditions are highly favorable for infection. "
            "Inspect leaf surfaces within 24-48 hours. "
            "Consider preventive fungicide application."
        )
    elif risk_percent >= 40:
        level = "Moderate"
        elevated = True
        recommendation = (
            f"Moderate risk of {top_disease['name']} ({top_disease['telugu']}). "
            "Monitor leaf surfaces for early symptoms. "
            "Ensure good field drainage and airflow."
        )
    else:
        level = "Low"
        elevated = False
        recommendation = "Disease risk is currently low. No immediate action required."

    return {
        "disease_risk_level": level,
        "disease_risk_elevated": elevated,
        "disease_risk_percent": risk_percent,
        "top_disease_name": top_disease["name"] if top_disease else "None",
        "top_disease_telugu": top_disease["telugu"] if top_disease else "",
        "disease_risk_notes": recommendation,
    }


def calculate_water_stress(
    ndwi_current: float,
    ndwi_previous: float,
    ndmi_current: float,
    weather: dict,
) -> dict:
    """
    Water stress from NDWI (canopy water), NDMI (moisture), ET0, and rainfall.
    """
    rain_7d = weather.get("rainfall_7d", 0)
    et0 = weather.get("et0", 4.5)
    humidity = weather.get("humidity", 65)
    temp = weather.get("temperature", 30)

    # Aridity Index (rainfall vs evaporation demand)
    aridity = rain_7d / (et0 * 7 + 0.001)

    score = 0

    # NDWI (0-35 points) — plant canopy water content
    if ndwi_current < -0.15:
        score += 35
    elif ndwi_current < -0.05:
        score += 20
    elif ndwi_current < 0.05:
        score += 10
    else:
        score += 0  # Well-watered

    # NDMI (0-25 points) — soil/canopy moisture
    if ndmi_current < 0.0:
        score += 25
    elif ndmi_current < 0.1:
        score += 15
    elif ndmi_current < 0.2:
        score += 5

    # Aridity (0-20 points)
    if aridity < 0.3:
        score += 20
    elif aridity < 0.6:
        score += 12
    elif aridity < 1.0:
        score += 5

    # Temperature heat load (0-10 points)
    if temp > 38:
        score += 10
    elif temp > 33:
        score += 5

    # Low humidity (0-10 points)
    if humidity < 40:
        score += 10
    elif humidity < 60:
        score += 5

    score = min(100, score)

    if score >= 65:
        level = "High"
        confidence = 87
        recommendation = "Irrigate within 24-48 hours to prevent yield loss."
    elif score >= 35:
        level = "Moderate"
        confidence = 78
        recommendation = "Monitor soil moisture closely. Irrigate if no rain in next 3 days."
    else:
        level = "Low"
        confidence = 82
        recommendation = "Water levels appear adequate. Continue routine irrigation schedule."

    return {
        "water_stress_level": level,
        "water_stress_score": score,
        "water_stress_confidence": confidence,
        "water_stress_recommendation": recommendation,
        "aridity_index": round(aridity, 3),
    }
