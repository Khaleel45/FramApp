"""
Pond CRUD + satellite scan endpoints.
"""
import traceback
import random
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.database import get_db
from app.models.models import Pond
from app.services.weather_service import get_weather_for_farm
from app.services.pond_analysis import analyze_pond
from app.services.sentinel_auth import is_configured
from app.services import sentinel_client

router = APIRouter(prefix="/ponds", tags=["ponds"])


class PondIn(BaseModel):
    id: str
    name: str
    areaAcres: float = 0.0
    locationName: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    gpsPolygon: Optional[List[dict]] = None
    species: str = "Fish"
    stockingDate: str = ""


class PondOut(BaseModel):
    id: str
    name: str
    areaAcres: float
    locationName: str
    latitude: float
    longitude: float
    gpsPolygon: Optional[List[dict]]
    species: str
    stockingDate: str
    waterSpreadPercent: int
    waterTrend: str
    algaeBloomRisk: str
    heatStressRisk: str
    mortalityRisk: str
    dissolvedOxygen: float
    temperatureCelsius: float
    phLevel: float
    lastScanDate: str

    class Config:
        from_attributes = True


def _to_out(p: Pond) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "areaAcres": p.area_acres,
        "locationName": p.location_name,
        "latitude": p.latitude,
        "longitude": p.longitude,
        "gpsPolygon": p.gps_polygon,
        "species": p.species,
        "stockingDate": p.stocking_date,
        "waterSpreadPercent": p.water_spread_percent,
        "waterTrend": p.water_trend,
        "algaeBloomRisk": p.algae_bloom_risk,
        "heatStressRisk": p.heat_stress_risk,
        "mortalityRisk": p.mortality_risk,
        "dissolvedOxygen": p.dissolved_oxygen,
        "temperatureCelsius": p.temperature_celsius,
        "phLevel": p.ph_level,
        "lastScanDate": p.last_scan_date,
    }


@router.get("/", response_model=List[PondOut])
def get_ponds(device_id: str, db: Session = Depends(get_db)):
    ponds = db.query(Pond).filter(Pond.device_id == device_id).all()
    return [_to_out(p) for p in ponds]


@router.post("/", response_model=PondOut)
def upsert_pond(device_id: str, pond: PondIn, db: Session = Depends(get_db)):
    existing = db.query(Pond).filter(
        Pond.id == pond.id, Pond.device_id == device_id
    ).first()
    data = dict(
        device_id=device_id,
        name=pond.name,
        area_acres=pond.areaAcres,
        location_name=pond.locationName,
        latitude=pond.latitude,
        longitude=pond.longitude,
        gps_polygon=pond.gpsPolygon,
        species=pond.species,
        stocking_date=pond.stockingDate,
    )
    if existing:
        for k, v in data.items():
            setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return _to_out(existing)
    else:
        db_pond = Pond(id=pond.id, **data)
        db.add(db_pond)
        db.commit()
        db.refresh(db_pond)
        return _to_out(db_pond)


@router.delete("/{pond_id}")
def delete_pond(pond_id: str, device_id: str, db: Session = Depends(get_db)):
    pond = db.query(Pond).filter(
        Pond.id == pond_id, Pond.device_id == device_id
    ).first()
    if not pond:
        raise HTTPException(status_code=404, detail="Pond not found")
    db.delete(pond)
    db.commit()
    return {"message": "Pond deleted"}


@router.post("/scan/{pond_id}")
def scan_pond(pond_id: str, device_id: str, db: Session = Depends(get_db)):
    """Runs satellite + weather analysis for a pond."""
    pond = db.query(Pond).filter(
        Pond.id == pond_id, Pond.device_id == device_id
    ).first()
    if not pond:
        raise HTTPException(status_code=404, detail="Pond not found")

    # Always run weather (free, no credentials needed)
    weather = get_weather_for_farm(pond.latitude, pond.longitude)

    # Sentinel indices if configured
    ndwi_current = None
    ndwi_previous = None
    ndvi_on_water = None

    if is_configured() and pond.gps_polygon and len(pond.gps_polygon) >= 3:
        try:
            indices = sentinel_client.get_all_indices(pond.gps_polygon)
            ndwi_data = indices.get("ndwi", {})
            ndvi_data = indices.get("ndvi", {})
            if ndwi_data.get("available"):
                ndwi_current = ndwi_data["current"]
                ndwi_previous = ndwi_data.get("previous")
            if ndvi_data.get("available"):
                ndvi_on_water = ndvi_data["current"]
        except Exception as e:
            print(f"Sentinel scan failed for pond {pond_id}: {e}")
            # Fall through — weather-only analysis still runs

    result = analyze_pond(
        ndwi=ndwi_current,
        ndwi_previous=ndwi_previous,
        ndvi_on_water=ndvi_on_water,
        weather=weather,
        area_acres=pond.area_acres,
        species=pond.species or "Fish",
    )

    pond.water_spread_percent = result["water_spread_percent"]
    pond.water_trend = result["water_trend"]
    pond.algae_bloom_risk = result["algae_bloom_risk"]
    pond.heat_stress_risk = result["heat_stress_risk"]
    pond.mortality_risk = result["mortality_risk"]
    pond.dissolved_oxygen = result["dissolved_oxygen"]
    pond.temperature_celsius = result["temperature_celsius"]
    pond.ph_level = result["ph_level"]
    pond.last_scan_date = datetime.utcnow().strftime("%Y-%m-%d")

    db.commit()
    db.refresh(pond)

    return {
        "success": True,
        **_to_out(pond),
        "weather": {
            "temperature": weather.get("temperature"),
            "humidity": weather.get("humidity"),
            "rainfall_7d": weather.get("rainfall_7d"),
        },
        "satellite_used": ndwi_current is not None,
    }
