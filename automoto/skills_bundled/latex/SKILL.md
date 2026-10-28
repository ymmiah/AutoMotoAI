---
name: latex
description: Write and build LaTeX documents (reports, CVs, papers, maths) to PDF with Tectonic or pdflatex.
category: documents
tools: write_file, edit_file, run_app
apps: tectonic|pdflatex|latexmk
status: live
---
# LaTeX

1. `write_file` `doc/main.tex`: `\documentclass[11pt,a4paper]{article}`, `\usepackage[margin=2.5cm]{geometry}`,
   `\usepackage{amsmath,graphicx,hyperref}`, `\usepackage[utf8]{inputenc}` (pdflatex only), sections, `\label`/`\ref`.
2. Bibliography: `refs.bib` + `\usepackage[backend=biber]{biblatex}` / `\addbibresource{refs.bib}` / `\printbibliography`
   (Tectonic runs biber automatically), or classic `\bibliographystyle{plain}` + `\bibliography{refs}`.
3. Build (pick what `list_apps` shows as installed):
   - Tectonic: `run_app` `tectonic` `["doc/main.tex"]` (downloads packages the first time; needs internet).
   - pdflatex: `run_app` `pdflatex` `["-interaction=nonstopmode", "-output-directory", "doc", "doc/main.tex"]` twice.
   - latexmk: `run_app` `latexmk` `["-pdf", "-interaction=nonstopmode", "doc/main.tex"]`.
4. Fix errors from the log: the first `! ...` line and `l.<n>` tell you the line. Common: missing `}` or `$`,
   undefined control sequence (missing package), `&` outside tables, unescaped `% _ # &`.
5. Shell escape (`-shell-escape`, `\write18`) is refused - it would let a document run commands.
6. Report the PDF path and page count (`run_app` `imagemagick` `["identify", "doc/main.pdf"]` if available).
