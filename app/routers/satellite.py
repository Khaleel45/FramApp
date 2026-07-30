"""
Satellite scan with zone-level analysis.
Falls back gracefully when Sentinel data is unavailable (clouds, no polygon).
"""
import traceback
import random
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Farm
from app.services import crop_analysis
from app.services.sentinel_auth import is_configured, SentinelAuthError
from app.services.weather_service import get_weather_for_farm
from app.services.crop_risk_engine import (
    calculate_pest_risk, calculate_disease_risk, calculate_water_stress
)
from app.services.zone_splitter import split_into_zones, aggregate_zone_results

router = APIRouter(prefix="/satellite", tags=["satellite"])


@router.get("/status")
def satellite_status():
    return {
        "sentinel_configured": is_configured(),
        "message": (
            "Ready to scan farms."
            if is_configured()
            else "Add SENTINEL_CLIENT_ID and SENTINEL_CLIENT_SECRET in Railway Variables."
        ),
    }


def _make_bbox_polygon(lat: float, lng: float, area_acres: float) -> list:
    """
    Creates a bounding box polygon from a center point and area.
    Used when farm has no drawn boundary or polygon is too small.
    """
    # Approximate degrees per acre at India's latitude
    delta = (area_acres ** 0.5) * 0.003
    return [
        {"lat": lat - delta, "lng": lng - delta},
        {"lat": lat + delta, "lng": lng - delta},
        {"lat": lat + delta, "lng": lng + delta},
        {"lat": lat - delta, "lng": lng + delta},
    ]


def _scan_with_sentinel(polygon: list, weather: dict, crop_type: str,
                         sowing_date: str, waterlogging: str) -> dict:
    """Attempts Sentinel scan, returns None indices if unavailable."""
    try:
        from app.services import sentinel_client
        indices = sentinel_client.get_all_indices(polygon)
        return indices
    except Exception as e:
        print(f"Sentinel scan error: {e}")
        return {
            "ndvi": {"available": False, "reason": str(e), "current": None, "previous": None},
            "ndwi": {"available": False, "reason": str(e), "current": None, "previous": None},
            "ndmi": {"available": False, "reason": str(e), "current": None, "previous": None},
        }


def _run_risk_models(ndvi_current, ndvi_previous, ndwi_current, ndwi_previous,
                     ndmi_current, ndmi_previous, weather, crop_type,
                     sowing_date, waterlogging):
    """Runs all risk models with satellite or fallback values."""
    ndvi_c = ndvi_current if ndvi_current is not None else 0.5
    ndvi_p = ndvi_previous if ndvi_previous is not None else ndvi_c
    ndwi_c = ndwi_current if ndwi_current is not None else -0.05
    ndwi_p = ndwi_previous if ndwi_previous is not None else ndwi_c
    ndmi_c = ndmi_current if ndmi_current is not None else 0.1
    ndmi_p = ndmi_previous if ndmi_previous is not None else ndmi_c

    pest = calculate_pest_risk(crop_type, sowing_date, ndvi_c, ndvi_p, weather, waterlogging)
    disease = calculate_disease_risk(crop_type, sowing_date, ndvi_c, ndvi_p, ndmi_c, ndmi_p, weather)
    water = calculate_water_stress(ndwi_c, ndwi_p, ndmi_c, weather)

    return pest, disease, water


