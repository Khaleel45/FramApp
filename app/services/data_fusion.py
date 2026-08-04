"""
Multi-satellite data fusion engine.
Automatically selects the best available data source for each farm scan.

Priority order:
1. Sentinel-2 (NDVI + NDWI + NDMI at 10m) — best quality
2. MODIS (NDVI at 250m, daily) — good fallback, lower resolution
3. Sentinel-1 (soil moisture via radar) — always available, different data
4. Weather-only (Open-Meteo) — always available, no satellite at all

The fusion engine combines whatever is available to produce the most
accurate health score possible, and always reports which sources
were used so the farmer understands the confidence level.
"""
from datetime import datetime
import math


def fuse_data_sources(
    sentinel2_indices: dict,
    sentinel1_moisture: dict,
    modis_ndvi: dict,
    weather: dict,
    crop_type: str,
    sowing_date: str,
    farm_name: str,
) -> dict:
    """
    Combines all available satellite + weather data into a single
    consistent set of farm health metrics.

    Returns:
    - health_score: 0-100
    - health_status: text description
    - ndvi: best available NDVI value
    - water_stress_level: from S2 NDWI + S1 moisture + weather
    - data_sources: list of which sources contributed
    - confidence: overall confidence level
    - data_quality: 'satellite' | 'modis' | 'radar_only' | 'weather_only'
    """
    from app.services.crop_analysis import ndvi_to_health_score, ndvi_to_health_status
    from app.services.crop_risk_engine import calculate_water_stress

    sources_used = []
    ndvi_value = None
    ndvi_source = None
    ndwi_value = None
    ndmi_value = None
    soil_moisture = None
    waterlogging = False

    # ─── Step 1: Best NDVI source ────────────────────────────────────
    s2_ndvi = sentinel2_indices.get("ndvi", {})
    if s2_ndvi.get("available"):
        ndvi_value = s2_ndvi["current"]
        ndvi_previous = s2_ndvi.get("previous", ndvi_value)
        ndvi_source = "Sentinel-2 (10m)"
        sources_used.append("Sentinel-2")
        confidence = 92
        data_quality = "satellite"
    elif modis_ndvi.get("available"):
        ndvi_value = modis_ndvi["ndvi"]
        ndvi_previous = ndvi_value  # No trend from MODIS single point
        ndvi_source = "MODIS (250m daily)"
        sources_used.append("MODIS")
        confidence = 72
        data_quality = "modis"
    else:
        ndvi_value = None
        ndvi_previous = None
        ndvi_source = None
        confidence = 55
        data_quality = "radar_only" if sentinel1_moisture.get("available") else "weather_only"

    # ─── Step 2: Water data (S2 NDWI + S1 moisture) ──────────────────
    s2_ndwi = sentinel2_indices.get("ndwi", {})
    s2_ndmi = sentinel2_indices.get("ndmi", {})

    if s2_ndwi.get("available"):
        ndwi_value = s2_ndwi["current"]
        ndwi_previous = s2_ndwi.get("previous", ndwi_value)
        sources_used.append("S2-Water")
    else:
        ndwi_value = None
        ndwi_previous = None

    if s2_ndmi.get("available"):
        ndmi_value = s2_ndmi["current"]
        ndmi_previous = s2_ndmi.get("previous", ndmi_value)
    else:
        ndmi_value = None
        ndmi_previous = None

    # Sentinel-1 soil moisture
    if sentinel1_moisture.get("available"):
        soil_moisture = sentinel1_moisture.get("soil_moisture_level", "Moderate")
        waterlogging = sentinel1_moisture.get("waterlogging_detected", False)
        if "Sentinel-1" not in sources_used:
            sources_used.append("Sentinel-1")

        # S1 can fill in NDWI when S2 unavailable
        if ndwi_value is None:
            # Convert S1 moisture to approximate NDWI equivalent
            moisture_to_ndwi = {
                "Very High": 0.3,
                "High": 0.1,
                "Moderate": -0.05,
                "Low": -0.15,
                "Very Low": -0.25,
            }
            ndwi_value = moisture_to_ndwi.get(soil_moisture, -0.05)
            ndwi_previous = ndwi_value
            data_quality = "radar_only" if ndvi_value is None else data_quality

    if "Open-Meteo" not in sources_used and weather.get("available"):
        sources_used.append("Open-Meteo")

    # ─── Step 3: Health score ─────────────────────────────────────────
    if ndvi_value is not None:
        health_score = ndvi_to_health_score(ndvi_value)
        health_status = ndvi_to_health_status(ndvi_value)
    else:
        # Weather-based estimate when no NDVI at all
        # Penalise based on risk conditions
        base = 75
        temp = weather.get("temperature", 30)
        humidity = weather.get("humidity", 65)
        rain_7d = weather.get("rainfall_7d", 0)

        # Penalise extreme conditions
        if temp > 40:
            base -= 15
        elif temp > 36:
            base -= 8

        if rain_7d > 80:  # Waterlogging risk
            base -= 10
        elif rain_7d < 5 and temp > 33:  # Drought stress
            base -= 12

        if waterlogging:
            base -= 10

        health_score = max(30, int(base))
        health_status = (
            "Good (Weather Estimate)" if health_score >= 70
            else "Needs Attention (Weather Estimate)" if health_score >= 50
            else "Critical (Weather Estimate)"
        )
        data_quality = "weather_only"
        confidence = max(40, confidence)

    # ─── Step 4: Water stress using best available water data ─────────
    ndwi_c = ndwi_value if ndwi_value is not None else -0.05
    ndwi_p = ndwi_previous if ndwi_previous is not None else ndwi_c
    ndmi_c = ndmi_value if ndmi_value is not None else 0.1
    ndmi_p = ndmi_previous if ndmi_previous is not None else ndmi_c

    water_result = calculate_water_stress(ndwi_c, ndwi_p, ndmi_c, weather)

    # Override with S1 if it shows a different picture
    if sentinel1_moisture.get("available"):
        s1_moisture = sentinel1_moisture["soil_moisture_level"]
        if s1_moisture in ("Very High", "High") and waterlogging:
            water_result["water_stress_level"] = "Low"  # Paradox: waterlogged = not drought stressed
            water_result["waterlogging"] = True
        elif s1_moisture in ("Very Low", "Low"):
            # S1 confirms dry soil — override weather estimate if needed
            if water_result["water_stress_level"] == "Low":
                water_result["water_stress_level"] = "Moderate"

    # ─── Step 5: Build confidence label ──────────────────────────────
    if len(sources_used) >= 3:
        confidence = min(confidence + 10, 95)
    elif len(sources_used) == 2:
        confidence = min(confidence + 5, 88)

    confidence_label = (
        "High" if confidence >= 80
        else "Moderate" if confidence >= 60
        else "Low"
    )

    quality_labels = {
        "satellite": "Sentinel-2 satellite (10m resolution)",
        "modis": "MODIS satellite (250m daily)",
        "radar_only": "Sentinel-1 radar + weather (clouds blocking optical)",
        "weather_only": "Weather estimate only (no satellite pass)",
    }

    return {
        "health_score": health_score,
        "health_status": health_status,
        "ndvi": ndvi_value,
        "ndvi_previous": ndvi_previous,
        "ndvi_source": ndvi_source,
        "ndwi": ndwi_c,
        "ndmi": ndmi_c,
        "water_stress_level": water_result["water_stress_level"],
        "water_stress_confidence": water_result.get("water_stress_confidence", 70),
        "waterlogging_detected": waterlogging or water_result.get("waterlogging", False),
        "soil_moisture_level": soil_moisture,
        "sources_used": sources_used,
        "data_quality": data_quality,
        "data_quality_label": quality_labels[data_quality],
        "confidence": confidence,
        "confidence_label": confidence_label,
        "scan_date": datetime.utcnow().strftime("%Y-%m-%d"),
    }
