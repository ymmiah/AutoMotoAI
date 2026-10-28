---
name: graphic-design
description: Make graphics - logos, icons, banners, social images, thumbnails - as SVG and PNG with ImageMagick or Inkscape.
category: design
tools: write_file, run_app
apps: imagemagick|inkscape
status: live
---
# Graphic design

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
