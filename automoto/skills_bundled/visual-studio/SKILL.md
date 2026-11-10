---
name: visual-studio
description: Make a brand-coloured design, a layout-repair proposal, a promo GIF, or a multi-page deck in Visual Studio.
category: design
tools: visual_export, visual_repair, visual_brand_save, visual_pages_export, visual_ai_review
status: live
---
# Visual Studio

Build the file they asked for. A single infographic can still use `visual_create`. Use these tools when they want the studio: a GIF, a brand kit, a repair, or several pages.

1. A promo GIF is `visual_export` with `format` `gif` and an `animation` such as `{"effect":"flow","frames":12,"duration_ms":100,"loop":0}`.
2. Several slides are `visual_pages_export` with one canvas spec per page and `format` `pptx`.
3. Brand colours can be saved with `visual_brand_save` (background, ink, muted, accent, card, border, tone0, tone1, tone2). Saving a kit does not paint the canvas; pass the colours in the spec too.
4. `visual_repair` proposes fixes and does not apply them. Show the summary. Do not export `proposed_spec` unless the user agrees.
5. `visual_ai_review` is local-only and does not edit the design.
6. Name the GIF, deck or brand file.
