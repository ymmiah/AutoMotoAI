"""Hermetic Git for tests: ignore the host's identity, signing and default branch."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

GIT_USER_NAME = "T"
GIT_USER_EMAIL = "t@example.com"

# Command-line overrides beat a host ~/.gitconfig (commit.gpgsign, init.defaultBranch, …).
OVERRIDES = [
    "-c", f"user.name={GIT_USER_NAME}",
    "-c", f"user.email={GIT_USER_EMAIL}",
    "-c", "commit.gpgsign=false",
    "-c", "tag.gpgsign=false",
    "-c", "init.defaultBranch=main",
    "-c", "core.autocrlf=false",
    "-c", "advice.detachedHead=false",
]


def isolate_environ(env: dict | None = None) -> dict:
    """Drop host Git config so signing, identity and default branch cannot leak in."""
    env = dict(os.environ if env is None else env)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_COUNT"] = "0"
    env.pop("GIT_CONFIG_PARAMETERS", None)
    for key in [k for k in env if k.startswith("GIT_CONFIG_KEY_") or k.startswith("GIT_CONFIG_VALUE_")]:
        env.pop(key, None)
    env["GIT_AUTHOR_NAME"] = GIT_USER_NAME
    env["GIT_AUTHOR_EMAIL"] = GIT_USER_EMAIL
    env["GIT_COMMITTER_NAME"] = GIT_USER_NAME
    env["GIT_COMMITTER_EMAIL"] = GIT_USER_EMAIL
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("LC_ALL", "C")
    return env


def run_git(cwd, *args, check=True, extra=None):
    """Run git in *cwd* with a sealed identity, no signing, and branch name main."""
    argv = ["git", *OVERRIDES]
    if extra:
        argv.extend(extra)
    if cwd is not None:
        argv.extend(["-c", "safe.directory=" + str(Path(cwd).resolve())])
    argv.extend(args)
    return subprocess.run(
        argv, cwd=cwd, env=isolate_environ(os.environ),
        capture_output=True, text=True, check=check,
    )
