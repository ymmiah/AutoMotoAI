"""Research Studio tools. Evidence comes from the studio's pinned local retrieval.

DOI lookup is online-only and is removed in offline mode by the registry.
A later research module auto-registers as ``automoto/<name>_studio_tools.py``.
"""

from __future__ import annotations

import json

from automoto.studio_registry import S, StudioSpec, call_studio, obj, studio_request
from automoto.tools import Tool, ToolContext, ToolFailed


def research_query(ctx: ToolContext, question: str, paths: list | str, title: str = "",
                   mode: str = "evidence") -> str:
    from automoto import research_studio

    body = research_studio.ProjectIn.model_validate(_project(question, paths, title, mode))
    return call_studio(research_studio.query_project, body, studio_request("POST"))


def research_save(ctx: ToolContext, question: str, paths: list | str, title: str = "",
                  mode: str = "evidence") -> str:
    from automoto import research_studio

    body = research_studio.ProjectIn.model_validate(_project(question, paths, title, mode))
    return call_studio(research_studio.save_project, body, studio_request("POST"))


def research_list(ctx: ToolContext) -> str:
    from automoto import research_studio

    return call_studio(research_studio.list_projects, studio_request("GET"))


def research_verify_doi(ctx: ToolContext, doi: str) -> str:
    """Live DOI check. The registry hides this tool when offline mode is on."""
    from automoto import research_discovery

    body = research_discovery.DoiIn.model_validate({"doi": doi})
    return call_studio(research_discovery.verify_doi, body, studio_request("POST"))


def _project(question: str, paths: list | str, title: str, mode: str) -> dict:
    sources = [_pin(path) for path in _paths(paths)]
    if not sources:
        raise ToolFailed("Name at least one local source file.")
    label = (title or question).strip()
    if len(label) < 3:
        raise ToolFailed("Give the research question at least three characters.")
    return {"title": label[:120], "question": question, "sources": sources,
            "mode": mode if mode in ("evidence", "outline") else "evidence"}


def _pin(path: str) -> dict:
    """Checksum from the studio, then the query re-checks it. A changed file is refused."""
    from automoto import document_research

    info = json.loads(call_studio(document_research.source_info, str(path), studio_request("GET")))
    return {"path": info["path"], "sha256": info["sha256"]}


def _paths(value: list | str) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(item) for item in value if str(item).strip()]


STUDIO = StudioSpec(
    id="research",
    name="Research Studio",
    hosted_ok=True,
    approval="risky",
    online_only=("research_verify_doi",),
    words=r"\b(doi|literature|research studio|research question|research evidence|crossref|openalex)\b|\b10\.\d{4,9}/",
    exts=(),
    skills=("research-studio",),
    fuzzy=("doi", "literature", "citation"),
    how="Answer only from the user's files: research_query with the file paths. It pins each file's "
        "checksum and returns quotes, not a made-up bibliography. research_save writes a new evidence "
        "project. research_verify_doi checks a DOI online and is unavailable offline; never invent a DOI "
        "or a citation the tool did not return. Name the saved file when you finish.",
    labels={
        "research_query": "Searching your sources",
        "research_save": "Saving the research project",
        "research_list": "Listing research projects",
        "research_verify_doi": "Checking the DOI",
    },
    tools=(
        Tool("research_query", "Find evidence for a question in local files. Pins each file's checksum. "
             "Does not browse, invent citations, or modify the sources. mode is evidence or outline.",
             obj({"question": S, "paths": {"type": "array", "items": S}, "title": S, "mode": S},
                 ["question", "paths"]), "safe", research_query),
        Tool("research_save", "Save a new evidence project from local files. Sources are checksum-pinned. "
             "Create-only; sources are not edited.",
             obj({"question": S, "paths": {"type": "array", "items": S}, "title": S, "mode": S},
                 ["question", "paths"]), "risky", research_save),
        Tool("research_list", "List saved Research Studio projects.", obj({}), "safe", research_list),
        Tool("research_verify_doi", "Check a DOI with the studio's online lookup. Unavailable in offline mode. "
             "Does not save a citation unless you then research_save local evidence.",
             obj({"doi": S}, ["doi"]), "safe", research_verify_doi),
    ),
)
