---
name: project-scaffold
description: Create a small new project (Python, web or Node) in the workspace with README and tests.
---
# Project scaffold

1. Confirm the language and name from the request; default to Python if unclear.
2. Create files with `write_file` under `<name>/` in the workspace:
   - `README.md` (what it is, how to run, how to test)
   - source file(s) with a minimal working entry point
   - one test file
   - `.gitignore`
3. Run the tests with `run_shell` (needs approval) and fix failures.
4. Finish with the file tree and the exact commands to run it.
