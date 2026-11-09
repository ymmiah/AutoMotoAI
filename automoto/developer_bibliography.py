"""Developer Studio V10: local BibTeX/BibLaTeX preflight and opt-in DOI evidence.

Source is NEVER executed or changed. External Crossref lookup occurs only from
the dedicated, explicitly invoked verify endpoint. Registry metadata does NOT
certify that a publication exists, is peer-reviewed, or matches the source.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_latex as latex
from automoto import developer_index as source_index
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/bibliography", tags=["developer-bibliography"])
MAX_BIB_BYTES = 96 * 1024
MAX_ENTRIES = 200
MAX_REPORT_ITEMS = 120
MAX_CROSSREF_BYTES = 256 * 1024
MAX_EVIDENCE = 64
EVIDENCE_TTL = 1800
SCHEMA_VERSION = "1.0.0"
DOI_PATTERN = re.compile(r"^10\.\d{4,9}/[A-Za-z0-9._;()/:\-+<>%]+$", re.I)
ENTRY_START = re.compile(r"@\s*([A-Za-z]+)\s*([({])", re.I)
FIELD_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,60}")
ENTRY_KEY = re.compile(r"[A-Za-z0-9:_./+\-]{1,140}")
UNKNOWN = frozenset({"string", "comment", "preamble"})
REQUIRED = ("title", "author")
BOOKLIKE = frozenset({"book", "inbook", "incollection", "proceedings", "manual", "phdthesis", "mastersthesis"})
PLACEHOLDER = re.compile(r"\b(?:placeholder|insert\s+(?:real|verified)|replace\s+with|author\s+name|unknown\s+author|example\s+source|sample\s+(?:journal|title))\b", re.I)
EVIDENCE: "OrderedDict[tuple, dict]" = OrderedDict()
EVIDENCE_LOCK = threading.RLock()


class ProjectIn(latex.ProjectIn):
    pass


class VerifyIn(ProjectIn):
    key: str = Field(min_length=1, max_length=140)


class FormatIn(ProjectIn):
    key: str = Field(min_length=1, max_length=140)
    style: Literal["harvard", "ieee"]


def _normalise_doi(value: str) -> Optional[str]:
    doi = value.strip()
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I)
    if not DOI_PATTERN.fullmatch(doi) or len(doi) > 200:
        return None
    return doi.casefold()


def _normalised_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _year(fields: dict) -> Optional[str]:
    """BibLaTeX date is valid year evidence; never infer absent dates."""
    year = fields.get("year", "").strip()
    if re.fullmatch(r"[12]\d{3}", year):
        return year
    date = fields.get("date", "").strip()
    if re.fullmatch(r"[12]\d{3}(?:-\d{2}(?:-\d{2})?)?", date):
        return date[:4]
    return None


def _location(text: str, offset: int, path: str) -> dict:
    return {"path": path, **latex._position(text, offset)}


def _skip(text: str, offset: int) -> int:
    """Skip whitespace and BibTeX-style percent comments outside entry values."""
    n = len(text)
    while offset < n:
        if text[offset].isspace():
            offset += 1
        elif text[offset] == "%":
            end = text.find("\n", offset)
            offset = n if end == -1 else end + 1
        else:
            break
    return offset


def _braced(text: str, pos: int, left: str, right: str) -> tuple[str, int]:
    """Read a nested value without evaluating TeX commands or BibTeX macros."""
    depth = 1
    i = pos + 1
    limit = len(text)
    while i < limit:
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == left:
            depth += 1
        elif char == right:
            depth -= 1
            if depth == 0:
                return text[pos + 1:i], i + 1
        i += 1
        if depth > 40:
            break
    raise ValueError("Unterminated or excessively nested bibliography value.")


def _quoted(text: str, pos: int) -> tuple[str, int]:
    i = pos + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == '"':
            return text[pos + 1:i], i + 1
        else:
            i += 1
    raise ValueError("Unterminated bibliography quoted value.")


def _value(text: str, offset: int) -> tuple[str, int]:
    i = _skip(text, offset)
    if i >= len(text):
        raise ValueError("Bibliography value is missing.")
    if text[i] == "{":
        return _braced(text, i, "{", "}")
    if text[i] == '"':
        return _quoted(text, i)
    end = i
    while end < len(text) and text[end] not in ",}\r\n#":
        end += 1
    if end == i:
        raise ValueError("Bibliography value cannot be interpreted.")
    return text[i:end].strip(), end


def _entry_block(text: str, start: int, delimiter: str) -> tuple[str, int]:
    """Find balanced entry outer delimiter, preserving nested braces/quoted text."""
    closing = "}" if delimiter == "{" else ")"
    stack = [delimiter]
    quote = False
    i = start + 1
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            quote = not quote
            i += 1
            continue
        if not quote:
            if ch in "{(":
                stack.append(ch)
                if len(stack) > 40:
                    break
            elif ch in "})":
                if not stack or {"}": "{", ")": "("}[ch] != stack[-1]:
                    raise ValueError("Unbalanced bibliography entry.")
                stack.pop()
                if not stack:
                    return text[start + 1:i], i + 1
        i += 1
    raise ValueError("Unterminated bibliography entry.")


def _next_entry(text: str, cursor: int):
    """Skip percent comments before parsing the next literal entry marker."""
    while cursor < len(text):
        if text[cursor] == "%":
            end = text.find("\n", cursor)
            cursor = len(text) if end < 0 else end + 1
            continue
        if text[cursor] == "@":
            match = ENTRY_START.match(text, cursor)
            if match:
                return match
        cursor += 1
    return None


def _parse_bib(text: str, path: str) -> tuple[list[dict], list[dict]]:
    entries, errors = [], []
    if len(text.encode("utf-8")) > MAX_BIB_BYTES:
        return entries, [{"code": "oversized-bib", "path": path,
                          "line": 0, "character": 0, "message": "Bibliography file exceeds size limit."}]
    i = 0
    while i < len(text):
        if len(entries) >= MAX_ENTRIES or len(errors) >= MAX_REPORT_ITEMS:
            errors.append({"code": "bib-limit", "path": path, "line": 0, "character": 0,
                           "message": "Bibliography parser reached its bounded limit."})
            break
        match = _next_entry(text, i)
        if not match:
            break
        kind = match.group(1).casefold()
        try:
            block, after = _entry_block(text, match.end(2) - 1, match.group(2))
        except ValueError as exc:
            errors.append({"code": "malformed-entry", **_location(text, match.start(), path),
                           "message": str(exc)})
            break
        i = after
        if kind in UNKNOWN:
            continue
        comma = block.find(",")
        if comma < 0 or not ENTRY_KEY.fullmatch(block[:comma].strip()):
            errors.append({"code": "invalid-bibkey", **_location(text, match.start(), path),
                           "message": "Entry must have a safe citation key followed by a comma."})
            continue
        key = block[:comma].strip()
        fields = {}
        cursor = comma + 1
        malformed = None
        while cursor < len(block):
            cursor = _skip(block, cursor)
            if cursor >= len(block):
                break
            if block[cursor] == ",":
                cursor += 1
                continue
            field = FIELD_NAME.match(block, cursor)
            if not field:
                malformed = "Unsupported or malformed bibliography field."
                break
            cursor = _skip(block, field.end())
            if cursor >= len(block) or block[cursor] != "=":
                malformed = "Bibliography field is missing an equals sign."
                break
            try:
                value, cursor = _value(block, cursor + 1)
            except ValueError as exc:
                malformed = str(exc)
                break
            cursor = _skip(block, cursor)
            if cursor < len(block) and block[cursor] == "#":
                malformed = "BibTeX string concatenation and macros are not expanded."
                break
            name = field.group(0).casefold()
            if name in fields:
                malformed = "Duplicate bibliography field: " + name
                break
            fields[name] = value[:1000]
            if len(fields) > 45:
                malformed = "Bibliography field cap reached."
                break
        if malformed:
            errors.append({"code": "malformed-fields", **_location(text, match.start(), path),
                           "message": malformed + " Entry " + key + " is not trusted."})
            continue
        entries.append({"key": key, "type": kind, "path": path,
                        **_location(text, match.start(), path),
                        "fields": fields, "parser": "bounded-bibtex-literal",
                        "source": "local-bibliography", "metadata_verified": False})
    return entries, errors[:MAX_REPORT_ITEMS]


def _crossref_fetch(doi: str) -> dict:
    """Only fetch a fixed HTTPS registry endpoint; never accept an arbitrary URL."""
    from urllib.request import HTTPRedirectHandler
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            return None
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={
        "User-Agent": "AutoMotoDeveloperStudio/10 (explicit DOI metadata validation)",
        "Accept": "application/json",
    })
    try:
        with opener.open(request, timeout=5) as response:
            if response.status != 200:
                raise HTTPException(502, "Bibliographic registry returned a non-success response.")
            payload = response.read(MAX_CROSSREF_BYTES + 1)
        if len(payload) > MAX_CROSSREF_BYTES:
            raise HTTPException(502, "Bibliographic registry response was too large.")
        record = json.loads(payload)
        if not isinstance(record, dict) or not isinstance(record.get("message"), dict):
            raise ValueError("Invalid registry metadata shape.")
        return record["message"]
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(404, "Crossref does not have a record for this DOI.") from exc
        raise HTTPException(502, "Crossref metadata lookup failed.") from exc
    except (urllib.error.URLError, OSError, ValueError, UnicodeError, TimeoutError) as exc:
        raise HTTPException(502, "Crossref metadata unavailable; no verification was recorded.") from exc


def _metadata(raw: dict, requested: str) -> dict:
    doi = _normalise_doi(str(raw.get("DOI", "")))
    if doi != requested:
        raise HTTPException(502, "Registry DOI does not match the requested identifier.")
    def first(key):
        value = raw.get(key, [])
        return value[0][:500] if isinstance(value, list) and value and isinstance(value[0], str) else ""
    author = raw.get("author", [])
    people = []
    if isinstance(author, list):
        for item in author[:12]:
            if isinstance(item, dict):
                family = str(item.get("family", ""))[:100]
                given = str(item.get("given", ""))[:100]
                if family or given:
                    people.append({"given": given, "family": family})
    dateparts = raw.get("published", raw.get("issued", {}))
    year = None
    if isinstance(dateparts, dict):
        parts = dateparts.get("date-parts", [])
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            value = parts[0][0]
            if isinstance(value, int) and 1000 <= value <= 2200:
                year = value
    return {"doi": doi, "title": first("title"), "container_title": first("container-title"),
            "author": people, "year": year, "volume": str(raw.get("volume", ""))[:80],
            "issue": str(raw.get("issue", ""))[:80], "pages": str(raw.get("page", ""))[:120],
            "publisher": str(raw.get("publisher", ""))[:200],
            "record_type": str(raw.get("type", ""))[:80],
            "source": "Crossref registry metadata", "peer_review_verified": False,
            "publication_authenticity_verified": False}


def _evidence_key(root: Path, doi: str) -> tuple:
    identity = studio._identity(root)
    return (identity["path"], identity["device"], identity["inode"], doi)


def _evidence_get(root: Path, doi: str) -> Optional[dict]:
    with EVIDENCE_LOCK:
        key = _evidence_key(root, doi)
        item = EVIDENCE.get(key)
        if item is None:
            return None
        if time.monotonic() - item["checked_at"] > EVIDENCE_TTL:
            EVIDENCE.pop(key, None)
            return None
        EVIDENCE.move_to_end(key)
        return item["metadata"].copy()


def _evidence_store(root: Path, doi: str, metadata: dict) -> None:
    with EVIDENCE_LOCK:
        key = _evidence_key(root, doi)
        EVIDENCE[key] = {"checked_at": time.monotonic(), "metadata": metadata}
        EVIDENCE.move_to_end(key)
        while len(EVIDENCE) > MAX_EVIDENCE:
            EVIDENCE.popitem(last=False)


def _bib_sources(root: Path, body: ProjectIn, graph: dict) -> list[str]:
    targets = set()
    for path in graph["files"]:
        source = latex._read(root, path, body.active_path, body.active_text)
        if source is None:
            continue
        for item in latex._commands(path, source)["bibfiles"]:
            dest = latex._safe_relative(root, path, item["value"], ".bib")
            if dest is not None:
                targets.add(dest)
    return sorted(targets)[:latex.MAX_FILES]


def _report(root: Path, body: ProjectIn) -> dict:
    graph = latex._analyse(root, body)
    warnings = []
    entries = []
    bibpaths = _bib_sources(root, body, graph)
    truncated = graph["truncated"] or len(bibpaths) >= latex.MAX_FILES
    total = 0
    for path in bibpaths:
        result = source_index._source(root, path)
        if result is None:
            warnings.append({"code": "unreadable-bib", "path": path,
                             "message": "Bibliography is missing, restricted or too large."})
            continue
        text, digest, size = result
        total += size
        if total > latex.MAX_TOTAL_BYTES or len(entries) >= MAX_ENTRIES:
            truncated = True
            break
        found, parse_errors = _parse_bib(text, path)
        entries.extend(found[:max(0, MAX_ENTRIES - len(entries))])
        warnings.extend(parse_errors[:MAX_REPORT_ITEMS - len(warnings)])
    citation_order = list(dict.fromkeys(item["value"] for item in graph["citations"]))
    cited = set(citation_order)
    keycounts = Counter(entry["key"] for entry in entries)
    for entry in entries:
        fields = entry["fields"]
        missing = [key for key in REQUIRED if not fields.get(key)]
        if not _year(fields):
            missing.append("year/date")
        if entry["type"] in BOOKLIKE and not (fields.get("publisher") or fields.get("institution") or fields.get("school")):
            missing.append("publisher/institution")
        doi = _normalise_doi(fields.get("doi", "")) if fields.get("doi") else None
        issues = []
        if missing:
            issues.append("missing bibliographic fields: " + ", ".join(missing))
        if fields.get("doi") and not doi:
            issues.append("malformed DOI")
        if keycounts[entry["key"]] > 1:
            issues.append("duplicate citation key")
        if any(PLACEHOLDER.search(fields.get(field, "")) for field in ("title", "author", "journal")):
            issues.append("placeholder citation metadata")
        evidence = _evidence_get(root, doi) if doi else None
        matches = {}
        if evidence:
            title = _normalised_text(fields.get("title", ""))
            authoritative = _normalised_text(evidence["title"])
            if title and authoritative:
                matches["title"] = title == authoritative
            try:
                bibyear = int(_year(fields) or "")
            except (TypeError, ValueError):
                bibyear = None
            if bibyear and evidence["year"]:
                matches["year"] = bibyear == evidence["year"]
            family = evidence["author"][0]["family"] if evidence["author"] else ""
            if family and fields.get("author"):
                matches["first_author_family"] = _normalised_text(family) in _normalised_text(fields["author"])
            if not matches or any(value is False for value in matches.values()):
                issues.append("possible Crossref bibliographic metadata mismatch")
        entry["doi_normalised"] = doi
        entry["doi_evidence"] = "crossref-record-matched" if evidence else "not-checked"
        entry["registry_matches"] = matches
        entry["issues"] = issues
        entry["preflight"] = "review" if issues else "registry_checked" if evidence else "unverified"
        entry["cited"] = entry["key"] in cited
        entry["metadata_verified"] = evidence is not None
    missing_citations = sorted(cited - set(keycounts))[:MAX_REPORT_ITEMS]
    duplicate_keys = sorted(key for key, count in keycounts.items() if count > 1)[:MAX_REPORT_ITEMS]
    unresolved = sum(1 for item in graph["diagnostics"] if item["code"] == "unresolved-citation")
    blocking = bool(missing_citations or duplicate_keys or any(e["issues"] for e in entries) or
                    warnings or graph["truncated"])
    return {"schema_version": SCHEMA_VERSION, "project": str(root), "main": body.main,
            "bibliography_system": _bibliography_backend(root, body, graph),
            "entries": entries[:MAX_ENTRIES], "entry_count": len(entries),
            "bib_files": bibpaths, "cited_keys": citation_order[:MAX_REPORT_ITEMS],
            "missing_citations": missing_citations, "duplicate_keys": duplicate_keys,
            "parser_warnings": warnings[:MAX_REPORT_ITEMS],
            "static_citation_diagnostics": graph["diagnostics"][:MAX_REPORT_ITEMS],
            "blocking_issues": blocking, "unresolved_citation_count": unresolved,
            "truncated": truncated, "crossref_lookup_automatic": False,
            "preflight_only": True, "ready_for_publication": False,
            "source_modified": False, "source_executed": False,
            "registry_data_not_proof_of_authenticity": True}


@router.post("/preflight")
def preflight(request: Request, body: ProjectIn):
    studio._auth(request)
    root = studio._project(body.project)
    return _report(root, body)


@router.post("/verify-doi")
def verify_doi(request: Request, body: VerifyIn):
    studio._auth(request)
    root = studio._project(body.project)
    report = _report(root, body)
    found = [entry for entry in report["entries"] if entry["key"] == body.key]
    if len(found) != 1:
        raise HTTPException(409, "Citation key must resolve to exactly one local bibliography entry.")
    value = found[0]["fields"].get("doi")
    doi = _normalise_doi(value) if value else None
    if not doi:
        raise HTTPException(422, "Citation entry has no valid DOI to check.")
    metadata = _metadata(_crossref_fetch(doi), doi)
    _evidence_store(root, doi, metadata)
    # Reuse exactly the same comparison rules as normal preflight after verification.
    result = _report(root, body)
    entry = next(item for item in result["entries"] if item["key"] == body.key)
    return {"key": body.key, "doi": doi, "registry": metadata,
            "entry_preflight": entry["preflight"], "possible_mismatches": entry["issues"],
            "field_comparison": entry["registry_matches"],
            "source": "Crossref registry; this request contacted Crossref explicitly",
            "query_contains_only_doi": True, "source_modified": False,
            "publication_authenticity_verified": False, "peer_review_verified": False}


def _authors(value: str, ieee: bool) -> Optional[str]:
    authors = [v.strip() for v in re.split(r"\s+and\s+", value) if v.strip()]
    if not authors:
        return None
    output = []
    for name in authors[:12]:
        if "," in name:
            family, given = (s.strip() for s in name.split(",", 1))
        else:
            bits = name.split()
            if len(bits) < 2:
                return None
            family, given = bits[-1], " ".join(bits[:-1])
        if not family or not given:
            return None
        initials = " ".join(word[0].upper() + "." for word in re.findall(r"[A-Za-z]+", given)[:5])
        if not initials:
            return None
        output.append((initials + " " + family) if ieee else (family + ", " + initials))
    return ", ".join(output)


def _format_entry(entry: dict, style: str, number: Optional[int]) -> dict:
    fields = entry["fields"]
    missing = [name for name in REQUIRED if not fields.get(name)]
    if not _year(fields):
        missing.append("year/date")
    if missing or entry["issues"]:
        raise HTTPException(409, "Citation preflight incomplete or mismatched. Resolve fields and warnings first.")
    authors = _authors(fields["author"], style == "ieee")
    if not authors:
        raise HTTPException(409, "Author field cannot be safely formatted with the supported literal name rules.")
    title = fields["title"].strip()
    year = _year(fields)
    container = (fields.get("journal") or fields.get("journaltitle") or
                 fields.get("booktitle") or fields.get("publisher") or "").strip()
    doi = entry["doi_normalised"]
    if style == "harvard":
        result = authors + " (" + year + ") '" + title + "'"
        if container:
            result += ", " + container
        if fields.get("volume"):
            result += ", " + fields["volume"]
        if fields.get("number"):
            result += "(" + fields["number"] + ")"
        if fields.get("pages"):
            result += ", pp. " + fields["pages"]
        if doi:
            result += ". https://doi.org/" + doi
        else:
            result += "."
    else:
        result = ("[" + str(number) + "] " if number is not None else "[n] ")
        result += authors + ', "' + title + ',"'
        if container:
            result += " " + container + ","
        if fields.get("volume"):
            result += " vol. " + fields["volume"] + ","
        if fields.get("number"):
            result += " no. " + fields["number"] + ","
        if fields.get("pages"):
            result += " pp. " + fields["pages"] + ","
        result += " " + year + "."
        if doi:
            result += " doi: " + doi + "."
    return {"style": style, "key": entry["key"], "reference": result,
            "number": number, "doi_registry_checked": entry["metadata_verified"],
            "source": "local BibTeX/BibLaTeX fields; illustrative preview",
            "formal_style_guide_verified": False, "source_modified": False,
            "ready_for_publication": False}



def _bibliography_backend(root: Path, body: ProjectIn, graph: dict) -> dict:
    has_biblatex = False
    has_bibliography = False
    has_biber_option = False
    has_print = False
    for path in graph["files"]:
        text = latex._read(root, path, body.active_path, body.active_text)
        if text is None:
            continue
        safe = latex._mask(text)
        has_biblatex |= bool(re.search(
            r"\\usepackage(?:\s*\[[^\]\r\n]{0,160}\])?\s*\{biblatex\}", safe))
        has_biber_option |= bool(re.search(
            r"\\usepackage\s*\[[^\]\r\n]*backend\s*=\s*biber[^\]\r\n]*\]\s*\{biblatex\}", safe))
        has_bibliography |= bool(re.search(r"\\bibliography\s*\{", safe))
        has_print |= bool(re.search(r"\\printbibliography\b", safe))
    if has_biblatex and (has_print or has_biber_option):
        variant = "biblatex"  # biber common but not certain without actual config/build
    elif has_bibliography and not has_biblatex:
        variant = "bibtex"
    else:
        variant = "unknown_or_mixed"
    return {"system": variant, "biber_requested": has_biber_option,
            "compiler_or_biber_executed": False,
            "static_detection_only": True}


@router.get("/toolchains")
def toolchains(request: Request, project: str):
    studio._auth(request)
    root = studio._project(project)
    tools = []
    for name in ("bibtex", "biber", "texlab", "latexmk", "tectonic"):
        resolved = shutil.which(name)
        status = "unavailable"
        if resolved:
            try:
                path = Path(resolved).resolve(strict=True)
                if (path.is_file() and stat.S_ISREG(path.stat().st_mode)
                    and not path.is_relative_to(root)):
                    status = "found_on_path_not_executed"
            except (OSError, ValueError):
                pass
        tools.append({"name": name, "status": status})
    return {"tools": tools, "versions_checked": False,
            "tools_executed": False, "project_modified": False}


@router.post("/format")
def format_reference(request: Request, body: FormatIn):
    studio._auth(request)
    root = studio._project(body.project)
    report = _report(root, body)
    matches = [entry for entry in report["entries"] if entry["key"] == body.key]
    if len(matches) != 1:
        raise HTTPException(409, "Citation key does not uniquely resolve.")
    # IEEE numbering follows the bounded source discovery order, not TeX's
    # expanded and compiled citation order. Mark as a preview, never canonical.
    seen = list(dict.fromkeys(report["cited_keys"]))
    number = seen.index(body.key) + 1 if body.key in seen else None
    return _format_entry(matches[0], body.style, number)


@router.get("/styles")
def styles(request: Request):
    studio._auth(request)
    return {"styles": [
        {"id": "harvard", "label": "Harvard author-date", "scope": "basic preview only; institution-specific rules differ"},
        {"id": "ieee", "label": "IEEE numbered", "scope": "basic preview; citation order not compiler-verified"},
    ], "automatic_registry_lookup": False, "publication_ready": False}
