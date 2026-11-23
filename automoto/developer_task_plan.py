"""V50 Developer Studio: inspectable, non-executing task plan previews.

Plans are deterministic suggestions, not proof of an implementation. No code,
models, package managers or commands are run by this endpoint. Agent execution
remains a distinct user-confirmed action with its existing per-tool approvals.
"""
from __future__ import annotations

import hashlib
import json
import re

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_grounding as grounding, developer_studio as studio

router = APIRouter(prefix="/api/developer/studio", tags=["developer-task-plan"])

MAX_PLAN_STEPS = 6
MAX_HINTS = 3


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    request: str = Field(min_length=5, max_length=2000)


def _category(request: str) -> str:
    text = request.casefold()
    if re.search(r"\b(login|log[ -]?in|sign[ -]?in|auth|signup|password|register)\b", text):
        return "authentication"
    if re.search(r"\b(bug|broken|crash|error|fail(?:ing|ed)?|debug|fix)\b", text):
        return "debugging"
    if re.search(r"\b(test|coverage|pytest|jest|unittest|spec)\b", text):
        return "testing"
    if re.search(r"\b(refactor|clean[ -]?up|optimis[ez]|performance|improve)\b", text):
        return "refactoring"
    if re.search(r"\b(page|website|form|frontend|css|layout|button|screen|component|ui)\b", text):
        return "interface"
    return "feature"


def _step(identifier: str, title: str, detail: str, check: str, *, paths=None):
    return {
        "id": identifier,
        "title": title,
        "detail": detail,
        "acceptance_check": check,
        "suggested_paths": paths or [],
        "status": "proposed",
    }


def _steps(category: str, hints: list[str]) -> list[dict]:
    paths = hints[:MAX_HINTS]
    first = _step("inspect", "Inspect the relevant project files",
                  "Read the related source, configuration and existing tests before changing anything.",
                  "Affected files and current behaviour are identified.", paths=paths)
    specifics = {
        "authentication": [
            _step("design", "Check the login and session design",
                  "Identify existing routes, identity providers, access controls and session handling. Avoid introducing a second authentication system.",
                  "The intended access and failure behaviour is documented."),
            _step("implement", "Implement the login change",
                  "Make the smallest compatible UI and server changes; validate input, access control and session handling.",
                  "Expected login and error states are supported.", paths=paths),
            _step("security", "Review authentication security",
                  "Check password handling, CSRF, rate limits, safe session cookies, data exposure and privilege boundaries as applicable.",
                  "Relevant security checks are recorded."),
        ],
        "debugging": [
            _step("reproduce", "Reproduce the reported problem",
                  "Find the relevant failing test or exact error before proposing a fix.",
                  "The failure has reproducible evidence."),
            _step("implement", "Fix the underlying cause",
                  "Apply a minimal, checksum-checked change without unrelated refactoring.",
                  "The fix addresses the observed cause.", paths=paths),
            _step("regression", "Add a regression check",
                  "Cover the original failure without suppressing the error.",
                  "The same failure is caught by a focused check."),
        ],
        "testing": [
            _step("identify", "Find the behaviour that needs tests",
                  "Review public inputs, expected outputs and existing test conventions.",
                  "The intended assertions are clear.", paths=paths),
            _step("implement", "Add focused test cases",
                  "Cover both expected behaviour and an important failure or edge case.",
                  "Tests verify behaviour rather than implementation details."),
        ],
        "refactoring": [
            _step("baseline", "Record the current behaviour",
                  "Identify callers, contracts and a regression baseline before restructuring.",
                  "Existing behaviour can be checked.", paths=paths),
            _step("implement", "Make one focused improvement",
                  "Preserve external interfaces and avoid needless dependency changes.",
                  "Public contracts remain compatible."),
        ],
        "interface": [
            _step("structure", "Check the existing interface design",
                  "Identify the component, routes, design tokens and mobile layout patterns.",
                  "The right page and its dependencies are understood.", paths=paths),
            _step("implement", "Build the requested interface",
                  "Reuse existing components, add keyboard support and preserve responsive behaviour.",
                  "The page meets the requested interaction and accessibility requirements."),
        ],
        "feature": [
            _step("scope", "Identify inputs, outputs and existing integrations",
                  "Locate the most relevant implementation files and define a small testable change.",
                  "Affected behaviour and dependencies are understood.", paths=paths),
            _step("implement", "Implement the feature incrementally",
                  "Change only necessary files and preserve existing behaviour.",
                  "The requested feature can be exercised."),
        ],
    }
    final = [
        _step("tests", "Run relevant checks",
              "Show the exact test or build command for approval before running it; capture failures as well as passes.",
              "Actual test results are available, or the reason tests could not run is clear."),
        _step("review", "Review changes and decide what to keep",
              "Inspect each diff and any residual risks; keep or undo changes using the existing checkpoint controls.",
              "Changes are reviewed by the user before they are retained or shared."),
    ]
    return [first, *specifics[category], *final][:MAX_PLAN_STEPS]


@router.post("/task-plan")
def task_plan(request: Request, body: PlanIn):
    studio._auth(request)
    root = studio._project(body.project)
    category = _category(body.request)
    search_terms = grounding._terms(body.request)
    evidence, scanned, size, truncated = grounding._search(root, search_terms) if search_terms else ([], 0, 0, False)
    # The plan contains paths and digests, not the potentially sensitive source excerpts.
    matched = [{
        "path": item["path"], "line_start": item["line_start"],
        "line_end": item["line_end"], "sha256": item["sha256"],
    } for item in evidence[:MAX_HINTS]]
    hints = list(dict.fromkeys(item["path"] for item in matched))
    steps = _steps(category, hints)
    identity = studio._identity(root)
    digest = hashlib.sha256(json.dumps({
        "identity": identity, "request": body.request,
        "steps": steps, "evidence": matched,
    }, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "plan_id": digest, "project": str(root), "request": body.request,
        "category": category, "steps": steps, "evidence": matched,
        "source_verified": bool(matched), "scan_truncated": truncated,
        "scanned_files": scanned, "scanned_bytes": size,
        "approval_required": True, "execution_started": False,
        "source_modified": False, "read_only": True, "local_only": True,
        "max_steps": MAX_PLAN_STEPS,
        "notice": ("This is a suggested plan. Matching source paths are evidence only; "
                   "steps are not completed and no action has started."),
    }
