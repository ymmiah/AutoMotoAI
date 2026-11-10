---
name: developer-studio
description: Read a project file, show a diff, and save a conflict-checked fix in Developer Studio.
category: code
tools: developer_open, developer_read, developer_search, developer_symbols, developer_diff, developer_save, developer_trust, developer_languages, developer_lsp, developer_run
status: live
---
# Developer Studio

This is for a project folder inside the workspace. It does not run the program unless `developer_run` is offered, and that tool is missing on a hosted server.

1. `developer_read` the file. Keep `sha256`, `encoding` and `newline`.
2. `developer_search` or `developer_symbols` to find the bug. Do not execute the source.
3. `developer_trust` the project before a diff or a save. Trust does not edit files.
4. `developer_diff` with the full new text and `expected_sha256`. It does not write. Show that diff.
5. `developer_save` only after the diff, with the same checksum. If the studio says the file changed, read it again and stop.
6. `developer_languages` and `developer_lsp` do not start compilers or language servers. `developer_run` runs only an adapter that is already registered and hash-pinned.
7. Say what changed and whether the file was written.
