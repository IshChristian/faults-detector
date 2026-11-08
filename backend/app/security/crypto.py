"""Encryption at rest for camera credentials (CREDENTIALS_ENCRYPTION_KEY, Fernet)."""
from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().credentials_encryption_key.encode())


def encrypt_secret(plain: str) -> bytes:
    return _fernet().encrypt(plain.encode())


def decrypt_secret(token: bytes) -> str:
    return _fernet().decrypt(bytes(token)).decode()
