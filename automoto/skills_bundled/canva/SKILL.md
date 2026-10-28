---
name: canva
description: Work with Canva designs through the official Canva MCP connector, or prepare assets for Canva locally.
category: design
connectors: canva
status: untested
---
# Canva

1. Connect once: Settings → Connectors → **Canva** → Enable, then restart `automoto serve`. The first call opens
   your browser to sign in to Canva (OAuth via `mcp-remote`). Tools then appear as `mcp__canva__…`.
2. Ask for what you need - list designs, create from a template, export as PNG/PDF. Every Canva tool call asks for approval.
3. Without the connector: make assets locally (`graphic-design` skill) at Canva's sizes
   (Instagram post 1080×1080, story 1080×1920, presentation 1920×1080) and upload them yourself.
4. Publishing or sharing designs is always confirmed by you.
