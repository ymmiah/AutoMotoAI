---
name: graphic-design
description: Create professionally composed static and animated visual assets using editable vectors, original images, and a shared design engine.
category: design
tools: visual_presets, visual_create, visual_check, image_compose, image_models, image_generate
apps: imagemagick|inkscape
status: live
---
# Graphic design

**Default design workflow (local, deterministic and offline-capable)**
1. Start with `visual_presets` if the user has not selected a visual style.
2. Decide the composition: `workflow` (2-6 nodes), `cards` (2-6 cards), `hero` (original existing photo), or `canvas` (precisely positioned native text, icons, shapes, lines, photos).
3. `visual_create(path, spec)` exports PNG, JPEG, SVG, PDF or editable PPTX. For a **real GIF** use a `.gif` path and `animation:{effect:'flow'|'pulse'|'float'|'reveal',frames:20,duration_ms:110,loop:0}`. Loop 0 runs continuously. Do not fake movement with multiple static frames.
4. `visual_check(path)` verifies GIF motion and frame count or PowerPoint editability and overflow. Always visually review critical final files; a structurally valid export is not guaranteed visually perfect.
5. Use the **original user's face/body/logo file** in a hero or canvas image component: the renderer aspect-fits or embeds it, never changes/recreates the identity. Avoid generative image editing unless the user explicitly authorises that change.
6. For required names, captions and pricing, keep text as a genuine text object; use PIL/native PowerPoint/SVG lettering, not diffusion-rendered labels. Reject overlong text rather than silently cutting it off.
7. Existing styles: `illustrated-workflow`, `editorial-light`, `premium-tech`, `commercial`. Standard canvases are 1280×720; GIFs may use up to 1 megapixel and 8-48 frames.
8. For actual original AI-generated art, use `image_models` then `image_generate` only if a compatible local ComfyUI checkpoint is installed. This is a separate capability, not needed for professional vector diagrams or GIFs.

**Core generation modes**
- `image_models`: detect a separately installed local ComfyUI service and its checkpoint models.
- `image_generate`: create genuinely new, original artwork via that installed local diffusion
  model. Checkpoints and ComfyUI are prerequisites; don't claim they are bundled, free of
  compute costs, or capable of preserving an exact reference identity.
- `image_compose`: compose the original user-supplied photo and/or logo with **exact** text
  and deliberate spacing. It never generatively redraws faces, changes body proportions,
  modifies brand marks, crops a photo, or replaces text. Preferred for identity fidelity.
- When visual text is part of the work, render it as text in the output layout rather than
  asking diffusion to paint letters (text-to-image spelling is unreliable).

1. Clarify size and use (e.g. 1200×630 social card, 512×512 icon, 1920×1080 banner), colours, text.
2. Draw vector first: `write_file` an SVG (`viewBox`, simple shapes, `<text>` with a common font family,
   2-3 brand colours, generous margins). Keep text ≥ 5% of the height so it reads on phones.
3. Export to PNG:
   - ImageMagick: `run_app` `imagemagick` `["-background", "none", "-density", "300", "logo.svg", "-resize", "512x512", "logo.png"]`
   - Inkscape (better SVG fidelity): `run_app` `inkscape` `["logo.svg", "--export-type=png", "--export-width=512"]`
4. Common edits with ImageMagick (`run_app` `imagemagick`):
   - resize/crop: `["in.jpg", "-resize", "1200x630^", "-gravity", "center", "-extent", "1200x630", "out.jpg"]`
   - text overlay: `["in.jpg", "-gravity", "south", "-pointsize", "48", "-fill", "white", "-annotate", "+0+40", "Hello", "out.jpg"]`
   - compress: `["in.png", "-strip", "-quality", "82", "out.jpg"]`
   - side-by-side: `["a.png", "b.png", "+append", "row.png"]` (`-append` stacks vertically)
5. Check the result with `run_app` `imagemagick` `["identify", "out.png"]` (or `["out.png", "-format", "%wx%h", "info:"]`).
6. Photoshop / Illustrator: see the `photoshop` and `illustrator` skills. Canva: the `canva` skill.
