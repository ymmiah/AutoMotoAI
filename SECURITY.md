# Security — AutoMoto AI v4

This file describes what the code in this repo **actually does**. (Earlier v3.x docs
listed features such as TOTP 2FA and encrypted key vaults that were never in the code;
they have been removed.)

## API keys (BYOK)
- No keys are baked in. You add your own in `.env` (git-ignored) or per session.
- Placeholder values from `.env.example` are ignored.
- The web UI's 🔑 Keys dialog keeps keys in `sessionStorage` only — they vanish when the
  tab closes, and are sent only to your local AutoMoto server for that request.
- The mobile app stores keys in the iOS Keychain / Android Keystore (`flutter_secure_storage`).
- Keys are never logged and never returned by `/api/status` (tests enforce this).
- Keys are sent only to the provider being called.

## Local server
- Binds to `127.0.0.1:8765` by default.
- Browser calls must carry a per-launch session token injected into the served page, so other
  websites you visit cannot drive your local API (CSRF protection; no CORS is enabled).
- Listening on a network interface (for the mobile app) is refused unless
  `AUTOMOTO_API_TOKEN` is set; remote clients must send `Authorization: Bearer <token>`.
  Use it only on a network you trust, or behind a VPN such as Tailscale.

## Desktop actions
- The AI can only **propose** actions from a fixed tool list; unknown tools are dropped.
- Anything that changes your machine (`confirm` / `danger` risk) needs your explicit Run / `y`.
- Desktop tools and screen capture are only available to clients on the same computer —
  never to the mobile app or other LAN clients.
- `run_command` is disabled unless `AUTOMOTO_ALLOW_SHELL=1`, and is still confirmed each time.
- `create_file` never overwrites; relative paths land in `AUTOMOTO_WORKDIR` (default `~/AutoMoto`).
- No delete tool exists. `pyautogui` fail-safe is on (slam the mouse into a corner to abort).
- Use AutoMoto only on machines you own or are authorised to automate.

## Reporting a vulnerability
Please open a private security advisory on GitHub
(<https://github.com/ymmiah/AutoMotoAI/security/advisories/new>) rather than a public issue.
