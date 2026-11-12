"""Guardrails so Developer Studio CI keeps using resilient infrastructure.

These checks fail if a workflow goes back to a bare `apt-get install`, or if a
job is added without `timeout-minutes`. They do not weaken any product
assertion; they only inspect CI files and the path-filter helper.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import importlib.util

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "pr_self_changed", ROOT / "scripts" / "ci" / "pr_self_changed.py"
)
_HELPER = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
_SPEC.loader.exec_module(_HELPER)
any_path_matches = _HELPER.any_path_matches
decide = _HELPER.decide
path_matches = _HELPER.path_matches

WORKFLOWS = ROOT / ".github" / "workflows"
APT_INSTALL = ROOT / "scripts" / "ci" / "apt-install.sh"
PR_HELPER = ROOT / "scripts" / "ci" / "pr_self_changed.py"

JOB_HEADER = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
JOB_LEVEL_USES = re.compile(r"^    uses:\s*")
JOB_LEVEL_TIMEOUT = re.compile(r"^    timeout-minutes:\s*\d+\s*$")
JOB_LEVEL_STEPS = re.compile(r"^    steps:\s*$")
APT_GET = re.compile(r"\bapt-get\s+(update|install)\b")
COMMENT_LINE = re.compile(r"^\s*#")


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


def _jobs(text: str) -> list[tuple[str, str]]:
    """Return (job_id, job_body) for top-level jobs: keys."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line == "jobs:")
    except StopIteration:
        return []
    jobs: list[tuple[str, list[str]]] = []
    current: str | None = None
    body: list[str] = []
    for line in lines[start + 1 :]:
        match = JOB_HEADER.match(line)
        if match:
            if current is not None:
                jobs.append((current, "\n".join(body)))
            current = match.group(1)
            body = []
            continue
        if current is not None:
            body.append(line)
    if current is not None:
        jobs.append((current, "\n".join(body)))
    return jobs


def _is_reusable_call(body: str) -> bool:
    has_uses = any(JOB_LEVEL_USES.match(line) for line in body.splitlines())
    has_steps = any(JOB_LEVEL_STEPS.match(line) for line in body.splitlines())
    return has_uses and not has_steps


def _code_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not COMMENT_LINE.match(line))


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda p: p.name)
def test_every_job_has_timeout_minutes(workflow: Path):
    jobs = _jobs(workflow.read_text(encoding="utf-8"))
    assert jobs, f"{workflow.name} has no jobs"
    missing = []
    for name, body in jobs:
        if _is_reusable_call(body):
            continue
        if not any(JOB_LEVEL_TIMEOUT.match(line) for line in body.splitlines()):
            missing.append(name)
    assert missing == [], f"{workflow.name} jobs missing timeout-minutes: {missing}"


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda p: p.name)
def test_workflows_do_not_call_apt_get_directly(workflow: Path):
    text = _code_lines(workflow.read_text(encoding="utf-8"))
    hits = APT_GET.findall(text)
    assert hits == [], (
        f"{workflow.name} must install packages with scripts/ci/apt-install.sh, "
        f"not apt-get directly (found {hits})"
    )


def test_apt_install_helper_still_exists_and_handles_renames():
    text = APT_INSTALL.read_text(encoding="utf-8")
    assert "p7zip-full) printf '%s' 7zip" in text
    assert "ocaml-nox) printf '%s' ocaml" in text
    assert "libpng16-16) printf '%s' libpng16-16t64" in text
    assert "package_in_cache()" in text
    assert "--retry-all-errors" in text
    assert "DNS-over-HTTPS" in text


