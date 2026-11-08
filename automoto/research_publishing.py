"""Research Studio V4: source-pinned academic reports and DOI-backed references.

Reuses V1/V3 evidence verification, V2 saved Crossref metadata and the existing
Document Assistant Word/PDF exporter. Does not infer source-paper identity, query
the network, generate conclusions, or overwrite existing research and reports.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from automoto import document_publishing, document_workspace, research_comparison, research_discovery
from automoto.visual_studio import _auth

router = APIRouter(prefix="/api/research/studio/publish", tags=["research-publishing"])
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
CITE = re.compile(r"\[@[^\]\n]*\]")
PREFIX = "artifacts/research/sources/"
MAX_MARKDOWN = 48_000


class CompareRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comparison_path: str = Field(..., min_length=45, max_length=140)


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_path: str = Field(..., min_length=3, max_length=600)
    source_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    metadata_path: str = Field(..., min_length=45, max_length=140)
    metadata_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    confirm_same_publication: Literal[True]


class ReportIn(CompareRef):
    comparison_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    title: str = Field(..., min_length=5, max_length=140)
    author: str = Field(..., min_length=2, max_length=130)
    institution: str = Field("", max_length=140)
    introduction: str = Field(..., min_length=15, max_length=1600)
    interpretation: str = Field("", max_length=1400)
    limitations: str = Field(..., min_length=12, max_length=1300)
    conclusion: str = Field(..., min_length=15, max_length=1500)
    style: Literal["harvard", "ieee"] = "harvard"
    bindings: list[Binding] = Field(..., min_length=2, max_length=5)

    @model_validator(mode="after")
    def safe(self):
        for value in (self.title, self.author, self.institution, self.introduction,
                      self.interpretation, self.limitations, self.conclusion):
            if CONTROL.search(value) or CITE.search(value):
                raise ValueError("Author text cannot contain controls or fabricated citation markers.")
        if any(not x.strip() for x in (self.title, self.author, self.introduction,
                                        self.limitations, self.conclusion)):
            raise ValueError("Report title and required authored sections cannot be blank.")
        if len({b.source_path for b in self.bindings}) != len(self.bindings):
            raise ValueError("A source may be bound to one bibliographic entry only.")
        if len({b.metadata_path for b in self.bindings}) != len(self.bindings):
            raise ValueError("One DOI record cannot be presented as several different publications.")
        return self


class ExportIn(ReportIn):
    format: Literal["docx", "pdf"] = "docx"
    acknowledgement: Literal["EXPORT REVIEW"]
    confirm_checked_references: Literal[True]


class SaveDraftIn(ReportIn):
    acknowledgement: Literal["SAVE DRAFT"]
    confirm_checked_references: Literal[True]


def _comparison(raw: str, sha256: str | None = None) -> tuple[dict, dict, str]:
    path = research_comparison._file(raw)
    digest = document_workspace._sha(path)
    if sha256 is not None and sha256 != digest:
        raise HTTPException(409, "Comparison changed: reload the source and reviews.")
    entry = research_comparison._read_saved(path)
    ref = research_comparison.ProjectRef(project_path=entry["review"]["project_path"])
    current = research_comparison._prepare(ref, entry["project_sha256"])
    if (entry["project"] != current["project"]
            or entry["evidence"] != current["evidence"]
            or entry["partial_sources"] != current["partial_sources"]):
        raise HTTPException(422, "Historical review differs from current source-verified research.")
    reviewed = research_comparison.ComparisonIn.model_validate(entry["review"])
    if research_comparison._report(current, reviewed) != entry["report"]:
        raise HTTPException(422, "Historical review content is inconsistent.")
    return entry, current, digest


def _metadata_path(raw: str) -> Path:
    if not isinstance(raw, str) or not raw.startswith(PREFIX) or not research_discovery.FILE.fullmatch(raw[len(PREFIX):]):
        raise HTTPException(403, "Only privately saved V2 DOI records are supported.")
    path = research_discovery._folder("sources") / raw[len(PREFIX):]
    if path.is_symlink() or not path.is_file():
        raise HTTPException(404, "Saved bibliographic record does not exist.")
    if path.stat().st_size > research_discovery.MAX_METADATA_BYTES:
        raise HTTPException(413, "Bibliographic record is oversized.")
    return path


def _required(value: object, cap: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > cap:
        raise ValueError("Bibliographic record has missing or oversized fields.")
    if CONTROL.search(value) or CITE.search(value):
        raise ValueError("Bibliographic record has unsafe or forged citation text.")
    return value.strip()


def _metadata(binding: Binding) -> dict:
    path = _metadata_path(binding.metadata_path)
    if document_workspace._sha(path) != binding.metadata_sha256:
        raise HTTPException(409, "Saved DOI record changed: reselect the original bibliographic metadata.")
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(envelope, dict) or envelope.get("schema") != "research-source-v2":
            raise ValueError("Wrong bibliographic source schema.")
        meta = envelope["metadata"]
        if not isinstance(meta, dict) or meta.get("registry") != "Crossref":
            raise ValueError("Only Crossref-verified saved DOI records can be used in V4.")
        doi = research_discovery._normalise_doi(_required(meta.get("doi"), 260))
        if meta.get("doi_url") != "https://doi.org/" + doi:
            raise ValueError("Canonical DOI URL does not match the registered DOI.")
        title = _required(meta.get("title"), 320)
        authors = meta.get("authors")
        if not isinstance(authors, list) or not 1 <= len(authors) <= 8:
            raise ValueError("Author information must be present in the saved record.")
        authors = [_required(author, 100) for author in authors]
        publication_date = _required(meta.get("publication_date"), 10)
        if not re.fullmatch(r"[12][0-9]{3}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12][0-9]|3[01]))?)?", publication_date):
            raise ValueError("A real publication year must be known; no dates are guessed.")
        retrieved_at = _required(meta.get("retrieved_at"), 55)
        if datetime.fromisoformat(retrieved_at).tzinfo is None:
            raise ValueError("A source retrieval date with timezone is required.")
        venue = meta.get("venue")
        if venue is not None:
            venue = _required(venue, 180)
        kind = meta.get("type")
        if kind is not None:
            kind = _required(kind, 60)
    except (ValueError, TypeError, OSError, UnicodeError, KeyError, HTTPException):
        raise HTTPException(422, "Saved DOI record is missing required or consistent metadata.") from None
    return {
        "source_path": binding.source_path, "source_sha256": binding.source_sha256,
        "metadata_path": binding.metadata_path, "metadata_sha256": binding.metadata_sha256,
        "doi": doi, "title": title, "authors": authors, "year": publication_date[:4],
        "publication_date": publication_date, "retrieved_at": retrieved_at,
        "venue": venue, "type": kind,
    }


def _records(current: dict, bindings: list[Binding]) -> list[dict]:
    sources = current["project"]["sources"]
    if len(sources) != len(bindings) or {s["path"] for s in sources} != {b.source_path for b in bindings}:
        raise HTTPException(422, "Link exactly one saved DOI record to every pinned original document.")
    by_source = {b.source_path: b for b in bindings}
    result = []
    for source in sources:
        binding = by_source[source["path"]]
        if binding.source_sha256 != source["sha256"]:
            raise HTTPException(409, "Document fingerprint does not match the confirmed publication association.")
        result.append(_metadata(binding))
    if len({item["doi"] for item in result}) != len(result):
        raise HTTPException(422, "Two different documents cannot be presented as separate publications under one DOI.")
    return result


def _reference(meta: dict, i: int) -> document_publishing.Reference:
    names = meta["authors"]
    return document_publishing.Reference(
        id="r" + str(i), authors=", ".join(names), author_label=names[0],
        year=meta["year"], title=meta["title"],
        type="journal" if meta["type"] == "journal-article" and meta["venue"] else "web",
        journal=meta["venue"] if meta["type"] == "journal-article" else None,
        doi=meta["doi"], url="https://doi.org/" + meta["doi"],
        accessed=meta["retrieved_at"][:10],
    )


def _plain(value: str) -> str:
    if CITE.search(value):
        raise HTTPException(422, "Source quotation contains citation-marker syntax; review it manually.")
    return re.sub(r"([\\*_{}\[\]#|<>~])", r"\\\1", value.replace("\r", ""))


def _paragraphs(value: str) -> str:
    return "\n\n".join(_plain(p.strip()) for p in re.split(r"\n\s*\n", value.strip()) if p.strip())


def _quotation(value: str) -> str:
    return "\n".join("> " + _plain(line) for line in value.splitlines())


def _assemble(body: ReportIn) -> tuple[document_workspace.DocumentSource, dict]:
    entry, current, digest = _comparison(body.comparison_path, body.comparison_sha256)
    records = _records(current, body.bindings)
    refs = [_reference(item, i) for i, item in enumerate(records, 1)]
    report = entry["report"]
    lookup = {item["source_path"]: (i, item) for i, item in enumerate(records, 1)}
    parts = [
        "# " + _plain(body.title), "",
        "## Research provenance and limitations", "",
        "This is a human-reviewed evidence comparison, not an automatically verified scientific conclusion. "
        "Bibliographic fields come from historical Crossref metadata and may need checking against the original publication.", "",
        "Research comparison SHA-256: " + digest, "",
        "Original research question:", "", _quotation(current["project"]["question"]), "",
        "## Research context and scope", "", _paragraphs(body.introduction), "",
        "## Reviewer-assessed claim", "", _quotation(report["claim"]), "",
        "## Evidence by source", "",
    ]
    for source in report["source_coverage"]:
        i, meta = lookup[source["path"]]
        parts.extend([
            "### Source " + str(i) + ": " + _plain(meta["title"]), "",
            "Registered source reference: [@r" + str(i) + "]", "",
            "Local source file: " + _plain(source["path"]), "",
            "Pinned document SHA-256: " + source["sha256"], "",
            "Registered DOI: " + meta["doi"], "",
            "Registry metadata captured: " + meta["retrieved_at"], "",
            "Methodology (reviewer-labelled): " + source["methodology"].replace("_", " "), "",
            "Quality (reviewer-labelled): " + source["quality"].replace("_", " "), "",
            "Source coverage: " + str(source["excerpt_count"]) + " excerpts", "",
        ])
        if source["limitations"]:
            parts.extend(["Reviewer limitations: " + _plain(source["limitations"]), ""])
        if source["gap"]:
            parts.extend(["Evidence coverage warning: " + source["gap"].replace("_", " "), ""])
        for excerpt in report["matrix"]:
            if excerpt["source"] != source["path"]:
                continue
            parts.extend([
                "#### Evidence " + excerpt["id"], "",
                _quotation(excerpt["quote"]), "",
                "Human stance: " + excerpt["stance"] + " (not machine-verified)", "",
                "Reviewer explanation: " + (_plain(excerpt["rationale"]) if excerpt["rationale"]
                                             else "Unreviewed"), "",
                "Extracted section: " + _plain(excerpt["section"]) + ", offset " +
                str(excerpt["offset"]) +
                (", PDF page " + str(excerpt["page"]) if excerpt["page"] else
                 " (no verified page number)"), "",
            ])
    counts = report["counts"]
    parts.extend([
        "## Evidence comparison summary", "",
        "Reviewer-labelled passages: supports " + str(counts["supports"]) +
        "; contradicts " + str(counts["contradicts"]) +
        "; uncertain " + str(counts["uncertain"]) +
        "; unreviewed " + str(counts["unreviewed"]) + ".", "",
        "Cross-source reviewer-labelled disagreement: " +
        ("Present" if report["disagreement_flag"] else "Not established") + ".", "",
        "## Interpretation (author supplied)", "",
        _paragraphs(body.interpretation) if body.interpretation.strip() else
        "No additional interpretation was entered.", "",
        "## Limitations and uncertainty", "", _paragraphs(body.limitations), "",
    ])
    for warning in report["warnings"]:
        parts.extend(["- " + _plain(warning), ""])
    parts.extend([
        "## Conclusion (author supplied)", "", _paragraphs(body.conclusion), "",
        "## Citation verification note", "",
        "References were compiled from historical DOI registry snapshots and deliberately linked "
        "to local files by the author. A valid DOI does not establish peer review or prove that "
        "the selected file is the corresponding paper. Verify author names, year, journal, "
        "document version, DOI, claim context and institutional reference formatting.", "",
    ])
    markdown = "\n".join(parts)
    if len(markdown) > MAX_MARKDOWN:
        raise HTTPException(413, "Generated report exceeds bounded Markdown size.")
    pub = document_publishing.PublicationOptions(
        reference_style=body.style, author=body.author, institution=body.institution,
        document_date=datetime.now().date().isoformat(),
        cover_page=True, contents_page=True, template="academic-report", references=refs,
    )
    doc = document_workspace.DocumentSource(
        name=body.title, markdown=markdown,
        options=document_workspace.LayoutOptions(
            page_size="A4", font="Times New Roman", font_size=11,
            line_spacing=1.5, margins_cm=2.5, page_numbers=True,
        ), publication=pub,
    )
    return doc, {
        "comparison_sha256": digest,
        "review_complete": bool(report["all_assessed"]),
        "references": len(refs),
        "source_bindings": [
            {"source_path": item["source_path"], "source_sha256": item["source_sha256"],
             "doi": item["doi"], "metadata_sha256": item["metadata_sha256"],
             "metadata_path": item["metadata_path"], "publication_date": item["publication_date"],
             "author_confirmed_association": True} for item in records
        ],
        "warnings": list(report["warnings"]) + [
            "Bibliographic metadata was checked when saved in V2, not against a live registry during this report.",
            "Crossref author display names may require manual adaptation to your institution's Harvard or IEEE variant.",
            "The association between a local file and a DOI was confirmed by the author, not independently proved.",
        ],
    }


@router.post("/prepare")
def prepare(body: CompareRef, request: Request):
    _auth(request)
    entry, current, digest = _comparison(body.comparison_path)
    records = []
    for path, data in research_discovery._saved_metadata():
        meta = data["metadata"]
        if meta.get("registry") != "Crossref":
            continue
        records.append({
            "path": path.relative_to(document_workspace._root()).as_posix(),
            "sha256": document_workspace._sha(path), "doi": meta.get("doi"),
            "title": meta.get("title"), "authors": meta.get("authors"),
            "publication_date": meta.get("publication_date"),
            "retrieved_at": meta.get("retrieved_at"), "venue": meta.get("venue"),
        })
    return {
        "comparison_path": body.comparison_path, "comparison_sha256": digest,
        "sources": current["project"]["sources"],
        "source_status": current["source_status"],
        "claim": entry["report"]["claim"],
        "review_complete": entry["report"]["all_assessed"],
        "metadata_records": records[:200],
        "no_network_requests": True, "source_files_modified": False,
        "warning": "Only link a source to its actual publication after personally checking the original.",
    }


@router.post("/preflight")
def preflight(body: ReportIn, request: Request):
    _auth(request)
    source, state = _assemble(body)
    result = document_workspace.preflight_document(source, request)
    ready = bool(state["review_complete"])
    return {
        "ready": ready, "word_build_valid": result["ready"],
        "word_bytes": result["word_bytes"],
        "reference_count": state["references"], "citation_style": body.style,
        "formatted_references": [
            ref.format(body.style, i) if body.style == "ieee" else ref.format("harvard")
            for i, ref in enumerate(source.publication.references, start=1)
        ],
        "report_markdown": source.markdown,
        "warnings": result["warnings"] + state["warnings"] +
        ([] if ready else ["Unreviewed excerpts remain; report export is blocked."]),
        "source_bindings": state["source_bindings"],
        "no_files_saved": True, "no_network_requests": True,
        "science_verified": False, "manual_reference_check_required": True,
    }


@router.post("/save-draft")
def save_draft(body: SaveDraftIn, request: Request):
    _auth(request)
    source, state = _assemble(body)
    if not state["review_complete"]:
        raise HTTPException(422, "All V3 excerpts require human classification before formal report saving.")
    saved = document_workspace.save_document(source, request)
    return {
        **saved, "create_only": True, "editable_in": "Document Assistant",
        "reference_count": state["references"], "citation_style": body.style,
        "source_files_modified": False, "manual_reference_check_required": True,
    }


@router.post("/export")
def export(body: ExportIn, request: Request):
    _auth(request)
    source, state = _assemble(body)
    if not state["review_complete"]:
        raise HTTPException(422, "All V3 excerpts require human classification before export.")
    result = document_workspace.export_document(
        document_workspace.ExportIn(**source.model_dump(), format=body.format), request)
    return {
        **result, "source_files_modified": False,
        "reference_count": state["references"], "citation_style": body.style,
        "comparison_sha256": state["comparison_sha256"],
        "manual_reference_check_required": True, "science_verified": False,
    }
