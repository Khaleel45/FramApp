"""
Silently splits a farm's GPS polygon into a grid of sub-zones for
granular scanning. The farmer never sees this — they see one farm with
one health score, but internally we scan each zone separately and can
pinpoint which part of the farm is under stress.

Zone naming uses compass directions so recommendations to the farmer
are human-readable: "Northwest zone shows high pest pressure"
rather than "Zone [2][1] has NDVI of 0.31".
"""
import math


# Zone names by grid position (row, col) — row 0 = north, col 0 = west
_ZONE_NAMES = {
    (0, 0): "Northwest", (0, 1): "North",    (0, 2): "Northeast",
    (1, 0): "West",      (1, 1): "Center",   (1, 2): "East",
    (2, 0): "Southwest", (2, 1): "South",    (2, 2): "Southeast",
}

# For 2x2 grids (smaller farms)
_ZONE_NAMES_2x2 = {
    (0, 0): "Northwest", (0, 1): "Northeast",
    (1, 0): "Southwest", (1, 1): "Southeast",
}


def split_into_zones(polygon_points: list, area_acres: float) -> list[dict]:
    """
    Splits a farm polygon into a grid of sub-zones based on farm size.
    Returns a list of zone dicts, each with:
      - name: human-readable direction (e.g. "Northwest")
      - polygon: GPS polygon for this zone (same format as farm polygon)
      - row, col: grid position
      - fraction: what fraction of total farm area this zone covers

    Grid size by area:
      < 5 acres  → 2x2 = 4 zones
      5-20 acres → 3x3 = 9 zones
      > 20 acres → 4x4 = 16 zones (named by compass + number)
    """
    if not polygon_points or len(polygon_points) < 3:
        return []

    # Determine grid size
    if area_acres < 5:
        grid = 2
    elif area_acres <= 20:
        grid = 3
    else:
        grid = 4

    # Compute bounding box of the polygon
    lats = [p["lat"] for p in polygon_points]
    lngs = [p["lng"] for p in polygon_points]
    min_lat, max_lat = min(lats), max(lats)
    min_lng, max_lng = min(lngs), max(lngs)

    lat_step = (max_lat - min_lat) / grid
    lng_step = (max_lng - min_lng) / grid

    zones = []
    for row in range(grid):
        for col in range(grid):
            zone_min_lat = min_lat + row * lat_step
            zone_max_lat = min_lat + (row + 1) * lat_step
            zone_min_lng = min_lng + col * lng_step
            zone_max_lng = min_lng + (col + 1) * lng_step

            # Zone polygon (always a rectangle)
            zone_polygon = [
                {"lat": zone_min_lat, "lng": zone_min_lng},
                {"lat": zone_max_lat, "lng": zone_min_lng},
                {"lat": zone_max_lat, "lng": zone_max_lng},
                {"lat": zone_min_lat, "lng": zone_max_lng},
            ]

            # Zone center point
            center_lat = (zone_min_lat + zone_max_lat) / 2
            center_lng = (zone_min_lng + zone_max_lng) / 2

            # Human-readable name
            if grid == 2:
                name = _ZONE_NAMES_2x2.get((row, col), f"Zone {row+1}-{col+1}")
            elif grid == 3:
                name = _ZONE_NAMES.get((row, col), f"Zone {row+1}-{col+1}")
            else:
                # 4x4: use quadrant + number
                quadrant = "North" if row < 2 else "South"
                side = "West" if col < 2 else "East"
                num = (row % 2) * 2 + (col % 2) + 1
                name = f"{quadrant}{side} {num}"

            zones.append({
                "name": name,
                "polygon": zone_polygon,
                "center_lat": center_lat,
                "center_lng": center_lng,
                "row": row,
                "col": col,
                "fraction": 1.0 / (grid * grid),
                "area_acres": round(area_acres / (grid * grid), 2),
            })

    return zones


