"""V49: bounded, read-only source evidence for Developer Studio chat.

Only verified files under an approved local workspace can be read. No commands,
network requests, file writes or persistent indexing are performed. Source text
is untrusted data, not an instruction to the assistant.
"""
from __future__ import annotations

import re
from collections import defaultdict

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_index as index, developer_studio as studio

router = APIRouter(prefix="/api/developer/studio", tags=["developer-grounding"])
MAX_FILES = 160
MAX_BYTES = 3 * 1024 * 1024
MAX_SOURCES = 8
MAX_TERMS = 10
MAX_LINE = 240

WORDS = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
STOP = frozenset({
    "and", "the", "for", "with", "from", "which", "where", "what", "when",
    "how", "does", "this", "that", "into", "about", "please", "could",
    "would", "should", "show", "find", "tell", "explain", "code", "file",
    "files", "project", "source", "function", "works", "work", "using",
    "used", "make", "add", "can", "are", "its", "our", "your", "why",
})
CREDENTIAL = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|"
    r"passwd|client[_-]?secret|secret[_-]?key|private[_-]?key)\b(\s*[:=]\s*)(.*)$"
)
BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}")


class GroundingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    question: str = Field(min_length=3, max_length=500)


def _terms(question: str) -> tuple[str, ...]:
    terms = []
    for term in WORDS.findall(question.casefold()):
        if term not in STOP and term not in terms:
            terms.append(term)
    return tuple(terms[:MAX_TERMS])


def _safe_line(line: str) -> str:
    line = line.replace("\x00", "")
    line = CREDENTIAL.sub(lambda m: m.group(1) + m.group(2) + "[redacted]", line)
    line = BEARER.sub("Bearer [redacted]", line)
    return line[:MAX_LINE] + ("…" if len(line) > MAX_LINE else "")


def _search(root, terms):
    candidates = []
    scanned = total_bytes = 0
    truncated = False
    for relative, warning in index._walk(root):
        if relative is None:
            truncated = True
            continue
        if scanned >= MAX_FILES or total_bytes >= MAX_BYTES:
            truncated = True
            break
        scanned += 1
        data = index._source(root, relative)
        if data is None:
            continue
        source, sha256, length = data
        if total_bytes + length > MAX_BYTES:
            truncated = True
            break
        total_bytes += length
        lines = source.splitlines()
        for at, line in enumerate(lines):
            low = line.casefold()
            matched = [term for term in terms if term in low]
            if not matched:
                continue
            path_hits = sum(term in relative.casefold() for term in matched)
            score = len(matched) * 10 + path_hits * 2
            if any(low.lstrip().startswith(prefix) for prefix in
                   ("def ", "class ", "function ", "export ", "async def ")):
                score += 3
            first = max(0, at - 1)
            last = min(len(lines), at + 2)
            excerpt = "\n".join(
                "L{}: {}".format(i + 1, _safe_line(lines[i]))
                for i in range(first, last)
            )
            candidates.append({
                "path": relative,
                "line_start": first + 1,
                "line_end": last,
                "matched_line": at + 1,
                "sha256": sha256,
                "excerpt": excerpt,
                "score": score,
            })
    candidates.sort(key=lambda x: (-x["score"], x["path"], x["matched_line"]))
    selected = []
    per_file = defaultdict(int)
    for item in candidates:
        if per_file[item["path"]] >= 2:
            continue
        per_file[item["path"]] += 1
        selected.append(item)
        if len(selected) == MAX_SOURCES:
            break
    for item in selected:
        item.pop("score")
    return selected, scanned, total_bytes, truncated or len(candidates) > MAX_SOURCES


@router.post("/grounding")
def grounding(request: Request, body: GroundingIn):
    studio._auth(request)
    root = studio._project(body.project)
    terms = _terms(body.question)
    if not terms:
        return {"sources": [], "message": "No searchable terms in the question.",
                "verified": False, "truncated": False, "read_only": True,
                "untrusted_source_text": True}
    sources, scanned, size, truncated = _search(root, terms)
    return {
        "sources": sources, "verified": bool(sources),
        "message": ("Source lines found. Check each claim against the cited lines."
                    if sources else "No matching project evidence. Do not guess."),
        "scanned_files": scanned, "scanned_bytes": size,
        "truncated": truncated, "read_only": True,
        "untrusted_source_text": True, "local_only": True,
    }
