"""Research Studio V3 — reviewer-controlled, source-audited evidence comparisons.

The software checks that quoted passages originate at the recorded offsets in
the original, SHA-256-pinned files. Only humans assign support/contradiction
labels and method/quality judgements. No inference, model, network access,
bibliographic invention or source-file modification happens in this module.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from automoto import document_research, document_workspace, research_studio
from automoto.visual_studio import _auth

router = APIRouter(prefix="/api/research/studio/compare", tags=["research-comparison"])
SCHEMA = "research-comparison-v3"
NAME = re.compile(r"^comparison-[0-9a-f]{24}\.comparison\.json$")
ID = re.compile(r"^S([1-5])-(0[1-8])$")
SHA = re.compile(r"^[0-9a-f]{64}$")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_FILE = 100_000
MAX_SAVED = 150


class ProjectRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_path: str = Field(..., min_length=25, max_length=110)


class ReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str = Field(..., pattern=r"^S[1-5]-0[1-8]$")
    stance: Literal["supports", "contradicts", "uncertain", "unreviewed"] = "unreviewed"
    rationale: str = Field("", max_length=500)

    @model_validator(mode="after")
    def safe_rationale(self):
        if CONTROL.search(self.rationale):
            raise ValueError("Rationale contains non-printable characters.")
        if self.stance != "unreviewed" and len(self.rationale.strip()) < 8:
            raise ValueError("A reviewed stance requires a rationale of at least eight characters.")
        return self


class SourceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_path: str = Field(..., min_length=3, max_length=600)
    methodology: Literal["not_assessed", "experimental", "observational", "review", "other"] = "not_assessed"
    quality: Literal["not_assessed", "low", "moderate", "high"] = "not_assessed"
    limitations: str = Field("", max_length=650)

    @model_validator(mode="after")
    def safe_notes(self):
        if CONTROL.search(self.limitations):
            raise ValueError("Methodology notes contain non-printable characters.")
        return self


class ComparisonIn(ProjectRef):
    project_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    claim: str = Field(..., min_length=8, max_length=320)
    annotations: list[ReviewItem] = Field(..., max_length=8)
    source_reviews: list[SourceReview] = Field(..., min_length=2, max_length=5)

    @model_validator(mode="after")
    def safe_comparison(self):
        if not self.claim.strip() or CONTROL.search(self.claim):
            raise ValueError("Research claim must contain printable text.")
        if len({x.evidence_id for x in self.annotations}) != len(self.annotations):
            raise ValueError("Each source excerpt may be classified only once.")
        if len({x.source_path for x in self.source_reviews}) != len(self.source_reviews):
            raise ValueError("Source-quality assessments must be unique.")
        return self


class SaveIn(ComparisonIn):
    acknowledgement: Literal["SAVE REVIEW"]
    confirm_human_classification: Literal[True]


def _folder(create: bool = False) -> Path:
    root = document_workspace._root()
    parent = root / "artifacts"
    research = parent / "research"
    folder = research / "comparisons"
    if any(p.is_symlink() for p in (parent, research, folder)):
        raise HTTPException(403, "Private comparison folders cannot be symlinks.")
    if create:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.exists() and (not folder.is_dir()
                            or not folder.resolve().is_relative_to(root)):
        raise HTTPException(403, "Comparison storage must remain private.")
    return folder


def _file(raw: str) -> Path:
    prefix = "artifacts/research/comparisons/"
    if not isinstance(raw, str) or not raw.startswith(prefix) or not NAME.fullmatch(raw[len(prefix):]):
        raise HTTPException(403, "Only create-only private research comparisons may be opened.")
    file = _folder() / raw[len(prefix):]
    if file.is_symlink() or not file.is_file():
        raise HTTPException(404, "Saved comparison not found.")
    return file


def _project(ref: ProjectRef) -> tuple[Path, dict, research_studio.ProjectIn, list[dict]]:
    file = research_studio._file(ref.project_path)
    data = research_studio._read(file)
    project = research_studio.ProjectIn.model_validate(data["project"])
    if len(project.sources) < 2:
        raise HTTPException(422, "Comparison requires at least two distinct source documents.")
    findings = data["result"]["evidence"]
    if not isinstance(findings, list) or len(findings) > document_research.MAX_EVIDENCE:
        raise HTTPException(422, "Saved research contains unsupported evidence.")
    return file, data, project, findings


def _verify_quotes(project: research_studio.ProjectIn, findings: list[dict]) -> None:
    """Check each saved quote against the original SHA-pinned extracted source.

    This rejects modified source files, forged IDs, arbitrary quotes, incorrect
    offsets and invented PDF pages. A quote's existence does NOT prove its
    contents are true or scientifically relevant to a reviewer claim.
    """
    extracts = []
    for source in project.sources:
        sections, _ = document_research._snapshot(source)
        extracts.append(sections)
    seen = set()
    for item in findings:
        if not isinstance(item, dict):
            raise HTTPException(422, "Saved research has malformed evidence.")
        marker = item.get("id")
        match = ID.fullmatch(marker) if isinstance(marker, str) else None
        if not match or marker in seen:
            raise HTTPException(422, "Saved evidence IDs are invalid or repeated.")
        seen.add(marker)
        index = int(match.group(1)) - 1
        src = project.sources[index]
        quote = item.get("quote")
        offset = item.get("offset")
        if (item.get("source") != src.path or item.get("sha256") != src.sha256
                or not isinstance(quote, str) or not 20 <= len(quote) <= 450
                or not isinstance(offset, int) or isinstance(offset, bool) or offset < 0
                or not isinstance(item.get("section"), str)
                or item.get("page") is not None and
                (not isinstance(item["page"], int) or isinstance(item["page"], bool)
                 or not 1 <= item["page"] <= document_research.MAX_PDF_PAGES)):
            raise HTTPException(422, "Saved quote has inconsistent source identity.")
        # Exact byte-for-byte extracted text position rather than a loose text search.
        if not any(label == item["section"] and page == item.get("page")
                   and section[offset:offset + len(quote)] == quote
                   for label, page, section in extracts[index]):
            raise HTTPException(422, "Saved quote does not match its recorded source and offset.")


def _prepare(ref: ProjectRef, expected_sha: str | None = None) -> dict:
    file, data, project, findings = _project(ref)
    current_sha = document_workspace._sha(file)
    if expected_sha is not None and current_sha != expected_sha:
        raise HTTPException(409, "Saved source research changed. Prepare this comparison again.")
    _verify_quotes(project, findings)
    partial = data["result"].get("partial_sources") or []
    if not isinstance(partial, list) or any(not isinstance(p, str) for p in partial):
        raise HTTPException(422, "Invalid research extraction coverage.")
    if any(p not in {s.path for s in project.sources} for p in partial):
        raise HTTPException(422, "Extraction coverage does not match selected sources.")
    return {
        "project_path": ref.project_path, "project_sha256": current_sha,
        "project": project.model_dump(mode="json"),
        "evidence": [
            {key: e.get(key) for key in ("id", "source", "sha256", "page", "section",
                                         "offset", "quote")}
            for e in findings
        ],
        "partial_sources": partial,
        "source_status": research_studio._status(project),
        "source_count": len(project.sources),
        "evidence_count": len(findings),
        "source_files_modified": False, "no_model": True, "offline": True,
        "warning": "Quotation provenance verified, but relevance, article credibility and research conclusions are not machine-verified.",
    }


def _report(prepared: dict, body: ComparisonIn) -> dict:
    evidence = prepared["evidence"]
    expected_ids = {e["id"] for e in evidence}
    if {e.evidence_id for e in body.annotations} != expected_ids:
        raise HTTPException(422, "Classify every retrieved excerpt once, including any left unreviewed.")
    expected_paths = {s["path"] for s in prepared["project"]["sources"]}
    if {s.source_path for s in body.source_reviews} != expected_paths:
        raise HTTPException(422, "Assess every selected source, including sources with no matching excerpt.")
    by_id = {a.evidence_id: a for a in body.annotations}
    quality = {a.source_path: a for a in body.source_reviews}
    matrix, counts, coverage = [], {s: 0 for s in
                                     ("supports", "contradicts", "uncertain", "unreviewed")}, []
    for source in prepared["project"]["sources"]:
        path = source["path"]
        matches = [e for e in evidence if e["source"] == path]
        assessment = quality[path]
        coverage.append({
            "path": path, "sha256": source["sha256"], "excerpt_count": len(matches),
            "extraction_partial": path in prepared["partial_sources"],
            "methodology": assessment.methodology, "quality": assessment.quality,
            "limitations": assessment.limitations,
            "gap": "no_retrieved_excerpt" if not matches else
                   "partial_extraction" if path in prepared["partial_sources"] else None,
        })
        for excerpt in matches:
            annotation = by_id[excerpt["id"]]
            counts[annotation.stance] += 1
            matrix.append({
                **excerpt, "stance": annotation.stance, "rationale": annotation.rationale,
                "reviewer_assigned": annotation.stance != "unreviewed",
            })
    has_support = {e["source"] for e in matrix if e["stance"] == "supports"}
    has_challenge = {e["source"] for e in matrix if e["stance"] == "contradicts"}
    # Flag merely a *reviewer-labelled* disagreement across separate files.
    disagreement = bool(has_support and has_challenge and
                        any(a != b for a in has_support for b in has_challenge))
    warning = [
        "Positions and quality ratings are human review labels, not automated fact or study-quality verification.",
        "A retrieved quote may be relevant, misleading, incomplete or out of context.",
        "Absence of a matching excerpt does not establish the claim is false.",
    ]
    if not matrix:
        warning.append("No passages matched the source retrieval. The claim remains unassessed.")
    if counts["unreviewed"]:
        warning.append(f"{counts['unreviewed']} excerpt(s) remain unreviewed.")
    if any(item["extraction_partial"] for item in coverage):
        warning.append("Some documents were partially extracted: conclusions may be incomplete.")
    if any(item["gap"] == "no_retrieved_excerpt" for item in coverage):
        warning.append("One or more source documents have no matching retrieved excerpt.")
    return {
        "claim": body.claim.strip(), "matrix": matrix, "source_coverage": coverage,
        "counts": counts, "disagreement_flag": disagreement,
        "human_labelled": True, "science_verified": False, "automatic_contradiction_detection": False,
        "source_count": len(coverage), "evidence_count": len(matrix),
        "all_assessed": counts["unreviewed"] == 0 and bool(matrix),
        "ready_for_publication": False, "warnings": warning,
        "source_files_modified": False, "financial_postings": 0,
    }


def _read_saved(path: Path) -> dict:
    if path.stat().st_size > MAX_FILE:
        raise HTTPException(413, "Private comparison record exceeds the storage limit.")
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(entry, dict) or entry.get("schema") != SCHEMA:
            raise ValueError("Comparison schema was changed.")
        project = research_studio.ProjectIn.model_validate(entry["project"])
        body = ComparisonIn.model_validate(entry["review"])
        if len(project.sources) < 2 or body.project_sha256 != entry["project_sha256"]:
            raise ValueError("Comparison is inconsistent with the original research.")
        snapshot = {
            "project": project.model_dump(mode="json"), "evidence": entry["evidence"],
            "partial_sources": entry["partial_sources"],
        }
        stored = entry["report"]
        fresh = _report(snapshot, body)
        if fresh != stored:
            raise ValueError("Comparison summary is inconsistent with saved assessments.")
    except (OSError, UnicodeError, KeyError, TypeError, ValueError, AttributeError, HTTPException):
        raise HTTPException(422, "Saved comparison has invalid or inconsistent content.") from None
    return entry


@router.post("/prepare")
def prepare(body: ProjectRef, request: Request):
    _auth(request)
    return _prepare(body)


@router.post("/preview")
def preview(body: ComparisonIn, request: Request):
    _auth(request)
    prepared = _prepare(body, body.project_sha256)
    return {"report": _report(prepared, body), "project_sha256": prepared["project_sha256"],
            "saved": False, "server_verified_quotes": True, "no_source_writes": True}


@router.get("/list")
def list_reviews(request: Request):
    _auth(request)
    folder = _folder()
    if not folder.is_dir():
        return {"comparisons": []}
    records = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name, reverse=True):
        if not NAME.fullmatch(path.name) or not path.is_file() or path.is_symlink():
            continue
        try:
            entry = _read_saved(path)
        except HTTPException:
            continue
        records.append({
            "path": path.relative_to(document_workspace._root()).as_posix(),
            "claim": entry["review"]["claim"], "created_at": entry["created_at"],
            "source_count": entry["report"]["source_count"],
            "disagreement_flag": entry["report"]["disagreement_flag"],
        })
        if len(records) >= 100:
            break
    return {"comparisons": records}


@router.get("/open")
def open_review(path: str, request: Request):
    _auth(request)
    entry = _read_saved(_file(path))
    project = research_studio.ProjectIn.model_validate(entry["project"])
    try:
        prior = research_studio._file(entry["review"]["project_path"])
        project_status = "current" if document_workspace._sha(prior) == entry["project_sha256"] else "changed"
    except (HTTPException, OSError, UnicodeError):
        project_status = "missing_or_unavailable"
    return {
        "path": path, "review": entry["review"], "report": entry["report"],
        "source_status": research_studio._status(project), "project_status": project_status,
        "historical_snapshot": True, "source_files_modified": False,
        "warning": "Historical human judgements, not current proof. Source/project changes require a new review.",
    }


@router.post("/save")
def save(body: SaveIn, request: Request):
    _auth(request)
    prepared = _prepare(body, body.project_sha256)
    report = _report(prepared, body)
    folder = _folder(create=True)
    if sum(1 for p in folder.iterdir() if NAME.fullmatch(p.name)
           and p.is_file() and not p.is_symlink()) >= MAX_SAVED:
        raise HTTPException(413, "Private comparison library reached its 150-review limit.")
    entry = {
        "schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_sha256": prepared["project_sha256"],
        "project": prepared["project"], "evidence": prepared["evidence"],
        "partial_sources": prepared["partial_sources"],
        "review": body.model_dump(mode="json", exclude={"acknowledgement", "confirm_human_classification"}),
        "report": report,
    }
    data = json.dumps(entry, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_FILE:
        raise HTTPException(413, "Comparison snapshot exceeds the size limit.")
    target = folder / f"comparison-{secrets.token_hex(12)}.comparison.json"
    document_workspace._atomic_file(target, data)
    return {
        "path": target.relative_to(document_workspace._root()).as_posix(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "create_only": True, "saved": True, "source_files_modified": False,
        "disagreement_flag": report["disagreement_flag"],
        "ready_for_publication": False,
        "message": "Human-labelled comparison saved as an immutable review snapshot.",
    }
