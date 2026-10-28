"""Where AutoMoto keeps its state: ``~/.automoto`` (override with ``AUTOMOTO_DATA_DIR``).

    ~/.automoto/
      workspace/      the sandbox - every file and shell tool is jailed here
      workspace/scratch/   writes here never need approval
      memory.db       SQLite: profile facts + dated journal
      skills/         your own SKILL.md folders (bundled examples ship in the package)
      routines.json   scheduled agent prompts
      routines.log    what each routine run did
      mcp.json        optional MCP servers to connect to
"""

from __future__ import annotations

from pathlib import Path

from automoto import config


def home() -> Path:
    p = Path(config.env("AUTOMOTO_DATA_DIR") or Path.home() / ".automoto").expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def workspace() -> Path:
    p = Path(config.env("AUTOMOTO_WORKSPACE") or home() / "workspace").expanduser()
    (p / "scratch").mkdir(parents=True, exist_ok=True)
    return p.resolve()


def memory_db() -> Path:
    return Path(config.env("AUTOMOTO_MEMORY_DB") or home() / "memory.db").expanduser()


def skills_dir() -> Path:
    p = home() / "skills"
    p.mkdir(parents=True, exist_ok=True)
    return p


def routines_file() -> Path:
    return home() / "routines.json"


def routines_log() -> Path:
    return home() / "routines.log"


def mcp_file() -> Path:
    return Path(config.env("AUTOMOTO_MCP_CONFIG") or home() / "mcp.json").expanduser()
