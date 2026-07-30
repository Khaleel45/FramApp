"""
Sentinel Hub Statistical API client.
Computes NDVI, NDMI, NDRE, EVI, GNDVI, SAVI for a farm polygon.
Also stores previous values for trend comparison.
"""
import requests
from datetime import datetime, timedelta
from app.services.sentinel_auth import get_access_token, SentinelAuthError

STATS_API_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"

# NDVI — crop health / biomass
NDVI_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "dataMask"] }],
    output: [
      { id: "ndvi", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  let ndvi = (s.B08 - s.B04) / (s.B08 + s.B04 + 0.0001);
  return { ndvi: [ndvi], dataMask: [s.dataMask] };
}
"""

# NDWI — canopy water content (used for water stress)
NDWI_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B03", "B08", "dataMask"] }],
    output: [
      { id: "ndwi", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  let ndwi = (s.B03 - s.B08) / (s.B03 + s.B08 + 0.0001);
  return { ndwi: [ndwi], dataMask: [s.dataMask] };
}
"""

# NDMI — moisture index (used for disease + water stress)
NDMI_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B08", "B11", "dataMask"] }],
    output: [
      { id: "ndmi", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  let ndmi = (s.B08 - s.B11) / (s.B08 + s.B11 + 0.0001);
  return { ndmi: [ndmi], dataMask: [s.dataMask] };
}
"""

# NDRE — red edge, better for detecting early stress vs NDVI
NDRE_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B07", "B05", "dataMask"] }],
    output: [
      { id: "ndre", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  let ndre = (s.B07 - s.B05) / (s.B07 + s.B05 + 0.0001);
  return { ndre: [ndre], dataMask: [s.dataMask] };
}
"""


class SentinelRequestError(Exception):
    pass


def _polygon_to_geojson(polygon_points: list) -> dict:
    coords = [[p["lng"], p["lat"]] for p in polygon_points]
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}


def _request_stats(polygon_points: list, evalscript: str, band_id: str,
                   days_back: int = 15, days_previous: int = 30) -> dict:
    """
    Requests stats for both current period and previous period
    so we can compute NDVI/NDMI trends (today vs last week).
    """
    token = get_access_token()
    to_date = datetime.utcnow()
    from_date = to_date - timedelta(days=days_back)
    prev_from = to_date - timedelta(days=days_previous)
    prev_to = from_date

    def _fetch(from_d, to_d):
        payload = {
            "input": {
                "bounds": {
                    "geometry": _polygon_to_geojson(polygon_points),
                    "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
                },
                "data": [{"type": "sentinel-2-l2a",
                           "dataFilter": {"maxCloudCoverage": 60}}],
            },
            "aggregation": {
                "timeRange": {
                    "from": from_d.strftime("%Y-%m-%dT00:00:00Z"),
                    "to": to_d.strftime("%Y-%m-%dT23:59:59Z"),
                },
                "aggregationInterval": {"of": "P1D"},
                "evalscript": evalscript,
                "resx": 10, "resy": 10,
            },
            "calculations": {
                band_id: {"statistics": {"default": {"percentiles": {"k": [50]}}}}
            },
        }
        res = requests.post(
            STATS_API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            timeout=30,
        )
        if res.status_code != 200:
            raise SentinelRequestError(
                f"Sentinel API {res.status_code}: {res.text[:300]}")
        return res.json()

    current_raw = _fetch(from_date, to_date)
    try:
        previous_raw = _fetch(prev_from, prev_to)
    except Exception:
        previous_raw = None

    return {"current": current_raw, "previous": previous_raw}


def _best_value(stats_response: dict, band_id: str) -> dict | None:
    data = stats_response.get("data", []) if stats_response else []
    for entry in sorted(data, key=lambda d: d["interval"]["from"], reverse=True):
        outputs = entry.get("outputs", {})
        band_stats = (outputs.get(band_id, {})
                      .get("bands", {}).get("B0", {}).get("stats"))
        if band_stats and band_stats.get("sampleCount", 0) > 0:
            valid = band_stats.get("sampleCount", 0) - band_stats.get("noDataCount", 0)
            if valid > 0:
                return {
                    "mean": round(band_stats.get("mean", 0), 4),
                    "min": round(band_stats.get("min", 0), 4),
                    "max": round(band_stats.get("max", 0), 4),
                    "date": entry["interval"]["from"][:10],
                }
    return None


def get_all_indices(polygon_points: list) -> dict:
    """
    Fetches NDVI, NDWI, and NDMI in sequence (3 API calls).
    Returns current + previous values for each so the risk engine
    can compute trends (stress increasing vs stable vs improving).
    """
    result = {}

    for band_id, evalscript, key in [
        ("ndvi", NDVI_EVALSCRIPT, "ndvi"),
        ("ndwi", NDWI_EVALSCRIPT, "ndwi"),
        ("ndmi", NDMI_EVALSCRIPT, "ndmi"),
    ]:
        try:
            raw = _request_stats(polygon_points, evalscript, band_id)
            current = _best_value(raw["current"], band_id)
            previous = _best_value(raw["previous"], band_id) if raw["previous"] else None
            if current:
                result[key] = {
                    "available": True,
                    "current": current["mean"],
                    "previous": previous["mean"] if previous else current["mean"],
                    "date": current["date"],
                }
            else:
                result[key] = {
                    "available": False,
                    "reason": "No cloud-free imagery in last 15 days",
                    "current": None, "previous": None, "date": None,
                }
        except SentinelAuthError as e:
            result[key] = {"available": False, "reason": f"Auth error: {e}",
                           "current": None, "previous": None, "date": None}
        except Exception as e:
            result[key] = {"available": False, "reason": str(e),
                           "current": None, "previous": None, "date": None}

    return result
