"""Developer Studio tools for what is on main: explore, search, symbols, diff, save, languages.

Edits and program runs are approval-gated. ``developer_run`` is host execution and is
removed when local apps are off, including hosted multi-user servers. The studio's
own local-only auth still refuses hosted calls if a tool is invoked anyway.

LaTeX, BibTeX, TeX build, Typst, Quarto, JS/TS tooling and frontend preview are not
wired here. When those modules land, name them ``automoto/<name>_studio_tools.py``
with a ``STUDIO`` spec and the assistant picks them up with no edit to tools.py
or planner.py.
"""

from __future__ import annotations

from automoto.studio_registry import S, StudioSpec, call_studio, obj, studio_request, workspace_dir
from automoto.tools import Tool, ToolContext, ToolFailed


def developer_open(ctx: ToolContext, project: str) -> str:
    from automoto import developer_studio

    body = developer_studio.OpenIn.model_validate({"project": workspace_dir(project)})
    return call_studio(developer_studio.open_project, body, studio_request("POST"))


def developer_read(ctx: ToolContext, project: str, path: str) -> str:
    from automoto import developer_editor

    return call_studio(developer_editor.open_file, studio_request("GET"), workspace_dir(project), path, "auto")


def developer_search(ctx: ToolContext, project: str, query: str, directory: str = ".") -> str:
    from automoto import developer_navigation

    body = developer_navigation.SearchIn.model_validate({
        "project": workspace_dir(project), "directory": directory or ".", "query": query,
    })
    return call_studio(developer_navigation.search, studio_request("POST"), body)


def developer_symbols(ctx: ToolContext, project: str, query: str = "", path: str = "") -> str:
    from automoto import developer_index

    data = {"project": workspace_dir(project), "query": query}
    if path:
        data["path"] = path
    body = developer_index.SymbolIn.model_validate(data)
    return call_studio(developer_index.symbols, studio_request("POST"), body)


def developer_diff(ctx: ToolContext, project: str, path: str, text: str, expected_sha256: str,
                   encoding: str = "utf-8", newline: str = "lf") -> str:
    """Preview only. saved_to_disk is false. Pass expected_sha256 from developer_read."""
    from automoto import developer_lifecycle

    body = _working_copy(project, path, text, expected_sha256, encoding, newline)
    return call_studio(developer_lifecycle.diff_preview, studio_request("POST"),
                       developer_lifecycle.WorkingCopy.model_validate(body))


def developer_save(ctx: ToolContext, project: str, path: str, text: str, expected_sha256: str,
                   encoding: str = "utf-8", newline: str = "lf") -> str:
    """Conflict-checked save. The studio writes only when the checksum still matches."""
    from automoto import developer_editor

    root = workspace_dir(project)
    body = developer_editor.SaveIn.model_validate({
        "project": root, "path": path, "text": text, "encoding": encoding, "newline": newline,
        "expected_sha256": expected_sha256, "confirmed": True,
    })
    return call_studio(developer_editor.save_file, studio_request("POST"), body)


def developer_trust(ctx: ToolContext, project: str) -> str:
    """Record trust for this exact folder. Does not edit or run source."""
    from automoto import developer_studio

    body = developer_studio.TrustIn.model_validate({
        "project": workspace_dir(project), "trusted": True, "confirmed": True,
    })
    return call_studio(developer_studio.trust_project, body, studio_request("POST"))


def developer_languages(ctx: ToolContext, project: str) -> str:
    from automoto import developer_languages

    body = developer_languages.DetectIn.model_validate({
        "project": workspace_dir(project), "probe_tools": False,
    })
    return call_studio(developer_languages.detect, studio_request("POST"), body)


def developer_lsp(ctx: ToolContext, project: str) -> str:
    """Which language servers exist. Does not start one."""
    from automoto import developer_lsp

    return call_studio(developer_lsp.servers, studio_request("GET"), workspace_dir(project))


def developer_run(ctx: ToolContext, project: str, adapter_id: str) -> str:
    """Run an adapter the user already registered and hash-pinned. Does not register one."""
    from automoto import developer_adapters

    body = developer_adapters.RunIn.model_validate({
        "project": workspace_dir(project), "id": adapter_id, "confirmed": True,
        "accept_execution_and_write_risk": True,
    })
    return call_studio(developer_adapters.run, studio_request("POST"), body)


