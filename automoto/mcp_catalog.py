"""Curated MCP connectors for popular services.

Enabling one writes an entry to ``~/.automoto/mcp.json`` that refers to your token by
**environment variable name** (``${NOTION_TOKEN}``), so the token itself lives only in your
``.env`` / environment - never in mcp.json and never in the API. AutoMoto's MCP client speaks
**stdio**; vendor-hosted (remote, OAuth) servers are reached through the ``mcp-remote`` bridge
(``npx -y mcp-remote <url>``), which opens your browser to sign in the first time.

``status``: ``live`` = connected and listed tools on a real machine; ``unit`` = config
generation unit-tested only; ``untested`` = needs an account/OAuth sign-in we could not do.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from automoto import home


@dataclass
class Connector:
    id: str
    name: str
    vendor: str           # official | community
    transport: str        # stdio | remote (via mcp-remote)
    command: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)  # values are ${VAR} placeholders
    needs: list[str] = field(default_factory=list)     # env vars the user must set
    docs: str = ""
    note: str = ""
    status: str = "untested"

    def entry(self) -> dict[str, Any]:
        return {"command": self.command, "args": list(self.args), "env": dict(self.env), "trust": False,
                "catalog": self.id}


def _remote(cid: str, name: str, url: str, docs: str, note: str = "") -> Connector:
    return Connector(cid, name, "official", "remote", "npx", ["-y", "mcp-remote", url], docs=docs,
                     note=("Signs in with OAuth in your browser on first use (via mcp-remote). " + note).strip())


CATALOG: list[Connector] = [
    Connector("github", "GitHub", "official", "stdio", "docker",
              ["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", "ghcr.io/github/github-mcp-server"],
              {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"}, ["GITHUB_TOKEN"],
              "https://github.com/github/github-mcp-server",
              "Needs Docker. Without Docker use the built-in service_api tool (GITHUB_TOKEN) instead."),
    _remote("gitlab", "GitLab", "https://gitlab.com/api/v4/mcp", "https://docs.gitlab.com/user/model_context_protocol/mcp_server/",
            "Self-managed GitLab: replace gitlab.com with your host."),
    _remote("notion", "Notion", "https://mcp.notion.com/mcp", "https://developers.notion.com/guides/mcp/get-started-with-mcp"),
    _remote("figma", "Figma", "https://mcp.figma.com/mcp", "https://developers.figma.com/docs/figma-mcp-server/",
            "Figma only admits clients from its MCP catalog, so this may be refused until AutoMoto is listed."),
    _remote("canva", "Canva", "https://mcp.canva.com/mcp", "https://www.canva.dev/docs/mcp/"),
    _remote("vercel", "Vercel", "https://mcp.vercel.com", "https://vercel.com/docs/mcp/vercel-mcp"),
    _remote("google-drive", "Google Drive", "https://drivemcp.googleapis.com/mcp/v1",
            "https://developers.google.com/workspace/drive", "Google may require a Workspace account or Cloud project."),
    Connector("onedrive", "OneDrive / Microsoft 365", "community", "stdio", "npx", ["-y", "@softeria/ms-365-mcp-server"],
              docs="https://github.com/Softeria/ms-365-mcp-server",
              note="Device-code sign-in with your Microsoft account. Personal mode covers OneDrive files, Outlook, Excel."),
    Connector("zotero", "Zotero", "community", "stdio", "uvx", ["zotero-mcp"], {"ZOTERO_LOCAL": "true"},
              docs="https://github.com/54yyyu/zotero-mcp",
              note="Uses the Zotero desktop app's local API (Settings → Advanced → allow other applications). "
                   "Or use the built-in service_api tool with ZOTERO_API_KEY."),
    Connector("filesystem-docs", "Folder (read/write) - reference server", "official", "stdio", "npx",
              ["-y", "@modelcontextprotocol/server-filesystem", "${AUTOMOTO_MCP_FOLDER}"], needs=["AUTOMOTO_MCP_FOLDER"],
              docs="https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
              note="Gives the agent one extra folder through MCP. Prefer Settings → Files, which keeps the path blocklist.",
              status="live"),
]
BY_ID = {c.id: c for c in CATALOG}
_VAR = re.compile(r"\$\{([A-Z0-9_]+)\}")


def expand(value: str) -> str:
    """Replace ${VAR} with the environment value ('' if unset)."""
    return _VAR.sub(lambda m: os.environ.get(m.group(1), ""), value)


def _file() -> Path:
    return home.mcp_file()


def read_config() -> dict[str, Any]:
    p = _file()
    if not p.exists():
        return {"servers": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("servers", {})
    return data


def _write(data: dict[str, Any]) -> None:
    p = _file()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)


def enable(cid: str) -> dict[str, Any]:
    c = BY_ID.get(cid)
    if not c:
        raise KeyError(cid)
    data = read_config()
    data["servers"][c.id] = c.entry()
    _write(data)
    return data["servers"][c.id]


def disable(cid: str) -> bool:
    data = read_config()
    if cid not in data["servers"]:
        return False
    del data["servers"][cid]
    _write(data)
    return True


def listing() -> list[dict[str, Any]]:
    enabled = read_config()["servers"]
    out = []
    for c in CATALOG:
        d = asdict(c)
        d["enabled"] = c.id in enabled
        d["missing_env"] = [v for v in c.needs if not os.environ.get(v)]  # names only, never values
        out.append(d)
    return out
