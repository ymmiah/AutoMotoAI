---
name: bug-fixing
description: Fix a bug - reproduce it, read the traceback, find the cause, make the smallest fix, add a test, verify.
category: coding
tools: read_file, search_files, edit_file, run_shell
status: live
---
# Bug fixing

1. **Reproduce.** Get the exact command, input and error. Run it (`run_shell`, needs approval) and keep the output.
2. **Read the error bottom-up.** The last frame in *your* code is usually the culprit; note file and line.
3. **Locate.** `search_files` for the function/message, `read_file` the surrounding code (±40 lines) and its callers.
4. **Explain the cause in one sentence** before changing anything (wrong type, off-by-one, None, race, wrong path, stale cache…).
5. **Write a failing test first** when the project has tests (pytest / npm test / go test).
6. **Smallest fix** with `edit_file` (exact old → new). Don't refactor unrelated code. Keep style.
7. **Verify:** run the failing test, then the whole suite. If something else breaks, revert your change and rethink.
8. **Report:** cause, fix (file:line), test added, commands run and their results. Mention anything you could not verify.

Common causes: mutable default args (Python), `==` vs `===` (JS), async not awaited, timezone-naive dates,
paths with backslashes on Windows, integer division, missing `encoding="utf-8"`, unhandled empty input.
