# Visual Studio v6 — local vision-model design review

**Status:** source feature branch, not a published Microsoft Store update.

## What is new

Visual Studio now provides a separate **Local AI design review** button in addition to the deterministic **Inspect & repair** feature.

- The user's explicit click runs review using the locally selected **Ollama vision-capable model**, when that model is installed and Ollama is enabled.
- The canvas is rendered with the same actual visual renderer as export and downscaled to at most 960 × 720 before being sent to Ollama.
- Only an Ollama HTTP endpoint on loopback (127.0.0.1 / localhost / ::1) is accepted. The tool never downloads a model automatically, falls back to remote/cloud AI or writes to disk.
- The vision model is asked to inspect hierarchy, spacing, alignment, typography, colours and balance, then return bounded, structured notes and optional field suggestions.
- Source file paths, original text and alt labels are not sent as textual metadata. **The preview image itself contains whatever visible content the user chose to review**.
- Every model-suggested editable change is treated as untrusted. Strict filtering permits only limited `x`, `y`, `font_size` and `colour` adjustments on unlocked, ungrouped, non-image elements. Invalid indices, out-of-range geometry, overly large changes, malformed colours, duplicate edits and colour suggestions that would worsen measured contrast are discarded.
- Existing v5 per-field checkboxes, before/after previews, server quality validation and Undo remain mandatory. No design is ever changed simply because AI recommended it.
- Notes are advisory, subjective and may be inaccurate. The tool does **not** claim an objective aesthetic score or reconstruct flattened image layers.

## How to use it

1. Open **Settings > Offline AI**, install/start Ollama and download/select an **image-capable** model which advertises its `vision` capability. Ordinary text-only models cannot inspect screenshots.
2. Open Visual Studio and make sure the original design passes the structural preview checks; use **Inspect & repair** first if it does not.
3. Select **Local AI design review**. The editor shows observations, candidate field adjustments and the model name.
4. Accept only changes you want. Each selection is rendered again and cannot be applied until it passes the standard quality check.
5. Keep the original or approve the selected changes; undo is available. Save/export only when satisfied.

If Ollama is disabled, stopped, cannot be reached on loopback, the selected model is not downloaded or is not vision capable, the review returns an informative error and never pretends to have inspected the canvas. A CPU-only vision model may take significant time.

**Privacy:** models can see the rasterised artwork because the user specifically requests visual review. Do not use this feature to review sensitive imagery you do not want sent to the configured local model process.

## Security and release limitations

The `POST /api/visual/studio/ai-review` endpoint requires normal authentication and respects the existing specification limit, workspace asset rules, server request throttling and origin checks. It is deliberately excluded from hosted mode's allowed paths.

The next iteration may explore richer multi-layer layout assistance, semantic references and brand kits. This v6 feature provides real local AI observations and bounded manual-preview edits, not arbitrary AI-generated code or unrestricted edits.

## Tests

- `python -m pytest -q tests/test_visual_ai_review.py tests/test_visual_repair.py tests/test_visual_studio.py`
- `cd apps/desktop && npm run test:ui` (a stubbed local model response is used for the browser review path; actual model quality must still be manually checked with a downloaded vision model)
- Verify offline failure path, exact text and asset hashes, protected layers, and Windows packaging in CI.

**Microsoft Store publication remains paused** until all agreed AutoMoto AI milestones are complete. Internal branches, tests and development previews are allowed.
