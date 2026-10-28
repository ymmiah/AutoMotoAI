---
name: autocad
description: Automate AutoCAD with .scr scripts through the official accoreconsole (Windows) - batch plot, purge, convert drawings.
category: cad
tools: write_file, run_app_script, open_in_app
apps: autocad
status: untested
---
# AutoCAD

Windows only: `accoreconsole.exe /i drawing.dwg /s script.scr` (AutoCAD's official core console, no GUI).
macOS AutoCAD has no core console - AutoMoto can only open drawings there. Untested by AutoMoto's authors.

1. `write_file` `cad/cleanup.scr` (one command per line; blank line = Enter):
   ```
   -PURGE
   A
   *
   N
   AUDIT
   Y
   QSAVE
   ```
2. `run_app_script` `autocad` `cad/cleanup.scr` with `target` = `cad/plan.dwg` (approval).
3. PDF plot: use `-EXPORT` / `-PLOT` command sequences for your page setup; test on a copy first.
4. Open for manual work: `open_in_app` `autocad` `cad/plan.dwg`.
