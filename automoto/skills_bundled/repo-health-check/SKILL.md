---
name: repo-health-check
description: Check a code project in the workspace - layout, tests, obvious bugs - and report.
---
# Repo health check

1. `list_dir` the project root, then the main source folder.
2. `read_file` the README, the dependency file (requirements.txt / package.json / pyproject.toml) and the CI config if present.
3. If the user approves, `run_shell` the test command (e.g. `python -m pytest -q` or `npm test`). Report pass/fail counts honestly.
4. Report in this order: what the project is, how to run it, test result, top 3 risks or bugs with file names, quick wins.
5. Do not change files unless the user asked for fixes.
