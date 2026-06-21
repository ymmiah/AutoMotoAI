# Security Policy

**Last Updated**: June 21, 2026  
**Version**: 3.1.0

---

## Reporting Vulnerabilities

**Do NOT open a public GitHub issue for security vulnerabilities.**

Report privately to **ymmiah96@gmail.com** with subject:  
`[SECURITY] Vulnerability Report - AutoMoto AI`

Include: description, impact, reproduction steps, proof-of-concept, environment details.  
We acknowledge within **48 hours** and provide a fix timeline within **7 days**.

---

## Implemented Security Features (v3.1)

All five features below are **fully implemented** — not roadmap items.

### 1. Encrypted Configuration Storage (`src/core/secret_store.py`)

API keys are **never stored in plain text** on disk.

| Detail | Value |
|---|---|
| Algorithm | Fernet — AES-128-CBC + HMAC-SHA256 (symmetric authenticated encryption) |
| Key derivation | PBKDF2-HMAC-SHA256, 200 000 iterations |
| KDF "password" | SHA-256 of hostname + username + OS + machine arch |
| Salt | 16 random bytes, prepended to `~/.automotoai/secrets.enc` |
| File permissions | `0o600` — readable only by the owning user |
| Fallback | Plain `.env` if `cryptography` not installed (warns in logs) |

**Migrate existing .env keys to the encrypted store:**

```bash
# Via the API (while server is running)
curl -s -X POST http://127.0.0.1:5000/api/security/secrets/migrate \
  -H "X-Requested-With: XMLHttpRequest" \
  -H "Content-Type: application/json" \
  -d '{"session_token":""}'

# Or directly from Python
python -c "
from src.core.secret_store import secret_store
secret_store.migrate_from_env(['OPENAI_API_KEY','GEMINI_API_KEY','ANTHROPIC_API_KEY','BLACKBOX_API_KEY'])
"
```

After migration the `.env` file can be safely deleted or emptied.

---

### 2. Two-Factor Authentication (`src/core/totp.py`)

Sensitive operations require TOTP verification when 2FA is enabled.

**Protected operations:**
- `POST /api/monitor/kill` — terminate a process
- `POST /api/files/delete` — delete a file or directory
- `POST /api/apps/launch` — launch an application

**Setup flow:**

```
1. POST /api/auth/2fa/setup
   → Returns { otpauth_uri, secret, issuer }
   → Scan the otpauth_uri with Google Authenticator / Authy / 1Password

2. POST /api/auth/2fa/verify  { "code": "123456", "session_token": "…" }
   → Returns { sensitive_token, ttl_seconds: 1800 }

3. Include sensitive_token in all protected operation payloads:
   POST /api/monitor/kill  { "pid": 1234, "sensitive_token": "…", "session_token": "…" }
```

| Detail | Value |
|---|---|
| Algorithm | TOTP (RFC 6238), SHA-1, 30-second window |
| Clock tolerance | ±1 window (±30 s) to account for clock skew |
| Sensitive token lifetime | 30 minutes |
| Token format | `{expiry_unix}:{HMAC-SHA256}` |
| Secret storage | Encrypted secret store (see §1) |
| If not configured | All sensitive ops pass through (opt-in, non-breaking) |

**Check 2FA status:**

```
GET /api/auth/2fa/status → { "enabled": true/false }
```

---

### 3. Audit Logging (`src/core/audit.py`)

Every HTTP request is recorded in a tamper-evident audit log.

**Log file:** `logs/audit.jsonl` (one JSON object per line)

**Entry schema:**

```json
{
  "ts":          "2026-06-21T12:34:56.789Z",
  "session":     "a1b2c3d4e5f6",
  "ip":          "127.0.0.1",
  "method":      "POST",
  "path":        "/api/monitor/kill",
  "action":      "api_monitor_kill",
  "result":      "ok | error | denied",
  "status":      200,
  "duration_ms": 45,
  "extra":       { "reason": "…" },
  "hmac":        "sha256hex…"
}
```

**Integrity chain:**  
Each entry's `hmac` = HMAC-SHA256(`entry_json + prev_entry_hmac`, audit_key).  
This creates a chain: tampering with any entry breaks all subsequent HMACs.

**Verify integrity offline:**

```bash
python -m src.core.audit --verify
# → ✓ Audit log OK — 1024 entries verified.
# → ✗ Integrity violation at line 437
```

**Via the API:**

```
GET /api/security/audit/verify → { "ok": true, "message": "…" }
```

**HMAC key storage:** `~/.automotoai/audit.key` (`0o600`), auto-generated on first use.  
Override with `AUTOMOTO_AUDIT_KEY` environment variable.

**Session privacy:** Session tokens are stored as the first 12 hex characters of their SHA-256 hash — not the raw token.

---

### 4. Sandboxed Execution Environment (`src/core/sandbox.py`)

All 18 AI tool calls execute inside a sandboxed thread pool.

| Protection layer | Detail |
|---|---|
| **Execution timeout** | Each tool call runs in `concurrent.futures.ThreadPoolExecutor` with a configurable deadline (default 60 s). `TimeoutError` is returned to the AI as a tool result. |
| **Resource tracking** | Each session has a `ResourceGuard` counting file writes (default limit 200) and cumulative bytes written (default 500 MB). Exceeding either returns `PermissionError`. |
| **Path allowlist** | File operations may only access paths under `Path.home()` by default. Configurable via `SANDBOX_ALLOWED_PATHS`. |
| **Subprocess env stripping** | `clean_env()` strips `OPENAI_*`, `GEMINI_*`, `ANTHROPIC_*`, `BLACKBOX_*`, `FLASK_SECRET*`, `AWS_*`, `AZURE_*`, `GCP_*` from any child process environment. |

