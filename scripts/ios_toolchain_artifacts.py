#!/usr/bin/env python3
"""Check the iPhone support-file lock. Does not download or publish anything."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automoto.ios_toolchain_scan import ROOT, hits  # noqa: E402


def main() -> int:
    found = hits()
    if found:
        print("\n".join(found))
        return 1
    lock = json.loads((ROOT / "Artifacts.json").read_text(encoding="utf-8"))
    if "github.com/ymmiah/AutoMotoAI" not in lock.get("base_url", ""):
        print("support files must use this project's releases")
        return 1
    waiting = [key for key, entry in lock.get("artifacts", {}).items()
               if key.startswith(("darwin-tools", "open-apple-macros")) and not entry.get("sha256")]
    if waiting:
        print("unpublished: " + ", ".join(waiting))
    print("This command does not build or upload those files and does not create a release.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
