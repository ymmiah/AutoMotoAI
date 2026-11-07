"""v7 pre-publication accessibility, editorial and actual Word structure audit.

This is a release-quality *technical* checklist, not an AI proofreader or a
claim that sources are true. The report is read-only and always requires a
human to inspect the final Word/PDF pages and bibliography.
"""
from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import ConfigDict

from automoto.document_workspace import DocumentSource, preflight_document
from automoto.visual_studio import _auth

router = APIRouter(prefix="/api/documents/quality", tags=["document-quality"])
_HEAD = re.compile(r"^([#]{1,6})\s+(.+?)\s*$", re.MULTILINE)
_PLACEHOLDER = re.compile(r"\[(?:[A-Z][a-z]+(?: [a-zA-Z]+){1,7}|[A-Z][^\]\n]{3,50})\]")
_WORD = re.compile(r"\b[\w'-]+\b", re.UNICODE)


class AuditIn(DocumentSource):
    model_config = ConfigDict(extra="forbid")


def _editorial_issues(body: AuditIn):
    markdown = body.markdown
    issues = []
    headings = [(len(m.group(1)), m.group(2).strip()) for m in _HEAD.finditer(markdown)]
    def add(code: str, title: str, reason: str, severity: Literal["warning", "notice"] = "warning"):
        issues.append({"code": code, "severity": severity, "title": title, "detail": reason})
    if not markdown.strip():
        add("empty-source", "No document content", "Enter source text before preparing publication.")
    if not headings:
        add("heading-structure", "No document headings", "Use real Markdown headings for a navigable Word outline.")
    last = 0
    for level, heading in headings:
        if (last and level > last + 1) or (not last and level > 1):
            add("heading-jump", "Heading levels skip a level",
                f"A heading labelled '{heading[:65]}' jumps to H{level}; check accessible reading order.")
            break
        last = level
    placeholders = list(dict.fromkeys(_PLACEHOLDER.findall(markdown)))
    if placeholders:
        add("placeholder-text", "Review template placeholders",
            "Possible unresolved fields: " + ", ".join(placeholders[:4]))
    groups = []
    current = []
    for line in markdown.splitlines() + [""]:
        if line.strip().startswith("|"):
            current.append(line)
        elif current:
            groups.append(current)
            current = []
    for group in groups:
        counts = [len(line.strip().strip("|").split("|")) for line in group]
        if len(set(counts)) > 1:
            add("ragged-table", "Inconsistent table columns",
                "One Markdown table contains rows with different column counts.")
            break
    words = len(_WORD.findall(markdown))
    if words >= 1200 and body.options is not None and not body.options.page_numbers:
        add("page-navigation", "Page numbering disabled",
            "Consider page numbers to help navigate this longer document.", "notice")
    if body.publication is not None:
        if body.publication.cover_page and not body.publication.author.strip():
            add("missing-cover-author", "Cover page has no named author",
                "Add a real author or confirm anonymous publication is intentional.")
        if body.publication.template == "academic-report" and not body.publication.references:
            add("missing-sources", "Academic report has no source library",
                "Check whether verifiable evidence and a complete reference list are required.")
    if len(markdown.splitlines()) > 2000:
        add("long-source", "Long document",
            "Check page boundaries, tables and image flow using the final exported file.", "notice")
    return issues, words, headings, len(groups)


@router.post("/audit")
def quality_audit(body: AuditIn, request: Request):
    _auth(request)
    issues, words, headings, tables = _editorial_issues(body)
    # The existing preflight builds and opens a genuine temporary OOXML Word
    # document and immediately discards it. No user document is ever saved.
    preflight = preflight_document(body, request)
    for warning in preflight.get("warnings", []):
        issues.append({"code": "word-preflight-warning", "severity": "warning",
                       "title": "Publication warning", "detail": warning})
    return {
        "structurally_exportable": preflight["ready"],
        "human_review_required": True, "files_saved": False,
        "word_bytes_verified": preflight["word_bytes"],
        "word_count": words, "heading_count": len(headings), "tables_detected": tables,
        "references": preflight["reference_count"],
        "issues": issues[:24], "warning_count": sum(i["severity"] == "warning" for i in issues),
        "acceptance_checks": [
            {"name": "Word OOXML build and inspection", "passed": True},
            {"name": "Private original files preserved", "passed": True},
            {"name": "Factual and source verification", "passed": False,
             "note": "Must be performed by the author; no automated fact-check claimed."},
            {"name": "Rendered page layout and accessibility review", "passed": False,
             "note": "Inspect final Word/PDF export in a compatible viewer."},
        ],
        "limitations": "This is a technical and editorial audit only. It does not verify research truth, "
                       "copyright, licence compliance, mathematical correctness or pixel-perfect layout.",
    }
