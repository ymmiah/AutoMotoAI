---
name: web-design
description: Design and build a responsive, accessible website (HTML/CSS/JS) and preview it.
category: design
tools: write_file, run_app
optional_apps: python|node
status: live
---
# Web design

1. Ask (or infer) the purpose, audience, pages and brand colours. Default: one page, mobile-first.
2. Scaffold in `site/` with `write_file`:
   - `index.html`: semantic landmarks (`header`, `nav`, `main`, `footer`), one `h1`, `lang`, `meta viewport`,
     descriptive `alt` text, labelled form fields.
   - `styles.css`: CSS custom properties for colours/spacing, `clamp()` type scale, flex/grid layout,
     `@media (min-width: 48rem)` breakpoints, `:focus-visible` outlines, `prefers-reduced-motion` and
     `prefers-color-scheme` support.
   - `script.js` only if needed (no inline scripts, `defer`).
3. Check contrast (text ≥ 4.5:1, large text ≥ 3:1) and that everything works with the keyboard.
4. Check: `search_files` for `<img` without `alt`, make sure every page links `styles.css`, and if ImageMagick or
   a browser isn't available just open `site/index.html` with `open_in_app` `vscode`. Tell the user to open
   `site/index.html` in a browser (or run `python -m http.server --directory site` themselves).
5. Report: file tree, colour palette, breakpoints, accessibility notes and next steps (deploy with the `vercel` skill).
