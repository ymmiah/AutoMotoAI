"""V55: bounded-agent test runs with a hard deadline and honest pass/fail evidence.

The bounded coding agent may ask to run the project's *detected* test command, and
nothing else. There is no command text in the tool's arguments: the model can only
pick a recipe id that V41 detection already offers from the project's manifests.

Lifecycle (read with docs/DEVELOPER-STUDIO-V55.md):

1. Prepare (read-only): the server checks the trusted project, detects the test
   recipes, resolves the executable and fixes a time limit that fits inside the
   session's remaining V52 budget. Nothing runs.
2. Review: the approval card shows only server-made evidence: the exact command,
   where it came from, the time limit and what the run can and cannot touch.
3. Run: only after that one approval. The recipe is detected again and must hash to
   the same command, so a manifest edited during the approval wait is refused. The
   V41 runner starts it in its own process group (its own session on Unix) with a
   reduced environment and no input. On the time limit, Stop or task cancellation,
   the whole process group is killed, not only the first process.
4. Evidence: the verdict comes from the exit code *and* the parsed test summary.
   An exit code of 0 with no recognised summary is ``passed_exit_code_only``, never
   ``passed``; zero tests is ``no_tests``. Output is capped, redacted and returned to
   the model as untrusted data.

This is process containment, not an operating-system sandbox: test code runs as the
user and can read or change files and use the network like any program they run.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import HTTPException

from automoto import developer_run as run_mod
from automoto import developer_safe_patch as patch
from automoto import redaction, sandbox
from automoto.tools import Tool, ToolContext, ToolFailed

VERSION = "1.0.0"
MAX_SECONDS = 180     # one agent test run, at most
MIN_SECONDS = 10      # below this, a run is refused rather than started to be killed
DEADLINE_MARGIN = 5   # seconds kept back so the agent can still report after the run
OUTPUT_TAIL = 12_000  # characters of (redacted) output returned to the model
POLL = 0.1

VERDICTS = ("passed", "failed", "no_tests", "passed_exit_code_only", "timed_out", "cancelled")
ISOLATION = ("Runs in its own process group with a reduced environment and no keyboard input. "
             "The whole group is stopped at the time limit, on Stop or when the task is cancelled. "
             "This is not a sandbox: the tests run as you and can read or change files and use the "
             "network, like any program you run.")


def _unavailable(ctx: ToolContext, **kwargs) -> str:
    """Fail closed if the action is called outside the bounded loop's bridge."""
    raise ToolFailed("A test run can only start through the bounded approval gateway.")


def test_tool() -> Tool:
    return Tool(
        "developer_agent_test",
        "Run this project's detected test command once, after the user approves it, and get "
        "honest evidence back: verdict, passed/failed/skipped counts, failing test names and "
        "the end of the output. You cannot choose the command: pass a recipe id only when the "
        "project offers more than one (an error lists them). The run has a hard time limit "
        "inside this session's budget. Report the verdict exactly; passed_exit_code_only and "
        "no_tests are not a pass. Cannot change files, install packages, deploy or share.",
        {
            "type": "object",
            "properties": {
                "recipe": {"type": "string", "pattern": r"^[a-z0-9:_.-]{1,80}$",
                           "description": "Optional detected test recipe id, for example python:pytest."},
            },
            "additionalProperties": False,
        },
        "risky", _unavailable, group="studio:developer",
    )


# --------------------------------------------------------------------------- prepare

def _test_recipes(root) -> list[dict]:
    return [r for r in run_mod.detect_recipes(root) if r["kind"] == "test"]


def _choose(recipes: list[dict], wanted: Any) -> dict:
    ids = ", ".join(r["id"] for r in recipes)
    if wanted is not None and (not isinstance(wanted, str) or not wanted):
        raise ToolFailed("recipe must be a detected recipe id: " + ids)
    if wanted:
        found = next((r for r in recipes if r["id"] == wanted), None)
        if found is None:
            raise ToolFailed(f"'{str(wanted)[:80]}' is not a detected test command here. Detected: {ids}.")
        return found
    if len(recipes) > 1:
        raise ToolFailed("This project has more than one test command. Pass recipe as one of: " + ids + ".")
    return recipes[0]


def _time_limit(budget) -> int:
    remaining = budget.remaining() if budget is not None else float(MAX_SECONDS + DEADLINE_MARGIN)
    return int(min(MAX_SECONDS, remaining - DEADLINE_MARGIN))


def prepare(args: dict, budget=None) -> dict:
    """Read-only: everything the approval card shows is computed here, by the server."""
    if not isinstance(args, dict) or set(args) - {"recipe"}:
        raise ToolFailed("developer_agent_test takes only an optional recipe id.")
    try:
        root = patch._trusted(str(sandbox.root()))
    except HTTPException as exc:
        raise ToolFailed(str(exc.detail)[:300]) from None
    recipes = _test_recipes(root)
    if not recipes:
        raise ToolFailed("No test command was detected for this project (pytest, npm test, go test or "
                         "cargo test). Tell the user tests could not be run; do not claim they passed.")
    recipe = _choose(recipes, args.get("recipe"))
    env = run_mod._env(root, "test", None)
    if run_mod._executable(recipe["argv"][0], env) is None:
        raise ToolFailed(f"{recipe['argv'][0]} is not installed or not on PATH, so the tests cannot run here.")
    limit = _time_limit(budget)
    if limit < MIN_SECONDS:
        raise ToolFailed("Not enough time is left in this session to run the tests safely. "
                         "Tell the user the tests were not run.")
    with run_mod.LOCK:
        if any(r.live and r.root == root and r.kind == "test" for r in run_mod.RUNS.values()):
            raise ToolFailed("A test run is already going for this project. Wait for it or stop it first.")
    return {
        "root": root, "recipe_id": recipe["id"], "label": recipe["label"], "source": recipe["source"],
        "command": " ".join(recipe["argv"]), "command_sha256": run_mod._command_sha(root, recipe),
        "time_limit_seconds": limit,
    }


