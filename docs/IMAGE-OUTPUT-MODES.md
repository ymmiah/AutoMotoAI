# Universal image output choices — Visual Studio

**Feature branch:** `feature/universal-image-output-modes`. This feature is not included in the published Microsoft Store application until a verified, signed update ships.

## New rule — applies to EVERY image creation request

Before generating original artwork, marketing visuals, product graphics, photos, illustrations, logos, infographics or an animated GIF, AutoMoto asks which delivery type the user wants:

1. **Single finished image** — render the requested PNG/JPEG/etc. Do **not** generate additional image formats or an editable project.
2. **Image + editable layers** — render the image **and** save a Visual Studio `.design.json` file. Existing native text, vector icons, shapes and photos remain independent editable objects.
3. **Animated GIF only** — render the animated GIF without unnecessary image variants or layer project.
4. **Animated GIF + editable layers** — animated GIF and the source Visual Studio composition with its separately editable objects and timeline, when supported.

These are **independent** concepts: file type (PNG, JPEG, SVG, GIF, etc.) and editability (flat or layered). The UI offers choices at image request time; the `visual_create`, `image_generate` and `image_compose` tools accept `output_mode:'flat'|'layered'`. Do not generate every variant automatically.

## Truthful layer preservation

- **Native AutoMoto diagram**: title, text, connectors, cards, shapes and icons are genuine independent layers in Visual Studio, even if the exported image itself is flattened.
- **AI diffusion artwork**: the model outputs a raster image. Its actual pixels are stored as **one protected image layer**; additional text, icons and shapes are independently editable. Claiming that an arbitrary diffusion model returns separate original face/body/background or semantic text layers would be misleading.
- **Source-faithful composition**: in layered mode the input photograph, input logo, exact title and exact subtitle each become independent native image/text layers. Neither photo nor brand logo is AI-redrawn.
- **Ordinary imported PNG/JPEG/WebP/BMP**: opens in Visual Studio with its original pixels as a single layer. No speculative extraction, background segmentation or invented vector components.
- **Existing GIF**: if an AutoMoto editable project is available, open it; otherwise open a first-frame image layer for manual static edits, retaining the GIF file intact. This is not the same as recovering an arbitrary animation's original keyframes.
- **Untrusted SVG**: arbitrary SVGs are not executed or automatically reinterpreted as safe editor layers. Native projects preserve their verified objects; unsafe legacy vector files should undergo separate sanitisation and import work.

## User paths

**From Files:** locate any PNG, JPEG, WebP, BMP or GIF → click **Edit layers** → authenticated `POST /api/visual/studio/import` → Visual Studio opens the exact source image in one layer, or a verified previously saved multi-layer scene. Use the editor's Text, Icon and Shape tools for additional layers.

**From Visual Studio:** choose **Output → Single finished file** or **Editable layers + file** independently of **Format**. GIF is just another format. The latter includes a usable project; the first generates only the requested visual and its required safety/provenance manifest.

**From AI agent:** the composer asks the user for one of the four image delivery choices. The resulting explicit preference passes through the agent message. Generated layered projects open in the same Studio project registry as manually authored artwork.

## Output and provenance

- Finished visual: `artifacts/...` as requested.
- When selected only: `artifacts/visual-studio/<name>-<id>.design.json`.
- Creation metadata (`<filename>.visual.json`) stores selected output mode, the actual project path if any, source hashes and rendered output hash. Existing source photos are never overwritten.
- A native layered project is re-opened directly from the known provenance manifest when its output hash matches. If a flat image has no native project, import it as a single raster layer instead of inventing hidden editable objects.

## Security / bounds

- All imported artwork must remain inside the signed-in user's workspace, no absolute or path traversal input.
- Images are decoded and limited to 24MB and 36 megapixels.
- Drafts are saved with generated names inside each account's isolated Visual Studio folder.
- Studio images are scaled to a bounded canvas (up to 1920×1080, 2.1 megapixels) with aspect-fit. Source image pixels and original files are retained, not cropped.
- Uploaded photos/logos are not sent to cloud image services by these composition tools.
- Existing authentication, CSRF, storage quota and export/preview limits remain required.

## Tests

Run `pytest -q tests/test_image_output_choices.py tests/test_visual_studio.py tests/test_visual_foundation.py tests/test_visual_design.py`; run the real-browser `apps/desktop` UI smoke suite to verify the output chooser and Open in Visual Studio flow.

**Limitation:** full semantic layer separation from arbitrary AI-generated raster artwork (e.g. identifying hair, clothing, individual objects or background) is not available. It would require specialised segmentation and manual fidelity checks, and even then is not guaranteed exact. Do not represent it as implemented.
