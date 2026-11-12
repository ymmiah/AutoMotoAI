#!/usr/bin/env python3
"""Decide whether a CI event should run heavy macOS / real-toolchain jobs.

Non-pull_request events (push to main, schedule, workflow_dispatch) always
qualify. A pull request qualifies only when it touches one of the
version-specific path patterns. Shared files such as automoto/server.py or
developer-studio.js are deliberately excluded from those patterns so that a
new Developer Studio version does not re-queue every older version's macOS
jobs. Ubuntu jobs still run because the workflow-level path filters include
the shared files.

If the pull-request file list cannot be retrieved, this script reports
self=true so coverage is not silently dropped.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Iterable, List, Optional, Sequence


def path_matches(path: str, pattern: str) -> bool:
    path = path.replace("\\", "/").lstrip("./")
    pattern = pattern.strip().strip("\"'").replace("\\", "/")
    if not pattern or pattern.startswith("#"):
        return False
    if path == pattern:
        return True
    regex = "^" + re.escape(pattern)
    regex = regex.replace(r"\*\*/", "(?:.*/)?")
    regex = regex.replace(r"\*\*", ".*")
    regex = regex.replace(r"\*", "[^/]*")
    regex = regex.replace(r"\?", ".")
    regex += "$"
    return re.search(regex, path) is not None


def any_path_matches(files: Iterable[str], patterns: Sequence[str]) -> bool:
    cleaned = [p.strip() for p in patterns if p.strip() and not p.strip().startswith("#")]
    for path in files:
        for pattern in cleaned:
            if path_matches(path, pattern):
                return True
    return False


def load_patterns(text: str) -> List[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


def fetch_pr_files(repo: str, number: int, token: str) -> List[str]:
    files: List[str] = []
    url: Optional[str] = (
        f"https://api.github.com/repos/{repo}/pulls/{number}/files?per_page=100"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "automoto-ci-pr-self-changed",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    while url:
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
                files.extend(item.get("filename", "") for item in payload if item.get("filename"))
                link = response.headers.get("Link", "")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"could not list pull request files: {exc}") from exc
        url = None
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.split(";", 1)[0].strip().strip("<>")
                break
    return files


def decide(
    event: str,
    files: Optional[Sequence[str]],
    patterns: Sequence[str],
    *,
    repo: str = "",
    pr: Optional[int] = None,
    token: str = "",
) -> bool:
    event = (event or "").strip()
    if event != "pull_request":
        return True
    if files is None:
        if not repo or not pr:
            raise RuntimeError("pull_request event needs --files, or --repo and --pr")
        files = fetch_pr_files(repo, pr, token)
    return any_path_matches(files, patterns)


def write_output(path: str, value: bool) -> None:
    line = f"self={'true' if value else 'false'}\n"
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
    sys.stdout.write(line)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--pr", default="", help="Pull request number")
    parser.add_argument("--patterns", default="", help="Newline or comma separated patterns")
    parser.add_argument("--patterns-file", default="")
    parser.add_argument("--files", default="", help="Comma-separated file list (tests / offline)")
    parser.add_argument("--files-file", default="")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    args = parser.parse_args(argv)

    if args.patterns_file:
        with open(args.patterns_file, encoding="utf-8") as handle:
            patterns = load_patterns(handle.read())
    else:
        patterns = load_patterns(args.patterns.replace(",", "\n"))

    files: Optional[List[str]]
    if args.files_file:
        with open(args.files_file, encoding="utf-8") as handle:
            files = [line.strip() for line in handle if line.strip()]
    elif args.files:
        files = [part.strip() for part in args.files.split(",") if part.strip()]
    else:
        files = None

    pr_number: Optional[int] = None
    if str(args.pr).strip():
        pr_number = int(args.pr)

    try:
        value = decide(
            args.event,
            files,
            patterns,
            repo=args.repo,
            pr=pr_number,
            token=args.token,
        )
    except Exception as exc:  # noqa: BLE001 — fail closed toward running macOS
        sys.stderr.write(f"pr_self_changed: {exc}; defaulting to self=true so coverage is kept\n")
        value = True
    write_output(args.github_output, value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
