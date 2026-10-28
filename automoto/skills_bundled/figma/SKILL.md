---
name: figma
description: Read Figma files (frames, components, styles, images) with the Figma REST API or the Figma MCP connector, and turn designs into code.
category: design
tools: service_api
env: FIGMA_TOKEN
connectors: figma
status: unit
---
# Figma

Token: `FIGMA_TOKEN` (Figma → Settings → Security → Personal access tokens, read-only scopes). The file key is the
part after `/design/` or `/file/` in the Figma URL.
- File structure: `service_api` figma `/v1/files/KEY` with `query {depth: 2}` (pages and top-level frames)
- Specific nodes: `/v1/files/KEY/nodes` with `query {ids: "1:2,1:3"}`
- Render frames as images: `/v1/images/KEY` with `query {ids: "1:2", format: "png", scale: 2}` → returns image URLs;
  download them with `fetch_url` only if needed (they are on Figma's CDN).
- Styles/components: `/v1/files/KEY/styles`, `/v1/files/KEY/components`
Design → code: map colours and type to CSS variables, keep the 8-pt spacing grid, implement hover/focus/disabled states
(`web-design`, `html-css` skills).
Alternative: Settings → Connectors → Figma (Figma's remote MCP; Figma only admits clients in its MCP catalog).