**Environment variables:**

| Variable | Default | Description |
|---|---|---|
| `SANDBOX_TOOL_TIMEOUT` | `60` | Seconds before a tool call times out |
| `SANDBOX_MAX_FILES` | `200` | Max file-write ops per session |
| `SANDBOX_MAX_BYTES` | `524288000` | Max bytes written per session (500 MB) |
| `SANDBOX_ALLOWED_PATHS` | `~` | Colon-separated allowed path prefixes |

**Sandbox status API:**

```
GET /api/security/status → { sandbox: { tool_timeout_s, max_files_per_session, … } }
```

---

### 5. Automatic Security Updates (`src/core/updater.py`)

A background daemon thread checks every installed package against PyPI on startup and every 24 hours.

**What it checks:**
- Installed version vs latest PyPI release for every entry in `requirements.txt`
- Critical packages (`cryptography`, `flask`, `openai`, `anthropic`, etc.) are flagged at `WARNING` level
- Results are exposed via `GET /api/security/status`

**What it does NOT do:**  
Packages are **never auto-installed**. Updates are reported only. Apply them manually:

```bash
pip install --upgrade cryptography flask openai anthropic pillow
# Or upgrade everything:
pip install --upgrade -r requirements.txt
```

**Configure check interval:**

```env
SECURITY_CHECK_INTERVAL_HOURS=24
```

---

## Existing Security Measures (v3.0)

| Measure | Implementation |
|---|---|
| **CSRF protection** | `X-Requested-With: XMLHttpRequest` required on all mutating endpoints |
| **Server-issued session tokens** | `secrets.token_urlsafe(32)` — clients cannot forge tokens |
| **App launch allowlist** | Only pre-approved executables (notepad, calc, chrome…) via `_ALLOWED_APPS` |
| **PID guard** | Cannot kill PID < 100 (init, kernel threads) |
| **Output path sandboxing** | Document + image writes restricted to `~/Documents/AutoMotoAI_Documents/` |
| **Input length limits** | Chat 120 KB · Document content 500 KB · Path 4096 B · Batch 20 files · Image upload 8 MB |
| **Sanitised error messages** | Stack traces and internal paths never returned to clients |
| **Security headers** | CSP · X-Frame-Options DENY · X-Content-Type-Options · X-XSS-Protection · Referrer-Policy · Permissions-Policy |
| **Safe integer parsing** | `_safe_int()` with explicit range clamping on all numeric params |
| **Download path traversal protection** | `Path(filename).name` strips all directory components |
| **Debug mode unconditionally off** | `debug=False` in `server.py`; never pass `FLASK_DEBUG=true` |
| **Loopback-only binding** | Default `WEB_HOST=127.0.0.1` |
| **No `shell=True`** | All subprocess calls use list arguments |
| **No `eval()` / `exec()`** | Confirmed absent in all source files |

---

## Quick Security Hardening Checklist

```bash
# 1. Install security packages
pip install cryptography pyotp qrcode[pil]

# 2. Migrate API keys to encrypted store
python -c "
from dotenv import load_dotenv; load_dotenv()
from src.core.secret_store import secret_store
secret_store.migrate_from_env([
    'OPENAI_API_KEY','GEMINI_API_KEY',
    'ANTHROPIC_API_KEY','BLACKBOX_API_KEY'
])
"

# 3. Set up 2FA (scan QR with authenticator app)
curl -X POST http://127.0.0.1:5000/api/auth/2fa/setup \
  -H "X-Requested-With: XMLHttpRequest" \
  -H "Content-Type: application/json" -d '{}'

# 4. Verify audit log integrity
python -m src.core.audit --verify

# 5. Check for security updates
curl http://127.0.0.1:5000/api/security/status | python -m json.tool

# 6. Scan dependencies for CVEs (optional)
pip install pip-audit && pip-audit -r requirements.txt
```

---

## Security API Reference

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/api/auth/2fa/setup` | POST | CSRF | Generate TOTP secret + OTPAuth URI |
| `/api/auth/2fa/verify` | POST | CSRF | Verify TOTP code → sensitive_token |
| `/api/auth/2fa/status` | GET | — | Check whether 2FA is configured |
| `/api/security/status` | GET | — | Full security posture: updates + sandbox + 2FA + audit |
| `/api/security/audit/verify` | GET | — | Verify audit log HMAC chain |
| `/api/security/secrets/migrate` | POST | CSRF | Migrate .env API keys to encrypted store |

---

## Network Security

AutoMoto AI binds to `127.0.0.1` (loopback) by default.  
**If you expose the server on a public interface you MUST add your own authentication layer** — a reverse proxy with TLS + HTTP Basic Auth, or a VPN.  Threats that loopback binding does not prevent:

- Other local processes (SSRF, local scripts) — mitigated by 2FA on sensitive ops
- Malicious browser extensions — mitigated by CSRF header check

---

## AI Provider Security

| Provider | Security Posture |
|---|---|
| OpenAI | SOC 2 Type II, enterprise-grade, data retention opt-out available |
| Google Gemini | Google Cloud security standards, GDPR compliant |
| Anthropic Claude | Constitutional AI, safety-focused, SOC 2 |
| BLACKBOX AI | API key auth, HTTPS enforced |

API keys are sent only to their respective provider endpoints — never logged, never returned to the browser.

---

## Hall of Fame

We thank security researchers who responsibly disclose vulnerabilities. Your name will be acknowledged here with your permission.

---

## Contact

- **Security issues**: ymmiah96@gmail.com (private)
- **General issues**: [GitHub Issues](https://github.com/ymmiah/automotoai/issues)
- **Discussions**: [GitHub Discussions](https://github.com/ymmiah/automotoai/discussions)
