"""
NASA MODIS Terra/Aqua NDVI via the MODIS Web Service API.
Free, no API key required for basic access.
Resolution: 250m per pixel — lower than Sentinel-2 (10m)
but available DAILY and works through moderate cloud cover.

Used as fallback when Sentinel-2 has no cloud-free pass.
MODIS Terra passes over India around 10:30 AM local time.
MODIS Aqua passes over India around 1:30 PM local time.
Together they give 1-2 chances per day for clear imagery.

API: AppEEARS (Application for Extracting and Exploring
Analysis Ready Samples) from NASA LPDAAC.
Endpoint: appeears.earthdatacloud.nasa.gov
"""
import requests
from datetime import datetime, timedelta

MODIS_API = "https://appeears.earthdatacloud.nasa.gov/api"
MODIS_PRODUCT = "MOD13Q1.061"  # MODIS Terra Vegetation Indices 16-day 250m


def get_modis_ndvi(lat: float, lng: float) -> dict:
    """
    Gets the latest MODIS NDVI value for a point location.
    Uses the AppEEARS point sample API — no authentication needed
    for single-point queries.

    MODIS NDVI scale: raw value / 10000 = actual NDVI
    (e.g. raw 5000 = NDVI 0.50)

    Returns NDVI and data quality flag.
    """
    try:
        today = datetime.utcnow().date()
        month_ago = today - timedelta(days=32)

        # AppEEARS point sample endpoint
        url = (
            f"{MODIS_API}/pointsampling"
            f"?product={MODIS_PRODUCT}"
            f"&layer=_250m_16_days_NDVI"
            f"&lat={lat}&lon={lng}"
            f"&startDate={month_ago.strftime('%m-%d-%Y')}"
            f"&endDate={today.strftime('%m-%d-%Y')}"
            f"&kmAboveBelow=0&kmLeftRight=0"
        )

        res = requests.get(url, timeout=15)

        if res.status_code == 200:
            data = res.json()
            samples = data if isinstance(data, list) else []

            # Find the most recent valid sample
            valid_samples = [
                s for s in samples
                if s.get("value") is not None
                and s.get("value", -3000) > -3000  # Filter fill values
            ]

            if valid_samples:
                latest = max(valid_samples, key=lambda s: s.get("date", ""))
                raw_ndvi = latest["value"]
                ndvi = round(raw_ndvi / 10000, 4)
                return {
                    "available": True,
                    "ndvi": ndvi,
                    "raw_value": raw_ndvi,
                    "date": latest.get("date", str(today))[:10],
                    "source": "MODIS Terra 250m (16-day composite)",
                    "resolution_m": 250,
                }

        # Try alternative: NASA Earthdata REST API
        return _get_modis_via_earthdata(lat, lng)

    except Exception as e:
        print(f"MODIS AppEEARS error: {e}")
        return _get_modis_via_earthdata(lat, lng)


def _get_modis_via_earthdata(lat: float, lng: float) -> dict:
    """
    Alternative MODIS access via NASA's ORNL DAAC REST service.
    Also free, no authentication for basic queries.
    """
    try:
        today = datetime.utcnow().date()
        start = today - timedelta(days=30)

        url = (
            "https://modis.ornl.gov/rst/api/v1/MOD13Q1/subset"
            f"?latitude={lat}&longitude={lng}"
            f"&startDate=A{start.strftime('%Y%j')}"
            f"&endDate=A{today.strftime('%Y%j')}"
            f"&kmAboveBelow=0&kmLeftRight=0"
            "&band=250m_16_days_NDVI"
        )

        res = requests.get(url, timeout=15)

        if res.status_code == 200:
            data = res.json()
            subsets = data.get("subset", [])
            if subsets:
                latest = subsets[-1]
                raw_data = latest.get("data", [])
                if raw_data:
                    raw_ndvi = raw_data[0]
                    if raw_ndvi > -3000:  # Valid NDVI
                        ndvi = round(raw_ndvi / 10000, 4)
                        return {
                            "available": True,
                            "ndvi": ndvi,
                            "raw_value": raw_ndvi,
                            "date": latest.get("calendar_date", str(today)),
                            "source": "MODIS Terra 250m via ORNL DAAC",
                            "resolution_m": 250,
                        }

    except Exception as e:
        print(f"MODIS ORNL error: {e}")

    return {
        "available": False,
        "reason": "MODIS data not available for this location/date",
    }
