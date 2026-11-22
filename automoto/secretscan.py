"""Find secrets in text that is about to leave the computer (pre-push scan, .patch export).

Shared by Developer Studio sharing (V46) and anything else that needs "does this look like a
password or key?". Hits are reported with the value masked; the value itself is never returned.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from automoto import redaction

# Each rule: (id, plain-words name, pattern). Group "v" (if present) is the secret part.
RULES: list[tuple[str, str, re.Pattern]] = [
    ("github", "GitHub token", re.compile(r"(?<![A-Za-z0-9_])(?P<v>(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{20,255})")),
    ("gitlab", "GitLab token", re.compile(
        r"(?<![A-Za-z0-9_])(?P<v>gl(?:pat|oas|rt|dt|ft|cbt|ptt|soat|imt|agent|ffct|wt)-[A-Za-z0-9_\-]{16,})")),
    ("aws_key", "AWS access key", re.compile(r"(?<![A-Z0-9])(?P<v>(?:AKIA|ASIA)[A-Z0-9]{16})(?![A-Z0-9])")),
    ("aws_secret", "AWS secret key", re.compile(
        r"(?i)aws_?secret_?(?:access_?)?key\W{0,4}(?P<v>[A-Za-z0-9/+]{40})(?![A-Za-z0-9/+])")),
    ("google", "Google API key", re.compile(r"(?<![A-Za-z0-9_])(?P<v>AIza[0-9A-Za-z_\-]{35})")),
    ("slack", "Slack token", re.compile(r"(?<![A-Za-z0-9])(?P<v>xox[abposr]-[A-Za-z0-9-]{10,})")),
    ("stripe", "Stripe secret key", re.compile(r"(?<![A-Za-z0-9])(?P<v>(?:sk|rk)_live_[A-Za-z0-9]{16,})")),
    ("openai", "AI service key", re.compile(r"(?<![A-Za-z0-9])(?P<v>sk-(?:proj-|ant-[a-z0-9]{2,6}-)?[A-Za-z0-9_\-]{32,})")),
    ("hf", "Hugging Face token", re.compile(r"(?<![A-Za-z0-9])(?P<v>hf_[A-Za-z0-9]{30,})")),
    ("pem", "private key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("jwt", "login token (JWT)", re.compile(
        r"(?<![A-Za-z0-9_\-])(?P<v>eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})")),
    ("url_password", "password inside a web address", re.compile(
        r"(?i)\b[a-z][a-z0-9+.\-]{1,20}://[^\s:/@'\"]{1,64}:(?P<v>[^\s@/'\"]{6,128})@[A-Za-z0-9.\-]+")),
]
ASSIGN = re.compile(
    r"(?i)(?P<name>[A-Za-z0-9_.\-]{0,40}(?:password|passwd|pwd|secret|token|api[_\-]?key|apikey|access[_\-]?key|"
    r"client[_\-]?secret|private[_\-]?key|auth))[\"']?\s*(?:=|:|:=|=>)\s*[\"']?(?P<v>[^\s\"'`,;)}\]]{12,200})")
PLACEHOLDER = re.compile(
    r"(?i)^(?:x{4,}|\*{4,}|\.{3,}|<[^>]*>|\$\{?[A-Za-z_][\w.]*\}?|%\(?\w+\)?s?|\{\{.*\}\}|"
    r"(?:your|my|example|sample|dummy|fake|test|placeholder|changeme|change_me|replace|redacted|none|null|"
    r"undefined|todo|secret|password|token)[\w\-.]*)$")
CODE_HINT = re.compile(r"(?i)(?:os\.environ|getenv|process\.env|env\(|settings\.|config\.|self\.|request\.|"
                       r"\(|\)|\[|\]|^\w+\.\w+$)")


def entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def mask(value: str) -> str:
    """Never shows enough to be useful: a short prefix (a public token type) and the length."""
    prefix = ""
    m = re.match(r"(github_pat_|gh[pousr]_|gl[a-z]{2,6}-|AKIA|ASIA|AIza|xox[a-z]-|sk_live_|rk_live_|sk-|hf_|eyJ)", value)
    if m:
        prefix = m.group(1)
    return f"{prefix}… ({len(value)} characters, hidden)"


@dataclass
class Hit:
    rule: str
    name: str
    line: int | None
    masked: str

    def as_dict(self) -> dict:
        return {"rule": self.rule, "name": self.name, "line": self.line, "masked": self.masked}


def scan_line(text: str, *, generic: bool = True) -> list[tuple[str, str, str]]:
    """[(rule, plain name, masked)] for one line of text."""
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for rule, name, pat in RULES:
        for m in pat.finditer(text):
            val = m.groupdict().get("v") or m.group(0)
            if val in seen:
                continue
            seen.add(val)
            out.append((rule, name, mask(val) if rule != "pem" else "private key block"))
    if generic and not out:
        for m in ASSIGN.finditer(text):
            val = m.group("v").strip()
            if (PLACEHOLDER.match(val) or CODE_HINT.search(val) or entropy(val) < 3.5
                    or not re.search(r"[0-9]", val) or not re.search(r"[A-Za-z]", val)):
                continue
            out.append(("assignment", f"value of {m.group('name')[-40:]}", mask(val)))
    return out


def scan_text(text: str, *, known: tuple[str, ...] = (), generic: bool = True) -> list[Hit]:
    hits: list[Hit] = []
    for n, line in enumerate(text.splitlines(), 1):
        for rule, name, masked in scan_line(line, generic=generic):
            hits.append(Hit(rule, name, n, masked))
    for secret in known:
        if secret and redaction.contains_secret(text, secret):
            hits.append(Hit("signed_in_token", "your sign-in token", None, "hidden"))
    return hits