def _working_copy(project: str, path: str, text: str, expected_sha256: str, encoding: str, newline: str) -> dict:
    if not expected_sha256:
        raise ToolFailed("Pass expected_sha256 from developer_read. The save is refused if the file changed.")
    return {"project": workspace_dir(project), "path": path, "text": text, "encoding": encoding,
            "newline": newline, "expected_sha256": expected_sha256, "confirmed": True}


_FILE = {"project": S, "path": S, "text": S, "expected_sha256": S, "encoding": S, "newline": S}

STUDIO = StudioSpec(
    id="developer",
    name="Developer Studio",
    hosted_ok=False,
    approval="risky",
    host_exec=("developer_run",),
    words=r"\b(developer studio|show the diff|repo file|language server|trust this project)\b",
    exts=(".py", ".js", ".mjs", ".ts", ".tsx", ".jsx"),
    skills=("developer-studio",),
    fuzzy=("diff", "typescript", "repository"),
    how="Open the project folder (a path inside the workspace), developer_read the file and keep "
        "sha256, encoding and newline. developer_search and developer_symbols are read-only. "
        "developer_trust is required before a diff or save and does not run code. "
        "developer_diff shows the change and does not write. developer_save writes only when "
        "expected_sha256 still matches; if it does not, read again and stop. "
        "developer_languages and developer_lsp do not start programs. developer_run only runs an "
        "adapter that is already registered and hash-pinned, and it is absent on hosted servers. "
        "Do not claim a fix without the diff or the new file.",
    labels={
        "developer_open": "Opening the project",
        "developer_read": "Reading the source file",
        "developer_search": "Searching the project",
        "developer_symbols": "Finding symbols",
        "developer_diff": "Showing the diff",
        "developer_save": "Saving the source file",
        "developer_trust": "Trusting the project",
        "developer_languages": "Detecting languages",
        "developer_lsp": "Checking language servers",
        "developer_run": "Running a project tool",
    },
    tools=(
        Tool("developer_open", "Open a project folder inside the workspace. Read-only. Not available on a hosted server.",
             obj({"project": S}, ["project"]), "safe", developer_open),
        Tool("developer_read", "Read a source file with its checksum, encoding and newline. Does not execute it.",
             obj({"project": S, "path": S}, ["project", "path"]), "safe", developer_read),
        Tool("developer_search", "Literal search in a trusted-or-open project. Does not replace or execute.",
             obj({"project": S, "query": S, "directory": S}, ["project", "query"]), "safe", developer_search),
        Tool("developer_symbols", "List symbols in the project index. Does not execute source.",
             obj({"project": S, "query": S, "path": S}, ["project"]), "safe", developer_symbols),
        Tool("developer_diff", "Unified diff of a working copy against the file. Does not save. "
             "Requires expected_sha256 from developer_read and a trusted project.",
             obj(_FILE, ["project", "path", "text", "expected_sha256"]), "safe", developer_diff),
        Tool("developer_save", "Save source only when expected_sha256 still matches the file on disk. "
             "Needs a trusted project. Approval is required.",
             obj(_FILE, ["project", "path", "text", "expected_sha256"]), "risky", developer_save),
        Tool("developer_trust", "Trust this exact project folder so later edits are allowed. Does not edit or run files.",
             obj({"project": S}, ["project"]), "risky", developer_trust),
        Tool("developer_languages", "Detect languages in the project without running compilers or package managers.",
             obj({"project": S}, ["project"]), "safe", developer_languages),
        Tool("developer_lsp", "List language servers and whether a binary is installed. Does not start one.",
             obj({"project": S}, ["project"]), "safe", developer_lsp),
        Tool("developer_run", "Run an already registered, hash-pinned adapter in a trusted project. "
             "Does not register or install anything. Not available on a hosted server.",
             obj({"project": S, "adapter_id": S}, ["project", "adapter_id"]), "risky", developer_run),
    ),
)
