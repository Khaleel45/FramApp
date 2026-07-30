"""
Fetches real weather data from Open-Meteo (free, no API key needed).
Fixed to use the correct Open-Meteo v1 API parameter names.
"""
import requests
from datetime import datetime, timedelta, timezone


def get_weather_for_farm(lat: float, lng: float) -> dict:
    """
    Returns current + 7-day weather for a farm location.
    Uses Open-Meteo free API - works globally, no key required.
    """
    try:
        today = datetime.now(timezone.utc).date()
        week_ago = today - timedelta(days=7)

        # Correct Open-Meteo API - humidity is hourly only, not daily
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lng}"
            "&daily=temperature_2m_max,temperature_2m_min,"
            "precipitation_sum,wind_speed_10m_max,"
            "et0_fao_evapotranspiration"
            "&hourly=relative_humidity_2m,precipitation,temperature_2m"
            f"&start_date={week_ago}&end_date={today}"
            "&timezone=Asia%2FKolkata"
            "&wind_speed_unit=kmh"
        )

        res = requests.get(url, timeout=12)
        if res.status_code != 200:
            print(f"Open-Meteo returned {res.status_code}: {res.text[:200]}")
            return _default_weather(lat, lng)

        data = res.json()
        daily = data.get("daily", {})
        hourly = data.get("hourly", {})

        temps_max = daily.get("temperature_2m_max", [])
        temps_min = daily.get("temperature_2m_min", [])
        rainfall = daily.get("precipitation_sum", [])
        wind = daily.get("wind_speed_10m_max", [])
        et0 = daily.get("et0_fao_evapotranspiration", [])

        # Hourly humidity (use last 24 hours)
        hourly_humidity = hourly.get("relative_humidity_2m", [])
        hourly_rain = hourly.get("precipitation", [])
        hourly_temp = hourly.get("temperature_2m", [])

        # Latest day values
        latest_temp_max = _safe(temps_max, -1, 33)
        latest_temp_min = _safe(temps_min, -1, 24)
        latest_temp = (latest_temp_max + latest_temp_min) / 2
        latest_rain = _safe(rainfall, -1, 0)
        latest_wind = _safe(wind, -1, 12)
        latest_et0 = _safe(et0, -1, 4.5)

        # Humidity from hourly data (last 24 hours average)
        last_24h_humidity = [h for h in hourly_humidity[-24:] if h is not None]
        latest_humidity = sum(last_24h_humidity) / len(last_24h_humidity) if last_24h_humidity else 65.0

        # 7-day totals
        total_rain_7d = sum(r for r in rainfall if r is not None)
        rain_last_3d = sum(r for r in rainfall[-3:] if r is not None)

        # Leaf wetness (hours where humidity > 80% or rain > 0.1mm)
        leaf_wetness_hours = sum(
            1 for h, r in zip(hourly_humidity[-24:], hourly_rain[-24:])
            if (h or 0) > 80 or (r or 0) > 0.1
        )

        result = {
            "available": True,
            "temperature": round(latest_temp, 1),
            "temperature_max": round(latest_temp_max, 1),
            "temperature_min": round(latest_temp_min, 1),
            "humidity": round(latest_humidity, 1),
            "rainfall_today": round(latest_rain, 1),
            "rainfall_7d": round(total_rain_7d, 1),
            "rainfall_3d": round(rain_last_3d, 1),
            "wind_speed": round(latest_wind, 1),
            "et0": round(latest_et0, 2),
            "leaf_wetness_hours": leaf_wetness_hours,
            "date": str(today),
        }
        print(f"Weather OK for ({lat:.2f},{lng:.2f}): {result['temperature']}°C, "
              f"{result['humidity']}% RH, {result['rainfall_7d']}mm/7d")
        return result

    except requests.exceptions.ConnectionError as e:
        print(f"Weather API connection error for ({lat},{lng}): {e}")
        return _default_weather(lat, lng)
    except Exception as e:
        print(f"Weather API error for ({lat},{lng}): {e}")
        return _default_weather(lat, lng)


def _safe(lst, idx, default):
    try:
        v = lst[idx]
        return v if v is not None else default
    except (IndexError, TypeError):
        return default


def _default_weather(lat: float = 0, lng: float = 0) -> dict:
    """
    Fallback when API is unavailable. Uses seasonal estimates for
    Telangana/AP based on typical monsoon patterns rather than
    a single hardcoded value, so at least the risk models get
    plausible inputs even without live data.
    """
    from datetime import datetime
    month = datetime.now().month
    # Monsoon season (Jun-Sep): hot and humid
    if 6 <= month <= 9:
        temp, humidity, rain = 29.0, 82.0, 45.0
    # Winter (Nov-Feb): mild and dry
    elif month in (11, 12, 1, 2):
        temp, humidity, rain = 24.0, 55.0, 5.0
    # Summer (Mar-May): very hot, dry
    else:
        temp, humidity, rain = 36.0, 45.0, 2.0

    return {
        "available": False,
        "temperature": temp,
        "temperature_max": temp + 4,
        "temperature_min": temp - 4,
        "humidity": humidity,
        "rainfall_today": 0.0,
        "rainfall_7d": rain,
        "rainfall_3d": rain / 3,
        "wind_speed": 12.0,
        "et0": 4.5,
        "leaf_wetness_hours": 4 if humidity > 75 else 0,
        "date": str(datetime.now().date()),
    }
