"""Automatic long-term memory: learn lasting facts and preferences from what the user says.

Deterministic (no model call, works offline and on small models): a few plain patterns on the user's own
messages - "my name is…", "call me…", "I prefer…", "I like / don't like…", "I'm a…", "I study / work…",
"I live in…", "my favourite X is…", "remember that…", "always / never …". Facts are saved with the tag
``auto``; a fact with a *key* (name, location, role…) replaces the older one; near-duplicates are skipped.
Anything that looks like a secret or contact detail (passwords, keys, tokens, card or phone numbers,
e-mail addresses) is never stored. Everything can be viewed, edited and deleted in Memory, and the
``auto_memory`` setting turns it off.
"""

from __future__ import annotations

import re
from typing import Any

SECRETISH = re.compile(r"(passw|pass ?code|passcode|pin\b|api[ _-]?key|token|secret|private key|ssh|otp|2fa|"
                       r"\bkey is\b|sk-[a-z0-9]|ghp_|bearer|credit card|card number|cvv|iban|sort code|"
                       r"national insurance|ssn|social security|@[a-z0-9-]+\.[a-z]|\d{6,}|\+\d{2,})", re.I)
_SENT = re.compile(r"(?<=[.!?;\n])\s+|\n")
_CLEAN = re.compile(r"[\s,.;:!]+$")
_NOT_THINGS = r"(?!(?:it|this|that|these|those|the answer|your|you|to know|to ask|so|very|really|a lot)\b)"

# (pattern, key or None, template, category). {0} is the captured text.
RULES: list[tuple[re.Pattern[str], str | None, str, str]] = [
    (re.compile(r"\b(?i:my name is|call me)\s+([A-Za-z][\w'-]+(?:\s+[A-Z][\w'-]+){0,3})"), "name", "The user's name is {0}", "About you"),
    (re.compile(r"\b(?i:i live in|i'm based in|i am based in|i'm from|i am from)\s+([A-Z][\w' -]{1,60})"), "location",
     "Lives in / is from {0}", "About you"),
    (re.compile(r"\bmy time ?zone is\s+([\w/+:-]{2,40})", re.I), "timezone", "Time zone: {0}", "About you"),
    (re.compile(r"\bi(?:'m| am) (?:a|an)\s+((?:[\w-]+\s+){0,4}?(?:student|developer|engineer|designer|teacher|lecturer|"
                r"researcher|writer|manager|analyst|nurse|doctor|scientist|freelancer|founder|artist|programmer|"
                r"[\w-]{3,}(?:er|ist|or|ian|ant)))\b", re.I), "role", "Is a {0}", "About you"),
    (re.compile(r"\bi(?:'m| am)? ?(?:studying|study|doing)\s+((?:an? |the )?(?:bsc|ba|msc|ma|phd|degree|course|"
                r"top-?up|a-?levels?|gcses?|hnd|btec)[\w ()&,'-]{0,80})", re.I), "study", "Studies {0}", "Work and study"),
    (re.compile(r"\bi work ((?:as|at|for|in)\s+[\w ()&,'.-]{2,80})", re.I), "work", "Works {0}", "Work and study"),
    (re.compile(r"\bmy favou?rite\s+([\w -]{2,30}?)\s+(?:is|are)\s+([\w ()&,'.+#-]{1,60})", re.I), "fav:{0}",
     "Favourite {0}: {1}", "Likes and dislikes"),
    (re.compile(r"\bi (?:really )?(?:prefer)\s+" + _NOT_THINGS + r"([\w ()&,'.+#/-]{2,100})", re.I), None, "Prefers {0}",
     "Preferences"),
    (re.compile(r"\bi (?:really )?(?:like|love|enjoy)\s+" + _NOT_THINGS + r"([\w ()&,'.+#/-]{2,80})", re.I), None,
     "Likes {0}", "Likes and dislikes"),
    (re.compile(r"\bi (?:don't|do not|dont) (?:really )?like\s+" + _NOT_THINGS + r"([\w ()&,'.+#/-]{2,80})|\bi hate\s+"
                + _NOT_THINGS + r"([\w ()&,'.+#/-]{2,80})", re.I), None, "Dislikes {0}", "Likes and dislikes"),
    (re.compile(r"\bremember (?:that )?(?!to\b|me\b)(.{4,200})", re.I), None, "{0}", "Notes"),
    (re.compile(r"^(?:please )?((?:always|never) (?!mind\b)[\w ()&,'.+#/:-]{4,160})", re.I), None, "{0}", "Preferences"),
]


def _ok(s: str) -> bool:
    return bool(s) and not SECRETISH.search(s)


def extract(text: str) -> list[dict[str, Any]]:
    """Facts in one user message: [{"key": str|None, "text": str, "category": str}]."""
    if not isinstance(text, str) or not text.strip() or len(text) > 20000:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sent in _SENT.split(text.strip())[:80]:
        sent = sent.strip().strip("\"'`")
        if not sent or sent.endswith("?") or len(sent) > 400 or not _ok(sent):
            continue
        if re.match(r"^(?:what|who|where|when|how|why|can|could|would|do|does|is|are)\b", sent, re.I):
            continue
        for rx, key, tpl, cat in RULES:
            m = rx.search(sent)
            if not m:
                continue
            groups = [_CLEAN.sub("", g.strip()) for g in m.groups() if g]
            if not groups or any(len(g) < 2 for g in groups):
                continue
            if key == "name":
                groups = [" ".join(w[:1].upper() + w[1:] for w in groups[0].split())]
            fact = tpl.format(*groups)
            fact = fact[0].upper() + fact[1:]
            k = key.format(*[g.lower() for g in groups]) if key else None
            if fact.lower() in seen or not _ok(fact):
                continue
            seen.add(fact.lower())
            out.append({"key": k, "text": fact[:300], "category": cat})
            if key or tpl == "{0}":
                break  # one fact per sentence for keyed/verbatim rules
    return out[:8]


def enabled() -> bool:
    try:
        from automoto import settings

        return settings.get("auto_memory") is not False
    except Exception:
        return True


def learn(memory: Any, text: str, source: str = "chat") -> list[dict[str, Any]]:
    """Save what ``text`` (a user message) says about the user. Returns the facts that were new or changed."""
    if not enabled() or memory is None:
        return []
    saved = []
    for f in extract(text):
        try:
            r = memory.upsert(f["text"], key=f["key"], tags=f"auto,{f['category']}", source=source)
        except Exception:
            continue
        if not r.get("duplicate"):
            saved.append({"id": r["id"], "text": f["text"], "category": f["category"], "replaced": r.get("replaced")})
    if saved:
        try:
            memory.mirror()
        except Exception:
            pass
    return saved


def user_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type", "text") == "text")
    return ""
