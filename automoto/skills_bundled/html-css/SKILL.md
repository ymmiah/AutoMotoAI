---
name: html-css
description: Write or fix HTML and CSS - semantic markup, layout (flex/grid), responsive design and accessibility.
category: coding
tools: read_file, edit_file, write_file
status: live
---
# HTML & CSS

- Markup: semantic elements first (`button` not `div onclick`), one `h1` per page, headings in order,
  `label for=` on inputs, `alt` on images (empty `alt=""` for decoration), `lang` on `<html>`.
- Layout: flexbox for one direction, grid for two; avoid fixed heights; `gap` over margins;
  `min()`, `max()`, `clamp()` for fluid sizes; `aspect-ratio` for media.
- Responsive: mobile-first CSS, `@media (min-width: …)` steps, `max-width: 100%` images, test at 360px.
- Accessibility: visible `:focus-visible`, contrast ≥ 4.5:1, `prefers-reduced-motion`, no text in images.
- Debugging layout: add `outline: 1px solid red` temporarily, check the cascade/specificity, look for
  overflow (`overflow-x` on body usually means a too-wide child).
- When fixing a file, `read_file` it first and use `edit_file` for small, exact changes.
