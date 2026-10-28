---
name: zotero
description: Search your Zotero library, get citations and build bibliographies (service_api with ZOTERO_API_KEY, or the Zotero MCP connector).
category: research
tools: service_api
env: ZOTERO_API_KEY
status: unit
---
# Zotero

Web API: `ZOTERO_API_KEY` and `ZOTERO_USER_ID` (numeric, from zotero.org/settings/keys).
- Search: `service_api` zotero `/users/{user}/items` with `query {q: "attention", limit: 10, format: "json"}`
- Citation: same path with `query {q: "...", format: "bibtex"}` → paste into `refs.bib` (`latex` skill)
- Formatted bibliography: `query {format: "bib", style: "apa"}`
- Collections: `/users/{user}/collections`
Local alternative (no key): Settings → Connectors → Zotero (uses the Zotero desktop app's local API).
