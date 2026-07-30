"""
Handles OAuth2 authentication with Copernicus Data Space Ecosystem's
Sentinel Hub API. Tokens expire after ~10 minutes, so this caches the
current token and refreshes it automatically when it's about to expire.

To get credentials (free):
1. Sign up at https://dataspace.copernicus.eu/
2. Go to https://shapps.dataspace.copernicus.eu/dashboard/#/account/settings
3. Create an OAuth client -> copy Client ID and Client Secret
4. Set these as environment variables on Railway:
   SENTINEL_CLIENT_ID=...
   SENTINEL_CLIENT_SECRET=...
"""
import os
import time
import requests
from threading import Lock

TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"

_token_cache = {"access_token": None, "expires_at": 0}
_lock = Lock()


class SentinelAuthError(Exception):
    pass


def get_access_token() -> str:
    """
    Returns a valid access token, fetching a new one if the cached
    token is missing or about to expire. Thread-safe.
    """
    with _lock:
        now = time.time()
        if _token_cache["access_token"] and now < _token_cache["expires_at"] - 30:
            return _token_cache["access_token"]

        client_id = os.getenv("SENTINEL_CLIENT_ID")
        client_secret = os.getenv("SENTINEL_CLIENT_SECRET")

        if not client_id or not client_secret:
            raise SentinelAuthError(
                "SENTINEL_CLIENT_ID / SENTINEL_CLIENT_SECRET not set. "
                "Sign up free at https://dataspace.copernicus.eu/ and create "
                "an OAuth client, then set these as Railway environment variables."
            )

        response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=15,
        )

        if response.status_code != 200:
            raise SentinelAuthError(
                f"Copernicus auth failed ({response.status_code}): {response.text[:300]}"
            )

        data = response.json()
        _token_cache["access_token"] = data["access_token"]
        _token_cache["expires_at"] = now + data.get("expires_in", 600)
        return _token_cache["access_token"]


def is_configured() -> bool:
    """Quick check used by the API to report whether credentials exist
    at all, without making a network call."""
    return bool(os.getenv("SENTINEL_CLIENT_ID")) and bool(os.getenv("SENTINEL_CLIENT_SECRET"))
