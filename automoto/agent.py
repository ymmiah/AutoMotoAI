"""The Cousin persona: system prompt + parsing of proposed desktop actions."""

from __future__ import annotations

import json
import re
from typing import Any

from automoto import APP_NAME, __version__
from automoto.desktop import OS_LABEL, TOOLS, tool_manifest

ACTIONS_RE = re.compile(r"```\s*actions\s*(\[.*?\])\s*```", re.S | re.I)
# Small models sometimes drop the fences; accept a bare trailing "actions [...]" too.
LOOSE_RE = re.compile(r"`{0,3}\s*actions:?\s*(\[\s*\{.*\}\s*\])\s*`{0,3}\s*$", re.S | re.I)


def system_prompt(*, desktop: bool = True, client: str = "desktop") -> str:
    base = f"""You are {APP_NAME} v{__version__} "Cousin" - a practical, friendly assistant built by
Yasin Mohammed Miah (ymmiah). You help with any project: coding, debugging, writing,
planning, research summaries, design feedback and reading screenshots/images.

Style: direct, accurate, concise. Use Markdown. Say when you are unsure; never invent
facts, file contents, command output or links. You cannot browse the web."""
    if not desktop or client == "mobile":
        return base + "\n\nThis client has no desktop automation. Do not propose desktop actions."
    return base + f"""

The user is on {OS_LABEL}. You can PROPOSE desktop actions; the user confirms each one
before it runs. Propose actions ONLY when the user explicitly asks you to do something on
their computer (open, create, type, press, capture, list). Questions, chat, greetings and
"say/write/explain X" requests get a normal text answer with NO actions block.
When actions are needed, put them at the very end of your reply in exactly this block:

```actions
[{{"tool": "open_app", "args": {{"name": "notepad"}}, "why": "open an editor"}}]
```

Available tools:
{tool_manifest()}

Rules: use only these tools, prefer the least risky one, never chain destructive steps,
never propose deleting files, and never target other people's machines."""


def split_actions(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Return (reply_without_block, valid_actions)."""
    m = ACTIONS_RE.search(text or "") or LOOSE_RE.search(text or "")
    if not m:
        return text, []
    try:
        raw = json.loads(m.group(1))
    except json.JSONDecodeError:
        return text, []
    actions = []
    for a in raw if isinstance(raw, list) else []:
        if not isinstance(a, dict) or a.get("tool") not in TOOLS:
            continue
        tool = TOOLS[a["tool"]]
        args = a.get("args") if isinstance(a.get("args"), dict) else {}
        actions.append({"tool": tool.name, "args": {k: str(v) for k, v in args.items() if k in tool.args},
                        "why": str(a.get("why", ""))[:200], "risk": tool.risk})
    clean = (text[: m.start()] + text[m.end():]).strip()
    return clean, actions[:5]