@router.post("/scan/{farm_id}")
def scan_farm(farm_id: str, device_id: str, db: Session = Depends(get_db)):
    if not is_configured():
        raise HTTPException(status_code=503,
            detail="Sentinel Hub credentials not set in Railway Variables.")

    farm = db.query(Farm).filter(
        Farm.id == farm_id, Farm.device_id == device_id
    ).first()
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")

    try:
        # Step 1: Weather always runs — free, no credentials needed
        weather = get_weather_for_farm(farm.latitude, farm.longitude)
        print(f"Weather for {farm.name}: {weather['temperature']}°C, "
              f"{weather['humidity']}% RH, available={weather['available']}")

        # Step 2: Use drawn polygon or generate bbox from center
        polygon = farm.gps_polygon
        using_bbox = False
        if not polygon or len(polygon) < 3:
            polygon = _make_bbox_polygon(
                farm.latitude, farm.longitude, farm.area_acres or 2.0
            )
            using_bbox = True
            print(f"No polygon for {farm.name}, using center bbox")

        # Step 3: Zone splitting
        zones = split_into_zones(polygon, farm.area_acres or 2.0)
        print(f"Split {farm.name} into {len(zones)} zones")

        # Step 4: Full farm Sentinel scan
        indices = _scan_with_sentinel(
            polygon, weather,
            farm.crop_type or "Rice",
            farm.sowing_date or str(datetime.utcnow().date()),
            farm.waterlogging_severity or "None",
        )

        ndvi = indices.get("ndvi", {})
        ndwi = indices.get("ndwi", {})
        ndmi = indices.get("ndmi", {})

        sentinel_available = ndvi.get("available", False)
        print(f"Sentinel data available: {sentinel_available}")

        # Step 5: Zone-level analysis
        zone_results = []
        if sentinel_available and not using_bbox and len(zones) > 1:
            # Scan each zone individually with Sentinel
            from app.services import sentinel_client
            for zone in zones:
                try:
                    zone_indices = sentinel_client.get_all_indices(zone["polygon"])
                    z_ndvi = zone_indices.get("ndvi", {})
                    z_ndwi = zone_indices.get("ndwi", {})
                    z_ndmi = zone_indices.get("ndmi", {})

                    z_pest, z_disease, z_water = _run_risk_models(
                        z_ndvi.get("current"), z_ndvi.get("previous"),
                        z_ndwi.get("current"), z_ndwi.get("previous"),
                        z_ndmi.get("current"), z_ndmi.get("previous"),
                        weather, farm.crop_type or "Rice",
                        farm.sowing_date or str(datetime.utcnow().date()),
                        farm.waterlogging_severity or "None",
                    )

                    zone_results.append({
                        "zone_name": zone["name"],
                        "area_acres": zone["area_acres"],
                        "ndvi_available": z_ndvi.get("available", False),
                        "ndvi": z_ndvi.get("current", ndvi.get("current", 0.5)),
                        "pest_risk_percent": z_pest["pest_risk_percent"],
                        "disease_risk_level": z_disease["disease_risk_level"],
                        "water_stress_level": z_water["water_stress_level"],
                    })
                except Exception as e:
                    zone_results.append({
                        "zone_name": zone["name"],
                        "area_acres": zone["area_acres"],
                        "ndvi_available": False,
                        "ndvi": ndvi.get("current", 0.5),
                        "pest_risk_percent": 0,
                        "disease_risk_level": "Low",
                        "water_stress_level": "Low",
                    })
        else:
            # Single zone result from full farm scan
            # (no polygon, clouds, or only 1 zone)
            zone_results = [{
                "zone_name": "Full Farm",
                "area_acres": farm.area_acres or 2.0,
                "ndvi_available": sentinel_available,
                "ndvi": ndvi.get("current", 0.5),
                "pest_risk_percent": 0,
                "disease_risk_level": "Low",
                "water_stress_level": "Low",
            }]

        # Step 6: Risk models on full farm indices
        pest, disease, water = _run_risk_models(
            ndvi.get("current"), ndvi.get("previous"),
            ndwi.get("current"), ndwi.get("previous"),
            ndmi.get("current"), ndmi.get("previous"),
            weather, farm.crop_type or "Rice",
            farm.sowing_date or str(datetime.utcnow().date()),
            farm.waterlogging_severity or "None",
        )

        # Step 7: Aggregate zone results
        aggregated = aggregate_zone_results(zone_results, farm.name)

        # Step 8: Waterlogging detection
        wl_sev, wl_note = crop_analysis.detect_waterlogging(ndwi.get("current"))

        # Step 9: Build health score
        if sentinel_available:
            health_score = crop_analysis.ndvi_to_health_score(ndvi["current"])
            health_status = crop_analysis.ndvi_to_health_status(ndvi["current"])
        else:
            # Weather-based health estimate
            health_score = aggregated.get("health_score", farm.health_score)
            health_status = aggregated.get("health_status", farm.health_status)

        hotspots = aggregated.get("hotspot_zones", [])

        # Step 10: Save to DB
        farm.health_score = health_score
        farm.health_status = health_status
        farm.water_stress_level = water["water_stress_level"]
        farm.water_stress_confidence = water["water_stress_confidence"]
        farm.water_stress_area = water.get("water_stress_recommendation", "")
        farm.waterlogging_severity = wl_sev
        farm.pest_risk_percent = pest["pest_risk_percent"]
        farm.pest_hotspots = [z["zone_name"] for z in hotspots] if hotspots else []
        farm.disease_risk_level = disease["disease_risk_level"]
        farm.disease_risk_elevated = disease["disease_risk_elevated"]
        farm.disease_risk_notes = (
            aggregated.get("summary") or disease["disease_risk_notes"]
        )
        farm.last_scan_date = str(datetime.utcnow().date())

        db.commit()
        db.refresh(farm)

        zone_count = len(zone_results)
        zones_with_data = sum(1 for z in zone_results if z.get("ndvi_available"))

        return {
            "success": True,
            "farm_id": farm.id,
            "farm_name": farm.name,
            "health_score": farm.health_score,
            "health_status": farm.health_status,
            "water_stress_level": farm.water_stress_level,
            "waterlogging_severity": farm.waterlogging_severity,
            "pest_risk_percent": farm.pest_risk_percent,
            "disease_risk_level": farm.disease_risk_level,
            "disease_risk_notes": farm.disease_risk_notes,
            "last_scan_date": farm.last_scan_date,
            "ndvi": ndvi,
            "ndwi": ndwi,
            "sentinel_available": sentinel_available,
            "used_bbox": using_bbox,
            "zone_analysis": {
                "zone_count": zone_count,
                "zones_scanned": zones_with_data,
                "hotspot_zones": hotspots,
                "zone_alerts": aggregated.get("zone_alerts", []),
                "summary": aggregated.get("summary", ""),
                "ndvi_average": aggregated.get("ndvi_average"),
            },
            "weather": {
                "temperature": weather.get("temperature"),
                "humidity": weather.get("humidity"),
                "rainfall_7d": weather.get("rainfall_7d"),
                "leaf_wetness_hours": weather.get("leaf_wetness_hours"),
                "weather_available": weather.get("available", False),
            },
        }

    except SentinelAuthError as e:
        raise HTTPException(status_code=401, detail=f"Sentinel auth failed: {e}")
    except Exception as e:
        print(f"Scan error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Scan error: {str(e)}")


