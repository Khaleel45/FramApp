"""
Generates a visual zone map as SVG showing which parts of a farm
are stressed, healthy, or under pest/disease attack.

The farmer sees:
- Their farm boundary as a rectangle
- Each zone coloured by health (green = healthy, red = stressed)
- Zone name in compass direction (Northwest, Center, etc.)
- A clear label showing what's happening in each zone

This runs server-side and returns the SVG as a string.
The Flutter app displays it inline so the farmer immediately
sees WHICH part of their farm needs attention.
"""


def generate_zone_map_svg(
    zones: list,
    zone_results: list,
    farm_name: str,
    hotspot_zones: list,
) -> str:
    """
    Generates an SVG map of the farm split into zones.

    zones: list of zone dicts from zone_splitter.py
    zone_results: list of scan results per zone
    farm_name: display name
    hotspot_zones: list of zone names that are stressed

    Returns SVG string.
    """
    if not zones:
        return ""

    # Determine grid size from zone count
    total_zones = len(zones)
    if total_zones <= 4:
        grid = 2
    elif total_zones <= 9:
        grid = 3
    else:
        grid = 4

    # SVG dimensions
    SVG_W = 320
    SVG_H = 320
    PADDING = 32
    LABEL_H = 28
    map_w = SVG_W - 2 * PADDING
    map_h = SVG_H - 2 * PADDING - LABEL_H
    cell_w = map_w / grid
    cell_h = map_h / grid

    # Build zone result lookup
    result_by_name = {}
    for r in zone_results:
        result_by_name[r.get("zone_name", "")] = r

    hotspot_set = {h["zone"] if isinstance(h, dict) else h for h in hotspot_zones}

    # Color logic
    def zone_color(zone_name: str, result: dict) -> tuple:
        """Returns (fill, stroke, text_color)"""
        ndvi = result.get("ndvi", 0.5) if result else 0.5
        pest = result.get("pest_risk_percent", 0) if result else 0
        is_hotspot = zone_name in hotspot_set

        if is_hotspot or (ndvi < 0.3 and ndvi > 0):
            # Critical — red
            return "#FEE2E2", "#DC2626", "#991B1B"
        elif pest > 50 or (ndvi < 0.45 and ndvi > 0):
            # Warning — amber
            return "#FEF3C7", "#D97706", "#92400E"
        elif ndvi >= 0.6:
            # Healthy — green
            return "#D1FAE5", "#059669", "#065F46"
        elif ndvi >= 0.45:
            # Moderate — light green
            return "#ECFDF5", "#10B981", "#065F46"
        else:
            # Unknown/no data — grey
            return "#F3F4F6", "#9CA3AF", "#374151"

    # Generate SVG
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {SVG_W} {SVG_H}" '
        f'width="{SVG_W}" height="{SVG_H}">',
        # Background
        f'<rect width="{SVG_W}" height="{SVG_H}" fill="#0D1117" rx="12"/>',
        # Title
        f'<text x="{SVG_W//2}" y="20" '
        f'text-anchor="middle" font-family="sans-serif" '
        f'font-size="11" font-weight="600" fill="#E5E7EB">'
        f'{farm_name[:28]} — Zone Analysis</text>',
        # Farm boundary outline
        f'<rect x="{PADDING}" y="{PADDING + 8}" '
        f'width="{map_w}" height="{map_h}" '
        f'fill="none" stroke="#374151" stroke-width="1.5" '
        f'stroke-dasharray="4 2" rx="4"/>',
    ]

    # Draw each zone
    for zone in zones:
        row = zone.get("row", 0)
        col = zone.get("col", 0)
        zone_name = zone.get("name", "")
        result = result_by_name.get(zone_name, {})

        x = PADDING + col * cell_w
        y = PADDING + 8 + row * cell_h
        w = cell_w - 2
        h = cell_h - 2

        fill, stroke, text_color = zone_color(zone_name, result)
        is_hotspot = zone_name in hotspot_set

        # Zone rectangle
        svg_parts.append(
            f'<rect x="{x+1:.1f}" y="{y+1:.1f}" '
            f'width="{w:.1f}" height="{h:.1f}" '
            f'fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{"2" if is_hotspot else "1"}" rx="3"/>'
        )

        # Hotspot indicator
        if is_hotspot:
            svg_parts.append(
                f'<rect x="{x+1:.1f}" y="{y+1:.1f}" '
                f'width="{w:.1f}" height="4" '
                f'fill="{stroke}" rx="3"/>'
            )

        # Zone name
        cx = x + cell_w / 2
        cy = y + cell_h / 2 - 6

        # Short name for small cells
        short_name = zone_name.replace("North", "N").replace("South", "S") \
                               .replace("East", "E").replace("West", "W") \
                               .replace("Center", "Ctr")

        svg_parts.append(
            f'<text x="{cx:.1f}" y="{cy:.1f}" '
            f'text-anchor="middle" dominant-baseline="middle" '
            f'font-family="sans-serif" font-size="9" '
            f'font-weight="600" fill="{text_color}">'
            f'{short_name}</text>'
        )

        # Pest risk if available
        pest = result.get("pest_risk_percent", 0) if result else 0
        ndvi = result.get("ndvi") if result else None
        if ndvi is not None:
            label = f"NDVI {ndvi:.2f}"
        elif pest > 0:
            label = f"Pest {pest}%"
        else:
            label = "No data"

        svg_parts.append(
            f'<text x="{cx:.1f}" y="{cy + 13:.1f}" '
            f'text-anchor="middle" dominant-baseline="middle" '
            f'font-family="sans-serif" font-size="8" '
            f'fill="{text_color}" opacity="0.8">'
            f'{label}</text>'
        )

        # Alert icon for hotspot
        if is_hotspot:
            svg_parts.append(
                f'<text x="{cx:.1f}" y="{cy + 24:.1f}" '
                f'text-anchor="middle" dominant-baseline="middle" '
                f'font-family="sans-serif" font-size="10" fill="#DC2626">'
                f'⚠</text>'
            )

    # Legend
    legend_y = SVG_H - 20
    items = [
        ("#D1FAE5", "#059669", "Healthy"),
        ("#FEF3C7", "#D97706", "Monitor"),
        ("#FEE2E2", "#DC2626", "Inspect"),
        ("#F3F4F6", "#9CA3AF", "No data"),
    ]
    total_legend_w = len(items) * 72
    legend_start = (SVG_W - total_legend_w) / 2

    for i, (fill, stroke, label) in enumerate(items):
        lx = legend_start + i * 72
        svg_parts.append(
            f'<rect x="{lx:.0f}" y="{legend_y - 8}" '
            f'width="10" height="10" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="1" rx="2"/>'
        )
        svg_parts.append(
            f'<text x="{lx + 13:.0f}" y="{legend_y:.0f}" '
            f'font-family="sans-serif" font-size="8" fill="#9CA3AF">'
            f'{label}</text>'
        )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)
