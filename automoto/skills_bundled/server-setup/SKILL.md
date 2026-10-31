---
name: server-setup
description: Help the user run their own server - on their PC, through a free Cloudflare Tunnel, with Docker, or on a free cloud VM (Oracle Always Free) - with checks, ready-made files and step-by-step guidance.
category: system
tools: server_setup, run_shell, system_info
status: live
---
# Set up your own server

Talk like you are helping a beginner. Short steps, one at a time, and say what each step does.

1. **Ask what they want** (only if unclear): just this computer, reach it from their phone, or always on in the
   cloud. Free options first: `local` → `tunnel` (free Cloudflare quick tunnel) → `docker` → `oracle`
   (Always Free VM, always on). `render` is a demo only: its free plan wipes data on every restart.
2. **Check**: `server_setup action=check`. Explain any ✗ in plain words (e.g. "Docker isn't installed - only
   needed for the Docker option").
3. **Plan**: `server_setup action=plan target=<choice>` and show the numbered steps.
4. **Write the files**: `server_setup action=write target=<choice>` (add `domain=` if they have one). Files go to
   `artifacts/server-setup/<target>/`; link the folder and `CHECKLIST.md`.
5. **Walk through it**: one step at a time. After each step, run its check (e.g. `docker --version`,
   `curl -s 127.0.0.1:8765/api/health`) with `run_shell` **only if they ask you to**; each command needs their
   approval. Never run installers silently.

Safety rules
- Never ask for, store or write real API keys or passwords into files or chat. `.env.template` has placeholders;
  the user fills them in themselves and keeps `.env` private.
- Public servers must use multi-user mode (`AUTOMOTO_MODE=multiuser`), a long admin password, HTTPS (tunnel or
  Caddy) and `AUTOMOTO_ALLOWED_HOSTS` set to the real host name.
- Never open SSH or database ports to the internet; only 443 (or nothing, with a tunnel).
- Do not sign the user up for anything. Tell them which site to visit and what to click.
- Full guide: docs/SERVER-SETUP.md.
