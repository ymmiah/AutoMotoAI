# Hosting AutoMoto AI for other people (multi-user mode)

AutoMoto AI normally runs **single-user on your own computer** (`python -m automoto serve`). Nothing in this
guide changes that. **Hosted mode** is an opt-in second way to run it: one server, many accounts, each with
its own sandbox and a usage limit (1 hour a day by default) that you control as the admin.

```bash
AUTOMOTO_MODE=multiuser python -m automoto serve --hosted      # or: docker run ... (below)
```

## What people get (and don't get)

| | Local mode (default) | Hosted mode |
|---|---|---|
| Who | you | anyone with an account |
| Sign-in | one-time link / token | username + password (scrypt), session cookie |
| Tools | everything, incl. shell, local apps, desktop, connectors | web research, memory, skills, Office / archive / WordPress / data files, chat |
| Files | sandbox + folders you allow | the user's own workspace only (`<data>/users/<id>/`) |
| Approvals | your policy | always **ask** |
| AI keys | yours (BYOK) | the server's keys; users can't add their own |
| Usage limit | none | per user, per period (default 60 min / day) |

Not available to hosted users (admins included): shell commands, running apps, desktop control, your
folders, MCP / connector secrets, routines, settings. Those routes return 404 in hosted mode — the server
uses an allow-list, so a new endpoint is closed until it's reviewed for hosted use.

## How usage is counted

* **Active usage** = wall-clock time the server spends on model calls (agent steps, chat replies, run
  summaries) **plus** tool run time. Time spent waiting for the user to approve, or idle, doesn't count.
* The limit is checked **before every model call**. A call that's already running finishes; the next one is
  refused with *"You've reached your usage limit… resets at X"*. The GUI shows a meter in the sidebar.
* Period: a day starting at `AUTOMOTO_QUOTA_RESET_HOUR` (UTC, default 0). Set `AUTOMOTO_QUOTA_PERIOD_DAYS=7` for weekly.
* Optional caps per period: AI requests (`AUTOMOTO_DEFAULT_REQUEST_CAP`) and estimated tokens
  (`AUTOMOTO_DEFAULT_TOKEN_CAP`, ~4 characters per token).
* Admins are unlimited. Suspended users can't sign in.

## Admin guide

Create yourself as admin first (CLI on the server, or the two env vars on a container host):

```bash
python -m automoto admin create yasin                 # prompts for a password (10+ chars)
# or: AUTOMOTO_ADMIN_USER=yasin AUTOMOTO_ADMIN_PASSWORD='…'  (only used when no admin exists yet)
```

Then sign in to the web page → **Admin**. Everything there also exists on the CLI:

| Task | GUI (Admin page) | CLI |
|---|---|---|
| List users and usage | Users table | `automoto admin list` |
| Give someone more time **today** | **+ Bonus** (minutes, expires at the next reset by default) | `automoto admin bonus ben 30` |
| Change someone's limit | **Quota** → minutes, or blank for unlimited | `automoto admin quota ben --minutes 120` / `--unlimited` / `--default` |
| Start their period over | **Reset** | `automoto admin reset ben` |
| Suspend / unsuspend | **Suspend** | `automoto admin suspend ben` / `unsuspend` |
| Delete (and their files) | **Delete** | `automoto admin delete ben --yes` |
| Change the default for everyone | Defaults → *Default minutes / period* | `automoto admin settings --default-minutes 60` |
| Open sign-up / invite-only / closed | Defaults → *Sign-up* | `automoto admin settings --signup invite` |
| Invite codes | Invite codes → link `/?invite=am-…` | `automoto admin invite --uses 5 --days 7` |
| Usage and audit logs | bottom of the page | `automoto admin usage` / `automoto admin audit` |

