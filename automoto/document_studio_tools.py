"""Document Assistant tools. Each one calls the studio endpoint; nothing is reimplemented.

Future document modules register themselves: add ``automoto/<name>_studio_tools.py``
with a ``STUDIO`` spec. The assistant picks it up with no change to tools.py or planner.py.
"""

from __future__ import annotations

import hashlib

from automoto.studio_registry import OBJ, S, StudioSpec, call_studio, obj, studio_request
from automoto.tools import Tool, ToolContext, ToolFailed

_READ = (
    "Read-only. Imported Office files stay untouched. "
    "A later copy edit must pass this sha256 back as document_revise."
)


def document_list(ctx: ToolContext) -> str:
    from automoto import document_workspace

    return call_studio(document_workspace.list_documents, studio_request("GET"))


def document_open(ctx: ToolContext, path: str) -> str:
    from automoto import document_workspace

    return call_studio(document_workspace.open_document, studio_request("GET"), path)


def document_preflight(ctx: ToolContext, name: str, markdown: str, publication: dict | None = None,
                       options: dict | None = None) -> str:
    """Check the Word build. The studio saves nothing."""
    from automoto import document_workspace

    body = document_workspace.DocumentSource.model_validate(_source(name, markdown, publication, options))
    return call_studio(document_workspace.preflight_document, body, studio_request("POST"))


def document_save(ctx: ToolContext, name: str, markdown: str, publication: dict | None = None,
                  options: dict | None = None) -> str:
    from automoto import document_workspace

    body = document_workspace.DocumentSource.model_validate(_source(name, markdown, publication, options))
    return call_studio(document_workspace.save_document, body, studio_request("POST"))


def document_export(ctx: ToolContext, name: str, markdown: str, format: str = "docx",
                    publication: dict | None = None, options: dict | None = None) -> str:
    from automoto import document_workspace

    data = _source(name, markdown, publication, options)
    data["format"] = format or "docx"
    body = document_workspace.ExportIn.model_validate(data)
    return call_studio(document_workspace.export_document, body, studio_request("POST"))


def document_revise(ctx: ToolContext, path: str, find: str, replace: str, sha256: str) -> str:
    """New DOCX copy only. The studio refuses the write when sha256 is stale."""
    from automoto import document_workspace

    body = document_workspace.ReplaceIn.model_validate(
        {"path": path, "sha256": sha256, "find": find, "replace": replace})
    return call_studio(document_workspace.replace_copy, body, studio_request("POST"))


def document_ai_review(ctx: ToolContext, mode: str, markdown: str = "", source_path: str = "",
                       source_sha256: str = "") -> str:
    """Local Ollama only. Returns a proposal and does not change the document."""
    from automoto import document_ai

    if source_path:
        if not source_sha256:
            raise ToolFailed("Pass source_sha256 from document_open before reviewing an imported file.")
        data = {"mode": mode, "source_path": source_path, "source_sha256": source_sha256}
    else:
        if not markdown:
            raise ToolFailed("Pass the markdown to review, or an imported path plus its checksum.")
        data = {"mode": mode, "markdown": markdown,
                "sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest()}
    body = document_ai.AIReviewIn.model_validate(data)
    return call_studio(document_ai.review_document, body, studio_request("POST"))


def _source(name: str, markdown: str, publication: dict | None, options: dict | None) -> dict:
    data: dict = {"name": name, "markdown": markdown}
    if publication:
        data["publication"] = publication
    if options:
        data["options"] = options
    return data


_PROPS = {"name": S, "markdown": S, "publication": OBJ, "options": OBJ}

STUDIO = StudioSpec(
    id="document",
    name="Document Assistant",
    hosted_ok=True,
    approval="risky",
    local_only=("document_ai_review",),
    words=r"\b(thesis|harvard|ieee|document assistant|citations?|chapter|coursework)\b",
    exts=(".docx", ".doc", ".odt", ".rtf"),
    skills=("document-assistant",),
    fuzzy=("thesis", "harvard", "citation", "chapter"),
    how="Open with document_open (keep the sha256). Write a new draft with document_save, "
        "check it with document_preflight, and publish a new Word file with document_export "
        "(publication.reference_style harvard or ieee, and publication.references the user supplied). "
        "document_revise makes a new copy only when sha256 still matches. "
        "document_ai_review is local and returns a proposal; do not apply it yourself. "
        "Finish by naming the file.",
    labels={
        "document_list": "Listing documents",
        "document_open": "Opening the document",
        "document_preflight": "Checking the document",
        "document_save": "Saving the draft",
        "document_export": "Exporting the document",
        "document_revise": "Saving a revised copy",
        "document_ai_review": "Reviewing the wording",
    },
    tools=(
        Tool("document_list", "List Document Assistant drafts and uploaded documents.", obj({}), "safe", document_list),
        Tool("document_open", "Open a document from uploads/ or the Document Assistant folder. " + _READ,
             obj({"path": S}, ["path"]), "safe", document_open),
        Tool("document_preflight", "Check that this markdown will build as Word. Saves nothing.",
             obj(_PROPS, ["name", "markdown"]), "safe", document_preflight),
        Tool("document_save", "Save a new editable markdown draft. Does not overwrite another file.",
             obj(_PROPS, ["name", "markdown"]), "risky", document_save),
        Tool("document_export", "Publish a new Word or PDF file from markdown, with Harvard or IEEE references "
             "when publication is set. PDF needs LibreOffice. Originals are not overwritten.",
             obj({**_PROPS, "format": S}, ["name", "markdown"]), "risky", document_export),
        Tool("document_revise", "Replace one exact phrase in a new DOCX copy. Requires sha256 from document_open. "
             "The original file is not changed.",
             obj({"path": S, "find": S, "replace": S, "sha256": S}, ["path", "find", "replace", "sha256"]),
             "risky", document_revise),
        Tool("document_ai_review", "Ask the local offline model to proofread, rewrite or summarise. "
             "Returns a proposal only; nothing is saved. Not available on a hosted server. "
             "Imported files need source_sha256 from document_open.",
             obj({"mode": S, "markdown": S, "source_path": S, "source_sha256": S}, ["mode"]),
             "risky", document_ai_review),
    ),
)
