"""Help someone run their OWN server: on their PC (optionally reachable through a Cloudflare Tunnel), with
Docker, or on a free cloud VM (Oracle Always Free first). Used by the ``server-setup`` skill.

``server_setup`` never runs installers or commands itself. It
* ``check``s this computer (read-only: versions, free port, Docker/cloudflared present, memory, disk),
* gives a ``plan`` (numbered steps with the exact commands), and
* ``write``s ready-to-use files into ``artifacts/server-setup/<target>/`` (new files only, no secrets:
  keys are placeholders the user fills in).
Anything that installs or starts something goes through ``run_shell``, which asks for approval first.
"""

from __future__ import annotations

import json
import platform
import shutil
import socket
import sys
from pathlib import Path

from automoto import __version__, brand, sandbox
from automoto.tools import Tool, ToolContext, ToolFailed

TARGETS = {
    "local": "this computer only (free, simplest)",
    "tunnel": "this computer + a free Cloudflare Tunnel so you can reach it from your phone anywhere",
    "docker": "Docker on this computer or any server (keeps data in a volume)",
    "oracle": "Oracle Cloud Always Free VM: always on, free, keeps data (needs a card for identity check)",
    "render": "Render free web service: quick demo only, data is wiped on every restart",
}
REPO = "https://github.com/ymmiah/AutoMotoAI"


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


def check(port: int = 8765) -> dict:
    from automoto import local_llm

    hw = local_llm.hardware()
    du = shutil.disk_usage(str(sandbox.default_root()))
    items = [
        ("Python 3.10+", sys.version_info >= (3, 10), platform.python_version()),
        (f"{brand.name()} installed", True, __version__),
        (f"Port {port} free", _port_free(port), "free" if _port_free(port) else f"something already uses port {port}"),
        ("Docker", bool(shutil.which("docker")), shutil.which("docker") or "not installed (only needed for Docker/Oracle)"),
        ("cloudflared (for a tunnel)", bool(shutil.which("cloudflared")), shutil.which("cloudflared") or "not installed (only needed for a tunnel)"),
        ("git", bool(shutil.which("git")), shutil.which("git") or "not installed"),
        ("Memory 2 GB+", (hw.get("ram_gb") or 0) >= 2, f"{hw.get('ram_gb')} GB"),
        ("Free disk 2 GB+", du.free > 2 * 1024 ** 3, f"{du.free / 1024 ** 3:.1f} GB free"),
    ]
    return {"os": f"{platform.system()} {platform.machine()}",
            "checks": [{"check": n, "ok": bool(ok), "detail": str(d)} for n, ok, d in items],
            "note": "Read-only check. Nothing was installed or changed."}


def _env_template(target: str, domain: str, admin: str) -> str:
    host = domain or ("your-tunnel-name.trycloudflare.com" if target == "tunnel" else "127.0.0.1")
    return f"""# {brand.name()} server settings. Fill in the <...> parts. Keep this file private (never share or commit it).
# One AI key is enough (free ones: NVIDIA, Gemini, Groq, OpenRouter) - or use Ollama for offline AI.
NVIDIA_API_KEY=<paste your key>
# GEMINI_API_KEY=<optional backup key>
AUTOMOTO_MODE=multiuser
AUTOMOTO_ADMIN_USER={admin}
AUTOMOTO_ADMIN_PASSWORD=<choose a long password>
AUTOMOTO_ALLOWED_HOSTS={host}
AUTOMOTO_COOKIE_SECURE={"0" if target in ("local", "docker") and not domain else "1"}
""" + ("# Safe only because the port is published on 127.0.0.1 and Caddy/the tunnel is the only way in:\n"
       "AUTOMOTO_FORWARDED_ALLOW_IPS=*\n" if target == "oracle" else "")