@router.post("/scan-all")
def scan_all_farms(device_id: str, db: Session = Depends(get_db)):
    if not is_configured():
        raise HTTPException(status_code=503, detail="Sentinel credentials not set.")
    farms = db.query(Farm).filter(Farm.device_id == device_id).all()
    results = []
    for farm in farms:
        polygon = farm.gps_polygon
        if not polygon or len(polygon) < 3:
            polygon = _make_bbox_polygon(farm.latitude, farm.longitude, farm.area_acres or 2.0)
        zones = split_into_zones(polygon, farm.area_acres or 2.0)
        results.append({"farm_id": farm.id, "name": farm.name, "zones": len(zones)})
    return {"scanned": len(results), "results": results}


@router.post("/test-scan/{farm_id}")
def test_scan(farm_id: str, device_id: str, db: Session = Depends(get_db)):
    """Test with fake satellite + real weather + real zone splitting."""
    farm = db.query(Farm).filter(
        Farm.id == farm_id, Farm.device_id == device_id
    ).first()
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")

    weather = get_weather_for_farm(farm.latitude, farm.longitude)

    polygon = farm.gps_polygon
    if not polygon or len(polygon) < 3:
        polygon = _make_bbox_polygon(farm.latitude, farm.longitude, farm.area_acres or 2.0)

    zones = split_into_zones(polygon, farm.area_acres or 2.0)
    if not zones:
        zones = [{"name": "Full Farm", "area_acres": farm.area_acres or 2.0}]

    base_ndvi = round(random.uniform(0.45, 0.72), 3)
    stressed_zones = random.sample(range(len(zones)), k=max(1, len(zones) // 4))

    zone_results = []
    for i, zone in enumerate(zones):
        ndvi = round(base_ndvi - random.uniform(0.15, 0.28), 3) if i in stressed_zones \
               else round(base_ndvi + random.uniform(-0.05, 0.08), 3)
        ndvi = max(0.1, min(0.9, ndvi))
        ndvi_prev = round(ndvi + random.uniform(0.02, 0.10), 3)
        ndwi = round(random.uniform(-0.15, 0.10), 3)
        ndmi = round(random.uniform(0.05, 0.25), 3)

        pest, disease, water = _run_risk_models(
            ndvi, ndvi_prev, ndwi, ndwi - 0.03, ndmi, ndmi + 0.05,
            weather, farm.crop_type or "Rice",
            farm.sowing_date or str(datetime.utcnow().date()),
            "None",
        )
        zone_results.append({
            "zone_name": zone["name"],
            "area_acres": zone.get("area_acres", 2.0),
            "ndvi_available": True,
            "ndvi": ndvi,
            "pest_risk_percent": pest["pest_risk_percent"],
            "top_pest": pest.get("top_pest_name", ""),
            "disease_risk_level": disease["disease_risk_level"],
            "water_stress_level": water["water_stress_level"],
        })

    aggregated = aggregate_zone_results(zone_results, farm.name)
    hotspots = aggregated.get("hotspot_zones", [])
    max_pest = max(zone_results, key=lambda z: z.get("pest_risk_percent", 0))

    farm.health_score = aggregated.get("health_score", 70)
    farm.health_status = aggregated.get("health_status", "Good")
    farm.pest_risk_percent = max_pest.get("pest_risk_percent", 0)
    farm.pest_hotspots = [z["zone_name"] for z in hotspots]
    farm.disease_risk_level = max_pest.get("disease_risk_level", "Low")
    farm.disease_risk_elevated = len(hotspots) > 0
    farm.disease_risk_notes = aggregated.get("summary", "")
    farm.last_scan_date = f"TEST-{datetime.utcnow().strftime('%Y-%m-%d')}"
    db.commit()
    db.refresh(farm)

    return {
        "success": True,
        "test": True,
        "farm_id": farm.id,
        "farm_name": farm.name,
        "health_score": farm.health_score,
        "health_status": farm.health_status,
        "pest_risk_percent": farm.pest_risk_percent,
        "disease_risk_level": farm.disease_risk_level,
        "disease_risk_notes": farm.disease_risk_notes,
        "last_scan_date": farm.last_scan_date,
        "zone_analysis": {
            "zone_count": len(zone_results),
            "zones_scanned": len(zone_results),
            "hotspot_zones": hotspots,
            "zone_alerts": aggregated.get("zone_alerts", []),
            "summary": aggregated.get("summary", ""),
        },
        "weather": weather,
        "note": f"Fake satellite, real weather + crop risk. Farm split into {len(zones)} zones.",
    }
