---
name: graphic-design
description: Make graphics - logos, icons, banners, social images, thumbnails - as SVG and PNG with ImageMagick or Inkscape.
category: design
tools: write_file, run_app
apps: imagemagick|inkscape
status: live
---
# Graphic design

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
