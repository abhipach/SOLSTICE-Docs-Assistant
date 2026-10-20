"""Fixed demo login verification for the Streamlit prototype."""
from __future__ import annotations

import hashlib
import hmac

ALGORITHM = "pbkdf2_sha256"
MIN_ITERATIONS = 100_000
MAX_ITERATIONS = 1_000_000
DUMMY_PASSWORD_HASH = (
    f"{ALGORITHM}$600000$00000000000000000000000000000000$"
    "0000000000000000000000000000000000000000000000000000000000000000"
)
DEMO_USERNAME = "admin"
DEMO_PASSWORD_HASH = (
    "pbkdf2_sha256$600000$1ee06e3e8a8406a19c908901dbfa3b07$"
    "3b503919700f2d5795c28ce91e333d40334b47fdb146ffbd3026613f6e7fb2ba"
)
DEMO_USERS = {DEMO_USERNAME: DEMO_PASSWORD_HASH}


class AuthConfigurationError(ValueError):
    """Raised when configured login accounts are invalid."""


def _parse_hash(encoded: str) -> tuple[int, bytes, bytes]:
    try:
        algorithm, raw_iterations, raw_salt, raw_digest = encoded.split("$")
        iterations = int(raw_iterations)
        salt = bytes.fromhex(raw_salt)
        digest = bytes.fromhex(raw_digest)
    except (AttributeError, ValueError) as exc:
        raise AuthConfigurationError("A configured password hash is malformed") from exc

    if (
        algorithm != ALGORITHM
        or not MIN_ITERATIONS <= iterations <= MAX_ITERATIONS
        or len(salt) != 16
        or len(digest) != 32
    ):
        raise AuthConfigurationError("A configured password hash uses invalid parameters")
    return iterations, salt, digest


def verify_password(password: str, encoded: str) -> bool:
    iterations, salt, expected = _parse_hash(encoded)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)
