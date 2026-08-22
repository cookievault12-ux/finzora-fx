"""HTTP Basic Auth, restricted to a single hardcoded account.

Simpler than a full Google OAuth flow (no Google Cloud Console setup
required) while meeting the same requirement: exactly one account can ever
log in, hardcoded rather than read from an env var, so nothing (a typo, a
copied config) can silently widen who's allowed in. The browser's native
Basic Auth prompt is used rather than a custom login page — no session
cookies to manage; the browser just resends credentials on every request
once the user enters them.

The password is never stored in plaintext anywhere — not in this code, not
in Railway's env vars, not in any file in this repo. Only its salted
PBKDF2-HMAC-SHA256 hash is stored, in the APP_PASSWORD_HASH env var.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials

# Hardcoded on purpose, not an env var — see module docstring.
ALLOWED_USERNAME = "cookievault12@gmail.com"

_PBKDF2_ITERATIONS = 200_000

_security = HTTPBasic()


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Returns 'salt_hex$digest_hex' — the only form of the password that
    should ever be written to disk, an env var, or a chat message."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, digest_hex = stored_hash.split("$", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    expected = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return hmac.compare_digest(expected.hex(), digest_hex)


def require_login(credentials: HTTPBasicCredentials = Depends(_security)) -> str:
    """FastAPI dependency: prompts the browser's native Basic Auth dialog
    if no (or wrong) credentials are supplied. Both username and password
    are compared with constant-time comparisons (hmac.compare_digest) to
    avoid leaking timing information about which part was wrong."""
    stored_hash = os.environ.get("APP_PASSWORD_HASH")
    if not stored_hash:
        raise HTTPException(status_code=500, detail="APP_PASSWORD_HASH is not configured.")

    username_ok = hmac.compare_digest(credentials.username, ALLOWED_USERNAME)
    password_ok = verify_password(credentials.password, stored_hash)
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
