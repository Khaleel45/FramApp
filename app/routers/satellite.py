"""
Satellite scan — multi-source fusion pipeline.
Sentinel-2 + Sentinel-1 + MODIS + Weather combined.
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
from app.services.data_fusion import fuse_data_sources
from app.services.zone_map_generator import generate_zone_map_svg

router = APIRouter(prefix="/satellite", tags=["satellite"])


@router.get("/status")
def satellite_status():
    return {
        "sentinel_configured": is_configured(),
        "sources_available": [
            "Sentinel-2 (NDVI/NDWI/NDMI, 10m, every 5 days)",
            "Sentinel-1 (soil moisture/flooding, radar, every 6-12 days)",
            "MODIS (NDVI, 250m, daily)",
            "Open-Meteo (weather, real-time)",
        ],
        "message": (
            "All sources ready."
            if is_configured()
            else "Add SENTINEL_CLIENT_ID + SENTINEL_CLIENT_SECRET in Railway Variables."
        ),
    }


def _make_bbox(lat, lng, acres):
    delta = (acres ** 0.5) * 0.003
    return [
        {"lat": lat - delta, "lng": lng - delta},
        {"lat": lat + delta, "lng": lng - delta},
        {"lat": lat + delta, "lng": lng + delta},
        {"lat": lat - delta, "lng": lng + delta},
    ]


def _run_risk_models(ndvi_c, ndvi_p, ndwi_c, ndwi_p, ndmi_c, ndmi_p,
                     weather, crop_type, sowing_date, waterlogging):
    ndvi_c = ndvi_c or 0.5
    ndvi_p = ndvi_p or ndvi_c
    ndwi_c = ndwi_c or -0.05
    ndwi_p = ndwi_p or ndwi_c
    ndmi_c = ndmi_c or 0.1
    ndmi_p = ndmi_p or ndmi_c
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
        Farm.id == farm_id, Farm.device_id == device_id).first()
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")

    try:
        # ── 1. Weather (always runs) ───────────────────────────────
        weather = get_weather_for_farm(farm.latitude, farm.longitude)
        print(f"Weather: {weather['temperature']}°C, {weather['humidity']}% RH")

        polygon = farm.gps_polygon
        using_bbox = False
        if not polygon or len(polygon) < 3:
            polygon = _make_bbox(farm.latitude, farm.longitude, farm.area_acres or 2.0)
            using_bbox = True

        # ── 2. Sentinel-2 (optical, 10m) ──────────────────────────
        from app.services import sentinel_client
        s2_indices = {}
        try:
            s2_indices = sentinel_client.get_all_indices(polygon)
            print(f"S2 NDVI available: {s2_indices.get('ndvi', {}).get('available')}")
        except Exception as e:
            print(f"S2 error: {e}")

        # ── 3. Sentinel-1 (radar, cloud-penetrating) ──────────────
        s1_moisture = {}
        try:
            from app.services.sentinel1_client import get_soil_moisture_index
            s1_moisture = get_soil_moisture_index(polygon)
            print(f"S1 moisture: {s1_moisture.get('soil_moisture_level', 'unavailable')}")
        except Exception as e:
            print(f"S1 error: {e}")

        # ── 4. MODIS (250m, daily) ─────────────────────────────────
        modis_ndvi = {}
        try:
            from app.services.modis_client import get_modis_ndvi
            modis_ndvi = get_modis_ndvi(farm.latitude, farm.longitude)
            print(f"MODIS NDVI available: {modis_ndvi.get('available')}")
        except Exception as e:
            print(f"MODIS error: {e}")

        # ── 5. Fuse all sources ────────────────────────────────────
        fused = fuse_data_sources(
            sentinel2_indices=s2_indices,
            sentinel1_moisture=s1_moisture,
            modis_ndvi=modis_ndvi,
            weather=weather,
            crop_type=farm.crop_type or "Rice",
            sowing_date=farm.sowing_date or str(datetime.utcnow().date()),
            farm_name=farm.name,
        )
        print(f"Fused: score={fused['health_score']}, quality={fused['data_quality']}, sources={fused['sources_used']}")

        # ── 6. Zone-level scanning ─────────────────────────────────
        zones = split_into_zones(polygon, farm.area_acres or 2.0)
        zone_results = []

        if s2_indices.get("ndvi", {}).get("available") and not using_bbox and len(zones) > 1:
            for zone in zones:
                try:
                    zi = sentinel_client.get_all_indices(zone["polygon"])
                    z_ndvi = zi.get("ndvi", {})
                    z_ndwi = zi.get("ndwi", {})
                    z_ndmi = zi.get("ndmi", {})
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
                        "ndvi": z_ndvi.get("current", fused["ndvi"] or 0.5),
                        "pest_risk_percent": z_pest["pest_risk_percent"],
                        "top_pest": z_pest.get("top_pest_name", ""),
                        "disease_risk_level": z_disease["disease_risk_level"],
                        "water_stress_level": z_water["water_stress_level"],
                    })
                except Exception as e:
                    zone_results.append({
                        "zone_name": zone["name"],
                        "area_acres": zone.get("area_acres", 2.0),
                        "ndvi_available": False,
                        "ndvi": fused["ndvi"] or 0.5,
                        "pest_risk_percent": 0,
                        "disease_risk_level": "Low",
                        "water_stress_level": "Low",
                    })
        else:
            zone_results = [{
                "zone_name": "Full Farm",
                "area_acres": farm.area_acres or 2.0,
                "ndvi_available": fused["ndvi"] is not None,
                "ndvi": fused["ndvi"] or 0.5,
                "pest_risk_percent": 0,
                "disease_risk_level": "Low",
                "water_stress_level": fused["water_stress_level"],
            }]

        # ── 7. Aggregate zones, find hotspots ─────────────────────
        aggregated = aggregate_zone_results(zone_results, farm.name)
        hotspots = aggregated.get("hotspot_zones", [])

        # ── 8. Farm-level risk models ─────────────────────────────
        wl = "Severe" if fused["waterlogging_detected"] else farm.waterlogging_severity or "None"
        pest, disease, water = _run_risk_models(
            fused["ndvi"], fused.get("ndvi_previous"),
            fused["ndwi"], fused["ndwi"],
            fused["ndmi"], fused["ndmi"],
            weather, farm.crop_type or "Rice",
            farm.sowing_date or str(datetime.utcnow().date()),
            wl,
        )

        # ── 9. Zone map SVG ───────────────────────────────────────
        zone_map_svg = generate_zone_map_svg(
            zones=zones,
            zone_results=zone_results,
            farm_name=farm.name,
            hotspot_zones=hotspots,
        )

        # ── 10. Save to database ──────────────────────────────────
        wl_sev, _ = crop_analysis.detect_waterlogging(fused["ndwi"])
        if fused["waterlogging_detected"]:
            wl_sev = "Severe"

        farm.health_score = fused["health_score"]
        farm.health_status = fused["health_status"]
        farm.water_stress_level = fused["water_stress_level"]
        farm.water_stress_confidence = fused["water_stress_confidence"]
        farm.waterlogging_severity = wl_sev
        farm.pest_risk_percent = pest["pest_risk_percent"]
        farm.pest_confidence = pest["pest_risk_percent"]
        farm.pest_hotspots = [z["zone_name"] for z in hotspots] if hotspots else []
        farm.disease_risk_level = disease["disease_risk_level"]
        farm.disease_risk_elevated = disease["disease_risk_elevated"]
        farm.disease_risk_notes = (
            aggregated.get("summary") or disease["disease_risk_notes"]
        )
        farm.last_scan_date = fused["scan_date"]
        db.commit()
        db.refresh(farm)

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
            "data_sources": fused["sources_used"],
            "data_quality": fused["data_quality"],
            "data_quality_label": fused["data_quality_label"],
            "confidence": fused["confidence"],
            "sentinel_available": s2_indices.get("ndvi", {}).get("available", False),
            "sentinel1_available": s1_moisture.get("available", False),
            "modis_available": modis_ndvi.get("available", False),
            "zone_analysis": {
                "zone_count": len(zone_results),
                "zones_scanned": sum(1 for z in zone_results if z.get("ndvi_available")),
                "hotspot_zones": hotspots,
                "zone_alerts": aggregated.get("zone_alerts", []),
                "summary": aggregated.get("summary", ""),
                "zone_map_svg": zone_map_svg,
            },
            "weather": {
                "temperature": weather.get("temperature"),
                "humidity": weather.get("humidity"),
                "rainfall_7d": weather.get("rainfall_7d"),
                "leaf_wetness_hours": weather.get("leaf_wetness_hours"),
                "available": weather.get("available", False),
            },
        }

    except SentinelAuthError as e:
        raise HTTPException(status_code=401, detail=f"Sentinel auth failed: {e}")
    except Exception as e:
        print(f"Scan error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Scan error: {str(e)}")


@router.post("/scan-all")
def scan_all_farms(device_id: str, db: Session = Depends(get_db)):
    farms = db.query(Farm).filter(Farm.device_id == device_id).all()
    results = []
    for farm in farms:
        polygon = farm.gps_polygon or _make_bbox(farm.latitude, farm.longitude, farm.area_acres or 2.0)
        zones = split_into_zones(polygon, farm.area_acres or 2.0)
        results.append({"farm_id": farm.id, "name": farm.name, "zones": len(zones)})
    return {"farms": len(results), "results": results}


@router.post("/test-scan/{farm_id}")
def test_scan(farm_id: str, device_id: str, db: Session = Depends(get_db)):
    farm = db.query(Farm).filter(
        Farm.id == farm_id, Farm.device_id == device_id).first()
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")

    weather = get_weather_for_farm(farm.latitude, farm.longitude)
    polygon = farm.gps_polygon or _make_bbox(farm.latitude, farm.longitude, farm.area_acres or 2.0)
    zones = split_into_zones(polygon, farm.area_acres or 2.0) or [
        {"name": "Full Farm", "area_acres": farm.area_acres or 2.0, "row": 0, "col": 0}]

    base_ndvi = round(random.uniform(0.45, 0.72), 3)
    stressed_idx = random.sample(range(len(zones)), k=max(1, len(zones) // 4))
    zone_results = []

    for i, zone in enumerate(zones):
        ndvi = round(base_ndvi - random.uniform(0.15, 0.28), 3) if i in stressed_idx \
               else round(base_ndvi + random.uniform(-0.05, 0.08), 3)
        ndvi = max(0.1, min(0.9, ndvi))
        ndwi = round(random.uniform(-0.15, 0.10), 3)
        ndmi = round(random.uniform(0.05, 0.25), 3)
        pest, disease, water = _run_risk_models(
            ndvi, ndvi + 0.06, ndwi, ndwi - 0.03, ndmi, ndmi + 0.05,
            weather, farm.crop_type or "Rice",
            farm.sowing_date or str(datetime.utcnow().date()), "None")
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
    zone_map_svg = generate_zone_map_svg(zones, zone_results, farm.name, hotspots)

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
        "success": True, "test": True,
        "farm_id": farm.id, "farm_name": farm.name,
        "health_score": farm.health_score,
        "health_status": farm.health_status,
        "pest_risk_percent": farm.pest_risk_percent,
        "disease_risk_level": farm.disease_risk_level,
        "disease_risk_notes": farm.disease_risk_notes,
        "last_scan_date": farm.last_scan_date,
        "data_sources": ["Weather (test)", "Synthetic NDVI"],
        "data_quality": "test",
        "data_quality_label": "Synthetic test data — not real satellite",
        "confidence": 70,
        "zone_analysis": {
            "zone_count": len(zones),
            "zones_scanned": len(zone_results),
            "hotspot_zones": hotspots,
            "zone_alerts": aggregated.get("zone_alerts", []),
            "summary": aggregated.get("summary", ""),
            "zone_map_svg": zone_map_svg,
        },
        "weather": weather,
        "note": f"Synthetic data. Farm split into {len(zones)} zones.",
    }
