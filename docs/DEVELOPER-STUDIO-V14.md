# AutoMoto AI — Developer Studio V14: Web UI & Frontend Frameworks

**Milestone:** Phase 4, V14 of 64. [Notion V14](https://app.notion.com/p/4131cc3365d681f1a6a6f78ea2492a4b).

**Dependency:** V13 merged to the V12 development branch after successful CI. V12 remains separate from main. V14 is a dependent draft feature, not a production release.

## Delivered

### Read-only frontend inventory
- Bounded local project scan of HTML, CSS, SCSS, JSX, TSX, Vue and Svelte source, through V7 path and dependency exclusions.
- Framework declarations from V13 package.json and config markers: React, Next.js, Vue, Angular, Svelte/SvelteKit, Nuxt, Vite and other supported declarations. Findings never claim that an installed framework version is independently verified.
- Build-script availability, file-format counts and bounded file list. No Node, npm, pnpm, yarn, Sass, compiler, development server, framework or package code runs during inspection.
- Source audit for CSS/SCSS remote imports, URLs and large min-width patterns; dynamic JSX/TSX/Vue/Svelte previews remain unimplemented and are labelled as such.

### HTML accessibility preflight
The bounded HTML parser reports missing document language/viewport/h1, heading-level jumps, missing image alt attributes, unnamed buttons and links, missing explicit control labels and duplicate IDs. Findings include source lines.

This is heuristic preflight, NOT a WCAG 2.2 conformance assessment, not a complete accessible-name algorithm, and not an analysis of the final JavaScript-generated DOM. Contrast, focus order, runtime interactions, screen readers, actual page performance, proper ARIA semantics and browser compatibility need independent checks.

### Layered, inert responsive HTML preview
- Reads project-local existing HTML and optional CSS, including the narrow explicitly selected generated paths dist/index.html, build/index.html and out/index.html after a separately approved V13 build. Other files inside generated directories remain excluded.
- Produces a short allowlisted HTML subset: strips scripts, iframes, event handlers, SVG, forms, images, links to external resources and unsafe/unsupported source tags; source images become inert placeholders.
- Includes only a conservative subset of local CSS selectors/properties/values. No CSS URL imports, remote fonts, external assets, Sass directives, CSS Modules, dynamic CSS-in-JS, script execution, network fetch or build tools.
- Wraps the sanitised source in a restrictive CSP with default-src none, script-src none, connect-src none, img-src none, form-action none and base-uri none. The UI sets iframe sandbox to an empty value: neither allow-scripts nor allow-same-origin is granted. Referrer policy is no-referrer.
- Lets the user view the same sanitised structural HTML at 375, 768 and 1440 CSS pixels. This is a bounded structural comparison and NOT pixel-perfect reproduction of the real framework or complete CSS.
- Reads only existing UTF-8 files under project identity with no-follow file handles; maximum 96 KiB per source and 600 HTML nodes. No project source writes, migrations, persistent state or automatic cloud uploads.

A sandboxed iframe plus conservative sanitizer adds defence in depth, but is NOT a general-purpose certified browser sandbox or a guarantee against all malicious input. Never present this preview as a production site.

## Authenticated local-only endpoints

- GET /api/developer/studio/frontend/inspect — bounded project files and declared frameworks.
- POST /api/developer/studio/frontend/audit — read-only HTML accessibility or CSS/component analysis.
- POST /api/developer/studio/frontend/preview — sanitised CSP srcdoc and local stylesheet subset, source SHA-256 and audit issues.

Hosted mode remains default-denied.

## Test evidence and remaining acceptance

Tests in tests/test_developer_frontend.py cover actual HTML/CSS/SCSS/TSX/Vue/Svelte files with declared Next/React/Vue/Angular/Svelte fixtures, blocked external image/CSS imports and scripts, source hashes, allowed generated HTML, a11y warnings, symlinks/traversal/size limits and denied hosted/unauthorised access.

The real browser smoke test exercises the local frontend panel, HTML/CSS fixture, TSX disclaimer, accessibility diagnostics, the strict sandbox iframe and CSP, absence of source script execution and external asset requests, and all three viewport widths.

Manual acceptance still required before Verified: actual installed React, Next.js, Vue, Angular and Svelte framework builds on supported platforms; real CSS/SCSS and browser screenshots; full WCAG, keyboard, screen-reader and touch assessment; CSP/sanitizer threat review; and performance/security review of generated application assets. Existing V13 explicitly approved tasks remain the only path for running project builds.

No merge into main, Microsoft Store upload, production deployment or source migration.

## Rollback

Remove the V14 router from server.py, the frontend UI mount from Developer Studio, and V14-only files. V1–V13 functionality, original project sources, trust settings and Research Studio data remain unchanged. Separately approved V13 scripts can have their own non-reversible effects; use version control/backups as needed.

References: [MDN iframe](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe); [MDN CSP](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy); [WCAG 2.2](https://www.w3.org/TR/WCAG22/).
