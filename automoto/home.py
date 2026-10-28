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


def base() -> Path:
    """The server's own data folder (hosted mode: accounts, sessions, usage, and users/<id>/)."""
    p = Path(config.env("AUTOMOTO_DATA_DIR") or Path.home() / ".automoto").expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def home() -> Path:
    """This user's data folder. Local mode: ``base()``. Hosted mode: ``base()/users/<id>``."""
    from automoto import tenancy

    t = tenancy.current()
    if t is not None:
        t.home.mkdir(parents=True, exist_ok=True)
        return t.home
    return base()


def workspace() -> Path:
    from automoto import tenancy

    t = tenancy.current()
    ws = (t.home / "workspace") if t is not None else None
    p = Path(ws or config.env("AUTOMOTO_WORKSPACE") or home() / "workspace").expanduser()
    (p / "scratch").mkdir(parents=True, exist_ok=True)
    return p.resolve()


def memory_db() -> Path:
    from automoto import tenancy

    if tenancy.current() is not None:
        return home() / "memory.db"
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
    from automoto import tenancy

    if tenancy.current() is not None:  # hosted users never get the host's MCP servers
        return home() / "mcp.json"
    return Path(config.env("AUTOMOTO_MCP_CONFIG") or home() / "mcp.json").expanduser()
