# AutoMoto Research Studio — V2: Scholarly Source Discovery & Provenance

**Milestone 2 of 7.** V2 adds explicit academic metadata discovery and controlled webpage capture alongside the existing local, source-pinned Research Studio. DOI registration, a registry record or a quoted source passage is **not proof** of peer review, high-quality methodology or accurate findings.

## Delivered

**Crossref search.** Query the public Crossref Works API using a short bibliographic search with at most ten matches. Use only approved response fields, normalise exact DOI, title, author, publication date (preserving missing month or day), venue, work type, registry and retrieval date, and remove duplicate DOIs. Crossref metadata originates from members and is not a scholarly quality guarantee.

**OpenAlex search.** The user may choose the public OpenAlex Works API without an API key for small queries, subject to its changing free quotas. No OpenAlex API key is created, requested or stored. Only DOI-bearing results are shown. Any OpenAlex retraction flag is shown as a warning; a missing flag does not imply that an article remains unretracted.

**Exact DOI verification.** Verify a supplied DOI by fetching the exact record from the Crossref registry and matching the returned DOI to the user request. A DOI lookup does not download the original paper or infer missing author, year or journal metadata. Invalid identifiers and unexpected response hosts are refused.

**Private, create-only metadata catalogue.** The explicit save action re-fetches metadata server-side after two user confirmations, deduplicates by DOI and records retrieved-at time, registry name and the bibliographic fields present. Up to 200 metadata-only records, capped at 16 KB each, are stored under the authenticated workspace in artifacts/research/sources. Existing sources are not modified.

**Explicit public webpage capture.** The user supplies a single HTTPS URL and confirms retrieval. The server verifies robots.txt (fail closed if unavailable or prohibited), DNS-pinned SSRF checks, TLS and no redirects; no scripts or page links are executed/followed. Only bounded HTML or plain text is accepted. Up to 9,000 characters of extracted text are saved as a new, prominently UNVERIFIED TXT source in the Document Assistant folder, with retrieval UTC, original URL, text checksum and separate provenance metadata under artifacts/research/pages. It is then selectable in V1's source-pinned local evidence search. Webpage capture does **not** grant copyright rights or verify the webpage's academic reliability. Respect site licences and check sources before publication.

## Security and offline limits

All new API routes require the existing AutoMoto authentication, origin/CSRF checks and hosted allowlisting. Data is strictly tenant-scoped. All external APIs are fixed-host, response-size-bounded, no-redirect, explicitly user triggered, and use the shared netguard DNS-pinned SSRF protection. Requests are rate-limited; no search crawler, background scanning, broad web collection, automatic retries or paid provider integration is introduced.

Local or environment-configured offline mode blocks **every** V2 external lookup and capture. V1 evidence retrieval remains offline-capable.

External metadata and page text are untrusted content. All UI text uses safe text-based DOM operations. This version produces metadata records and research material, not final Harvard/IEEE references.

## API

- POST /api/research/studio/discovery/search — Crossref/OpenAlex, user-initiated.
- POST /api/research/studio/discovery/verify-doi — exact Crossref DOI lookup.
- POST /api/research/studio/discovery/save-doi — re-fetch and create-only metadata snapshot after consent.
- GET /api/research/studio/discovery/saved — list private metadata.
- GET /api/research/studio/discovery/saved-entry — open a private, historical metadata snapshot.
- POST /api/research/studio/discovery/capture-page — consented, robots-aware single-page public HTML/text import.

## Acceptance

Python: python -m pytest -q tests/test_research_discovery.py tests/test_research_studio.py tests/test_document_research.py

All tests: python -m pytest -q

Browser: cd apps/desktop && npm run test:ui

Automated tests use mocked provider responses to remain independent of external network and keys. These validate DOI, source/date preservation, Crossref/OpenAlex normalisation, deduplication, offline refusal, robots, redirects, invalid content and URL schemes, private imports, SHA-256, historical snapshots, tenant separation and malicious publisher text rendering. Full Windows/Linux/macOS Python, Office, UI, Docker, VS Code, security, desktop installer and docs workflows must pass before the PR is merged.

Manual tests remain essential for real Crossref and OpenAlex availability, source metadata accuracy, robots compliance, HTML extraction quality, screen-reader behaviour, public site usage rights and publication-ready referencing.

## Remaining roadmap

V3 — source comparison and contradictory evidence. V4 — formal Harvard/IEEE citations and research reports. V5 — local opt-in AI synthesis. V6 — cross-studio approved workflows. V7 — final hardening and acceptance.

Microsoft Store publication remains deferred until separately authorised.