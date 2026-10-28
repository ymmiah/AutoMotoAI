---
name: research-brief
description: Research a topic on the web and write a short, sourced brief.
category: research
tools: web_search, fetch_url
status: live
---
# Research brief

1. Run 2-3 `web_search` queries with different wording (include the current year for anything recent).
2. `fetch_url` the 2-4 most relevant, most authoritative results. Prefer official docs, papers and primary sources.
3. Write the brief:
   - **Answer first** in 2-3 sentences.
   - Key facts as bullets, each with its source link.
   - "Unclear / conflicting" section if sources disagree.
4. If the user wants it saved, `write_file` it to `scratch/briefs/<topic>.md`.
5. Never invent links or numbers. If a page could not be fetched, say so.
