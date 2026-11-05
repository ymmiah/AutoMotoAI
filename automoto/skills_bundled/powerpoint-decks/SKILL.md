---
name: powerpoint-decks
description: Create PowerPoint (.pptx) presentations with a clear storyline, one idea per slide, a consistent theme, charts/tables/images and speaker notes - then export and review as PDF.
category: office
tools: office_create_pptx, office_edit, read_file, office_convert, office_check, office_review
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
- Prefer **native editorial layouts** over bullet dumps. Use `cards` (1-6 cards, each title/text/icon),
  `metrics` (1-4 facts), `steps` (2-5 stage names), `image_text`/`hero` (existing real
  image + exact copy), and `canvas` (per-element `type,x,y,w,h` in inches for exact placement).
  Also available: `title`, `section`, `bullets`, `two_content`, `comparison`,
  `image`, `table`, `chart`, `statement`, `quote`.
- **Icons:** add `icon:'shield'` or `'idea'`, `'chart'`, `'users'`, `'clock'`, `'target'`,
  `'cloud'`, `'file'`, `'image'`, `'sparkle'`, `'globe'`, `'check'`, etc. They're
  editable PowerPoint vector shapes; no icon-font or network dependency.
- Theme: readable `primary`, `accent`, `background`, `text`, `heading`, font and
  heading font. On dark backgrounds, use contrasting pale headings and body text.
- Visual variety: establish an art direction, avoid identical layouts in sequence, show
  genuine evidence/diagrams instead of tables when unnecessary, and use ample negative space.
  No invented figures: metrics/charts need supplied or verifiable data.
- `notes` on every content slide: what to say (2-5 sentences), the source of any figure, timings.

**Check**
1. `office_check` - fix overflow warnings (split the slide or shorten), empty placeholders, small fonts,
   missing alt text, missing notes.
2. `office_convert to=pdf` then `office_review` and look at every slide: nothing cut
   off, text readable at a distance, charts labelled, consistent alignment.
3. Report slide count, the storyline in one line per slide, and the .pptx/.pdf paths.