def aggregate_zone_results(zone_results: list[dict], farm_name: str) -> dict:
    """
    Takes individual zone scan results and produces:
    1. Overall farm health score (area-weighted average)
    2. Zone-level alerts identifying which specific zones need attention
    3. A farmer-friendly summary explaining exactly where to look

    This is what the farmer sees — not the raw zone data.
    """
    if not zone_results:
        return {}

    available = [z for z in zone_results if z.get("ndvi_available")]
    if not available:
        return {
            "health_score": 70,
            "health_status": "No satellite data available",
            "zone_alerts": [],
            "summary": "No cloud-free satellite pass available for this scan.",
            "hotspot_zones": [],
        }

    # Weighted average health score
    avg_ndvi = sum(z["ndvi"] for z in available) / len(available)
    from app.services.crop_analysis import ndvi_to_health_score, ndvi_to_health_status
    health_score = ndvi_to_health_score(avg_ndvi)
    health_status = ndvi_to_health_status(avg_ndvi)

    # Find stressed zones (NDVI significantly below farm average)
    ndvi_values = [z["ndvi"] for z in available]
    ndvi_avg = sum(ndvi_values) / len(ndvi_values)
    ndvi_std = (sum((x - ndvi_avg)**2 for x in ndvi_values) / len(ndvi_values)) ** 0.5

    hotspot_zones = []
    zone_alerts = []

    for z in available:
        deviation = ndvi_avg - z["ndvi"]
        if deviation > max(0.08, ndvi_std * 1.2):
            severity = "High" if deviation > 0.15 else "Moderate"
            hotspot_zones.append({
                "zone": z["zone_name"],
                "ndvi": round(z["ndvi"], 3),
                "deviation": round(deviation, 3),
                "severity": severity,
                "pest_risk": z.get("pest_risk_percent", 0),
                "disease_risk": z.get("disease_risk_level", "Low"),
            })
            zone_alerts.append({
                "zone": z["zone_name"],
                "severity": severity,
                "message": (
                    f"{z['zone_name']} zone shows {'significant' if severity == 'High' else 'moderate'} "
                    f"crop stress (NDVI {z['ndvi']:.2f} vs farm average {ndvi_avg:.2f}). "
                    f"{'Immediate inspection recommended.' if severity == 'High' else 'Monitor closely.'}"
                ),
                "pest_risk": z.get("pest_risk_percent", 0),
            })

    # Sort hotspots by severity
    hotspot_zones.sort(key=lambda x: x["deviation"], reverse=True)

    # Build farmer-friendly summary
    if not hotspot_zones:
        summary = (
            f"Your farm '{farm_name}' looks healthy across all zones. "
            f"Average crop health: {health_score}% ({health_status}). "
            f"No localized stress areas detected."
        )
    elif len(hotspot_zones) == 1:
        hz = hotspot_zones[0]
        summary = (
            f"⚠️ Stress detected in the {hz['zone']} zone of '{farm_name}'. "
            f"This area shows {hz['severity'].lower()} crop stress "
            f"compared to the rest of the farm. "
            f"Inspect the {hz['zone']} section first — this may indicate "
            f"early pest activity or water stress before it spreads. "
            f"Overall farm health: {health_score}%."
        )
    else:
        zone_list = ", ".join(h["zone"] for h in hotspot_zones[:3])
        worst = hotspot_zones[0]
        summary = (
            f"⚠️ Multiple stress zones detected in '{farm_name}': {zone_list}. "
            f"The {worst['zone']} zone is most affected. "
            f"Prioritize inspection of these areas to prevent spread to "
            f"the rest of the farm. Overall farm health: {health_score}%."
        )

    return {
        "health_score": health_score,
        "health_status": health_status,
        "zone_count": len(zone_results),
        "zones_scanned": len(available),
        "zone_alerts": zone_alerts,
        "hotspot_zones": hotspot_zones,
        "summary": summary,
        "ndvi_average": round(ndvi_avg, 3),
        "ndvi_min": round(min(ndvi_values), 3),
        "ndvi_max": round(max(ndvi_values), 3),
    }
