# Run your own AutoMoto server (the easy way)

> **Coming in the next beta.** This helper is on `main` and not yet in a tagged build.

You don't need to know servers. Just ask in the chat, for example:

* *"Help me run AutoMoto on my computer so I can use it from my phone."*
* *"Put AutoMoto on Oracle Cloud for free so it's always on."*
* *"Is my computer ready to host AutoMoto?"*

The assistant checks your computer, tells you the options, makes the files for you and walks you through it
one step at a time. **It never installs or starts anything without asking you first**, and it never puts your
real keys or passwords into files: you type those yourself.

## Step 0: pick where it lives (free options first)

| Option | Costs | Always on? | Good for |
|---|---|---|---|
| **This computer** | free | only while your computer is on | just you, at home |
| **This computer + Cloudflare Tunnel** | free | while your computer is on | using it from your phone anywhere |
| **Docker** (on your computer or a server) | free | if the machine is | tidy install, easy updates |
| **Oracle Cloud Always Free VM** | free (a card is used only to check who you are) | yes | always on, keeps your data |
| Render free web service | free | sleeps when idle | a quick demo only: **data is wiped on every restart** |

## Step 1: check your computer

Ask *"check if my computer can host AutoMoto"*. You get a list like:

* ✓ Python 3.10 or newer
* ✓ Port 8765 is free (nothing else is using it)
* ✗ Docker: not installed (only needed for the Docker and Oracle options)
* ✗ cloudflared: not installed (only needed for the tunnel)
* ✓ At least 2 GB memory and 2 GB free disk

This check only looks. It changes nothing.

## Step 2: get your files

Say which option you want. The assistant makes a folder for you:
`artifacts/server-setup/<option>/` (open it from **Files**). Inside:

| File | What it is |
|---|---|
| `CHECKLIST.md` | the steps, with a box to tick for each one |
| `.env.template` | your settings. Copy it to `.env` and fill in the `<...>` parts. **Keep `.env` private.** |
| `start-server.sh`, `start-tunnel.sh` | tunnel option: start the app, then the free tunnel |
| `automoto.service` | tunnel option on Linux: start the app automatically |
| `compose.yaml` | Docker and Oracle: runs the app with its data kept in a volume |
| `cloud-init.yaml` | Oracle: paste it when you create the VM so Docker is installed for you |
| `Caddyfile` | Oracle: free HTTPS for your own domain |

Running it again never overwrites your old files; it makes `oracle-2`, `oracle-3`, …

## Step 3: follow the checklist

### This computer + Cloudflare Tunnel (free, use it from your phone)

1. Install **cloudflared** (Windows: `winget install Cloudflare.cloudflared`, Mac: `brew install cloudflared`).
   Check: `cloudflared --version`.
2. Copy `.env.template` to `.env`. Paste one free AI key and choose a long admin password.
3. Create your admin account: `python -m automoto admin create <your-name>`.
4. Start the app: `./start-server.sh`. Check: <http://127.0.0.1:8765> shows the sign-in page.
5. Start the tunnel: `./start-tunnel.sh`. It prints an address like `https://three-random-words.trycloudflare.com`.
6. Put that host name in `AUTOMOTO_ALLOWED_HOSTS` in `.env` and restart the app.
7. Open the address on your phone and sign in.

The quick-tunnel address changes each time you start it. For a fixed address, use a free Cloudflare account and a
named tunnel ([HOSTING.md](HOSTING.md)).

### Oracle Cloud Always Free (always on)

1. Sign up at cloud.oracle.com and stay on **Always Free** shapes.
2. Create a VM: *Ampere A1 Flex*, Ubuntu, 2 OCPU / 12 GB. Under *Advanced*, paste `cloud-init.yaml`.
3. Open port 443 in the VM's security list (or skip this and use a Cloudflare Tunnel).
4. Copy `.env` and `compose.yaml` to `/opt/automoto/` on the VM.
5. On the VM: `cd /opt/automoto && sudo docker compose up -d`. Check: `curl -s 127.0.0.1:8765/api/health`.
6. Point your domain at the VM's IP and use the `Caddyfile` for HTTPS.
7. Back up the `automoto-data` volume now and then.

### Docker on your computer

1. Install Docker Desktop (Windows/Mac) or `docker.io` (Linux). Check: `docker --version`.
2. Copy `.env.template` to `.env` and fill it in.
3. `docker compose up -d --build`, then open <http://127.0.0.1:8765>.

## Want the assistant to run a step?

Say *"run step 4"*. You'll see exactly which command it wants to run and an **Approve / Deny** button. Nothing runs
until you approve, and the usual safety rules still apply (dangerous commands stay blocked).

## Safety checklist for a public server

* Multi-user mode on (`AUTOMOTO_MODE=multiuser`, already in the template), with a long admin password.
* HTTPS only: the tunnel or Caddy. The app itself listens on `127.0.0.1`.
* `AUTOMOTO_ALLOWED_HOSTS` is your real host name.
* Don't open SSH or database ports to the whole internet.
* Never share or commit `.env`.

More detail: [HOSTING.md](HOSTING.md) and [INSTALL.md](INSTALL.md).
