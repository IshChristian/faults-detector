"""Short-lived signed media URLs. The signature is the authorisation, so <img>/<video> tags work."""
import hashlib
import hmac
import time
from urllib.parse import quote

from app.config import get_settings


def _sig(key: str, exp: int) -> str:
    secret = get_settings().secret_key.encode()
    return hmac.new(secret, f"media:{key}:{exp}".encode(), hashlib.sha256).hexdigest()


def sign_media_url(key: str, ttl_seconds: int = 300, now: int | None = None) -> str:
    exp = (int(time.time()) if now is None else now) + ttl_seconds
    return f"/api/v1/media/{quote(key, safe='/')}?exp={exp}&sig={_sig(key, exp)}"


def verify_media_signature(key: str, exp: int, sig: str, now: int | None = None) -> bool:
    if (int(time.time()) if now is None else now) > exp:
        return False
    return hmac.compare_digest(_sig(key, exp), sig)
