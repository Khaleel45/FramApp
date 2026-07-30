from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine
from app.models.models import Base
from app.routers import farms, alerts, users, satellite, ponds
from app.scheduler import start_scheduler
import time

app = FastAPI(
    title="FarmiGrow AI API",
    description="Satellite-powered farm intelligence — Sentinel-2 + Weather + Crop Risk",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(farms.router)
app.include_router(alerts.router)
app.include_router(users.router)
app.include_router(satellite.router)
app.include_router(ponds.router)

@app.on_event("startup")
async def startup():
    max_retries = 5
    for i in range(max_retries):
        try:
            Base.metadata.create_all(bind=engine)
            print("✅ Database connected and tables created!")
            break
        except Exception as e:
            print(f"⚠️ DB connection attempt {i+1}/{max_retries} failed: {e}")
            if i < max_retries - 1:
                time.sleep(3)
            else:
                print("❌ Could not connect to database after retries")

    # Start daily automated satellite scan scheduler
    start_scheduler()

@app.get("/")
def root():
    return {
        "app": "FarmiGrow AI API",
        "version": "3.0.0",
        "status": "running",
        "features": [
            "Sentinel-2 NDVI/NDWI/NDMI",
            "Open-Meteo weather",
            "Crop-specific pest & disease models",
            "Daily automated scans"
        ]
    }

@app.get("/health")
def health():
    return {"status": "healthy"}
