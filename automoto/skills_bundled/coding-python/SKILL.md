---
name: coding-python
description: Write, run and test Python - project layout, venv, typing, pytest, packaging and common pitfalls.
category: coding
tools: write_file, edit_file, run_shell
apps: python
status: live
---
# Python

- Layout: `pyproject.toml`, `src/<pkg>/` or `<pkg>/`, `tests/test_*.py`, `README.md`, `.gitignore`.
- Environment: `python -m venv .venv` then `.venv/bin/pip install -e .[dev]` (Windows: `.venv\Scripts\pip`).
- Style: type hints, `pathlib`, f-strings, dataclasses, `encoding="utf-8"` on every open, no bare `except`.
- Tests: `python -m pytest -q`; use `tmp_path`, `monkeypatch`, `pytest.mark.parametrize`; test the edge cases.
- Lint: `python -m pyflakes .` or `ruff check .` if available; format with `black`/`ruff format` only if the project does.
- Debug: run with `python -X dev`, add `breakpoint()` only locally; read tracebacks bottom-up.
- Pitfalls: mutable default args, late binding in lambdas, float money (use `Decimal`), naive datetimes,
  circular imports, `is` vs `==`, modifying a list while iterating.
- Packaging: `python -m build`; CLIs via `[project.scripts]`; executables with PyInstaller (see `cross-platform-apps`).
