"""Secret redaction for logs, events, errors and API responses.

Two layers, both applied by :func:`redact`:

* **Patterns** for every GitHub and GitLab token prefix (and a few other common keys), including
  *partial* forms such as ``ghp_abcd…`` and tokens that were percent-encoded or base64'd (for
  example an echoed ``Authorization: Basic`` header).
* **Known secrets** registered at runtime (tokens loaded from the keychain or pasted at sign-in).
  For those we also catch the URL-encoded and base64 forms and any fragment of 12 or more
  characters, so a token that was cut in half or wrapped across two lines is still hidden.

:func:`install_log_redaction` wraps the logging record factory, so every log record in the process
(ours, uvicorn's and third-party libraries') is scrubbed before any handler sees it.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
import threading
import urllib.parse

MASK = "[redacted]"
# GitHub and GitLab tokens: the prefix plus at least 4 token characters, so partial forms such as
# "ghp_abcd…" are caught too. Other providers' keys need a realistic length, so ordinary words like
# "npm_config" or "hf_hub_download" in code and logs are left alone.
_GIT_PREFIXES = r"github_pat_|gh[pousr]_|gl(?:pat|oas|rt|dt|ft|cbt|ptt|soat|imt|agent|ffct|wt)-"
TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:(?:" + _GIT_PREFIXES + r")[A-Za-z0-9_\-.]{4,}"
    r"|xox[abposr]-[A-Za-z0-9-]{10,}|sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}|[rs]k_live_[A-Za-z0-9]{16,}"
    r"|(?:AKIA|ASIA)[A-Z0-9]{16}|AIza[A-Za-z0-9_\-]{30,}|hf_[A-Za-z0-9]{30,}|npm_[A-Za-z0-9]{30,})")
PEM_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)")
_B64_RUN = re.compile(r"[A-Za-z0-9+/_\-]{24,}={0,2}")
_PCT_RUN = re.compile(r"(?:%[0-9A-Fa-f]{2}|[A-Za-z0-9_.~\-])*%[0-9A-Fa-f]{2}(?:%[0-9A-Fa-f]{2}|[A-Za-z0-9_.~\-])*")
_FRAGMENT = 12

_lock = threading.Lock()
_known: dict[str, tuple[set[str], tuple[str, ...]]] = {}


def _variants(secret: str) -> tuple[str, ...]:
    raw = secret.encode()
    out = {secret, urllib.parse.quote(secret, safe=""), "".join(f"%{b:02X}" for b in raw),
           "".join(f"%{b:02x}" for b in raw), raw.hex()}
    for pre in (b"", b"x-access-token:", b"oauth2:", b":", b"git:"):
        for enc in (base64.b64encode, base64.urlsafe_b64encode):
            out.add(enc(pre + raw).decode().rstrip("="))
            out.add(enc(raw + b":").decode().rstrip("="))
    # Base64 of the token at any alignment inside a longer blob: drop the edge characters that
    # depend on the neighbouring bytes.
    for shift in (1, 2):
        enc = base64.b64encode(b"\0" * shift + raw).decode().rstrip("=")
        out.add(enc[4:-2])
    return tuple(v for v in out if len(v) >= 8)


def register(secret: str | None) -> None:
    """Remember a secret for this process so every later redact() hides it in any form."""
    s = (secret or "").strip()
    if len(s) < 8:
        return
    with _lock:
        if s in _known:
            return
        windows = {s[i:i + _FRAGMENT] for i in range(len(s) - _FRAGMENT + 1)} if len(s) >= 20 else set()
        _known[s] = (windows, _variants(s))


def forget(secret: str | None) -> None:
    with _lock:
        _known.pop((secret or "").strip(), None)


def _decoded_hit(blob: str) -> bool:
    for cand in (blob, blob + "=" * (-len(blob) % 4)):
        for dec in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                txt = dec(cand.encode()).decode("utf-8", "ignore")
            except (binascii.Error, ValueError):
                continue
            if TOKEN_RE.search(txt) or any(k in txt for k in _known):
                return True
    return False


def _fragments(text: str, windows: set[str]) -> str:
    if not windows or len(text) < _FRAGMENT:
        return text
    hits: list[tuple[int, int]] = []
    i, n = 0, len(text)
    while i <= n - _FRAGMENT:
        if text[i:i + _FRAGMENT] in windows:
            j = i + _FRAGMENT
            while j < n and text[j - _FRAGMENT + 1:j + 1] in windows:
                j += 1
            hits.append((i, j))
            i = j
        else:
            i += 1
    if not hits:
        return text
    out, last = [], 0
    for a, b in hits:
        out.append(text[last:a])
        out.append(MASK)
        last = b
    out.append(text[last:])
    return "".join(out)


def redact(text, extra: tuple[str, ...] | list[str] = ()) -> str:
    """Return ``text`` with every token-looking value and every known secret replaced."""
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    for e in extra or ():
        register(e)
        e = (e or "").strip()
        if len(e) >= 4:  # short test keys are still replaced exactly
            s = s.replace(e, MASK)
    with _lock:
        known = list(_known.items())
    for secret, (windows, variants) in sorted(known, key=lambda kv: -len(kv[0])):
        for v in sorted(variants, key=len, reverse=True):
            if v in s:
                s = s.replace(v, MASK)
        s = _fragments(s, windows)
    s = PEM_RE.sub(MASK, s)
    s = TOKEN_RE.sub(MASK, s)
    if "%" in s:
        s = _PCT_RUN.sub(lambda m: MASK if _hit_plain(urllib.parse.unquote(m.group(0))) else m.group(0), s)
    s = _B64_RUN.sub(lambda m: MASK if _decoded_hit(m.group(0)) else m.group(0), s)
    return s


def _hit_plain(txt: str) -> bool:
    return bool(TOKEN_RE.search(txt)) or any(k in txt for k in list(_known))


def contains_secret(text: str, secret: str) -> bool:
    """True if ``secret`` (or an encoded form or a 12+ character fragment of it) is in ``text``.
    Used by the tests and by the sign-in endpoints as a last guard before answering."""
    if not secret:
        return False
    if any(v in text for v in _variants(secret)):
        return True
    if len(secret) >= 20:
        return any(secret[i:i + _FRAGMENT] in text for i in range(len(secret) - _FRAGMENT + 1))
    return False


_installed = False


def install_log_redaction() -> None:
    """Scrub every log record in this process (message, args and traceback) before it is handled."""
    global _installed
    if _installed:
        return
    _installed = True
    base_factory = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = base_factory(*args, **kwargs)
        try:
            msg = record.getMessage()
            clean = redact(msg)
            if clean != msg:
                record.msg, record.args = clean, None
            if record.exc_info:
                text = logging.Formatter().formatException(record.exc_info)
                record.exc_text = redact(text)
            if record.stack_info:
                record.stack_info = redact(record.stack_info)
        except Exception:  # never let redaction break logging itself
            record.msg, record.args = "[log message hidden: could not be checked for secrets]", None
        return record

    logging.setLogRecordFactory(factory)
