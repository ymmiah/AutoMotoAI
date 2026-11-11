"""Fail if the vendored iPhone toolchain still names hosts it must not contact.

The MIT notice file is the only place those names are allowed. Everything else
under ``third_party/ios-toolchain`` is scanned as text.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FORBIDDEN = re.compile(r"xtool-org|sidestore|jkcoxson", re.IGNORECASE)
ALLOW_NAMES = {"NOTICE"}
ROOT = Path(__file__).resolve().parents[1] / "third_party" / "ios-toolchain"


def hits(root: Path | None = None) -> list[str]:
    """Return ``path:line: text`` for every forbidden host outside the notice."""
    base = root or ROOT
    found: list[str] = []
    if not base.is_dir():
        return [f"{base}: missing toolchain tree"]
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.name in ALLOW_NAMES:
            continue
        data = path.read_bytes()
        # latin-1 keeps every byte, so a host hidden in a fixture still matches.
        text = data.decode("latin-1").replace("\r\n", "\n")
        for number, line in enumerate(text.split("\n"), 1):
            if FORBIDDEN.search(line):
                snippet = line.strip()
                if len(snippet) > 180:
                    snippet = snippet[:180] + "…"
                found.append(f"{path.relative_to(base)}:{number}: {snippet}")
    return found


def main() -> int:
    found = hits()
    if found:
        print("\n".join(found))
        return 1
    print(f"no forbidden hosts under {ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
