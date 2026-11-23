"""V53: bounded-agent, approval-only bridge to V51's checked patch engine.

The model cannot save source directly. It may propose a bounded, exact-match
replacement in an *existing* file. The server prepares the V51 diff first,
shows it to the user, and commits that exact one-use preview only after the
task's separate human approval. This tool is never registered for an
unbounded/hosted/routine agent.
"""
from __future__ import annotations

import json

from fastapi import HTTPException
from pydantic import ValidationError

from automoto import developer_safe_patch as patch, sandbox
from automoto.studio_registry import studio_request
from automoto.tools import Tool, ToolContext, ToolFailed


def _unavailable(ctx: ToolContext, **kwargs) -> str:
    """Fail closed if the action is called outside the bounded loop's bridge."""
    raise ToolFailed("An agent patch can only be applied by the bounded approval gateway.")


def patch_tool() -> Tool:
    return Tool(
        "developer_agent_patch",
        "Propose a small exact one-occurrence change to an existing code file. "
        "Pass expected_sha256 from developer_read. Before this edit is applied, "
        "AutoMoto independently verifies the source, displays the exact unified "
        "diff and waits for the user to tap Apply once. Stale, large, ambiguous, "
        "protected, invalid or out-of-project edits fail closed. Cannot create "
        "new files, execute a command or share anything.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Existing project-relative source path."},
                "expected_sha256": {"type": "string", "description": "Original SHA-256 from developer_read."},
                "old_fragment": {"type": "string", "description": "Exact original text; must occur once."},
                "new_fragment": {"type": "string", "description": "Replacement text (may be empty)."},
            },
            "required": ["path", "expected_sha256", "old_fragment", "new_fragment"],
            "additionalProperties": False,
        },
        "risky", _unavailable, group="studio:developer",
    )


def prepare(args: dict) -> dict:
    """Build a V51 read-only preview, scoped to the actual sandbox root."""
    try:
        body = patch.PreviewIn.model_validate({
            "project": str(sandbox.root()),
            "path": args["path"],
            "expected_sha256": args["expected_sha256"],
            "old_fragment": args["old_fragment"],
            "new_fragment": args["new_fragment"],
        })
        return patch.preview(studio_request("POST"), body)
    except (HTTPException, ValidationError, KeyError, TypeError, ValueError) as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        raise ToolFailed(str(detail)[:900]) from None


def commit(prepared: dict) -> dict:
    """ONLY invoked by the bounded loop after a specific approved tool call."""
    try:
        root = patch._trusted(str(sandbox.root()))
        return patch._apply_checked(root, prepared["path"], prepared["token"],
                                    studio_request("POST"))
    except (HTTPException, ValidationError, KeyError, TypeError, ValueError) as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        raise ToolFailed(str(detail)[:900]) from None


def public_approval(prepared: dict) -> dict:
    """Server-created evidence: never accept a model-generated diff for approval."""
    return {
        "path": prepared["path"],
        "original_sha256": prepared["original_sha256"],
        "after_sha256": prepared["after_sha256"],
        "preview_diff": prepared["diff"],
        "changed_lines": prepared["changed_lines"],
        "syntax_checked": prepared["syntax_checked"],
        "prepared_by_server": True,
    }
