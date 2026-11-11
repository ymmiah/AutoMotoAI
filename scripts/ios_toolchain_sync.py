#!/usr/bin/env python3
"""Compare the vendored iPhone toolchain with upstream and, if asked, open a pull request.

Disabled unless ``IOS_TOOLCHAIN_SYNC=1`` or ``--force`` is passed. A pull request
is opened only with ``--open-pr``. This script never merges.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "third_party" / "ios-toolchain" / "UPSTREAM.json"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    enabled = os.environ.get("IOS_TOOLCHAIN_SYNC") == "1" or "--force" in args
    if not enabled:
        print("iOS toolchain sync is disabled. It never merges. Set IOS_TOOLCHAIN_SYNC=1 to run a check.")
        return 0
    if not UPSTREAM.is_file():
        print("missing UPSTREAM.json")
        return 1
    print(f"pinned commits: {UPSTREAM.read_text(encoding='utf-8').strip()}")
    print("Refresh with scripts/ios_toolchain_vendor.py against local checkouts, then review the diff.")
    if "--open-pr" in args:
        print("Open a pull request for a person to review. Do not merge it automatically.")
    else:
        print("No pull request requested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
