"""Research Studio V2 — explicit, rate-limited scholarly registry and webpage discovery.

Crossref and OpenAlex provide *deposited bibliographic metadata*, not verified
research outcomes. No model, speculative citation, arbitrary crawler, page
execution or automatic source import. Public requests use AutoMoto's existing
DNS-pinned SSRF guard and obey local offline configuration.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlencode, urlsplit
from urllib.robotparser import RobotFileParser

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from automoto import config, document_workspace, netguard, settings
from automoto.tools import html_to_text, _title
from automoto.visual_studio import _auth

router = APIRouter(prefix="/api/research/studio/discovery", tags=["research-discovery"])
DOI = re.compile(r"^10\.[0-9]{4,9}/[^\s<>\"#?]{1,220}$", re.I)
FILE = re.compile(r"^source-[0-9a-f]{24}\.source\.json$")
PAGE = re.compile(r"^web-[0-9a-f]{24}\.web\.json$")
DOC = re.compile(r"^web-source-[0-9a-f]{24}\.txt$")
MAX_SAVED = 200
MAX_METADATA_BYTES = 16_000
MAX_PAGE_TEXT = 9_000
MAX_PAGE_BODY = 250_000
_RATE_LOCK = threading.Lock()
_LAST_REQUEST = 0.0
_MIN_INTERVAL = 0.6


class SearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(..., min_length=3, max_length=180)
    provider: Literal["crossref", "openalex"] = "crossref"
    limit: int = Field(8, ge=1, le=10)


class DoiIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doi: str = Field(..., min_length=7, max_length=260)


class SaveDoi(DoiIn):
    confirm_metadata_only: Literal[True]


class CapturePage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(..., min_length=12, max_length=900)
    confirm_public_capture: Literal[True]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _online() -> None:
    configured = (config.env("AUTOMOTO_OFFLINE", "") or "").lower()
    if configured in ("1", "yes", "true", "on") or settings.get("offline"):
        raise HTTPException(403, "Research discovery requires Internet access; offline mode is enabled.")


def _rate() -> None:
    global _LAST_REQUEST
    # Do not accumulate unbounded pending jobs or retry a provider automatically.
    with _RATE_LOCK:
        current = time.monotonic()
        if current - _LAST_REQUEST < _MIN_INTERVAL:
            raise HTTPException(429, "Scholarly lookup is rate-limited. Retry shortly.")
        _LAST_REQUEST = current


def _get(url: str, *, host: str, cap: int = 350_000) -> netguard.Response:
    _online()
    _rate()
    if urlsplit(url).scheme != "https" or urlsplit(url).hostname != host:
        raise HTTPException(422, "Unapproved scholarly registry host.")
    try:
        result = netguard.request(url, timeout=10, total_timeout=22, max_bytes=cap,
                                  max_redirects=0, headers={"Accept": "application/json"})
    except (netguard.BlockedURL, OSError, TimeoutError, ValueError):
        raise HTTPException(503, "Scholarly source lookup failed securely.") from None
    if result.status in (403, 429):
        raise HTTPException(429, "Scholarly registry quota or access limit was reached.")
    if result.status == 404:
        raise HTTPException(404, "The requested DOI was not found in this registry.")
    if result.status != 200 or urlsplit(result.url).hostname != host:
        raise HTTPException(503, "Scholarly registry did not return a valid response.")
    if "json" not in result.content_type.lower():
        raise HTTPException(502, "Scholarly registry returned unexpected content.")
    return result


def _json(url: str, host: str) -> dict:
    result = _get(url, host=host)
    try:
        data = json.loads(result.body)
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (UnicodeError, ValueError, TypeError):
        raise HTTPException(502, "Scholarly metadata response was malformed.") from None


def _normalise_doi(raw: str) -> str:
    value = raw.strip()
    if value.lower().startswith("https://doi.org/"):
        value = value[len("https://doi.org/"):]
    elif value.lower().startswith("doi:"):
        value = value[4:].strip()
    # DOI suffix is case-insensitive and may contain punctuation, but not
    # fragments, whitespace or URL query delimiters in this bounded version.
    value = value.strip().lower()
    if not DOI.fullmatch(value) or ".." in value or "%2f" in value:
        raise HTTPException(422, "Enter a valid DOI beginning 10.xxxx/...")
    return value


def _date_parts(item: dict) -> str | None:
    for key in ("published", "issued", "published-print", "published-online", "created"):
        date = item.get(key)
        if not isinstance(date, dict):
            continue
        parts = date.get("date-parts")
        if not isinstance(parts, list) or not parts or not isinstance(parts[0], list):
            continue
        p = parts[0]
        if not p or not isinstance(p[0], int) or not 1000 <= p[0] <= 2200:
            continue
        if len(p) > 1 and isinstance(p[1], int) and 1 <= p[1] <= 12:
            if len(p) > 2 and isinstance(p[2], int) and 1 <= p[2] <= 31:
                return f"{p[0]:04d}-{p[1]:02d}-{p[2]:02d}"
            return f"{p[0]:04d}-{p[1]:02d}"
        return str(p[0])
    return None


def _clean(value, size=240) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:size]


def _crossref(item: dict, retrieved_at: str) -> dict | None:
    if not isinstance(item, dict):
        return None
    try:
        doi = _normalise_doi(item.get("DOI") or "")
    except HTTPException:
        return None
    title = item.get("title")
    if not isinstance(title, list) or not title or not isinstance(title[0], str):
        return None
    title = _clean(title[0], 400)
    if not title:
        return None
    names = []
    for person in (item.get("author") or [])[:12]:
        if not isinstance(person, dict):
            continue
        name = _clean(" ".join([person.get("given") or "", person.get("family") or ""]), 100)
        if name:
            names.append(name)
    container = item.get("container-title")
    venue = _clean(container[0], 180) if isinstance(container, list) and container else None
    date = _date_parts(item)
    return {
        "doi": doi, "title": title, "authors": names[:8], "venue": venue,
        "publication_date": date, "type": _clean(item.get("type"), 60) or None,
        "registry": "Crossref", "registry_url": "https://api.crossref.org/works/" + quote(doi, safe="/"),
        "doi_url": "https://doi.org/" + quote(doi, safe="/"),
        "retrieved_at": retrieved_at,
        "provenance": "Member-deposited Crossref metadata. Neither peer-review status nor article claims are independently verified.",
        "metadata_only": True,
    }


def _openalex(item: dict, retrieved_at: str) -> dict | None:
    if not isinstance(item, dict):
        return None
    try:
        doi = _normalise_doi(item.get("doi") or "")
    except HTTPException:
        return None
    title = _clean(item.get("title"), 400)
    if not title:
        return None
    names = []
    for authorship in (item.get("authorships") or [])[:10]:
        if isinstance(authorship, dict):
            author = authorship.get("author") or {}
            if isinstance(author, dict) and author.get("display_name"):
                names.append(_clean(author["display_name"], 100))
    location = item.get("primary_location") or {}
    journal = location.get("source") if isinstance(location, dict) else None
    venue = _clean(journal.get("display_name"), 180) if isinstance(journal, dict) else None
    date = item.get("publication_date")
    date = date if isinstance(date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else None
    registry_id = item.get("id") or ""
    if not isinstance(registry_id, str) or not re.fullmatch(r"https://openalex\.org/W[0-9]+", registry_id):
        registry_id = None
    return {
        "doi": doi, "title": title, "authors": names[:8], "venue": venue,
        "publication_date": date, "type": _clean(item.get("type"), 60) or None,
        "registry": "OpenAlex", "registry_url": registry_id,
        "doi_url": "https://doi.org/" + quote(doi, safe="/"),
        "retrieved_at": retrieved_at,
        "provenance": "OpenAlex-indexed work metadata. Search ranking, review status and study claims are not verified.",
        "metadata_only": True,
        "retraction_flag": item.get("is_retracted") is True,
    }


def _folder(kind: str, create: bool = False) -> Path:
    root = document_workspace._root()
    parent = root / "artifacts"
    research = parent / "research"
    directory = research / kind
    if kind not in ("sources", "pages"):
        raise HTTPException(422, "Unsupported private research archive.")
    if any(p.is_symlink() for p in (parent, research, directory)):
        raise HTTPException(403, "Research archive cannot use symlinks.")
    if create:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.exists() and (not directory.is_dir() or
                               not directory.resolve().is_relative_to(root)):
        raise HTTPException(403, "Research archive is not private.")
    return directory


def _saved_metadata() -> list[tuple[Path, dict]]:
    folder = _folder("sources")
    if not folder.is_dir():
        return []
    output = []
    for path in sorted(folder.iterdir()):
        if not FILE.fullmatch(path.name) or not path.is_file() or path.is_symlink():
            continue
        if path.stat().st_size > MAX_METADATA_BYTES:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("schema") == "research-source-v2" and isinstance(data.get("metadata"), dict):
                output.append((path, data))
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
            continue
        if len(output) >= MAX_SAVED:
            break
    return output


@router.post("/search")
def search(body: SearchIn, request: Request):
    _auth(request)
    _online()
    when = _now()
    if body.provider == "crossref":
        url = "https://api.crossref.org/works?" + urlencode({
            "query.bibliographic": body.query.strip(), "rows": body.limit,
            "select": "DOI,title,author,container-title,published,issued,published-online,type",
        })
        data = _json(url, "api.crossref.org")
        message = data.get("message")
        records = message.get("items", []) if isinstance(message, dict) else []
        convert = _crossref
    else:
        url = "https://api.openalex.org/works?" + urlencode({
            "search": body.query.strip(), "per_page": body.limit,
            "select": "id,doi,title,authorships,publication_date,primary_location,type,is_retracted",
        })
        data = _json(url, "api.openalex.org")
        records = data.get("results", [])
        convert = _openalex
    if not isinstance(records, list):
        raise HTTPException(502, "Scholarly search returned an unexpected result list.")
    seen, results = set(), []
    for item in records[:body.limit]:
        record = convert(item, when)
        if record and record["doi"] not in seen:
            seen.add(record["doi"])
            results.append(record)
    return {
        "provider": body.provider, "query": body.query.strip(), "results": results,
        "retrieved_at": when, "source_type": "bibliographic_metadata_only",
        "not_verified_claims": True, "external_request": True, "paid_api_required": False,
        "warning": "A DOI and registry listing do not establish peer review, reliable findings or full-text access. Verify the original publication.",
    }


@router.post("/verify-doi")
def verify_doi(body: DoiIn, request: Request):
    _auth(request)
    doi = _normalise_doi(body.doi)
    url = "https://api.crossref.org/works/" + quote(doi, safe="/")
    response = _json(url, "api.crossref.org")
    metadata = _crossref(response.get("message"), _now())
    if not metadata or metadata["doi"] != doi:
        raise HTTPException(422, "DOI metadata did not match the requested identifier.")
    return {"verified_in": "Crossref", "metadata": metadata, "registry_record_found": True,
            "research_claims_verified": False, "full_text_downloaded": False}


@router.get("/saved")
def saved_sources(request: Request):
    _auth(request)
    return {
        "sources": [
            {"path": p.relative_to(document_workspace._root()).as_posix(), **data["metadata"]}
            for p, data in _saved_metadata()
        ], "metadata_only": True,
    }


@router.get("/saved-entry")
def saved_entry(path: str, request: Request):
    _auth(request)
    prefix = "artifacts/research/sources/"
    if not isinstance(path, str) or not path.startswith(prefix) or not FILE.fullmatch(path[len(prefix):]):
        raise HTTPException(403, "Invalid private scholarly record path.")
    file = _folder("sources") / path[len(prefix):]
    if file.is_symlink() or not file.is_file():
        raise HTTPException(404, "Private scholarly record not found.")
    if file.stat().st_size > MAX_METADATA_BYTES:
        raise HTTPException(413, "Stored scholarly record is too large.")
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        if data.get("schema") != "research-source-v2" or not isinstance(data.get("metadata"), dict):
            raise ValueError
    except (UnicodeError, OSError, ValueError, TypeError, AttributeError):
        raise HTTPException(422, "Scholarly record is malformed.") from None
    return {"path": path, "metadata": data["metadata"],
            "historical_snapshot": True, "claim_verification": False}


@router.post("/save-doi")
def save_doi(body: SaveDoi, request: Request):
    _auth(request)
    verified = verify_doi(DoiIn(doi=body.doi), request)
    meta = verified["metadata"]
    for path, entry in _saved_metadata():
        if entry["metadata"].get("doi") == meta["doi"]:
            return {"path": path.relative_to(document_workspace._root()).as_posix(),
                    "already_saved": True, "metadata": entry["metadata"],
                    "fresh_metadata": meta, "source_files_modified": False}
    folder = _folder("sources", create=True)
    if len(_saved_metadata()) >= MAX_SAVED:
        raise HTTPException(413, "Scholarly source library has reached its 200-record limit.")
    data = {
        "schema": "research-source-v2", "saved_at": _now(), "metadata": meta,
        "licence": "Metadata only; original publication copyrights are not transferred.",
    }
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_METADATA_BYTES:
        raise HTTPException(413, "Scholarly metadata exceeds the safe storage limit.")
    target = folder / f"source-{secrets.token_hex(12)}.source.json"
    document_workspace._atomic_file(target, raw)
    return {"path": target.relative_to(document_workspace._root()).as_posix(),
            "already_saved": False, "metadata": meta,
            "sha256": hashlib.sha256(raw).hexdigest(), "source_files_modified": False,
            "citation_ready": False}


def _safe_page_url(url: str) -> tuple[str, str]:
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password \
            or parts.port not in (None, 443):
        raise HTTPException(422, "Use a public HTTPS webpage without credentials or custom ports.")
    if parts.fragment or len(parts.query) > 300 or len(url) > 900:
        raise HTTPException(422, "URL fragments or oversized queries are not permitted.")
    origin = "https://" + parts.hostname.lower()
    return url.strip(), origin


def _fetch_page(url: str) -> dict:
    _online()
    target, origin = _safe_page_url(url)
    host = urlsplit(target).hostname
    try:
        rules = netguard.request(origin + "/robots.txt", timeout=8, total_timeout=16,
                                 max_bytes=75_000, max_redirects=0)
    except (netguard.BlockedURL, OSError, TimeoutError, ValueError):
        raise HTTPException(503, "Could not check this site's robots.txt safely.") from None
    if rules.status == 200:
        robot = RobotFileParser()
        robot.parse(rules.text().splitlines()[:4000])
        if not robot.can_fetch("AutoMotoAI", target):
            raise HTTPException(403, "Website's robots.txt does not permit this page to be collected.")
        delay = robot.crawl_delay("AutoMotoAI") or robot.crawl_delay("*") or 0
        if delay and delay > 1:
            raise HTTPException(403, "This website requires a longer crawl delay; page capture is unavailable.")
    elif rules.status != 404:
        raise HTTPException(403, "Website robots policy could not be confirmed.")
    _rate()
    try:
        page = netguard.request(target, timeout=10, total_timeout=25,
                                max_bytes=MAX_PAGE_BODY, max_redirects=0,
                                headers={"Accept": "text/html,text/plain"})
    except (netguard.BlockedURL, OSError, TimeoutError, ValueError):
        raise HTTPException(503, "Public webpage could not be collected safely.") from None
    if page.status != 200 or urlsplit(page.url).hostname != host:
        raise HTTPException(422, "Webpage redirected, blocked or returned an unexpected response.")
    mime = page.content_type.lower().split(";", 1)[0]
    if mime not in ("text/html", "text/plain"):
        raise HTTPException(415, "Only public HTML and plain-text webpages are supported.")
    text = html_to_text(page.text()) if mime == "text/html" else page.text()
    text = text[:MAX_PAGE_TEXT].strip()
    if len(text) < 40:
        raise HTTPException(422, "Webpage had insufficient accessible text for an evidence snapshot.")
    title = _title(page.text()) if mime == "text/html" else urlsplit(target).hostname
    return {
        "url": target, "title": _clean(title, 180), "retrieved_at": _now(),
        "text": text, "chars": len(text), "truncated": len(page.text()) > MAX_PAGE_TEXT,
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "warning": "Captured webpage is untrusted extracted text, not independently verified scholarly evidence.",
    }


@router.post("/capture-page")
def capture_page(body: CapturePage, request: Request):
    _auth(request)
    item = _fetch_page(body.url)
    folder = _folder("pages", create=True)
    if len([p for p in folder.iterdir() if PAGE.fullmatch(p.name) and p.is_file()]) >= 100:
        raise HTTPException(413, "Public page snapshot limit reached (100).")
    doc_folder = document_workspace._folder()
    doc_folder.mkdir(parents=True, exist_ok=True)
    if doc_folder.is_symlink():
        raise HTTPException(403, "Document workspace cannot be a symlink.")
    token = secrets.token_hex(12)
    doc_path = doc_folder / f"web-source-{token}.txt"
    provenance_path = folder / f"web-{token}.web.json"
    source_text = (
        "UNVERIFIED PUBLIC WEBPAGE SNAPSHOT — RETRIEVED TEXT, NOT VERIFIED SCHOLARLY FACT\n"
        f"Page title: {item['title']}\nOriginal URL: {item['url']}\n"
        f"Retrieved UTC: {item['retrieved_at']}\n"
        f"Text SHA-256: {item['content_sha256']}\n\n"
        + item["text"]
    ).encode("utf-8")
    metadata = {
        "schema": "research-web-v2",
        "page": {key: value for key, value in item.items() if key != "text"},
        "document": doc_path.relative_to(document_workspace._root()).as_posix(),
        "document_sha256": hashlib.sha256(source_text).hexdigest(),
    }
    try:
        document_workspace._atomic_file(doc_path, source_text)
        document_workspace._atomic_file(
            provenance_path, json.dumps(metadata, ensure_ascii=False).encode("utf-8"))
    except Exception:
        # Do not leave an untracked imported source on partial write.
        doc_path.unlink(missing_ok=True)
        raise
    return {"document": metadata["document"], "sha256": metadata["document_sha256"],
            "provenance": provenance_path.relative_to(document_workspace._root()).as_posix(),
            "source_url": item["url"], "retrieved_at": item["retrieved_at"],
            "truncated": item["truncated"], "source_files_modified": False,
            "user_confirmed": True, "claim_verification": False,
            "warning": "Only public extracted webpage text was captured. Check licensing and read the original page before citing."}
