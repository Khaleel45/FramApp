"""
Translates raw satellite indices into health scores and
coordinates the full risk calculation pipeline.
"""
from datetime import datetime


def ndvi_to_health_score(ndvi: float) -> int:
    if ndvi is None:
        return 70
    clamped = max(0.0, min(1.0, ndvi))
    score = int(round(clamped * 110))
    return max(10, min(100, score))


def ndvi_to_health_status(ndvi: float) -> str:
    if ndvi is None:
        return "Awaiting Scan"
    if ndvi >= 0.7: return "Excellent"
    if ndvi >= 0.5: return "Good"
    if ndvi >= 0.3: return "Needs Attention"
    return "Critical"


def ndwi_to_water_stress(ndwi: float) -> tuple[str, int]:
    if ndwi is None:
        return "Unknown", 0
    if ndwi < -0.1: return "High", 88
    if ndwi < 0.05: return "Moderate", 80
    return "Low", 85


def detect_waterlogging(ndwi: float) -> tuple[str, str]:
    if ndwi is None:
        return "None", ""
    if ndwi > 0.25:
        return "Severe", "NDWI unusually high — possible standing water."
    if ndwi > 0.15:
        return "Moderate", "Elevated soil moisture, monitor drainage."
    return "None", ""


def build_full_update(
    indices: dict,
    weather: dict,
    pest_result: dict,
    disease_result: dict,
    water_result: dict,
) -> dict:
    """
    Combines all pipeline outputs into a single dict of farm fields
    ready to write to the database.
    """
    updates = {}
    today = datetime.utcnow().strftime("%Y-%m-%d")

    ndvi = indices.get("ndvi", {})
    ndwi = indices.get("ndwi", {})

    if ndvi.get("available"):
        ndvi_val = ndvi["current"]
        updates["health_score"] = ndvi_to_health_score(ndvi_val)
        updates["health_status"] = ndvi_to_health_status(ndvi_val)
        updates["last_scan_date"] = ndvi.get("date", today)

    if water_result:
        updates["water_stress_level"] = water_result.get("water_stress_level", "Low")
        updates["water_stress_confidence"] = water_result.get("water_stress_confidence", 75)
        updates["water_stress_area"] = water_result.get("water_stress_recommendation", "")

    if ndwi.get("available"):
        sev, note = detect_waterlogging(ndwi["current"])
        updates["waterlogging_severity"] = sev
        if note:
            updates["waterlogging_area"] = note

    if pest_result:
        updates["pest_risk_percent"] = pest_result.get("pest_risk_percent", 0)
        updates["pest_confidence"] = pest_result.get("pest_risk_percent", 0)
        top = pest_result.get("top_pest_name", "")
        updates["pest_hotspots"] = [top] if top and top != "None" else []

    if disease_result:
        updates["disease_risk_level"] = disease_result.get("disease_risk_level", "Low")
        updates["disease_risk_elevated"] = disease_result.get("disease_risk_elevated", False)
        updates["disease_risk_notes"] = disease_result.get("disease_risk_notes", "")

    return updates