def public_approval(prepared: dict) -> dict:
    """Server-created evidence for the approval card; the model supplies none of it."""
    return {
        "recipe": prepared["recipe_id"],
        "label": prepared["label"],
        "command": prepared["command"],
        "source": prepared["source"],
        "command_sha256": prepared["command_sha256"],
        "time_limit_seconds": prepared["time_limit_seconds"],
        "isolation": ISOLATION,
        "runs_project_code": True,
        "os_sandbox": False,
        "prepared_by_server": True,
        "test_run": True,
    }


# --------------------------------------------------------------------------- run

def verdict(status: str, exit_code: int | None, summary: dict) -> str:
    """Pass/fail from what was observed. Anything unproven is never called a pass."""
    if status == "timed_out":
        return "timed_out"
    if status == "stopped":
        return "cancelled"
    recognised = bool(summary.get("recognised"))
    failed = int(summary.get("failed") or 0)
    passed = int(summary.get("passed") or 0)
    if recognised and failed > 0:
        return "failed"
    if exit_code == 0:
        if not recognised:
            return "passed_exit_code_only"
        return "passed" if passed > 0 else "no_tests"
    if recognised and passed == 0 and int(summary.get("total") or 0) == 0:
        return "no_tests"  # for example pytest exit code 5: nothing was collected
    return "failed"


def _wait(run: run_mod.Run, cancel: threading.Event | None, budget) -> str | None:
    """Block until the run ends. Returns "cancel" or "deadline" if *we* stopped it."""
    why = None
    while run.ended is None:
        if why is None:
            if cancel is not None and cancel.is_set():
                why = "cancel"
            elif budget is not None and budget.check():
                why = "deadline"
            if why:
                run.stop()
        time.sleep(POLL)
    return why


def commit(prepared: dict, cancel: threading.Event | None = None, budget=None) -> dict:
    """ONLY invoked by the bounded loop after the user approved this exact command."""
    try:
        root = patch._trusted(str(sandbox.root()))
    except HTTPException as exc:
        raise ToolFailed(str(exc.detail)[:300]) from None
    if root != prepared["root"]:
        raise ToolFailed("The project changed since you approved the test run. Nothing ran.")
    recipe = next((r for r in _test_recipes(root) if r["id"] == prepared["recipe_id"]), None)
    if recipe is None or run_mod._command_sha(root, recipe) != prepared["command_sha256"]:
        raise ToolFailed("The test command changed since you approved it. Nothing ran; ask again.")
    # The approval wait used up time: the hard limit is the smaller of the approved
    # limit and what is left of the session now.
    limit = min(prepared["time_limit_seconds"], _time_limit(budget))
    if limit < MIN_SECONDS:
        raise ToolFailed("The session ran out of time while waiting for approval. Nothing ran.")
    env = run_mod._env(root, "test", None)
    exe = run_mod._executable(recipe["argv"][0], env)
    if exe is None:
        raise ToolFailed(f"{recipe['argv'][0]} is not installed or not on PATH, so the tests cannot run here.")
    with run_mod.LOCK:
        live = [r for r in run_mod.RUNS.values() if r.live]
        if any(r.root == root and r.kind == "test" for r in live):
            raise ToolFailed("A test run is already going for this project. Nothing new ran.")
        if len(live) >= run_mod.MAX_LIVE:
            raise ToolFailed("Too many runs at once. Stop one first. Nothing ran.")
        run = run_mod.Run(root, recipe, [exe, *recipe["argv"][1:]], None)
        run.limit = limit  # the watchdog kills the whole process group at this point
        for old in [r for r in run_mod.RUNS.values() if not r.live][:-12]:
            run_mod.RUNS.pop(old.id, None)
        run_mod.RUNS[run.id] = run  # shown in Review → Tests like a manual run
    try:
        run.start(env)
    except HTTPException as exc:
        raise ToolFailed(str(exc.detail)[:300]) from None
    why = _wait(run, cancel, budget)
    view = run.view(0)
    summary = view["summary"] or {}
    status = "timed_out" if why == "deadline" and view["status"] == "stopped" else view["status"]
    result = verdict(status, view["exit_code"], summary)
    output = view["output"]
    cut = len(output) > OUTPUT_TAIL
    tail = redaction.redact(output[-OUTPUT_TAIL:])
    return {
        "verdict": result,
        "passed": result == "passed",
        "counts": {k: int(summary.get(k) or 0) for k in ("passed", "failed", "skipped", "total")},
        "framework": summary.get("framework", "unknown"),
        "summary_recognised": bool(summary.get("recognised")),
        "failures": [str(f)[:160] for f in (summary.get("failures") or [])[:12]],
        "exit_code": view["exit_code"],
        "elapsed_ms": view["elapsed_ms"],
        "time_limit_seconds": limit,
        "timed_out": result == "timed_out",
        "cancelled": result == "cancelled",
        "command": prepared["command"],
        "run_id": view["run_id"],
        "output_tail": tail,
        "output_truncated": cut or bool(view["truncated"]),
        "evidence": "observed_by_server",
        "files_changed_by_automoto": False,
    }