def test_package_replacement_function():
    script = r"""
set -euo pipefail
# shellcheck source=scripts/ci/apt-install.sh
source scripts/ci/apt-install.sh
[ "$(package_replacement p7zip-full)" = 7zip ]
[ "$(package_replacement ocaml-nox)" = ocaml ]
[ "$(package_replacement libpng16-16)" = libpng16-16t64 ]
[ -z "$(package_replacement curl)" ]
"""
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize(
    "path,pattern,expected",
    [
        ("automoto/developer_logic.py", "automoto/developer_logic.py", True),
        (
            ".github/workflows/developer-shell-v26.yml",
            ".github/workflows/developer-shell-v26.yml",
            True,
        ),
        ("./automoto/developer_logic.py", "automoto/developer_logic.py", True),
        ("automoto/server.py", "automoto/developer_logic.py", False),
        ("tests/fixtures/v31-logic/test/v31_fixture.hs", "tests/fixtures/v31-logic/**", True),
        ("tests/fixtures/v23-android/app/src/Main.kt", "tests/fixtures/v23-*/**", True),
        ("tests/fixtures/v24-swift/x.swift", "tests/fixtures/v23-*/**", False),
        ("automoto/web/static/developer-studio.js", "automoto/web/static/developer-logic.js", False),
    ],
)
def test_path_pattern_matching(path: str, pattern: str, expected: bool):
    assert path_matches(path, pattern) is expected


def test_shared_server_change_does_not_qualify_as_own_files():
    patterns = [
        "automoto/developer_logic.py",
        "automoto/web/static/developer-logic.js",
        "tests/test_developer_logic.py",
        "tests/fixtures/v31-logic/**",
        ".github/workflows/developer-logic-v31.yml",
    ]
    shared = ["automoto/server.py", "automoto/web/static/developer-studio.js"]
    assert any_path_matches(shared, patterns) is False
    assert any_path_matches(shared + ["automoto/developer_logic.py"], patterns) is True


def test_non_pull_request_events_always_run_macos(tmp_path: Path):
    assert decide("push", [], ["automoto/developer_logic.py"]) is True
    assert decide("schedule", [], ["automoto/developer_logic.py"]) is True
    assert decide("workflow_dispatch", [], ["automoto/developer_logic.py"]) is True
    assert (
        decide(
            "pull_request",
            ["automoto/server.py"],
            ["automoto/developer_logic.py"],
        )
        is False
    )


def test_pr_self_changed_cli_writes_github_output(tmp_path: Path):
    out = tmp_path / "github-output"
    patterns = tmp_path / "patterns.txt"
    patterns.write_text("automoto/developer_go.py\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(PR_HELPER),
            "--event",
            "pull_request",
            "--files",
            "automoto/server.py,automoto/web/static/developer-studio.js",
            "--patterns-file",
            str(patterns),
            "--github-output",
            str(out),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "self=false" in out.read_text(encoding="utf-8")


def test_developer_workflows_gate_macos_and_keep_ubuntu_on_shared_paths():
    """Unrelated PRs still trigger Ubuntu jobs; macOS jobs need the path filter."""
    for path in sorted(WORKFLOWS.glob("developer-*.yml")):
        text = path.read_text(encoding="utf-8")
        assert "automoto/server.py" in text
        assert "uses: ./.github/workflows/ci-path-filter.yml" in text
        assert "needs: paths" in text
        assert "needs.paths.outputs.self == 'true'" in text
        assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in text
        assert "schedule:" in text
        assert "push:" in text
        # Shared files must not be in the reusable filter's own-file patterns.
        block = text.split("patterns: |", 1)[1].split("\n\n", 1)[0]
        assert "automoto/server.py" not in block
        assert "developer-studio.js" not in block


def test_v23_script_still_requires_status_ok_and_ui_marker():
    text = (ROOT / "tests" / "scripts" / "v23_android_emulator.sh").read_text(encoding="utf-8")
    assert 'grep -q "Status: ok"' in text
    assert "V23_ANDROID_EMULATOR_UI_PASS" in text
    assert "V23_ANDROID_RUNNING" in text
    assert "cat /sdcard/v23-window.xml | grep" not in text
    assert "| grep -q V23_ANDROID_RUNNING" not in text
