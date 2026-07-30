"""
Daily automated pipeline scheduler.
Runs every night at 2 AM IST (20:30 UTC) for all farms.
Triggered by Railway's built-in cron or by the startup background task.
"""
import threading
import time
from datetime import datetime, timezone
import schedule
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.models import Farm
from app.services.sentinel_auth import is_configured
from app.services import sentinel_client, crop_analysis
from app.services.weather_service import get_weather_for_farm
from app.services.crop_risk_engine import (
    calculate_pest_risk, calculate_disease_risk, calculate_water_stress
)


def run_daily_scan_all_farms():
    """Scans every farm in the database with a drawn boundary."""
    if not is_configured():
        print("Scheduler: Sentinel not configured, skipping daily scan.")
        return

    print(f"Scheduler: Starting daily scan at {datetime.utcnow().isoformat()}")
    db: Session = SessionLocal()
    try:
        farms = db.query(Farm).filter(Farm.gps_polygon.isnot(None)).all()
        farms_with_boundary = [f for f in farms if f.gps_polygon and len(f.gps_polygon) >= 3]
        print(f"Scheduler: Found {len(farms_with_boundary)} farms to scan")

        for farm in farms_with_boundary:
            try:
                print(f"Scheduler: Scanning {farm.name}...")
                indices = sentinel_client.get_all_indices(farm.gps_polygon)
                weather = get_weather_for_farm(farm.latitude, farm.longitude)

                ndwi = indices.get("ndwi", {})
                ndmi = indices.get("ndmi", {})
                ndvi = indices.get("ndvi", {})

                ndwi_c = ndwi.get("current") or -0.05
                ndwi_p = ndwi.get("previous") or ndwi_c
                ndmi_c = ndmi.get("current") or 0.1
                ndmi_p = ndmi.get("previous") or ndmi_c
                ndvi_c = ndvi.get("current") or 0.5
                ndvi_p = ndvi.get("previous") or ndvi_c

                water_result = calculate_water_stress(ndwi_c, ndwi_p, ndmi_c, weather)
                pest_result = calculate_pest_risk(
                    farm.crop_type, farm.sowing_date or "",
                    ndvi_c, ndvi_p, weather, farm.waterlogging_severity or "None"
                )
                disease_result = calculate_disease_risk(
                    farm.crop_type, farm.sowing_date or "",
                    ndvi_c, ndvi_p, ndmi_c, ndmi_p, weather
                )
                updates = crop_analysis.build_full_update(
                    indices, weather, pest_result, disease_result, water_result
                )
                for key, value in updates.items():
                    setattr(farm, key, value)
                print(f"Scheduler: {farm.name} done — health={farm.health_score}, "
                      f"pest={farm.pest_risk_percent}%, "
                      f"water={farm.water_stress_level}")
            except Exception as e:
                print(f"Scheduler: Error scanning {farm.name}: {e}")

        db.commit()
        print(f"Scheduler: Daily scan complete at {datetime.utcnow().isoformat()}")
    except Exception as e:
        print(f"Scheduler: Fatal error: {e}")
    finally:
        db.close()


def start_scheduler():
    """Starts the background scheduler thread."""
    # Run daily at 20:30 UTC (2:00 AM IST)
    schedule.every().day.at("20:30").do(run_daily_scan_all_farms)
    schedule.every().day.at("21:00").do(run_daily_scan_all_ponds)
    print("Scheduler: Farm scans at 20:30 UTC, Pond scans at 21:00 UTC (both IST 2-2:30 AM)")

    def loop():
        while True:
            schedule.run_pending()
            time.sleep(60)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    print("Scheduler: Background thread started")


def run_daily_scan_all_ponds():
    """Scans all ponds with weather data daily."""
    print(f"Scheduler: Starting daily pond scan at {datetime.utcnow().isoformat()}")
    db: Session = SessionLocal()
    try:
        from app.models.models import Pond
        from app.services.weather_service import get_weather_for_farm
        from app.services.pond_analysis import analyze_pond

        ponds = db.query(Pond).filter(Pond.latitude != 0.0).all()
        print(f"Scheduler: Found {len(ponds)} ponds to scan")

        for pond in ponds:
            try:
                weather = get_weather_for_farm(pond.latitude, pond.longitude)
                result = analyze_pond(None, None, None, weather, pond.area_acres, pond.species or "Fish")
                pond.temperature_celsius = result["temperature_celsius"]
                pond.dissolved_oxygen = result["dissolved_oxygen"]
                pond.ph_level = result["ph_level"]
                pond.algae_bloom_risk = result["algae_bloom_risk"]
                pond.heat_stress_risk = result["heat_stress_risk"]
                pond.mortality_risk = result["mortality_risk"]
                pond.water_trend = result["water_trend"]
                pond.last_scan_date = datetime.utcnow().strftime("%Y-%m-%d")
                print(f"Scheduler: Pond {pond.name} done — DO={pond.dissolved_oxygen}, temp={pond.temperature_celsius}")
            except Exception as e:
                print(f"Scheduler: Error scanning pond {pond.name}: {e}")

        db.commit()
        print(f"Scheduler: Daily pond scan complete")
    except Exception as e:
        print(f"Scheduler: Pond scan fatal error: {e}")
    finally:
        db.close()
