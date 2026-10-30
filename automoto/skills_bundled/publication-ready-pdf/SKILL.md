---
name: publication-ready-pdf
description: Export Word/Excel/PowerPoint/Markdown to a publication-ready PDF - tagged for accessibility, fonts embedded, bookmarks, metadata - and verify it page by page.
category: office
tools: office_convert, office_check, office_review, read_file
apps: libreoffice
status: live
---
# Publication-ready PDF

1. **Source first**: run `office_check` on the .docx/.pptx/.xlsx and fix errors (heading hierarchy
   drives PDF bookmarks and the tag tree; alt text becomes the PDF alt text; the document title becomes
   the PDF title). Recalculate spreadsheets with `office_recalc`.
2. **Export**: `office_convert path=… to=pdf`. AutoMoto uses LibreOffice headless with macros disabled
   and exports a *tagged* PDF with bookmarks, embedded fonts and 300 dpi images.
3. **Verify**: `office_check` on the PDF:
   - every font embedded (journals, printers and print-on-demand reject PDFs that aren't),
   - `Tagged: yes` (screen readers; required by many universities and public bodies),
   - a Title in the metadata, bookmarks for long documents, extractable text.
4. **Look at it**: `office_review ai=false` (renders the first pages, any page with a table/figure) or `office_review` for a
   vision critique. Fix layout issues in the source and export again.
5. For strict PDF/A archiving or print-shop CMYK/bleed requirements, say that AutoMoto produces a
   tagged PDF 1.7; PDF/A validation (e.g. veraPDF) and CMYK conversion are separate free tools.
6. Report page count, tagged/fonts status and the path.
