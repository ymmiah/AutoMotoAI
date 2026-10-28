---
name: powerpoint-decks
description: Create PowerPoint (.pptx) presentations with a clear storyline, one idea per slide, a consistent theme, charts/tables/images and speaker notes - then export and review as PDF.
category: office
tools: office_create_pptx, office_edit, office_read, office_convert, office_check, office_render, office_review
optional_apps: libreoffice
status: live
---
# PowerPoint decks

**Storyline first**
1. Audience, goal (inform / persuade / decide), time slot (≈1 slide per minute), and the one sentence
   they should remember.
2. Structure: title → agenda or the key message → 1 section per point (situation → insight → evidence
   → implication) → recommendation / next steps → questions/thank you.
3. Write slide titles as *headlines* that state the takeaway ("Sales grew 18% after the redesign"),
   not topics ("Sales").

**Build with `office_create_pptx`**
- One idea per slide; 3-6 bullets, ≤ 12 words each; sub-points only when needed.
- Layouts: `title`, `section` (dividers), `bullets`, `two_content`/`comparison` (before vs after,
  options), `image` (with alt + caption), `table` (≤ 7 rows), `chart` (column/bar/line/pie/stacked
  with real numbers), `statement`/`quote` (big message).
- Theme: one `primary`, one `accent` colour, one font for the whole deck; slide numbers on.
- `notes` on every content slide: what to say (2-5 sentences), the source of any figure, timings.

**Check**
1. `office_check` - fix overflow warnings (split the slide or shorten), empty placeholders, small fonts,
   missing alt text, missing notes.
2. `office_convert to=pdf` then `office_render`/`office_review` and look at every slide: nothing cut
   off, text readable at a distance, charts labelled, consistent alignment.
3. Report slide count, the storyline in one line per slide, and the .pptx/.pdf paths.
