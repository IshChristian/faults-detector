import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.common.errors import ApiError
from app.config import get_settings

_hasher = PasswordHasher()  # argon2id with library defaults
_ALGORITHM = "HS256"


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(pw: str, hash: str) -> bool:
    try:
        return _hasher.verify(hash, pw)
    except (VerificationError, InvalidHashError):
        return False


# Verifying against this keeps unknown-email logins as slow as wrong-password logins.
DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


def create_access_token(user) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    claims = {
        "sub": str(user.id),
        "role": user.role,
        "cid": str(user.customer_id) if user.customer_id else None,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=s.access_token_minutes),
    }
    return jwt.encode(claims, s.secret_key, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        claims = jwt.decode(token, get_settings().secret_key, algorithms=[_ALGORITHM],
                            options={"require": ["sub", "exp", "type"]})
    except jwt.PyJWTError as e:
        raise ApiError(401, "invalid-token", "Invalid or expired token") from e
    if claims.get("type") != "access":
        raise ApiError(401, "invalid-token", "Invalid or expired token")
    return claims


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_refresh_token(raw)
