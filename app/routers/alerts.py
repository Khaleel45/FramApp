from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Alert
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertIn(BaseModel):
    id: str
    farmId: Optional[str] = None
    farmName: str = ""
    type: str = "info"
    title: str
    message: str
    severity: str = "low"
    affectedArea: str = ""
    recommendation: str = ""
    resolved: bool = False


class AlertOut(BaseModel):
    id: str
    farmId: Optional[str]
    farmName: str
    type: str
    title: str
    message: str
    severity: str
    affectedArea: str
    recommendation: str
    resolved: bool

    class Config:
        from_attributes = True


def _to_out(a: Alert) -> dict:
    return {
        "id": a.id,
        "farmId": a.farm_id,
        "farmName": a.farm_name,
        "type": a.type,
        "title": a.title,
        "message": a.message,
        "severity": a.severity,
        "affectedArea": a.affected_area,
        "recommendation": a.recommendation,
        "resolved": a.resolved,
    }


@router.get("/", response_model=List[AlertOut])
def get_alerts(device_id: str, db: Session = Depends(get_db)):
    alerts = db.query(Alert).filter(Alert.device_id == device_id).order_by(Alert.created_at.desc()).all()
    return [_to_out(a) for a in alerts]


@router.post("/", response_model=AlertOut)
def upsert_alert(device_id: str, alert: AlertIn, db: Session = Depends(get_db)):
    existing = db.query(Alert).filter(Alert.id == alert.id, Alert.device_id == device_id).first()
    data = dict(
        device_id=device_id,
        farm_id=alert.farmId,
        farm_name=alert.farmName,
        type=alert.type,
        title=alert.title,
        message=alert.message,
        severity=alert.severity,
        affected_area=alert.affectedArea,
        recommendation=alert.recommendation,
        resolved=alert.resolved,
    )
    if existing:
        for key, value in data.items():
            setattr(existing, key, value)
        db.commit()
        db.refresh(existing)
        return _to_out(existing)
    else:
        db_alert = Alert(id=alert.id, **data)
        db.add(db_alert)
        db.commit()
        db.refresh(db_alert)
        return _to_out(db_alert)


@router.put("/{alert_id}/resolve")
def resolve_alert(alert_id: str, device_id: str, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id, Alert.device_id == device_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.resolved = True
    db.commit()
    return {"message": "Alert marked as resolved"}
