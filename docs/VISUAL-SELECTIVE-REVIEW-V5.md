# Visual Studio v5 — selective layout repair review

**Status:** source branch `feature/visual-studio-selective-review-v5`. This is not a Microsoft Store publication.

## What v5 adds

- **Before-and-after inspection:** the server renders the unmodified source canvas as a "Before" image when it can be safely rendered. It does not claim the source passed its quality checks. The "After" preview is the selected set of repairs, rendered by the same server renderer as export.
- **Individual choices:** each proposed field change has its own checkbox, with Select all and Clear selection. Coordinates, text size, and text colour can be accepted independently.
- **Preview and approval gate:** every selection recomposes a fresh candidate from the *original* immutable canvas snapshot. The ordinary authenticated `POST /api/visual/studio/preview` endpoint enforces the same quality checks as the editor. A failed/unfinished preview disables Apply; no repair is committed until explicit approval.
- **Stale-review protection:** edits to the canvas invalidate the pending proposal. Responses from older preview requests cannot make newer selections applicable.
- **Reversible edits:** accepting a verified selection records a single Undo step. Source imagery and logos, exact wording, hidden/locked/grouped flags and GIF settings are never rewritten by the repair engine.
- **Advisory design notes:** deterministic hints for margins, very small type and missing image alternative text. They are suggestions, **not AI-generated aesthetic judgements or automatic modifications**.

The existing v4 repair engine still only proposes conservative field changes to editable, ungrouped canvas objects. It does not change locked items or recognise the original semantic objects of a flattened AI-generated image.

## User workflow

1. Open a design in Visual Studio and choose **Inspect & repair**.
2. Compare the original preview with the proposed result. Inspect the descriptive field changes and any advisory notes.
3. Tick or untick individual adjustments. Every change to the selection is validated by the real server renderer; a subset with unresolved visual quality problems cannot be applied.
4. Choose **Apply selected repair** only when the new preview passes, or **Keep original** to dismiss. Undo remains available for accepted changes.
5. Save or export separately. Inspection does not automatically save/export or publish artwork.

If the original canvas cannot be rendered (for example, because its text cannot fit), the app reports the inspection without inventing a before-image. Server structural checks remain authoritative; visual judgement still requires human review.

## Security and quality boundaries

Only the already authenticated Visual Studio endpoints are used. Inputs, workspace media, rate limits and hosted-account protections remain enforced server-side. Changes are reconstructed only for `x`, `y`, `font_size` and `colour`, and are validated on preview. No asset overwrites or remote image uploads are part of v5.

## Validation

- `python -m pytest -q tests/test_visual_repair.py tests/test_visual_studio.py tests/test_visual_foundation.py tests/test_image_output_choices.py`
- `cd apps/desktop && npm run test:ui` (Playwright/Chromium installed)
- Review the generated browser screenshot `visual-studio-v5-selective-before-after.png`, inspect source hashes and check Windows packaging in CI.

**Still future work:** full model-based creative critique, multi-page editing, automatic semantic layer separation, advanced animation keyframes and polished selective photo retouching. None is implied by the v5 label.
