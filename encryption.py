import os
from cryptography.fernet import Fernet, InvalidToken


def _get_fernet() -> Fernet | None:
    key = os.getenv("DB_ENCRYPTION_KEY")
    if not key:
        return None
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str | None) -> str | None:
    if value is None:
        return None
    f = _get_fernet()
    if f is None:
        return value
    return f.encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if value is None:
        return None
    f = _get_fernet()
    if f is None:
        return value
    try:
        return f.decrypt(value.encode()).decode()
    except (InvalidToken, Exception):
        # Graceful fallback for any pre-encryption plaintext already in the DB
        return value