Every admin action goes to the audit log. Admins can't suspend, demote or delete themselves, and the last
admin can't be removed.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `AUTOMOTO_MODE` | *(local)* | `multiuser` turns hosted mode on (the Docker image sets it) |
| `AUTOMOTO_DATA_DIR` | `~/.automoto` | all data: `accounts.db`, `users/<id>/…` (`/data` in Docker) |
| `NVIDIA_API_KEY` (or other provider keys) | — | the AI keys all users share — **set as a secret**, never in the repo |
| `AUTOMOTO_ADMIN_USER` / `AUTOMOTO_ADMIN_PASSWORD` | — | create the first admin on start if none exists |
| `AUTOMOTO_ALLOWED_HOSTS` | localhost | your public host name(s), comma-separated. Render / Koyeb / HF host names are added automatically |
| `AUTOMOTO_SIGNUP` | `invite` | `open`, `invite` or `closed` (admin can change it later) |
| `AUTOMOTO_DEFAULT_QUOTA_MINUTES` | `60` | minutes per period for new and default users |
| `AUTOMOTO_QUOTA_PERIOD_DAYS` / `AUTOMOTO_QUOTA_RESET_HOUR` | `1` / `0` | period length and the UTC hour it starts |
| `AUTOMOTO_DEFAULT_REQUEST_CAP` / `AUTOMOTO_DEFAULT_TOKEN_CAP` | `0` (off) | extra caps per period |
| `AUTOMOTO_USER_MAX_TASKS` | `2` | agent runs at once per user |
| `AUTOMOTO_USER_STORAGE_MB` / `AUTOMOTO_HOSTED_MAX_UPLOAD_MB` | `200` / `20` | per-user storage and upload size |
| `AUTOMOTO_SESSION_DAYS` | `7` | sign-in lifetime |
| `AUTOMOTO_COOKIE_SECURE` | auto (https) | force the `Secure` cookie flag (the Docker image sets `1`; use HTTPS) |
| `AUTOMOTO_FORWARDED_ALLOW_IPS` | `127.0.0.1` | proxies whose `X-Forwarded-For` is trusted (for per-IP sign-in limits). `*` only when the app is reachable **only** through the platform's proxy (Render, Koyeb, HF) |
| `PORT` / `AUTOMOTO_PORT` | `8765` | listen port (`PORT` is set by most hosts) |
| `AUTOMOTO_SOURCE_URL` | the GitHub repo | where the **Source code** link in the web interface points. AutoMoto AI is AGPL-3.0: if you run a **changed** copy for other people, set this to where they can get your changed source (or get a [commercial licence](https://github.com/ymmiah/AutoMotoAI/blob/main/COMMERCIAL-LICENSE.md)) |

Do **not** set `AUTOMOTO_NET_ALLOW_CIDRS` on a public server — it would let users' web tools reach private networks.

## Apps and devices (one account everywhere)

The same server is the **account server** for every client: the web GUI, phones' browsers and the
**Windows app** (`apps/desktop`). A user's chats, files, memory, usage limit and bonus time live on the server,
so every device signed in to that account sees the same things.

How the app signs in:

1. The app sends the username and password once to `POST /api/auth/device/login` and gets a **device token**
   (`amd_…`). The server keeps only its SHA-256 hash; the app stores the token in the OS credential store
   (Windows Credential Manager), never in a file.
2. To open the window, the app asks `POST /api/auth/device/launch` (token in `Authorization: Bearer …`) for a
   one-time code valid for 60 seconds, then opens `/?device_launch=<code>`. That becomes a normal browser session
   tied to the device, so the GUI works exactly as in a browser.
3. Device tokens **expire** after `AUTOMOTO_DEVICE_DAYS` without use (each use extends it). A user can have at most 20;
   the oldest is dropped.

Revoking:

* The user: **Account → My devices → Sign out** (also lists browser sessions), or *AutoMoto → Sign out of this device*
  in the app.
* The admin: **Admin → Signed-in apps → Sign out**, for any user.
* Changing a password, suspending or deleting a user signs out every device at once.

Security rules the server enforces:

* Device tokens are accepted **only over HTTPS** (or from the same machine). Put the server behind Caddy or
  Cloudflare Tunnel (below) — the app also refuses `http://` addresses that aren't `localhost`.
* Bearer requests can't be made by a web page in a browser (it would need the token), so they skip the CSRF check;
  cookie requests still need the CSRF token and a same-origin `Origin`.
* CORS is answered only for the app's own origins (`tauri://localhost`, `http(s)://tauri.localhost`) on the device
  endpoints, without credentials. App sign-in has the same per-IP and per-user limits as the web sign-in; launch
  codes are rate-limited per IP.

| Variable | Default | Meaning |
|---|---|---|
| `AUTOMOTO_DEVICE_DAYS` | `90` | a device token expires after this many days without use |
| `AUTOMOTO_APP_ORIGINS` | — | extra app origins allowed by CORS, comma-separated (only if you build your own client) |
| `AUTOMOTO_ALLOW_HTTP_DEVICES` | off | `1` accepts device tokens over plain HTTP — **testing only** |

**Building the app with your server pre-filled:** set the repository variable `AUTOMOTO_DEFAULT_SERVER`
(*Settings → Secrets and variables → Actions → Variables*) to e.g. `https://automoto.example.org`. The Windows app
workflow bakes it in as the default server address; users can still change it on the sign-in screen.

## Free hosting — what's actually free (checked October 2026)

Free tiers change often; check the provider's page before you rely on one. The big catch for AutoMoto is
**persistent storage**: accounts, usage and users' files live in `/data`. Without a persistent disk they
vanish on every restart.

| Option | Free? | Keeps data? | Notes |
|---|---|---|---|
| **Your own PC + Cloudflare Tunnel** | Yes | **Yes** | Best free choice if your PC can stay on. Tunnel is free; a quick tunnel gives a random `trycloudflare.com` URL, a named tunnel needs a domain on Cloudflare. |
| **Oracle Cloud Always Free VM** | Yes (card needed for identity check) | **Yes** (up to 200 GB block storage) | Ampere A1 Arm VM (2 OCPU / 12 GB in total since Aug 2026). Popular regions sometimes say "out of capacity". Best free always-on option. |
| **Render** (free web service) | Yes | **No** | Sleeps after 15 min idle (~1 min to wake), 750 h / month. No disks on the free plan, so **all accounts and files are wiped** on every sleep / redeploy. Demo only — the admin is recreated from env each start, but users aren't. |
| **Koyeb** (free instance) | Yes | **No** | 1 service, 0.1 vCPU / 512 MB, sleeps when idle, no volumes on free. Demo only. |
| **Hugging Face Spaces** (Docker) | **No** | No (paid storage) | Docker / Gradio Spaces on free CPU now need a PRO subscription; only static Spaces are free. |
| **Fly.io** | **No** | Yes (paid volumes) | No free tier for new accounts (short trial only); a small always-on machine is a few dollars a month. |

### Option A — your PC + Cloudflare Tunnel (free, persistent)

```bash
pip install "automoto-ai[office,data]"   # or clone the repo and pip install -e .
export AUTOMOTO_MODE=multiuser NVIDIA_API_KEY=…  AUTOMOTO_COOKIE_SECURE=1
python -m automoto admin create yasin
# quick tunnel (random URL, no account needed):
cloudflared tunnel --url http://127.0.0.1:8765
# put the printed host name in AUTOMOTO_ALLOWED_HOSTS, then:
AUTOMOTO_ALLOWED_HOSTS=random-words.trycloudflare.com python -m automoto serve --hosted
```

`cloudflared` connects from your PC to localhost, so leave `AUTOMOTO_FORWARDED_ALLOW_IPS` at its default.
For a stable URL, add a domain to Cloudflare and create a named tunnel (`cloudflared tunnel create automoto`).

### Option B — Oracle Cloud Always Free VM (free, persistent)

1. Sign up at cloud.oracle.com (card used for verification; stay on *Always Free* shapes).
2. Create a VM: *Ampere A1 Flex*, Ubuntu, up to 2 OCPU / 12 GB. Open port 443 (or use a Cloudflare Tunnel and open nothing).
3. On the VM:
   ```bash
   sudo apt-get update && sudo apt-get install -y docker.io
   git clone https://github.com/ymmiah/AutoMotoAI && cd AutoMotoAI && sudo docker build -t automoto .
   sudo docker run -d --restart unless-stopped --name automoto -p 127.0.0.1:8765:8765 -v automoto-data:/data \
     -e NVIDIA_API_KEY=… -e AUTOMOTO_ADMIN_USER=yasin -e AUTOMOTO_ADMIN_PASSWORD='…' \
     -e AUTOMOTO_ALLOWED_HOSTS=your.domain -e AUTOMOTO_FORWARDED_ALLOW_IPS='*' automoto
   ```
4. Put HTTPS in front: Caddy (`your.domain { reverse_proxy 127.0.0.1:8765 }`) or `cloudflared`. Because the port is
   published on `127.0.0.1` only, the proxy is the only way in, so `AUTOMOTO_FORWARDED_ALLOW_IPS='*'` is safe and lets
   the per-IP sign-in limits see real visitors (Docker shows every proxied request as coming from its bridge IP).
   Step-by-step with Docker Compose, Oracle's firewall rules and a Caddyfile: [INSTALL.md § 7B](INSTALL.md#b-oracle-cloud-always-free-vm--caddy-free-always-on-https).
5. Back up the `automoto-data` volume now and then (`accounts.db` and `users/`).

### Option C — Render free (demo only, data is wiped)

Fork the repo → Render → *New → Blueprint* → pick the repo (uses `render.yaml`). Set `NVIDIA_API_KEY`,
`AUTOMOTO_ADMIN_USER`, `AUTOMOTO_ADMIN_PASSWORD` as secrets. Your admin comes back after every restart; other
accounts and all files do not.

## Docker

```bash
docker build -t automoto .                               # add --build-arg WITH_OFFICE=1 for LibreOffice (PDF export)
docker run -d -p 127.0.0.1:8765:8765 -v automoto-data:/data -e NVIDIA_API_KEY=… \
  -e AUTOMOTO_ADMIN_USER=yasin -e AUTOMOTO_ADMIN_PASSWORD='…' -e AUTOMOTO_ALLOWED_HOSTS=your.domain automoto
docker exec -it <container> python -m automoto admin list
```

The image runs as a non-root user (uid 10001), stores everything in `/data`, and includes poppler, PHP (for
`php -l` checks) and 7-Zip. CI builds it and smoke-tests the login page and admin bootstrap.

## Limits of hosted mode (be honest with your users)

* Single process: rate limits, lockouts and running tasks are in memory — run one instance, not several.
* No e-mail: no verification and no "forgot password" — the admin resets passwords (`automoto admin passwd`).
* Token caps are estimates (characters ÷ 4), not provider-billed tokens.
* All users share the server's AI keys and provider rate limits; set the quotas with that in mind.
* Users' files are isolated by folder on one machine, not by container. Don't host people you don't trust
  with a server you care about; keep the host free of other secrets.
