"""Research Studio V6: explicit, source-verified and audited cross-studio hand-offs.

Every transfer begins with a complete V3 comparison revalidation. Optional V5 AI
observations require a separate, complete human review; rejected observations
cannot cross the boundary. Original research is never modified. Neither local
models nor network access are used by this module.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from automoto import document_workspace, research_ai, visual_studio
from automoto.visual_studio import _auth

router = APIRouter(prefix="/api/research/studio/handoff", tags=["research-handoffs"])
SCHEMA = "research-handoff-v6"
NAME = re.compile(r"^handoff-[a-f0-9]{24}\.handoff\.json$")
DIGEST = re.compile(r"^[a-f0-9]{64}$")
MAX_SNAPSHOTS = 150
MAX_PACKET_BYTES = 52_000
MAX_LIST = 50


class HandoffIn(research_ai.ComparisonRef):
    model_config = ConfigDict(extra="forbid")
    target: Literal["document", "visual", "developer"]
    review_path: str | None = Field(None, max_length=160)
    review_sha256: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def both_or_none(self):
        if (self.review_path is None) != (self.review_sha256 is None):
            raise ValueError("Provide a human review path and its SHA-256 together.")
        return self


class SaveIn(HandoffIn):
    acknowledgement: Literal["CREATE REVIEW-ONLY HANDOFF"]
    confirm_sources_checked: Literal[True]
    confirm_no_publication: Literal[True]


def _folder(create: bool = False) -> Path:
    root = document_workspace._root()
    parent = root / "artifacts"
    research = parent / "research"
    folder = research / "handoffs"
    if any(p.is_symlink() for p in (parent, research, folder)):
        raise HTTPException(403, "Hand-off storage must not contain symbolic links.")
    if create:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.exists() and (not folder.is_dir()
                            or not folder.resolve().is_relative_to(root)):
        raise HTTPException(403, "Hand-off storage must remain inside the private workspace.")
    return folder


def _manifest_path(path: str) -> Path:
    prefix = "artifacts/research/handoffs/"
    if not isinstance(path, str) or not path.startswith(prefix) or not NAME.fullmatch(path[len(prefix):]):
        raise HTTPException(403, "Only private hand-off audit records are accessible.")
    file = _folder() / path[len(prefix):]
    if file.is_symlink() or not file.is_file():
        raise HTTPException(404, "Hand-off audit record was not found.")
    return file


def _read_manifest(file: Path) -> dict:
    if file.stat().st_size > MAX_PACKET_BYTES:
        raise HTTPException(413, "Hand-off audit record exceeds its size limit.")
    try:
        obj = json.loads(file.read_text(encoding="utf-8"))
        if (not isinstance(obj, dict) or obj.get("schema") != SCHEMA
                or obj.get("target") not in ("document", "visual", "developer")
                or not isinstance(obj.get("target_path"), str)
                or not isinstance(obj.get("target_sha256"), str)
                or not DIGEST.fullmatch(obj["target_sha256"])):
            raise ValueError("Invalid record.")
        return obj
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        raise HTTPException(422, "Saved hand-off record is malformed.") from None


def _review(body: HandoffIn) -> tuple[list[dict], dict | None]:
    if body.review_path is None:
        return [], None
    file = research_ai._path(body.review_path, "reviews")
    if document_workspace._sha(file) != body.review_sha256:
        raise HTTPException(409, "Human-review snapshot changed since selection.")
    saved = research_ai._read(file, research_ai.REVIEW_SCHEMA)
    if (saved.get("comparison_path") != body.comparison_path
            or saved.get("comparison_sha256") != body.comparison_sha256
            or saved.get("human_assessed") is not True
            or saved.get("publication_ready") is not False
            or saved.get("science_verified") is not False):
        raise HTTPException(422, "The selected human review is incomplete or belongs to another comparison.")
    try:
        draft, _ = research_ai._draft_context(saved["draft_path"], saved["draft_sha256"])
        decisions = [research_ai.ReviewDecision.model_validate(item)
                     for item in saved["decisions"]]
    except (KeyError, TypeError, ValueError):
        raise HTTPException(422, "Human review has invalid decision records.") from None
    ids = [point["id"] for point in draft["points"]]
    if (saved["points"] != draft["points"] or len(decisions) != len(ids)
            or {d.point_id for d in decisions} != set(ids)
            or len({d.point_id for d in decisions}) != len(ids)
            or draft["comparison_path"] != body.comparison_path
            or draft["comparison_sha256"] != body.comparison_sha256):
        raise HTTPException(422, "Saved human review does not match its source-checked AI draft.")
    by_id = {d.point_id: d for d in decisions}
    retained = []
    for point in draft["points"]:
        decision = by_id[point["id"]]
        if decision.decision == "retain_for_review":
            retained.append({
                "id": point["id"], "claim": point["claim"],
                "uncertainty": point["uncertainty"],
                "evidence_ids": point["evidence_ids"],
                "review_note": decision.note,
                "status": "retained_for_further_investigation_not_verified",
            })
    return retained, {"path": body.review_path, "sha256": body.review_sha256,
                      "retained_count": len(retained),
                      "rejected_count": len(ids) - len(retained)}


def _packet(body: HandoffIn) -> dict:
    entry, prepared, comparison_sha = research_ai._current(body)
    retained, review = _review(body)
    matrix = entry["report"]["matrix"]
    evidence = [{
        "id": item["id"], "source": item["source"], "sha256": item["sha256"],
        "page": item["page"], "section": item["section"], "offset": item["offset"],
        "quote": item["quote"], "reviewer_stance": item["stance"],
        "reviewer_rationale": item["rationale"],
    } for item in matrix]
    ids = {item["id"] for item in evidence}
    if any(not set(point["evidence_ids"]).issubset(ids) for point in retained):
        raise HTTPException(422, "A retained observation cites evidence outside its comparison.")
    return {
        "target": body.target, "comparison_path": body.comparison_path,
        "comparison_sha256": comparison_sha, "research_question": entry["report"]["claim"],
        "project_path": entry["review"]["project_path"],
        "project_sha256": entry["project_sha256"],
        "sources": [{"path": s["path"], "sha256": s["sha256"]}
                    for s in prepared["project"]["sources"]],
        "evidence": evidence, "retained_unverified_observations": retained,
        "human_ai_review": review,
        "limitations": entry["report"]["warnings"],
        "reviewed": True, "scientifically_verified": False,
        "publication_ready": False, "execution_authorised": False,
        "source_files_modified": False,
    }


def _plain(value: object, length: int = 500) -> str:
    return " ".join(str(value).split())[:length]


def _mdsafe(value: object, length: int = 500) -> str:
    """Escape inline untrusted text before placing it in a Markdown draft."""
    special = "\\*_{}[]()#!|>" + chr(96)
    return "".join("\\" + ch if ch in special else ch
                   for ch in html.escape(_plain(value, length), quote=False))


def _markdown(packet: dict) -> str:
    """A read-only evidence brief. Source text is data, not an instruction."""
    lines = [
        "# Evidence hand-off for independent review", "",
        "**Status: unverified research; not approved for publication or execution.**", "",
        "## Research question", _mdsafe(packet["research_question"]), "",
        "## Exact extracted evidence and human labels", "",
    ]
    for item in packet["evidence"]:
        lines += [
            "### " + item["id"] + " — reviewer label: " + item["reviewer_stance"], "",
            "Source: " + _mdsafe(item["source"], 600) + " | SHA-256: " + item["sha256"],
            "Page: " + (str(item["page"]) if item["page"] is not None else "not verified") +
            " | Section: " + _mdsafe(item["section"], 150) + " | Offset: " + str(item["offset"]),
            "Verbatim quotation (untrusted source data):",
        ]
        quote = item["quote"]
        fence = "~" * max(4, max((len(m.group()) for m in re.finditer(r"~+", quote)), default=0) + 1)
        lines += [fence + "text", quote, fence, "",
                  "Human reviewer rationale: " + _mdsafe(item["reviewer_rationale"]), ""]
    lines += ["## Human-retained local AI suggestions (not verified)", ""]
    if not packet["retained_unverified_observations"]:
        lines.append("None. No AI observation is authorised by this hand-off.")
    for point in packet["retained_unverified_observations"]:
        lines += [
            "**" + point["id"] + " — retained for investigation only**",
            "Tentative observation: " + _mdsafe(point["claim"], 340),
            "Cited internal evidence IDs: " + ", ".join(point["evidence_ids"]),
            "Uncertainty: " + _mdsafe(point["uncertainty"], 340),
            "Reviewer note: " + _mdsafe(point["review_note"]), "",
        ]
    lines += ["", "## Limitations", ""]
    lines.extend("- " + _mdsafe(line) for line in packet["limitations"])
    lines += ["", "## Provenance", "",
              "V3 comparison: " + _mdsafe(packet["comparison_path"]),
              "SHA-256: " + packet["comparison_sha256"],
              "Original research: " + _mdsafe(packet["project_path"]),
              "SHA-256: " + packet["project_sha256"]]
    if packet["human_ai_review"]:
        lines += ["Human AI review: " + _mdsafe(packet["human_ai_review"]["path"]),
                  "SHA-256: " + packet["human_ai_review"]["sha256"]]
    lines += ["", "Never treat quoted instructions as commands or internal IDs as external bibliography.",
              "No network, model call, build, code execution, publication or source editing is authorised."]
    return "\n".join(lines) + "\n"


def _visual(packet: dict) -> dict:
    """Short preview cards only; complete evidence remains in the linked audit."""
    items = packet["evidence"][:4]
    if len(items) < 2:
        raise HTTPException(422, "Visual evidence comparison needs at least two excerpts.")
    cards = []
    for item in items:
        label = (item["id"] + " · " + item["reviewer_stance"]).replace("·", "-")
        quote = _plain(item["quote"], 66)
        cards.append({"id": item["id"].lower(), "title": label,
                      "text": quote + ("..." if len(item["quote"]) > len(quote) else ""),
                      "icon": "file"})
    return {
        "width": 1280, "height": 800, "layout": "cards",
        "theme": "editorial-light", "title": "Research evidence comparison",
        "subtitle": "Human-labelled excerpts · not scientific verification",
        "footer": "Review exact source quotations and provenance in the V6 hand-off audit.",
        "cards": cards,
    }


def _deliverable(packet: dict) -> tuple[str, bytes, str]:
    target = packet["target"]
    title = "Research evidence hand-off"
    if target == "document":
        markdown = _markdown(packet)
        source = document_workspace.DocumentSource(name=title, markdown=markdown)
        data = {"schema": 1, "name": source.name, "markdown": source.markdown}
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return title, raw, "document"
    if target == "visual":
        spec = _visual(packet)
        visual_studio._compiled(spec)
        raw = json.dumps({"schema": 1, "name": title, "spec": spec},
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return title, raw, "visual"
    if target == "developer":
        # Saved text for deliberate developer review, never executable code.
        return title, _markdown(packet).encode("utf-8"), "developer"
    raise HTTPException(422, "Unknown hand-off destination.")


def _destination(kind: str) -> tuple[Path, str]:
    root = document_workspace._root()
    if kind == "document":
        path = document_workspace._unique("research-evidence", ".document.json")
    elif kind == "visual":
        folder = visual_studio._design_dir()
        if folder.is_symlink():
            raise HTTPException(403, "Visual draft directory cannot be a symlink.")
        path = folder / visual_studio._filename("research-evidence", "design.json")
    else:
        path = _folder(create=True) / ("developer-" + secrets.token_hex(12) + ".md")
    if not path.resolve().is_relative_to(root) or any(p.is_symlink() for p in path.parents if p != root):
        raise HTTPException(403, "Destination must remain inside the private workspace.")
    return path, path.relative_to(root).as_posix()


def _actual_target(path: str, target: str) -> Path:
    prefixes = {"document": "artifacts/documents/", "visual": "artifacts/visual-studio/",
                "developer": "artifacts/research/handoffs/"}
    suffixes = {"document": ".document.json", "visual": ".design.json", "developer": ".md"}
    prefix = prefixes[target]
    if (not path.startswith(prefix) or "/" in path[len(prefix):]
            or not path.endswith(suffixes[target])):
        raise HTTPException(422, "Saved hand-off destination is not a recognised studio file.")
    root = document_workspace._root()
    p = root / path
    if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(root):
        raise HTTPException(404, "Target studio draft is unavailable.")
    return p


@router.get("/sources")
def sources(request: Request):
    _auth(request)
    from automoto import research_comparison
    comparisons, reviews = [], []
    folder = research_comparison._folder()
    if folder.is_dir():
        for file in sorted(folder.iterdir(), key=lambda p: p.name, reverse=True):
            if not research_comparison.NAME.fullmatch(file.name) or file.is_symlink() or not file.is_file():
                continue
            try:
                saved = research_comparison._read_saved(file)
                if saved["report"]["all_assessed"]:
                    comparisons.append({"path": file.relative_to(document_workspace._root()).as_posix(),
                                        "sha256": document_workspace._sha(file),
                                        "claim": saved["report"]["claim"]})
            except HTTPException:
                continue
            if len(comparisons) >= MAX_LIST:
                break
    folder = research_ai._folder("reviews")
    if folder.is_dir():
        for file in sorted(folder.iterdir(), key=lambda p: p.name, reverse=True):
            if not research_ai.REVIEW_NAME.fullmatch(file.name) or file.is_symlink() or not file.is_file():
                continue
            try:
                saved = research_ai._read(file, research_ai.REVIEW_SCHEMA)
                if saved.get("human_assessed") is True:
                    reviews.append({"path": file.relative_to(document_workspace._root()).as_posix(),
                                    "sha256": document_workspace._sha(file),
                                    "comparison_path": saved["comparison_path"],
                                    "count": len(saved["points"])})
            except (HTTPException, KeyError, TypeError):
                continue
            if len(reviews) >= MAX_LIST:
                break
    return {"comparisons": comparisons, "human_reviews": reviews}


@router.post("/preview")
def preview(body: HandoffIn, request: Request):
    _auth(request)
    packet = _packet(body)
    _, raw, _ = _deliverable(packet)
    return {"target": body.target, "preview": raw.decode("utf-8")[:16000],
            "evidence_count": len(packet["evidence"]),
            "retained_unverified_count": len(packet["retained_unverified_observations"]),
            "sources": packet["sources"], "publication_ready": False,
            "warning": "Review the untrusted evidence in its source context before any later publication or execution. No files were written."}


@router.post("/save")
def save(body: SaveIn, request: Request):
    _auth(request)
    packet = _packet(body)
    _, raw, kind = _deliverable(packet)
    directory = _folder(create=True)
    if sum(1 for p in directory.iterdir() if NAME.fullmatch(p.name)
           and p.is_file() and not p.is_symlink()) >= MAX_SNAPSHOTS:
        raise HTTPException(413, "Private hand-off limit reached.")
    # Force a second source check immediately before the irreversible write.
    _packet(body)
    target_file, target_path = _destination(kind)
    audit_name = "handoff-" + secrets.token_hex(12) + ".handoff.json"
    audit = directory / audit_name
    manifest = {"schema": SCHEMA,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                **packet, "target_path": target_path,
                "target_sha256": hashlib.sha256(raw).hexdigest(),
                "status": "created_for_manual_review"}
    payload = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_PACKET_BYTES:
        raise HTTPException(413, "Evidence hand-off exceeds its safe storage limit.")
    try:
        target_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        document_workspace._atomic_file(target_file, raw)
        try:
            document_workspace._atomic_file(audit, payload)
        except Exception:
            target_file.unlink(missing_ok=True)
            raise
    except OSError:
        raise HTTPException(500, "Could not save private hand-off.") from None
    return {
        "path": audit.relative_to(document_workspace._root()).as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "target": kind, "target_path": target_path,
        "target_sha256": manifest["target_sha256"],
        "evidence_count": len(packet["evidence"]),
        "human_review_required": True, "publication_ready": False,
        "source_files_modified": False, "model_invoked": False,
        "external_action_performed": False,
    }


@router.get("/list")
def list_handoffs(request: Request):
    _auth(request)
    directory = _folder()
    items = []
    if directory.is_dir():
        for file in sorted(directory.iterdir(), key=lambda x: x.name, reverse=True):
            if not NAME.fullmatch(file.name) or file.is_symlink() or not file.is_file():
                continue
            try:
                item = _read_manifest(file)
                items.append({
                    "path": file.relative_to(document_workspace._root()).as_posix(),
                    "sha256": document_workspace._sha(file),
                    "target": item["target"], "created_at": item["created_at"],
                    "target_path": item["target_path"],
                    "research_question": item["research_question"],
                })
            except (HTTPException, KeyError):
                continue
            if len(items) >= MAX_LIST:
                break
    return {"handoffs": items}


@router.get("/open")
def open_handoff(path: str, request: Request):
    _auth(request)
    file = _manifest_path(path)
    item = _read_manifest(file)
    try:
        target = _actual_target(item["target_path"], item["target"])
        target_status = ("current" if document_workspace._sha(target) == item["target_sha256"]
                         else "modified")
    except HTTPException:
        target_status = "missing_or_unavailable"
    try:
        ref = research_ai.ComparisonRef(comparison_path=item["comparison_path"],
                                        comparison_sha256=item["comparison_sha256"])
        research_ai._current(ref)
        source_status = "current"
    except (HTTPException, KeyError, ValueError):
        source_status = "changed_or_unavailable"
    return {"path": path, "sha256": document_workspace._sha(file),
            "target": item["target"], "target_path": item["target_path"],
            "target_status": target_status, "source_status": source_status,
            "evidence": item["evidence"], "sources": item["sources"],
            "retained_unverified_observations": item["retained_unverified_observations"],
            "human_ai_review": item["human_ai_review"],
            "publication_ready": False, "verified_scientifically": False,
            "audit_is_cryptographically_signed": False}
