"""
Sentinel-1 SAR (Synthetic Aperture Radar) client.
Uses the same Copernicus CDSE credentials as Sentinel-2.
Sentinel-1 penetrates clouds, rain, and works at night —
giving us soil moisture and waterlogging data during Indian
monsoon when Sentinel-2 is blocked for weeks at a time.

What Sentinel-1 gives us:
- VV backscatter: soil moisture (high VV = wet soil)
- VH backscatter: crop structure, flooding detection
- VV-VH ratio: distinguishes water from vegetation

Revisit: every 6-12 days over India (ascending + descending passes).
Resolution: 10m (IW mode) — same as Sentinel-2.
"""
import requests
from datetime import datetime, timedelta
from app.services.sentinel_auth import get_access_token, SentinelAuthError

STATS_API_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"

# VV backscatter — primary soil moisture indicator
# High VV (close to 0 dB) = wet soil / flooding
# Low VV (very negative) = dry soil / bare land
VV_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["VV", "dataMask"] }],
    output: [
      { id: "vv", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  // Convert to dB scale: 10 * log10(VV)
  // Return raw linear for statistics (we convert in Python)
  return { vv: [s.VV], dataMask: [s.dataMask] };
}
"""

# VH backscatter — crop structure and flooding
VH_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["VH", "dataMask"] }],
    output: [
      { id: "vh", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  return { vh: [s.VH], dataMask: [s.dataMask] };
}
"""

import math


def _to_db(linear_value: float) -> float:
    """Convert linear SAR backscatter to dB scale."""
    if linear_value <= 0:
        return -30.0
    return round(10 * math.log10(linear_value), 2)


def _request_s1_stats(polygon_points: list, evalscript: str,
                       band_id: str, days_back: int = 12) -> dict:
    """Request Sentinel-1 statistics for a polygon."""
    try:
        token = get_access_token()
        to_date = datetime.utcnow()
        from_date = to_date - timedelta(days=days_back)

        coords = [[p["lng"], p["lat"]] for p in polygon_points]
        if coords[0] != coords[-1]:
            coords.append(coords[0])

        payload = {
            "input": {
                "bounds": {
                    "geometry": {"type": "Polygon", "coordinates": [coords]},
                    "properties": {
                        "crs": "http://www.opengis.net/def/crs/EPSG/0/4326"
                    },
                },
                "data": [{
                    "type": "sentinel-1-grd",
                    "dataFilter": {
                        "acquisitionMode": "IW",
                        "polarization": "DV",  # Dual-pol VV+VH
                        "orbitDirection": "ASCENDING",
                    }
                }],
            },
            "aggregation": {
                "timeRange": {
                    "from": from_date.strftime("%Y-%m-%dT00:00:00Z"),
                    "to": to_date.strftime("%Y-%m-%dT23:59:59Z"),
                },
                "aggregationInterval": {"of": "P1D"},
                "evalscript": evalscript,
                "resx": 10, "resy": 10,
            },
            "calculations": {
                band_id: {
                    "statistics": {
                        "default": {"percentiles": {"k": [50]}}
                    }
                }
            },
        }

        res = requests.post(
            STATS_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )

        if res.status_code != 200:
            print(f"Sentinel-1 API {res.status_code}: {res.text[:200]}")
            return {"available": False, "reason": f"API {res.status_code}"}

        data = res.json()
        entries = data.get("data", [])

        # Find best (most recent) entry with valid data
        for entry in sorted(entries,
                             key=lambda d: d["interval"]["from"],
                             reverse=True):
            stats = (entry.get("outputs", {})
                     .get(band_id, {})
                     .get("bands", {})
                     .get("B0", {})
                     .get("stats"))
            if stats and stats.get("sampleCount", 0) > 0:
                valid = (stats.get("sampleCount", 0) -
                         stats.get("noDataCount", 0))
                if valid > 0:
                    linear = stats.get("mean", 0)
                    return {
                        "available": True,
                        "linear": round(linear, 6),
                        "db": _to_db(linear),
                        "date": entry["interval"]["from"][:10],
                    }

        return {"available": False, "reason": "No valid S1 pass in last 12 days"}

    except SentinelAuthError as e:
        return {"available": False, "reason": f"Auth error: {e}"}
    except Exception as e:
        print(f"Sentinel-1 error: {e}")
        return {"available": False, "reason": str(e)}


def get_soil_moisture_index(polygon_points: list) -> dict:
    """
    Returns soil moisture and waterlogging indicators from Sentinel-1.

    VV dB interpretation for Indian agricultural soils:
    > -8 dB  : Very wet / possible standing water
    -8 to -12: Wet / irrigated / recent rain
    -12 to -16: Moderate moisture
    -16 to -20: Dry soil
    < -20 dB : Very dry / bare soil

    Returns:
    - soil_moisture_level: Low / Moderate / High / Very High
    - waterlogging_detected: bool
    - vv_db: actual VV value in dB
    - confidence: percentage
    """
    vv = _request_s1_stats(polygon_points, VV_EVALSCRIPT, "vv")
    vh = _request_s1_stats(polygon_points, VH_EVALSCRIPT, "vh")

    if not vv.get("available"):
        return {
            "available": False,
            "reason": vv.get("reason", "No Sentinel-1 data"),
        }

    vv_db = vv["db"]
    vh_db = vh["db"] if vh.get("available") else vv_db - 8

    # Cross-ratio VV/VH in dB = VV_db - VH_db
    # High ratio (>6) = open water / flooding
    # Low ratio (<3) = dense vegetation
    cross_ratio = vv_db - vh_db

    # Classify soil moisture
    if vv_db > -8:
        moisture_level = "Very High"
        waterlogging = cross_ratio > 6
    elif vv_db > -12:
        moisture_level = "High"
        waterlogging = cross_ratio > 7
    elif vv_db > -16:
        moisture_level = "Moderate"
        waterlogging = False
    elif vv_db > -20:
        moisture_level = "Low"
        waterlogging = False
    else:
        moisture_level = "Very Low"
        waterlogging = False

    # Confidence based on VH availability
    confidence = 85 if vh.get("available") else 70

    return {
        "available": True,
        "soil_moisture_level": moisture_level,
        "waterlogging_detected": waterlogging,
        "vv_db": vv_db,
        "vh_db": vh_db,
        "cross_ratio_db": round(cross_ratio, 2),
        "confidence": confidence,
        "date": vv["date"],
        "source": "Sentinel-1 SAR",
    }
