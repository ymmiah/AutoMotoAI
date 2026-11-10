"""V12 Research Studio -> Typst/Quarto, source-verified review-only transfer.

Revalidates the Research Studio V6 developer hand-off, the underlying V3
comparison and source file checksums, and optional V4 DOI/publication bindings.
Source quotations are JSON data only, never pasted into executable manuscripts.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import zipfile
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_manuscripts as manuscripts
from automoto import developer_studio as studio
from automoto import document_workspace, research_handoffs, research_publishing

router = APIRouter(prefix="/api/developer/studio/research-transfer",
                   tags=["developer-research-transfer"])
MAX_PACKAGE = 320 * 1024
MAX_FILES = 4
# Literal field safety: prevent BibTeX macro and structural injection.
SAFE_METADATA = re.compile(r"^[^\x00-\x1f\x7f\\{}%$#@&^~]{1,320}$")


class TransferIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    format: Literal["typst", "quarto"]
    handoff_path: str = Field(min_length=30, max_length=200)
    handoff_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bindings: list[research_publishing.Binding] = Field(default_factory=list, max_length=5)


class DownloadIn(TransferIn):
    confirmed: Literal[True]
    acknowledge_not_publication_ready: Literal[True]


def _verified_handoff(body: TransferIn) -> tuple[dict, dict]:
    audit = research_handoffs._manifest_path(body.handoff_path)
    if document_workspace._sha(audit) != body.handoff_sha256:
        raise HTTPException(409, "Research hand-off checksum changed; select the current audit.")
    saved = research_handoffs._read_manifest(audit)
    if saved["target"] != "developer":
        raise HTTPException(422, "Only Research Studio developer hand-offs may transfer.")
    target = research_handoffs._actual_target(saved["target_path"], "developer")
    if document_workspace._sha(target) != saved["target_sha256"]:
        raise HTTPException(409, "The original hand-off draft changed and requires review.")
    review = saved.get("human_ai_review")
    ref = research_handoffs.HandoffIn(
        comparison_path=saved["comparison_path"],
        comparison_sha256=saved["comparison_sha256"],
        target="developer",
        review_path=review["path"] if review else None,
        review_sha256=review["sha256"] if review else None,
    )
    fresh = research_handoffs._packet(ref)  # full V3/source/review validation
    for key, value in fresh.items():
        if saved.get(key) != value:
            raise HTTPException(409, "Research evidence differs from the saved reviewed hand-off.")
    if (fresh["reviewed"] is not True or fresh["publication_ready"] is not False
            or fresh["scientifically_verified"] is not False):
        raise HTTPException(422, "Research transfer must remain review-only.")
    return saved, fresh


def _bib_records(fresh: dict, bindings: list[research_publishing.Binding]) -> list[dict]:
    if not bindings:
        return []
    # Research Studio V4 confirms that EACH original source maps to exactly one
    # separately fingerprinted Crossref metadata record and the human has
    # explicitly confirmed that it describes the SAME publication.
    items = research_publishing._records({"project": {"sources": fresh["sources"]}}, bindings)
    result = []
    for item in items:
        for field in ("title", "year", "doi"):
            value = item[field]
            if not isinstance(value, str) or not SAFE_METADATA.fullmatch(value):
                raise HTTPException(422, "Bibliographic metadata needs manual escaping.")
        if not item["authors"] or not all(
                isinstance(name, str) and SAFE_METADATA.fullmatch(name) for name in item["authors"]):
            raise HTTPException(422, "Author metadata cannot be encoded as a safe BibTeX literal.")
        if item.get("venue") and not SAFE_METADATA.fullmatch(item["venue"]):
            raise HTTPException(422, "Publication venue needs manual escaping.")
        key = "ref_" + hashlib.sha256(item["doi"].encode("utf-8")).hexdigest()[:16]
        result.append({**item, "citation_key": key})
    if len({x["citation_key"] for x in result}) != len(result):
        raise HTTPException(422, "Citation keys are not unique.")
    return result


def _bib_output(records: list[dict]) -> str:
    lines = ["% Crossref-to-source association was explicitly confirmed in Research Studio V4.",
             "% Crossref is not proof of publication authenticity, integrity or peer review."]
    for item in records:
        kind = "article" if (item.get("type") == "journal-article" and item.get("venue")) else "misc"
        fields = [("title", item["title"]), ("author", " and ".join(item["authors"])),
                  ("year", item["year"]), ("doi", item["doi"])]
        if item.get("venue"):
            fields.append(("journal" if kind == "article" else "howpublished", item["venue"]))
        lines.append("@" + kind + "{" + item["citation_key"] + ",")
        lines.extend("  " + name + " = {" + value + "}," for name, value in fields)
        lines.append("}")
    return "\n".join(lines) + "\n"


def _package(root, body: TransferIn) -> dict:
    saved, fresh = _verified_handoff(body)
    records = _bib_records(fresh, body.bindings)
    main, starter = manuscripts._starter(body.format)
    if records:
        if body.format == "typst":
            starter += '\n#bibliography("references.bib")\n'
        else:
            starter = starter.replace("format: html\n", "format: html\nbibliography: references.bib\n")
    evidence = {
        "schema": "automoto-research-manuscript-evidence-v12",
        "source_handoff": {"path": body.handoff_path, "sha256": body.handoff_sha256,
                           "target_path": saved["target_path"],
                           "target_sha256": saved["target_sha256"]},
        "comparison": {"path": fresh["comparison_path"],
                       "sha256": fresh["comparison_sha256"]},
        "original_research": {"path": fresh["project_path"],
                              "sha256": fresh["project_sha256"]},
        "sources": fresh["sources"],
        "research_question": fresh["research_question"],
        "evidence": fresh["evidence"],
        "reviewed_ai_observations_not_facts": fresh["retained_unverified_observations"],
        "human_ai_review": fresh["human_ai_review"],
        "limitations": fresh["limitations"],
        "bibliographic_identity_confirmed": [
            {"source": x["source_path"], "source_sha256": x["source_sha256"],
             "metadata_path": x["metadata_path"], "metadata_sha256": x["metadata_sha256"],
             "doi": x["doi"], "citation_key": x["citation_key"]}
            for x in records],
        "publication_ready": False, "scientifically_verified": False,
        "requires_human_claim_and_citation_review": True,
    }
    files = {main: starter.encode("utf-8"),
             "evidence.review.json": json.dumps(evidence, ensure_ascii=False, indent=2).encode("utf-8")}
    if records:
        files["references.bib"] = _bib_output(records).encode("utf-8")
    if len(files)>MAX_FILES or sum(len(value) for value in files.values())>MAX_PACKAGE:
        raise HTTPException(413, "Source-verified research package exceeds size limit.")
    manifest = {"schema": manuscripts.VERSION, "format": body.format,
                "source_handoff_sha256": body.handoff_sha256,
                "files": [{"path": k, "sha256": hashlib.sha256(v).hexdigest(), "bytes": len(v)}
                          for k, v in sorted(files.items())],
                "review_only": True, "publication_ready": False,
                "manual_review_required": True, "source_written": False,
                "network_used": False, "compiler_executed": False}
    return {"manifest": manifest, "files": files}


@router.get("/handoffs")
def handoffs(request: Request):
    studio._auth(request)
    items = research_handoffs.list_handoffs(request)["handoffs"]
    return {"handoffs": [x for x in items if x["target"] == "developer"][:50],
            "automatic_transfer": False}


@router.post("/preview")
def preview(request: Request, body: TransferIn):
    studio._auth(request)
    root = studio._project(body.project)
    result = _package(root, body)
    return {"manifest": result["manifest"],
            "files": [{"path": name, "text": data.decode("utf-8")}
                      for name, data in result["files"].items()],
            "written": False, "publication_ready": False,
            "automatic_source_insertion": False}


@router.post("/download")
def download(request: Request, body: DownloadIn):
    studio._auth(request)
    root = studio._project(body.project)
    result = _package(root, body)  # recheck at moment of export
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, raw in sorted(result["files"].items()):
            archive.writestr(path, raw)
        archive.writestr("manifest.review.json",
                         json.dumps(result["manifest"], sort_keys=True).encode("utf-8"))
    raw = data.getvalue()
    if len(raw)>MAX_PACKAGE:
        raise HTTPException(413, "Manuscript archive is too large.")
    return {"filename": "automoto-research-" + body.format + "-review.zip",
            "zip_base64": base64.b64encode(raw).decode("ascii"),
            "zip_sha256": hashlib.sha256(raw).hexdigest(),
            "manifest": result["manifest"], "source_files_modified": False,
            "manual_publication_review_required": True,
            "network_used": False, "compiler_executed": False}
