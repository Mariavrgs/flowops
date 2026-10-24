import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# argon2-cffi's PasswordHasher uses Argon2id with the library's recommended defaults.
_hasher = PasswordHasher()

# Verified against when the email is unknown, so "unknown email" and "wrong password"
# take comparable time and cannot be told apart by timing.
DUMMY_HASH = _hasher.hash("flowops-dummy-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_token() -> str:
    """256 bits of randomness, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
