from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, JSON, Text
from sqlalchemy.sql import func
from app.database import Base


class Farm(Base):
    """
    Mirrors the Dart `Farm` model field-for-field so the mobile app
    can sync without any translation layer beyond snake_case <-> camelCase.
    `device_id` stands in for a user account until real auth exists -
    each phone installation gets its own farms.
    """
    __tablename__ = "farms"

    id = Column(String, primary_key=True, index=True)  # client-generated ID (timestamp-based)
    device_id = Column(String, nullable=False, index=True)

    name = Column(String, nullable=False)
    crop_type = Column(String, nullable=False)
    crop_type_telugu = Column(String, default="")
    sowing_date = Column(String, default="")
    area_acres = Column(Float, default=0.0)

    location_name = Column(String, default="")
    location_name_telugu = Column(String, default="")
    latitude = Column(Float, default=0.0)
    longitude = Column(Float, default=0.0)

    health_score = Column(Integer, default=78)
    health_status = Column(String, default="New Farm")
    health_status_telugu = Column(String, default="")

    water_stress_level = Column(String, default="Low")
    water_stress_confidence = Column(Integer, default=75)
    water_stress_area = Column(String, default="")
    water_stress_area_telugu = Column(String, default="")

    waterlogging_severity = Column(String, default="None")
    waterlogging_area = Column(String, default="")

    pest_risk_percent = Column(Integer, default=0)
    pest_confidence = Column(Integer, default=0)
    pest_hotspots = Column(JSON, default=list)

    disease_risk_level = Column(String, default="Low")
    disease_risk_elevated = Column(Boolean, default=False)
    disease_risk_notes = Column(String, default="")
    disease_risk_notes_telugu = Column(String, default="")

    last_scan_date = Column(String, default="Just now")
    gps_polygon = Column(JSON, default=list)  # [{"lat": .., "lng": ..}, ...]

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Alert(Base):
    """
    Generated server-side (or mirrored from client-side generation) from
    a farm's risk fields. Kept simple for now; the app currently
    generates these on-device from synced farm data, but storing them
    here allows push-notification fan-out later.
    """
    __tablename__ = "alerts"

    id = Column(String, primary_key=True, index=True)
    device_id = Column(String, nullable=False, index=True)
    farm_id = Column(String, nullable=True, index=True)
    farm_name = Column(String, default="")

    type = Column(String, default="info")  # water_stress, pest_infestation, disease_risk, waterlogging
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    severity = Column(String, default="info")  # high, medium, low
    affected_area = Column(String, default="")
    recommendation = Column(Text, default="")
    resolved = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserProfile(Base):
    """
    One row per device_id. Mirrors the Dart UserProfile model.
    """
    __tablename__ = "user_profiles"

    device_id = Column(String, primary_key=True, index=True)
    name = Column(String, default="Farmer")
    phone = Column(String, default="")
    location = Column(String, default="Telangana & Andhra Pradesh, India")
    role = Column(String, default="Farmer")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Pond(Base):
    """
    Aqua pond model. Satellite-derived water parameters:
    - water_spread_percent: how much of the pond boundary has water (from NDWI)
    - algae_bloom_risk: derived from NDVI on water surface (algae = high NDVI on water)
    - heat_stress_risk: derived from land surface temperature proxy
    - dissolved_oxygen: estimated from water clarity + temperature model
    - temperature_celsius: estimated from satellite thermal proxy + weather
    - ph_level: estimated from water color indices
    - mortality_risk: combined risk score for aquaculture fish/shrimp
    """
    __tablename__ = "ponds"

    id = Column(String, primary_key=True, index=True)
    device_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    area_acres = Column(Float, default=0.0)
    location_name = Column(String, default="")
    latitude = Column(Float, default=0.0)
    longitude = Column(Float, default=0.0)
    gps_polygon = Column(JSON, default=list)
    species = Column(String, default="Fish")  # Fish, Shrimp, Prawn etc.
    stocking_date = Column(String, default="")

    # Satellite + weather derived parameters
    water_spread_percent = Column(Integer, default=85)
    water_trend = Column(String, default="Stable")
    algae_bloom_risk = Column(String, default="Low")
    heat_stress_risk = Column(String, default="Low")
    mortality_risk = Column(String, default="Low")
    dissolved_oxygen = Column(Float, default=6.5)
    temperature_celsius = Column(Float, default=28.0)
    ph_level = Column(Float, default=7.5)
    last_scan_date = Column(String, default="Not scanned yet")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
