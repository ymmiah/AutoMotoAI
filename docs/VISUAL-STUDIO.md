# AutoMoto Visual Studio — Editor v1

**Status:** the editor v1 source was merged into `main` via [PR #13](https://github.com/ymmiah/AutoMotoAI/pull/13). The next layers and animation timeline build is on `feature/visual-studio-layers-timeline-v2`. These source changes are **not** proof that Microsoft Store has been updated.

## Open it

Run AutoMoto with the source from this branch, open the local web interface or connected account, then select **Visual Studio** from the left sidebar (`#/visual`).

Visual Studio uses the **same validated design renderer** as AutoMoto's agent. Its preview is a real raster rendering of the current specification, rather than a separate approximation drawn by the browser. It does not require a design subscription or remote asset CDN.

## Build a graphic

1. Pick a starting template: **Workflow**, **Feature cards**, **Poster** or **Blank canvas**.
2. Select a design theme: **Illustrated**, **Editorial light**, **Premium tech** or **Commercial**.
3. Edit the title/subtitle. Click an object or choose it in **Object inspector**.
4. Change text, size, coordinates, colours, icons, or other supported properties. Drag objects with mouse or touch; starter workflow groups move together and matching connectors are recalculated.
5. Add new Text, Shape or Icon objects. For user photographs and logos, upload the original file in **Files** first, then choose the uploaded image and click **Place image**.
6. Use Undo/Redo or **Save draft**. You can reopen previously saved drafts.
7. Select PNG, SVG, JPG, PDF, editable PowerPoint or **Animated GIF**, then click Export.

For animated GIFs you can select `flow`, `pulse`, `reveal` or `float`, frame count (8–48), delay (50–500 milliseconds) and loop mode. The GIF is genuinely animated with distinct frames; it is *not* a fake static image. Exports can be downloaded directly from the editor and browsed in **Files**.

The server produces:
- `artifacts/visual-studio/<name>-<id>.<format>` — final file
- `<name>-<id>.<format>.visual.json` — output hash, source image hashes and quality/provenance data
- `<name>-<id>.design.json` — editable source design specification

The renderer preserves the original photo/logo files, keeps exact text as text objects, and refuses invalid/unreadable compositions rather than silently clipping them. Editable PowerPoint text/shapes and SVG are available. GIF is a separately generated animated image, not a native animated PowerPoint object.

## Trust, privacy and security

- API endpoints authenticate using the existing AutoMoto local session / hosted account mechanism and its CSRF checks.
- References to images must point to files **inside the authenticated user's workspace**, never arbitrary host files or external URLs. The editor does not execute SVG supplied by users.
- Uploaded image contents are validated by the existing asset pipeline. Export and preview enforce bounded canvas dimensions, input sizes and rate limits.
- Drafts, exports and manifests use random unique filenames; existing files are never overwritten. Hosted users remain isolated in their own workspace and are subject to storage quotas.
- The interface does not send photographs to a cloud image generator. **Preservation means deterministic original-image placement**, not a claim of exact identity preservation under an AI generative edit.
- Saved drafts are user-controlled files. No external SaaS account or proprietary editor is necessary.

## Quality and validation

The source includes:
- `tests/test_visual_studio.py`: authenticated API coverage, actual preview decoding, original-image hashes, in-workspace draft save/reload, path-isolation tests, real multi-frame GIF, editable PowerPoint, bad-spec rejection.
- `apps/desktop/test/ui-smoke.cjs`: browser navigation, preview, selected-element edits, draft save and GIF export.
- The existing visual-foundation tests validate the shared renderer and GIF animation.

Before release, run `python -m pytest -q tests/test_visual_studio.py tests/test_visual_foundation.py tests/test_visual_design.py`; then run the desktop UI smoke suite (`npm run test:ui` from `apps/desktop`) with Chromium/Playwright installed.

## Limits of v1

This increment is a functional editor for common graphics and workflows, **not a full Figma/Canva replacement**. It does not yet include full design-object hierarchy and z-order controls, production keyframe timeline editing, arbitrary path animation, multi-slide editor UX, direct pixel-level AI retouching, or fully automatic aesthetic critique and self-repair. The existing agent can still generate multi-slide PowerPoints through `visual_create`; the editor itself currently opens one canvas at a time.

Production readiness depends on passing the full CI matrix, reviewing browser screenshots, and publishing a new signed Windows package. Merging the source branch alone is **not** Microsoft Store publication.
