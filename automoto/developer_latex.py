"""Developer Studio V9: bounded local multi-file LaTeX authoring intelligence.

This is a conservative lexical cross-reference validator, NOT a TeX engine or a
replacement for texlab. It never writes, compiles, installs or executes source.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict, deque
from pathlib import Path, PurePosixPath
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_index as index, developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/latex", tags=["developer-latex"])
MAX_FILES = 64
MAX_DEPTH = 12
MAX_TOTAL_BYTES = 2 * 1024 * 1024
MAX_TEXT_BYTES = 96 * 1024
MAX_DIAGNOSTICS = 120
MAX_ITEMS = 150
MAX_COMPLETIONS = 60
SCHEMA = "1.0.0"

COMMANDS = (
    "documentclass", "usepackage", "begin", "end", "chapter", "section",
    "subsection", "subsubsection", "paragraph", "subparagraph", "title", "author",
    "date", "maketitle", "tableofcontents", "listoffigures", "listoftables",
    "label", "ref", "eqref", "autoref", "cref", "pageref", "cite", "citep",
    "citet", "parencite", "textcite", "bibliography", "bibliographystyle",
    "addbibresource", "input", "include", "subfile", "footnote", "caption",
    "includegraphics", "textbf", "textit", "emph", "url", "href", "frac",
    "dfrac", "sqrt", "sum", "int", "lim", "left", "right", "mathbb",
    "mathbf", "mathrm", "text", "operatorname", "newcommand", "renewcommand",
    "newenvironment", "item", "centering", "hline", "toprule", "midrule",
    "bottomrule", "multicolumn", "align", "nonumber", "notag",
)
ENVIRONMENTS = (
    "document", "abstract", "equation", "equation*", "align", "align*",
    "gather", "gather*", "multline", "multline*", "itemize", "enumerate",
    "description", "figure", "table", "tabular", "center", "flushleft",
    "flushright", "quote", "quotation", "verbatim", "lstlisting",
    "theorem", "proof", "definition", "lemma",
)
MATH_SNIPPETS = (
    {"label": "Inline maths", "insert": "$a^2+b^2=c^2$"},
    {"label": "Displayed equation", "insert": "\\begin{equation}\n  E = mc^2\n  \\label{eq:energy}\n\\end{equation}"},
    {"label": "Aligned equations", "insert": "\\begin{align}\n  a &= b+c \\\\\n  d &= e+f\n\\end{align}"},
    {"label": "Fraction", "insert": "\\frac{numerator}{denominator}"},
    {"label": "Summation", "insert": "\\sum_{i=1}^{n} x_i"},
    {"label": "Matrix", "insert": "\\begin{bmatrix}\n  a & b \\\\\n  c & d\n\\end{bmatrix}"},
)
TEMPLATES = {
    "thesis": {
        "label": "Multi-file academic thesis",
        "description": "Original report-class structure with chapter includes, label navigation and a BibTeX bibliography. Requires a locally installed TeX distribution and packages for compilation.",
        "files": {
            "main.tex": "\\documentclass[12pt,a4paper]{report}\n"
                        "\\usepackage[T1]{fontenc}\n\\usepackage{amsmath}\n"
                        "\\usepackage{graphicx}\n\\usepackage{hyperref}\n"
                        "\\title{Research Thesis}\\author{Author Name}\\date{\\today}\n"
                        "\\begin{document}\n\\maketitle\n\\tableofcontents\n"
                        "\\input{chapters/introduction}\n"
                        "\\bibliographystyle{plain}\n\\bibliography{references}\n"
                        "\\end{document}\n",
            "chapters/introduction.tex": "\\chapter{Introduction}\\label{chap:intro}\n"
                                         "Describe the problem and motivation here.\n"
                                         "See Chapter~\\ref{chap:intro}. An example source is \\cite{sample2026}.\n"
                                         "\\begin{equation}\\label{eq:sample}\n"
                                         "  a^2+b^2=c^2\n\\end{equation}\n",
            "references.bib": "@article{sample2026,\n"
                              "  author = {Example, A.},\n"
                              "  title = {Replace with a verified publication},\n"
                              "  journal = {Placeholder Journal},\n"
                              "  year = {2026}\n}\n",
        },
    },
    "article": {
        "label": "Academic article",
        "description": "Original article-class document with abstract, sections, figure placeholder and bibliography. No references are certified.",
        "files": {
            "main.tex": "\\documentclass[11pt,a4paper]{article}\n"
                        "\\usepackage[T1]{fontenc}\n\\usepackage{amsmath}\n"
                        "\\usepackage{graphicx}\n\\usepackage{hyperref}\n"
                        "\\title{Academic Article}\\author{Author Name}\\date{\\today}\n"
                        "\\begin{document}\n\\maketitle\n"
                        "\\begin{abstract}\nState the research question and contribution.\n\\end{abstract}\n"
                        "\\section{Introduction}\\label{sec:introduction}\n"
                        "State the evidence and background.\n"
                        "\\section{Method}\\label{sec:method}\n"
                        "Explain the method and limitations; see Section~\\ref{sec:introduction}.\n"
                        "\\section{Results}\\label{sec:results}\n"
                        "Report measured results only.\n"
                        "\\section{Conclusion}\nSummarise limitations and conclusions.\n"
                        "\\end{document}\n",
        },
    },
}

# Lexical commands with explicit bounded arguments. These patterns are only
# used after comments/verbatim content have been masked without moving offsets.
CMD = re.compile(r"\\(?P<cmd>[A-Za-z@]+)\*?(?:\s*\[[^\]\r\n]{0,180}\]){0,2}\s*\{(?P<value>[^{}\r\n]{0,400})\}")
HEADING = frozenset({"part", "chapter", "section", "subsection", "subsubsection", "paragraph"})
REFS = frozenset({"ref", "eqref", "autoref", "cref", "Cref", "pageref", "vref", "nameref"})
CITES = frozenset({"cite", "citep", "citet", "Citep", "Citet", "parencite", "textcite", "autocite", "footcite", "nocite"})
INCLUDES = frozenset({"input", "include", "subfile"})
BIBS = frozenset({"bibliography", "addbibresource"})
BIB_ENTRY = re.compile(r"(?m)^[ \t]*@(article|book|inproceedings|misc|techreport|phdthesis|mastersthesis|unpublished|online|proceedings|incollection|manual|report)\s*\{\s*([A-Za-z0-9:_./-]{1,140})\s*,", re.I)
VERBATIM = re.compile(r"\\begin\{(verbatim|lstlisting|minted)\}.*?\\end\{\1\}", re.S)
INLINE_VERB = re.compile(r"\\verb\*?(?P<sep>[|!+~=;:])(?:(?!(?P=sep)).){0,2048}(?P=sep)", re.S)


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    main: str = Field(min_length=1, max_length=1024)
    active_path: Optional[str] = Field(default=None, max_length=1024)
    active_text: Optional[str] = Field(default=None, max_length=MAX_TEXT_BYTES)


class CompleteIn(ProjectIn):
    prefix: str = Field(default="", max_length=100)
    kind: Literal["auto", "command", "environment", "label", "citation"] = "auto"


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Literal["thesis", "article"]


def _mask(text: str) -> str:
    """Mask comments/verbatim, retaining newlines and character offsets."""
    def blank(s: str) -> str:
        return re.sub(r"[^\r\n]", " ", s)
    safe = VERBATIM.sub(lambda m: blank(m.group(0)), text)
    safe = INLINE_VERB.sub(lambda m: blank(m.group(0)), safe)
    rows = []
    for row in safe.splitlines(keepends=True):
        cut = len(row)
        for i, ch in enumerate(row):
            if ch == "%":
                backslashes = 0
                j = i - 1
                while j >= 0 and row[j] == "\\":
                    backslashes += 1
                    j -= 1
                if backslashes % 2 == 0:
                    cut = i
                    break
        rows.append(row[:cut] + blank(row[cut:]))
    return "".join(rows)


def _position(text: str, offset: int) -> dict:
    line = text.count("\n", 0, offset)
    start = text.rfind("\n", 0, offset) + 1
    return {"line": line, "character": len(text[start:offset].encode("utf-16-le")) // 2}


def _safe_relative(root: Path, current: str, value: str, ext: str) -> Optional[str]:
    """Resolve local relative includes lexically, then check every actual path segment."""
    val = value.strip()
    if (not val or "\x00" in val or "\\" in val or val.startswith(("/", "~"))
            or ":" in val or len(val) > 1024):
        return None
    try:
        parts = list(PurePosixPath(current).parent.parts)
        for token in val.split("/"):
            if token in ("", "."):
                continue
            if token == "..":
                if not parts:
                    return None
                parts.pop()
            else:
                parts.append(token)
        if not parts:
            return None
        candidate = PurePosixPath(*parts)
        if not candidate.suffix:
            candidate = PurePosixPath(str(candidate) + ext)
        relative = str(candidate)
        if (len(relative) > 1024 or candidate.suffix.casefold() != ext
                or any(index._excluded(part, i < len(parts) - 1)
                       for i, part in enumerate(candidate.parts))):
            return None
        checked = studio._path(root, relative)  # rejects linked or junction segments
        if checked == root or not checked.is_relative_to(root):
            return None
        return relative
    except (HTTPException, ValueError, OSError, UnicodeError):
        return None

def _read(root: Path, path: str, active_path: Optional[str], active_text: Optional[str]) -> Optional[str]:
    if path == active_path and active_text is not None:
        if len(active_text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise HTTPException(413, "Unsaved LaTeX buffer exceeds the file limit.")
        return active_text
    result = index._source(root, path)
    return result[0] if result else None


def _commands(path: str, text: str) -> dict:
    masked = _mask(text)
    found = {"headings": [], "labels": [], "refs": [], "cites": [], "includes": [],
             "bibfiles": [], "environments": [], "custom_commands": []}
    for match in CMD.finditer(masked):
        name, value = match.group("cmd"), match.group("value").strip()
        pos = _position(text, match.start("value"))
        item = {"value": value, "path": path, **pos}
        if name in HEADING:
            found["headings"].append({**item, "level": name})
        elif name == "label":
            found["labels"].append(item)
        elif name in REFS:
            found["refs"].extend({**item, "value": key.strip(), "command": name}
                                 for key in value.split(",")[:20] if key.strip())
        elif name in CITES:
            found["cites"].extend({**item, "value": key.strip(), "command": name}
                                  for key in value.split(",")[:20] if key.strip() and key.strip() != "*")
        elif name in INCLUDES:
            found["includes"].append(item)
        elif name in BIBS:
            found["bibfiles"].extend({**item, "value": key.strip()}
                                     for key in value.split(",")[:20] if key.strip())
        elif name in ("begin", "end"):
            found["environments"].append({**item, "command": name})
        elif name in ("newcommand", "renewcommand"):
            found["custom_commands"].append(item)
    return found


def _validate_root(root: Path, main: str, active_path: Optional[str]):
    for candidate in (main, active_path):
        if candidate is None:
            continue
        path = studio._path(root, candidate)
        if (path == root or path.suffix.casefold() != ".tex" or
                any(index._excluded(part, i < len(Path(candidate).parts) - 1)
                    for i, part in enumerate(Path(candidate).parts))):
            raise HTTPException(422, "Select a non-restricted project-local .tex file.")
        if not path.is_file():
            raise HTTPException(404, "LaTeX source file does not exist.")


def _analyse(root: Path, body: ProjectIn) -> dict:
    _validate_root(root, body.main, body.active_path)
    if body.active_text is not None and body.active_path is None:
        raise HTTPException(422, "Unsaved source requires its matching .tex path.")
    pending = deque([(body.main, 0)])
    read_paths = set()
    texts = {}
    declarations = []
    references = []
    citations = []
    includes = []
    bib_targets = []
    sections = []
    environments = []
    custom = []
    warnings = []
    total = 0
    truncated = False

    def warn(code: str, item: dict, detail: str, severity="warning"):
        if len(warnings) < MAX_DIAGNOSTICS:
            warnings.append({"code": code, "message": detail, "severity": severity,
                             "path": item["path"], "line": item["line"],
                             "character": item["character"]})

    while pending:
        file, depth = pending.popleft()
        if file in read_paths:
            continue
        if len(read_paths) >= MAX_FILES or depth > MAX_DEPTH:
            truncated = True
            break
        read_paths.add(file)
        try:
            source = _read(root, file, body.active_path, body.active_text)
        except (HTTPException, UnicodeEncodeError):
            source = None
        if source is None:
            warn("unreadable-tex", {"path": file, "line": 0, "character": 0},
                 "Included LaTeX source is missing, unsafe, oversized or not UTF-8.")
            continue
        size = len(source.encode("utf-8"))
        if total + size > MAX_TOTAL_BYTES:
            truncated = True
            break
        total += size
        texts[file] = source
        report = _commands(file, source)
        declarations.extend(report["labels"])
        references.extend(report["refs"])
        citations.extend(report["cites"])
        sections.extend(report["headings"])
        environments.extend(report["environments"])
        custom.extend(report["custom_commands"])
        for item in report["includes"]:
            target = _safe_relative(root, file, item["value"], ".tex")
            includes.append({**item, "target": target})
            if target is None:
                warn("unsafe-include", item, "LaTeX include resolves outside the approved source scope.")
            elif not (root / target).is_file():
                warn("missing-include", item, "Included .tex file is missing: " + target)
            elif target not in read_paths:
                pending.append((target, depth + 1))
        for item in report["bibfiles"]:
            target = _safe_relative(root, file, item["value"], ".bib")
            bib_targets.append({**item, "target": target})
            if target is None:
                warn("unsafe-bibliography", item, "Bibliography path is outside approved source scope.")
            elif not (root / target).is_file():
                warn("missing-bibliography", item, "Bibliography file is missing: " + target)

    # Distinct bibliography files may be referenced from multiple LaTeX chapters.
    bibkeys = []
    seen_bib = set()
    for item in bib_targets:
        path = item["target"]
        if path is None or path in seen_bib:
            continue
        seen_bib.add(path)
        bibtext = index._source(root, path)
        if bibtext is None:
            warn("unreadable-bibliography", item, "Bibliography is not safe readable UTF-8: " + path)
            continue
        size = bibtext[2]
        if total + size > MAX_TOTAL_BYTES:
            truncated = True
            break
        total += size
        text = bibtext[0]
        for entry in BIB_ENTRY.finditer(text):
            bibkeys.append({"value": entry.group(2), "path": path,
                            **_position(text, entry.start(2))})
            if len(bibkeys) >= MAX_ITEMS:
                truncated = True
                break
        if len(bibkeys) >= MAX_ITEMS:
            break

    labels_by_key = defaultdict(list)
    citations_by_key = defaultdict(list)
    for item in declarations:
        labels_by_key[item["value"]].append(item)
    for item in bibkeys:
        citations_by_key[item["value"]].append(item)
    for key, occurrences in labels_by_key.items():
        if len(occurrences) > 1:
            for item in occurrences:
                warn("duplicate-label", item, "Label is declared more than once: " + key, "error")
    for key, occurrences in citations_by_key.items():
        if len(occurrences) > 1:
            for item in occurrences:
                warn("duplicate-bibkey", item, "Bibliography key is declared more than once: " + key, "error")
    for item in references:
        if item["value"] not in labels_by_key:
            warn("unresolved-ref", item, "No local label definition for " + item["value"], "error")
    for item in citations:
        if item["value"] not in citations_by_key:
            warn("unresolved-citation", item, "No local bibliography entry for " + item["value"], "error")

    # Matching begin/end provides useful static diagnostics, but is not a TeX parser.
    stack = []
    for item in environments:
        if item["command"] == "begin":
            stack.append(item)
        elif not stack or stack[-1]["value"] != item["value"]:
            warn("unmatched-end", item, "Environment closes without matching begin: " + item["value"])
        else:
            stack.pop()
    for item in stack[:MAX_DIAGNOSTICS]:
        warn("unclosed-environment", item, "Environment is not closed: " + item["value"])

    # Limit responses even if a file contains thousands of declarations.
    cap = lambda rows: rows[:MAX_ITEMS]
    truncated = truncated or any(len(x) > MAX_ITEMS for x in
                                 (declarations, references, citations, sections, includes))
    return {
        "schema_version": SCHEMA, "main": body.main,
        "files": sorted(texts), "file_count": len(texts), "source_bytes": total,
        "labels": cap(declarations), "references": cap(references),
        "citations": cap(citations), "bibliography_keys": cap(bibkeys),
        "sections": cap(sections), "includes": cap(includes),
        "diagnostics": warnings, "truncated": truncated,
        "analysis_kind": "bounded-static-lexical-not-compiled",
        "compilation_verified": False, "lsp_diagnostics_included": False,
        "unsaved_buffer_used": body.active_text is not None,
        "source_executed": False, "source_modified": False,
        "limitations": "TeX macro expansion, package semantics, aux-file resolution and external resources are not evaluated.",
    }


@router.post("/analyse")
def analyse(request: Request, body: ProjectIn):
    studio._auth(request)
    root = studio._project(body.project)
    return _analyse(root, body)


@router.post("/complete")
def complete(request: Request, body: CompleteIn):
    studio._auth(request)
    root = studio._project(body.project)
    project = _analyse(root, body)
    prefix = body.prefix.lstrip("\\").casefold()
    categories = {
        "command": [{"label": "\\" + cmd, "kind": "command", "insert": "\\" + cmd}
                    for cmd in COMMANDS],
        "environment": [{"label": env, "kind": "environment",
                         "insert": "\\begin{" + env + "}\n  \n\\end{" + env + "}"}
                        for env in ENVIRONMENTS],
        "label": [{"label": x["value"], "kind": "reference", "insert": x["value"],
                   "path": x["path"], "line": x["line"]}
                  for x in project["labels"]],
        "citation": [{"label": x["value"], "kind": "citation", "insert": x["value"],
                      "path": x["path"], "line": x["line"]}
                     for x in project["bibliography_keys"]],
    }
    candidates = [x for key, rows in categories.items()
                  if body.kind in ("auto", key) for x in rows]
    candidates.sort(key=lambda x: (x["kind"], x["label"].casefold()))
    items = []
    used = set()
    for item in candidates:
        identity = (item["kind"], item["label"])
        if identity in used or not item["label"].lstrip("\\").casefold().startswith(prefix):
            continue
        used.add(identity)
        items.append(item)
        if len(items) >= MAX_COMPLETIONS:
            break
    return {"items": items, "truncated": project["truncated"] or len(items) >= MAX_COMPLETIONS,
            "source_modified": False, "execution_required": False,
            "analysis_kind": project["analysis_kind"]}


@router.get("/templates")
def templates(request: Request):
    studio._auth(request)
    return {"templates": [{"id": key, "label": value["label"],
                           "description": value["description"],
                           "files": list(value["files"])}
                          for key, value in TEMPLATES.items()],
            "applied": False, "requires_manual_review": True}


@router.post("/template-preview")
def template_preview(request: Request, body: TemplateIn):
    studio._auth(request)
    template = TEMPLATES[body.id]
    return {"id": body.id, "label": template["label"],
            "files": [{"path": path, "text": text}
                      for path, text in template["files"].items()],
            "applied": False, "writes_project": False,
            "references_placeholder_only": True,
            "note": "Templates are previews, not compiler-verified and never automatically written."}
