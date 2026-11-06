# AutoMoto Visual Design Foundation — implementation guide

This document describes the working branch `feature/visual-foundation-gif-engine` (PR #11). It is not a Microsoft Store release until reviewed, merged, packaged and accepted.

## What this release actually builds

One structured scene feeds **five export engines** using the existing Python dependencies:

- **PowerPoint** `.pptx`: editable text, vector shapes, icon primitives, connectors and original embedded pictures. Multiple scenes become multiple slides.
- **SVG** `.svg`: accessible-sized vector artwork, embedded local photos, escaped text; no scripts, remote image requests or user-supplied SVG markup execution.
- **PNG/JPEG**: locally rendered static images with layout validation.
- **PDF**: simple raster PDF of a rendered scene. For a full tagged publication document, use the established Office/PDF tools instead.
- **GIF** `.gif`: real animated image frames with `flow`, `pulse`, `float` and `reveal` effects.

This pipeline **does not** perform generative image editing itself. AutoMoto still offers a separate, opt-in `image_generate` tool through locally installed ComfyUI/checkpoint models. Source-faithful photos/logos enter this pipeline as **existing assets**. Source files are checked before and after export and are never rewritten by this design pipeline.

## Practical API — `visual_create`

Use `visual_presets` for supported styles and `visual_check` to inspect output. Store new files in `artifacts/` or `scratch/`, never overwrite originals.

### Example 1: a connected illustrated workflow

```json
{
  "path": "artifacts/invoice-processing.gif",
  "spec": {
    "layout": "workflow",
    "theme": "illustrated-workflow",
    "width": 960,
    "height": 540,
    "title": "Invoice processing",
    "subtitle": "From evidence to validated output",
    "nodes": [
      {"id": "receive", "title": "Receive", "text": "Original source", "icon": "file"},
      {"id": "extract", "title": "Extract", "text": "OCR and text", "icon": "image"},
      {"id": "validate", "title": "Validate", "text": "Check totals", "icon": "shield"},
      {"id": "deliver", "title": "Export", "text": "Approved output", "icon": "check"}
    ]
  },
  "animation": {
    "effect": "flow",
    "frames": 24,
    "duration_ms": 100,
    "loop": 0
  }
}
```

The output is an **animated GIF**, not a static slide or a GIF of identical frames. The moving highlighted position travels along each connecting line.

### Example 2: an editable PowerPoint deck

```json
{
  "path": "artifacts/automoto-capabilities.pptx",
  "spec": {
    "theme": "editorial-light",
    "slides": [
      {
        "layout": "cards",
        "title": "Our capabilities",
        "cards": [
          {"title": "Design", "text": "Editable elements", "icon": "target"},
          {"title": "Protect", "text": "Original assets", "icon": "shield"}
        ]
      },
      {
        "layout": "hero",
        "title": "Our original brand",
        "image": "uploads/brand-photo.png",
        "text": "Exactly provided brand copy",
        "alt": "Unmodified source photograph",
        "notes": "Talk through this source image without altering it."
      }
    ]
  }
}
```

Each scene becomes a real PowerPoint slide. Text boxes and shapes are native; the source photo is inserted with **contain/aspect-fit**. There are no fake image-generation steps.

### Example 3: surgical positioning

```json
{
  "path": "artifacts/architecture.svg",
  "spec": {
    "theme": "premium-tech",
    "layout": "canvas",
    "title": "Secure architecture",
    "elements": [
      {"type":"rect","x":80,"y":260,"w":240,"h":160,"fill":"#19283E"},
      {"type":"text","x":120,"y":310,"w":190,"h":48,"text":"Local engine","font_size":26},
      {"type":"line","x1":320,"y1":340,"x2":470,"y2":340,"colour":"#56B2FA"},
      {"type":"icon","x":500,"y":290,"w":70,"h":70,"name":"shield"}
    ]
  }
}
```

All coordinates are canvas pixels. Out-of-bounds geometries, invalid colours, unreadable text and unresolvable source assets cause an explicit error, rather than a silently damaged output.

## Four initial styles

- `editorial-light`: understated, readable academic and professional material.
- `illustrated-workflow`: rounded pastel nodes, playful outlined icons and connected workflow diagrams.
- `premium-tech`: restrained dark-blue technology visualisations with high-contrast text.
- `commercial`: light premium product/marketing layouts with warm accent tones.

These are original visual tokens, not copied reference-image characters, copyrighted stock illustrations or third-party logos.

## GIF animation: playback and limits

Animated GIF contains real changing frames with Pillow `save_all=True`, `append_images`, `duration`, `loop` and `disposal=2`. The encoder uses one shared adaptive palette across frames to reduce colour jumps. Loop `0` means continuous looping; other supported loop counts are `1`–`20`. Effects include:

| Effect | Visual behaviour |
|---|---|
| `flow` | Moving coloured progress marker along diagram connectors |
| `pulse` | Highlights steps or feature cards in sequence |
| `float` | Looped, restrained visual activity in the current section |
| `reveal` | Progressively brings diagram cards into view |

**Safety / performance limits:** GIF canvas up to 1,000,000 pixels, 8–48 frames, 50–500ms per frame, loops 0–20, no user-supplied scripts. More elaborate animated video and timeline keyframes are separate future development, not included here.

## Security and original asset protection

- Only local workspace/explicitly allowed files are read. No network access is needed for these renderers.
- Source raster images are verified by a real image decoder; maximum 24MB / 36MP, one frame.
- SVG embeds raster image bytes into a data URL (and escapes all text) instead of linking to external resources.
- Asset fingerprints are SHA-256 hashes checked before and after export. Originals remain unchanged. Scaling in an output may resample pixels but does **not** reshape the original subject, replace a face or alter source file bytes.
- Every `visual_create` output gets a sibling `<filename>.visual.json` provenance record with the exact output SHA-256, canvas dimensions, original-asset SHA-256 hashes and manual review status. This record does not mean a human has visually approved the result.
- Exact text is kept in native text elements. If text cannot fit its allocated space, the tool refuses to export rather than truncating it invisibly.
- A generated GIF has been checked for multiple frames. `visual_check` compares representative frames to detect visible motion.

## Current limitations to address in follow-on work

The first build provides a **working visual production engine**, not a complete Canva/Figma-like editor. It does not yet include every part of the long-term roadmap:

1. Drag-and-drop browser editor with object grouping/undo history.
2. Semantic shape-to-shape snapping and arbitrary path animations, complex character rigging and video exports.
3. Full automated screenshot critique and element-by-element AI visual repair.
4. Full PDF accessibility/tagging and exhaustive font-shaping checks across languages.
5. Installer-managed local diffusion models and masked generative image editing.
6. Frame-accurate animations inside PowerPoint: GIFs are separate exports and cannot be assumed to play as native PPTX animations.

Each requires separate design, testing and potentially new dependencies. Do not claim they are already complete.

## Production validation

Run `python -m pytest -q tests/test_visual_foundation.py tests/test_visual_design.py`, then `python -m scripts.ci.create_visual_samples <workspace>/showcase` to generate a comparison deck, connected workflow GIF, SVG and static images. Inspect exported previews manually and verify native PPTX objects in PowerPoint or LibreOffice.

The GitHub CI `visual-foundation` job produces a downloadable `automoto-visual-showcase` artifact if tests and rendering pass.

**Release policy:** change is isolated in PR #11 until approval and successful checks. Packaging, signing, Microsoft Partner Center upload and publication are separate actions.
