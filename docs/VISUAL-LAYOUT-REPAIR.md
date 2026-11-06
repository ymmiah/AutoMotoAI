# Visual Studio layout inspection and repair (v4)

**Development status:** implemented on a separate branch, awaiting independent CI and browser validation; not an announced Microsoft Store release.

## What this increment changes

Visual Studio now has an **Inspect & repair** command. It examines the actual editable design specification, prepares a list of narrowly scoped improvements, and—when the result passes the rendering quality gates—provides a preview of the proposed revision. It does not save, mutate, publish or replace the original design merely because the user clicked Inspect.

Supported targeted adjustments:

- **Independent text/icon collision:** reposition an ungrouped, unlocked element to the nearest available location on the same artboard.
- **Bounds:** move a freely editable, ungrouped object fully inside the existing artboard (without resizing the source picture).
- **Text overflow:** reduce font size within a conservative limit; never alter, drop or paraphrase the original wording.
- **Readability:** improve insufficient text contrast using known dark/light text colours.
- **Explicit opt-in:** display a per-field change list and a fresh rendered proposed preview. Press **Apply selected repair** to accept, or **Keep original** to discard. Accepted changes are part of the existing undo history.

If any structural or rendering issue remains, the editor reports it and disables one-click application. It never claims that the design is automatically repaired when it fails existing quality checks.

## What must remain unchanged

Original raster content, uploaded photographs, faces, logos, image paths, asset hashes, layer grouping, layer locks, hidden-layer flags, the GIF timeline and exact user wording are preserved. Locked or grouped art is never silently repositioned: complex group decisions are left to the user. Intentionally allowed overlaps are respected.

The inspection endpoint is **\`POST /api/visual/studio/repair\`** and requires existing AutoMoto authentication, CSRF protections, rate limits and workspace validation. It returns an inspected proposal but writes no files. Other APIs remain unchanged. Scene export does not automatically invoke the layout repair engine.

## Important fix in the same release

The main-branch browser suite had identified a failure in the **Files → Edit layers → Visual Studio** path. Its JavaScript was using a single-element selection API and then attempting to iterate it, preventing the button handlers from being installed. The change to list-based selectors fixes all three file-action bindings (**View**, **Edit layers**, **Open layers**). The existing Playwright test now exercises reopening a generated GIF, followed by layout inspection and discard.

## Tests and release criteria

- \`python -m pytest -q tests/test_visual_repair.py tests/test_visual_studio.py tests/test_visual_foundation.py tests/test_image_output_choices.py\`
- Run \`npm run test:ui\` in \`apps/desktop\` with Playwright Chromium installed to validate import, preview, inspection and keeping original.
- Check actual render quality and source hashes; no automatic Store publication.

This is deterministic **structural** layout repair, not an autonomous graphic designer able to interpret all branding decisions, image semantics or artistic intent. Creative visual critique and full scene reflow remain subsequent milestones.
