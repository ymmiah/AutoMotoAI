# Visual Studio v7 — advanced layer controls (internal development)

**Status:** feature branch only. Microsoft Store publication remains on hold until the wider AutoMoto roadmap is complete.

## Implemented in v7

Visual Studio now supports **multiple selected layer units**. Use Shift/Ctrl/Cmd-click in the layer panel or on the actual canvas to add or remove a selection. Use **Select unlocked** to collect all visible, unlocked non-connector units, and **Clear selection** to reset. A grouped card is always a single selectable unit even though its underlying text, icons and shape remain independently editable when ungrouped.

- **Batch movement:** drag multiple selected units together while keeping their relative positions. Arrow keys nudge one canvas unit (Shift+arrow is 10 units). A selection containing locked or hidden content cannot be transformed.
- **Snapping:** a user-controlled *Snap on drag* toggle (enabled by default) aligns nearby edges/centres to the canvas, other visible layers or an 8-unit grid within a 7-unit threshold. The snap is geometry-only and never edits original image pixels.
- **Align:** left, centre, right, top, middle and bottom, using the backmost selected layer unit as the anchor. If any layer would fall outside the artboard, the operation refuses the entire change.
- **Distribute:** even horizontal or vertical gaps between three or more selected units. It preserves the first and last extents and refuses negative spacing or out-of-bounds changes. Actual server quality checks still apply after editing.
- **Group / Ungroup:** combine two or more **previously independent** unlocked, visible layers into a new named logical unit. Existing groups cannot be nested or silently flattened. Grouping keeps the existing renderer z-order. Ungroup is blocked when a workflow connector references that group to prevent broken links.
- **Undo / Redo:** all successful changes use the editor's normal tracked history, including changing layer membership.

The actual renderer and export paths are unchanged. Original user image files, path references, artwork pixels, exact text and protected lock/visibility flags remain unchanged unless explicitly edited by the user through the existing inspector.

## Scope and limitations

This sprint introduces **one-level group operations**, not fully nested group hierarchies. Rotations, constraints, complex keyframe animations and multi-page canvas editing are future milestones. Selecting multiple layers disables the individual property inspector, delete, duplicate and resize handles to avoid ambiguous or destructive operations. Single-layer editing and existing workflow group resizing remain available.

The snapping toggle affects pointer drag, not keyboard nudging. The preview and export still report or block structurally invalid results (e.g. accidental text overlaps). Snap targets are calculated geometrically; guide-line overlays and advanced constraint solving are outside the current increment.

## QA

- `cd apps/desktop && node test/visual-layer-geometry.cjs`: no server required; tests whole-group moves, locking, atomic alignment, even distribution, snapping, safe grouping, workflow connector protection and original image references.
- `cd apps/desktop && npm run test:ui`: runs the geometry tests first, then the normal desktop UI smoke suite, including multi-select, align/distribute, group/ungroup and Undo/Redo.
- Full Python and Windows app CI remain required before merge, as does manual inspection of the generated `visual-studio-v7-group-align.png` screenshot.

**No release tag, installer publication or Microsoft Store submission is part of this task.**
