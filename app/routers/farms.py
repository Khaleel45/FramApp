from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Farm
from pydantic import BaseModel, Field
from typing import List, Optional

router = APIRouter(prefix="/farms", tags=["farms"])


class FarmIn(BaseModel):
    id: str
    name: str
    cropType: str
    cropTypeTelugu: str = ""
    sowingDate: str = ""
    areaAcres: float = 0.0
    locationName: str = ""
    locationNameTelugu: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    healthScore: int = 78
    healthStatus: str = "New Farm"
    healthStatusTelugu: str = ""
    waterStressLevel: str = "Low"
    waterStressConfidence: int = 75
    waterStressArea: str = ""
    waterStressAreaTelugu: str = ""
    waterloggingSeverity: str = "None"
    waterloggingArea: str = ""
    pestRiskPercent: int = 0
    pestConfidence: int = 0
    pestHotspots: List[str] = Field(default_factory=list)
    diseaseRiskLevel: str = "Low"
    diseaseRiskElevated: bool = False
    diseaseRiskNotes: str = ""
    diseaseRiskNotesTelugu: str = ""
    lastScanDate: str = "Just now"
    gpsPolygon: Optional[List[dict]] = None


class FarmOut(BaseModel):
    id: str
    name: str
    cropType: str
    cropTypeTelugu: str
    sowingDate: str
    areaAcres: float
    locationName: str
    locationNameTelugu: str
    latitude: float
    longitude: float
    healthScore: int
    healthStatus: str
    healthStatusTelugu: str
    waterStressLevel: str
    waterStressConfidence: int
    waterStressArea: str
    waterStressAreaTelugu: str
    waterloggingSeverity: str
    waterloggingArea: str
    pestRiskPercent: int
    pestConfidence: int
    pestHotspots: List[str]
    diseaseRiskLevel: str
    diseaseRiskElevated: bool
    diseaseRiskNotes: str
    diseaseRiskNotesTelugu: str
    lastScanDate: str
    gpsPolygon: Optional[List[dict]]

    class Config:
        from_attributes = True


def _to_out(f: Farm) -> dict:
    return {
        "id": f.id,
        "name": f.name,
        "cropType": f.crop_type,
        "cropTypeTelugu": f.crop_type_telugu,
        "sowingDate": f.sowing_date,
        "areaAcres": f.area_acres,
        "locationName": f.location_name,
        "locationNameTelugu": f.location_name_telugu,
        "latitude": f.latitude,
        "longitude": f.longitude,
        "healthScore": f.health_score,
        "healthStatus": f.health_status,
        "healthStatusTelugu": f.health_status_telugu,
        "waterStressLevel": f.water_stress_level,
        "waterStressConfidence": f.water_stress_confidence,
        "waterStressArea": f.water_stress_area,
        "waterStressAreaTelugu": f.water_stress_area_telugu,
        "waterloggingSeverity": f.waterlogging_severity,
        "waterloggingArea": f.waterlogging_area,
        "pestRiskPercent": f.pest_risk_percent,
        "pestConfidence": f.pest_confidence,
        "pestHotspots": f.pest_hotspots or [],
        "diseaseRiskLevel": f.disease_risk_level,
        "diseaseRiskElevated": f.disease_risk_elevated,
        "diseaseRiskNotes": f.disease_risk_notes,
        "diseaseRiskNotesTelugu": f.disease_risk_notes_telugu,
        "lastScanDate": f.last_scan_date,
        "gpsPolygon": f.gps_polygon or None,
    }


@router.get("/", response_model=List[FarmOut])
def get_farms(device_id: str, db: Session = Depends(get_db)):
    farms = db.query(Farm).filter(Farm.device_id == device_id).all()
    return [_to_out(f) for f in farms]


@router.post("/", response_model=FarmOut)
def upsert_farm(device_id: str, farm: FarmIn, db: Session = Depends(get_db)):
    existing = db.query(Farm).filter(Farm.id == farm.id, Farm.device_id == device_id).first()
    data = dict(
        device_id=device_id,
        name=farm.name,
        crop_type=farm.cropType,
        crop_type_telugu=farm.cropTypeTelugu,
        sowing_date=farm.sowingDate,
        area_acres=farm.areaAcres,
        location_name=farm.locationName,
        location_name_telugu=farm.locationNameTelugu,
        latitude=farm.latitude,
        longitude=farm.longitude,
        health_score=farm.healthScore,
        health_status=farm.healthStatus,
        health_status_telugu=farm.healthStatusTelugu,
        water_stress_level=farm.waterStressLevel,
        water_stress_confidence=farm.waterStressConfidence,
        water_stress_area=farm.waterStressArea,
        water_stress_area_telugu=farm.waterStressAreaTelugu,
        waterlogging_severity=farm.waterloggingSeverity,
        waterlogging_area=farm.waterloggingArea,
        pest_risk_percent=farm.pestRiskPercent,
        pest_confidence=farm.pestConfidence,
        pest_hotspots=farm.pestHotspots,
        disease_risk_level=farm.diseaseRiskLevel,
        disease_risk_elevated=farm.diseaseRiskElevated,
        disease_risk_notes=farm.diseaseRiskNotes,
        disease_risk_notes_telugu=farm.diseaseRiskNotesTelugu,
        last_scan_date=farm.lastScanDate,
        gps_polygon=farm.gpsPolygon,
    )

    if existing:
        for key, value in data.items():
            setattr(existing, key, value)
        db.commit()
        db.refresh(existing)
        return _to_out(existing)
    else:
        db_farm = Farm(id=farm.id, **data)
        db.add(db_farm)
        db.commit()
        db.refresh(db_farm)
        return _to_out(db_farm)


@router.delete("/{farm_id}")
def delete_farm(farm_id: str, device_id: str, db: Session = Depends(get_db)):
    farm = db.query(Farm).filter(Farm.id == farm_id, Farm.device_id == device_id).first()
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    db.delete(farm)
    db.commit()
    return {"message": "Farm deleted successfully"}
