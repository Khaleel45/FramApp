from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import UserProfile
from pydantic import BaseModel

router = APIRouter(prefix="/profile", tags=["profile"])


class ProfileIn(BaseModel):
    name: str = "Farmer"
    phone: str = ""
    location: str = "Telangana & Andhra Pradesh, India"
    role: str = "Farmer"


class ProfileOut(BaseModel):
    name: str
    phone: str
    location: str
    role: str

    class Config:
        from_attributes = True


@router.get("/", response_model=ProfileOut)
def get_profile(device_id: str, db: Session = Depends(get_db)):
    profile = db.query(UserProfile).filter(UserProfile.device_id == device_id).first()
    if not profile:
        # Return defaults if this device has never synced a profile yet
        return ProfileOut(name="Farmer", phone="", location="Telangana & Andhra Pradesh, India", role="Farmer")
    return profile


@router.post("/", response_model=ProfileOut)
def upsert_profile(device_id: str, profile: ProfileIn, db: Session = Depends(get_db)):
    existing = db.query(UserProfile).filter(UserProfile.device_id == device_id).first()
    if existing:
        existing.name = profile.name
        existing.phone = profile.phone
        existing.location = profile.location
        existing.role = profile.role
        db.commit()
        db.refresh(existing)
        return existing
    else:
        new_profile = UserProfile(device_id=device_id, **profile.dict())
        db.add(new_profile)
        db.commit()
        db.refresh(new_profile)
        return new_profile