def files_for(target: str, domain: str = "", admin: str = "admin") -> dict[str, str]:
    if target not in TARGETS:
        raise ToolFailed("target must be one of: " + ", ".join(TARGETS))
    f: dict[str, str] = {".env.template": _env_template(target, domain, admin)}
    compose = f"""# {brand.name()} with Docker Compose. Copy .env.template to .env, fill it in, then: docker compose up -d
services:
  automoto:
    image: automoto-ai:local
    build: {REPO}.git
    restart: unless-stopped
    env_file: .env
    ports:
      - "127.0.0.1:8765:8765"   # only this machine; HTTPS/tunnel goes in front
    volumes:
      - automoto-data:/data
volumes:
  automoto-data:
"""
    if target == "local":
        f["start.sh"] = "#!/usr/bin/env bash\nset -e\npython3 -m automoto serve\n"
        f["start.ps1"] = "python -m automoto serve\n"
    if target == "tunnel":
        f["start-server.sh"] = "#!/usr/bin/env bash\nset -a; . ./.env; set +a\npython3 -m automoto serve --hosted --no-browser\n"
        f["start-tunnel.sh"] = ("#!/usr/bin/env bash\n# Free quick tunnel: prints a https://<words>.trycloudflare.com address.\n"
                                "# Put that host name in AUTOMOTO_ALLOWED_HOSTS in .env, then restart start-server.sh.\n"
                                "cloudflared tunnel --url http://127.0.0.1:8765\n")
        f["start-tunnel.ps1"] = "cloudflared tunnel --url http://127.0.0.1:8765\n"
        f["automoto.service"] = """[Unit]
Description=AutoMoto AI server
After=network-online.target

[Service]
WorkingDirectory=%h/automoto-server
EnvironmentFile=%h/automoto-server/.env
ExecStart=/usr/bin/env python3 -m automoto serve --hosted --no-browser
Restart=on-failure

[Install]
WantedBy=default.target
"""
    if target in ("docker", "oracle"):
        f["compose.yaml"] = compose
    if target == "oracle":
        site = domain or "your.domain.example"
        f["Caddyfile"] = f"{site} {{\n  reverse_proxy 127.0.0.1:8765\n}}\n"
        f["cloud-init.yaml"] = f"""#cloud-config
# Paste into Oracle Cloud > Create instance > Advanced > Initialization script (Ubuntu image).
package_update: true
packages: [docker.io, docker-compose-v2, git, caddy]
runcmd:
  - systemctl enable --now docker
  - mkdir -p /opt/automoto
  - echo "Now copy .env and compose.yaml to /opt/automoto and run: cd /opt/automoto && docker compose up -d"
"""
    if target == "render":
        f["render-steps.md"] = (f"1. Fork {REPO} on GitHub.\n2. On render.com: New > Blueprint > pick your fork (it uses render.yaml).\n"
                                "3. Add NVIDIA_API_KEY, AUTOMOTO_ADMIN_USER and AUTOMOTO_ADMIN_PASSWORD as secrets.\n"
                                "4. Remember: the free plan wipes accounts and files on every restart. Demo only.\n")
    f["CHECKLIST.md"] = "\n".join(f"{i}. [ ] {s['do']}" + (f"\n   `{s['run']}`" if s.get("run") else "")
                                  for i, s in enumerate(plan(target, domain)["steps"], 1)) + "\n"
    return f


