---
name: research-studio
description: Answer a research question from the user's files, save the evidence, and check a DOI before citing it.
category: research
tools: research_query, research_save, research_list, research_verify_doi
status: live
---
# Research Studio

Quotes have to come from the files. Do not fill gaps from memory and do not invent a citation.

1. `research_query` with the question and the file paths. The tool pins each checksum. Use `mode` `outline` only when they asked for a writing plan, not for facts.
2. If a quote is what they need to keep, `research_save` a project. That file is the result.
3. A DOI is checked with `research_verify_doi` when the network is available. If the tool is missing or it fails, say you could not verify it. Never guess a DOI, a journal or a page number.
4. End with the quotes you actually got and the saved project path when you wrote one.
