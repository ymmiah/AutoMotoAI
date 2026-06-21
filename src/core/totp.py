"""
TOTP-based two-factor authentication (RFC 6238).

Uses pyotp for code generation and verification.  The TOTP secret is
stored in the encrypted secret store (secret_store.py).

Workflow
--------
  1. User calls POST /api/auth/setup-2fa
       → server generates a TOTP secret, saves it to encrypted store,
         returns an otpauth:// URI the user scans with an authenticator app.
  2. User calls POST /api/auth/verify-2fa  { "code": "123456" }
       → server verifies the TOTP code and issues a short-lived
         "sensitive_token" (valid 30 minutes) returned in the response.
  3. Sensitive API operations check for the sensitive_token in the
     request body. If 2FA is configured and the token is absent/expired,
     the request is rejected with HTTP 403.

If pyotp is not installed or no 2FA secret has been configured, all
checks pass (2FA is opt-in and non-breaking for existing users).
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_2FA_KEY  = "AUTOMOTO_2FA_SECRET"
_TOTP_ISSUER  = "AutoMotoAI"
_TOKEN_TTL    = 30 * 60   # 30-minute sensitive-operation window
_SENSITIVE_KEY_FILE = Path.home() / ".automotoai" / ".sensitive_key"

_AVAILABLE = False
try:
    import pyotp as _pyotp
    _AVAILABLE = True
except ImportError:
    pass


# ── signing key for sensitive tokens ─────────────────────────────────────────

def _signing_key() -> bytes:
    if _SENSITIVE_KEY_FILE.exists():
        return _SENSITIVE_KEY_FILE.read_bytes()
    key = os.urandom(32)
    _SENSITIVE_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SENSITIVE_KEY_FILE.write_bytes(key)
    try:
        _SENSITIVE_KEY_FILE.chmod(0o600)
    except (OSError, NotImplementedError):
        pass
    return key


# ── TOTP secret management ────────────────────────────────────────────────────

def _get_secret() -> str | None:
    from src.core.secret_store import secret_store
    val = secret_store.get(_2FA_KEY, "")
    return val or None


# ── public API ────────────────────────────────────────────────────────────────

def is_enabled() -> bool:
    """Return True if a TOTP secret has been configured."""
    return _AVAILABLE and bool(_get_secret())


def setup() -> dict:
    """
    Generate a new TOTP secret and return setup info.

    Returns
    -------
    {
      "secret":      base32 secret (show to user once, then discard),
      "otpauth_uri": otpauth:// URI for QR-code scanners,
      "issuer":      "AutoMotoAI",
    }
    """
    if not _AVAILABLE:
        raise RuntimeError("pyotp not installed: pip install pyotp")
    import getpass
    secret   = _pyotp.random_base32()
    account  = getpass.getuser() + "@automotoai"
    totp     = _pyotp.TOTP(secret)
    uri      = totp.provisioning_uri(name=account, issuer_name=_TOTP_ISSUER)
    # Persist encrypted
    from src.core.secret_store import secret_store
    secret_store.set(_2FA_KEY, secret)
    logger.info("2FA TOTP secret configured for %s", account)
    return {"secret": secret, "otpauth_uri": uri, "issuer": _TOTP_ISSUER}


def verify_code(code: str) -> bool:
    """Verify a TOTP code, accepting ±1 time window (30-second grace)."""
    if not _AVAILABLE:
        return False
    secret = _get_secret()
    if not secret:
        return False
    try:
        totp = _pyotp.TOTP(secret)
        return totp.verify(str(code).strip(), valid_window=1)
    except Exception as exc:
        logger.error("TOTP verify error: %s", exc)
        return False


def issue_sensitive_token(session_token: str) -> str:
    """
    Issue a short-lived token (TTL = 30 min) that authorises sensitive
    operations for the given session.  Format: "<expiry>:<hmac>".
    """
    expiry = int(time.time()) + _TOKEN_TTL
    payload = f"{expiry}:{session_token}".encode()
    mac     = _hmac.new(_signing_key(), payload, hashlib.sha256).hexdigest()
    return f"{expiry}:{mac}"


def validate_sensitive_token(token: str, session_token: str) -> bool:
    """
    Return True if *token* is a valid sensitive-operation token for
    *session_token* and has not expired.
    """
    try:
        expiry_str, mac = token.rsplit(":", 1)
        expiry = int(expiry_str)
    except (ValueError, AttributeError):
        return False
    if int(time.time()) > expiry:
        return False
    payload  = f"{expiry}:{session_token}".encode()
    expected = _hmac.new(_signing_key(), payload, hashlib.sha256).hexdigest()
    return _hmac.compare_digest(mac, expected)


def check_sensitive(token: str, session_token: str) -> bool:
    """
    If 2FA is enabled, require a valid sensitive_token.
    If 2FA is not configured, allow the operation unconditionally.
    """
    if not is_enabled():
        return True    # 2FA opt-in — pass through if not configured
    return validate_sensitive_token(token, session_token)