def plan(target: str, domain: str = "") -> dict:
    if target not in TARGETS:
        raise ToolFailed("target must be one of: " + ", ".join(TARGETS))
    S = []

    def step(do: str, run: str = "", check: str = "") -> None:
        S.append({k: v for k, v in (("do", do), ("run", run), ("check", check)) if v})

    if target == "local":
        step("Start the app", "python -m automoto serve", "your browser opens the chat")
    elif target == "tunnel":
        step("Install cloudflared (free, from Cloudflare)", "winget install Cloudflare.cloudflared  (Mac: brew install cloudflared)",
             "cloudflared --version")
        step("Copy .env.template to .env and fill in your AI key and an admin password")
        step("Create your admin account", "python -m automoto admin create <name>")
        step("Start the server", "./start-server.sh", "http://127.0.0.1:8765 shows the sign-in page")
        step("Start the tunnel and copy the https://… address it prints", "./start-tunnel.sh")
        step("Put that host name in AUTOMOTO_ALLOWED_HOSTS in .env and restart the server")
        step("Open the https address on your phone and sign in", check="the sign-in page loads over https")
    elif target == "docker":
        step("Install Docker Desktop (Windows/Mac) or docker.io (Linux)", check="docker --version")
        step("Copy .env.template to .env and fill it in")
        step("Start it", "docker compose up -d --build", "docker compose ps shows automoto running")
        step("Open http://127.0.0.1:8765 and sign in with the admin from .env")
    elif target == "oracle":
        step("Sign up at cloud.oracle.com (stay on Always Free shapes)")
        step("Create a VM: Ampere A1 Flex, Ubuntu, 2 OCPU / 12 GB; paste cloud-init.yaml as the initialization script")
        step("Open port 443 in the VM's security list (or skip this and use a Cloudflare Tunnel)")
        step("Copy .env and compose.yaml to the VM", "scp .env compose.yaml ubuntu@<vm-ip>:/opt/automoto/")
        step("Start it on the VM", "cd /opt/automoto && sudo docker compose up -d", "curl -s 127.0.0.1:8765/api/health")
        step(f"Point your domain at the VM and start Caddy with the Caddyfile (HTTPS for {domain or 'your domain'})",
             "sudo cp Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy", "https://your.domain shows the sign-in page")
        step("Back up the automoto-data volume now and then")
    else:
        step("Follow render-steps.md (demo only: data is wiped on restart)")
    return {"target": target, "what": TARGETS[target], "steps": S,
            "note": "I never run these myself without asking. Say 'run step N' and I'll ask for approval first."}


def write(target: str, domain: str = "", admin: str = "admin") -> dict:
    from automoto import layout

    base = layout.folder("artifacts") / "server-setup"
    out = base / target
    n = 2
    while out.exists():  # never overwrite earlier files
        out = base / f"{target}-{n}"
        n += 1
    out.mkdir(parents=True)
    written = []
    for name, text in files_for(target, domain, admin).items():
        p = out / name
        p.write_text(text, encoding="utf-8")
        if name.endswith(".sh"):
            p.chmod(0o755)
        written.append(sandbox.rel(p))
    return {"folder": sandbox.rel(out), "files": written,
            "next": "Open CHECKLIST.md. Copy .env.template to .env and fill in the <...> parts (keep it private)."}


def server_setup(ctx: ToolContext, action: str = "plan", target: str = "local", domain: str = "", admin: str = "admin") -> str:
    action = (action or "plan").lower()
    if domain and (len(domain) > 200 or not all(c.isalnum() or c in ".-" for c in domain)):
        raise ToolFailed("domain must look like example.com")
    if not admin.replace("_", "").replace("-", "").isalnum() or len(admin) > 40:
        raise ToolFailed("admin must be a simple user name")
    if action == "check":
        return json.dumps(check())
    if action == "targets":
        return json.dumps(TARGETS)
    if action == "plan":
        return json.dumps(plan(target, domain))
    if action == "write":
        return json.dumps(write(target, domain, admin))
    raise ToolFailed("action must be check, targets, plan or write")


TOOLS = [
    Tool("server_setup", "Help the user run their own server. action=check (read-only check of this computer), "
         "targets (free options), plan (numbered steps + commands for target=local|tunnel|docker|oracle|render) or "
         "write (ready-made config files into artifacts/server-setup/, no secrets). Never runs anything: use "
         "run_shell (asks approval) for a step the user wants run.",
         {"type": "object", "properties": {"action": {"type": "string"}, "target": {"type": "string"},
                                           "domain": {"type": "string"}, "admin": {"type": "string"}}},
         "safe", server_setup, "server"),
]
