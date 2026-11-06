# Visual Studio v3 — inspect, recommend and approve layout repairs

Development branch: `feature/visual-studio-audit-repair-v3`, stacked on Visual Studio v2. Not included in the published Microsoft Store app.

## Why this exists

AutoMoto's visual engine already rejects unreadable and overlapping content, but users could receive a hard error without a useful path to correct it. Visual Repair provides **read-only diagnostics** and **specific, reversible suggested edits**. It is not an unverified claim of fully autonomous aesthetic judgement.

## In Visual Studio

1. Open an image, diagram or saved layered design.
2. Select **Inspect design** to receive a structured list of problems without changing the canvas.
3. Select **Suggest safe fixes** to see individual proposals: which element and field would change, its old value, its new value and the reason.
4. Select **Apply fixes (undoable)** only if you accept the changes. Review the actual refreshed preview.
5. Use Undo to reverse the repair. Save or export only after reviewing the result.

The interface explicitly distinguishes proposed changes from applied changes. No repair writes a file until the user separately chooses Save or Export.

## Deterministic repair policies

| Issue | Repair | Boundary |
|---|---|---|
| Text does not fit its box | Reduce the same text object's font size, no lower than 12 px | Do not rewrite, paraphrase or truncate exact user wording |
| Poor contrast | Select a legible neutral light or dark text colour based on the colour behind it | Never recolour photographs or brand logos; preserve locked layers |
| Independent text/icon overlap | Move eligible ungrouped text/icons to available canvas space | Never reshape or generatively reconstruct protected photos, images, grouped diagrams or logos |
| An object partly outside the artboard | Move eligible object back inside its original canvas | Preserve dimensions; never crop, resize or stretch protected image pixels |
| Unsupported layout, font shaping, insufficient free space | Report remaining issue | Never claim a problem was fixed if no safe change was available |

Changes are limited to up to 70 recorded field adjustments per request and existing maximum canvas elements. The result includes both before/after quality reports and an explicit list of unresolved problems.

## New API

- `POST /api/visual/studio/inspect` — read-only `{name, spec}` → `{passed, issue_count, issues, repairable}`.
- `POST /api/visual/studio/repair` — read-only proposal `{name, spec}` → `{spec, changes, changed, before, after, message}`.

Both endpoints use the signed-in user's existing authentication, CSRF checks, workspace-only image paths, bounded request specification and expensive-route throttling. Neither action saves or overwrites user files.

## Quality limitations

A machine-readable geometry and contrast check cannot reliably judge all aspects of editorial design, culturally correct typography or user intent. Grouped objects, explicitly permitted overlaps and locked layers remain untouched. Complex-script/font-support warnings, non-editable generated raster content and ambiguous layouts require manual review. Do not call a design production-ready solely because the structural inspector reports zero issues.

## Tests and acceptance

Tests in `tests/test_visual_repair.py` confirm: contrast correction, exact-copy text fitting, independent collision resolution, lock and original-photo fidelity, out-of-bounds movement, no fabricated repairs and authenticated no-side-effect endpoints. Browser smoke tests create a low-contrast element, inspect it, preview proposals, explicitly accept a fix and verify the updated output.

Run `pytest -q tests/test_visual_repair.py tests/test_visual_studio.py tests/test_image_output_choices.py tests/test_visual_foundation.py`. CI executes browser smoke tests separately.

**Release boundary:** This is one incremental repair workflow, not a full vision-language model design critic, automated multi-slide redesign, or background worker. Release requires tested, reviewed, signed app packaging and separate Microsoft Store submission.
