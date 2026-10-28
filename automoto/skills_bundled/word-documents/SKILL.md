---
name: word-documents
description: Write Word (.docx) reports, essays, dissertations and letters to publication standard - title page, contents, real heading styles, tables, figures with captions, page numbers and Harvard references.
category: office
tools: office_create_docx, office_edit, office_read, office_convert, office_check, office_render
optional_apps: libreoffice
status: live
---
# Word documents

**Plan before you build**
1. Confirm the purpose, audience, length (words/pages), format rules (A4, font, spacing, referencing style)
   and deadline. For coursework, ask for or read the brief and marking criteria (office_read).
2. Outline: title page → contents → introduction → body sections (one idea each) → conclusion →
   references → appendices. Heading levels must not skip (1 → 2 → 3).

**Build with `office_create_docx`** (write to `scratch/` for drafts, the final path when ready)
- `properties.title` and `author` are always set (they become the PDF title and help accessibility).
- Title page block for academic work: title, subtitle, author, student_id, course, module,
  institution, supervisor, date, word_count. Add `{type:"toc"}` after it - page numbers are filled in
  automatically when LibreOffice is installed.
- Paragraphs: 1 idea each, 3-6 sentences. Inline `**bold**` sparingly, `*italic*` for titles/terms.
- Tables: `caption` ("Table n:" is added), first row is the header (repeats across pages), `source`.
- Images: PNG/JPEG only; always `alt` text and a `caption`; width ≤ 15 cm on A4.
- References (Harvard, Cite Them Right): give structured items (authors as "Surname, I.", year, title,
  journal/volume/issue/pages or publisher/place, url + accessed date for web). In the text cite as
  (Surname, Year) or Surname (Year); every citation must be in the list and vice versa.
  Never invent sources - search (web_search/fetch_url, or Zotero via service_api) and cite real ones.
- Default theme: Calibri 11 pt, 1.15 spacing, navy headings. Use `theme.justify` only if asked.

**Check before you hand it over**
1. `office_check` - fix every error and warning (heading jumps, missing alt text, TOC placeholders).
2. `office_convert to=pdf`, then `office_render` (or `office_review`) and look at the pages: no orphan
   headings at the bottom of a page, tables/figures not split awkwardly, page numbers present.
3. Report the word count, page count and where the .docx and .pdf are.

**Edits**: `office_edit` with `replace:[{old,new}]` keeps formatting; `append:[blocks]` adds sections.
Footnotes, tracked changes and complex fields are not supported by the builder - say so if asked.
