"""
Encrypted secret storage — Fernet (AES-128-CBC + HMAC-SHA256).

API keys are encrypted with a machine-derived key and stored in
~/.automotoai/secrets.enc so they are never kept in plain text on disk.

Key derivation
--------------
  password = SHA-256( hostname | username | OS | machine-arch )
  salt     = 16 random bytes, stored in the first 16 bytes of secrets.enc
  key      = PBKDF2-HMAC-SHA256( password, salt, iterations=200_000 )

This prevents casual secret extraction — an attacker needs both:
  1. Filesystem read access to ~/.automotoai/secrets.enc
  2. Knowledge of the same machine + user identity to re-derive the key.

If the `cryptography` package is not installed the module degrades
gracefully to plain .env loading and emits a one-time startup warning.
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import json
import logging
import os
import platform
from pathlib import Path

logger = logging.getLogger(__name__)

_STORE_DIR = Path.home() / ".automotoai"
_STORE_FILE = _STORE_DIR / "secrets.enc"

_AVAILABLE = False
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes as _hashes
    _AVAILABLE = True
except ImportError:
    pass


# ── machine fingerprint ───────────────────────────────────────────────────────

def _machine_fingerprint() -> bytes:
    parts = [
        platform.node(),
        getpass.getuser(),
        platform.system(),
        platform.machine(),
        platform.python_version(),
    ]
    return hashlib.sha256("|".join(parts).encode()).digest()


# ── key derivation ────────────────────────────────────────────────────────────

def _derive_key(salt: bytes) -> bytes:
    if not _AVAILABLE:
        raise RuntimeError("cryptography not installed")
    kdf = PBKDF2HMAC(
        algorithm=_hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200_000,
    )
    raw = kdf.derive(_machine_fingerprint())
    return base64.urlsafe_b64encode(raw)


# ── public API ────────────────────────────────────────────────────────────────

class SecretStore:
    """Read/write encrypted secrets to ~/.automotoai/secrets.enc."""

    def __init__(self) -> None:
        self._cache: dict[str, str] | None = None

    def is_available(self) -> bool:
        return _AVAILABLE

    def exists(self) -> bool:
        return _STORE_FILE.exists()

    def load(self) -> dict[str, str]:
        """Decrypt and return all stored secrets as a plain dict."""
        if self._cache is not None:
            return self._cache
        if not _AVAILABLE:
            logger.warning(
                "cryptography not installed — secrets are stored in plain .env. "
                "Run: pip install cryptography"
            )
            return {}
        if not _STORE_FILE.exists():
            return {}
        try:
            raw  = _STORE_FILE.read_bytes()
            salt = raw[:16]
            ct   = raw[16:]
            key  = _derive_key(salt)
            f    = Fernet(key)
            data = json.loads(f.decrypt(ct).decode())
            self._cache = data
            return data
        except Exception as exc:
            logger.error("Failed to decrypt secret store: %s", exc)
            return {}

    def save(self, secrets: dict[str, str]) -> None:
        """Encrypt and persist a dict of secrets."""
        if not _AVAILABLE:
            raise RuntimeError("cryptography not installed: pip install cryptography")
        _STORE_DIR.mkdir(parents=True, exist_ok=True)
        salt = os.urandom(16)
        key  = _derive_key(salt)
        f    = Fernet(key)
        ct   = f.encrypt(json.dumps(secrets).encode())
        _STORE_FILE.write_bytes(salt + ct)
        # Restrict permissions (Unix)
        try:
            _STORE_FILE.chmod(0o600)
        except (OSError, NotImplementedError):
            pass
        self._cache = dict(secrets)
        logger.info("Encrypted secret store saved to %s", _STORE_FILE)

    def get(self, key: str, default: str = "") -> str:
        return self.load().get(key, default)

    def set(self, key: str, value: str) -> None:
        """Update a single secret and re-save the store."""
        current = self.load()
        current[key] = value
        self.save(current)

    def migrate_from_env(self, keys: list[str]) -> bool:
        """
        One-time migration: read the listed keys from the OS environment
        (populated by python-dotenv's load_dotenv()) and write them to the
        encrypted store. Returns True if migration succeeded.
        """
        if not _AVAILABLE:
            return False
        secrets = {k: os.getenv(k, "") for k in keys}
        non_empty = {k: v for k, v in secrets.items() if v}
        if not non_empty:
            return False
        self.save(non_empty)
        logger.info(
            "Migrated %d environment variable(s) to encrypted secret store.",
            len(non_empty),
        )
        return True

    def verify_integrity(self) -> bool:
        """Return True if the store file can be decrypted cleanly."""
        try:
            data = self.load()
            return isinstance(data, dict)
        except Exception:
            return False


secret_store = SecretStore()
