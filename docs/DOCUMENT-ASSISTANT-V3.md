# Document Assistant v3 — Offline AI review with explicit approval

**Development only. Microsoft Store publication remains deferred.**

## Purpose

Document Assistant now offers opt-in **Proofread**, **Rewrite for clarity**, and **Source-grounded summary** actions. They use only an explicitly enabled, previously downloaded Ollama model on the user's computer. There is no cloud AI fallback and no new model download triggered by this workflow.

The existing native editable Markdown, structured Word export, paper controls, tables, heading outline and Undo/Redo all remain intact. Imported DOCX, PDF, PowerPoint and spreadsheet files remain read-only.

## How to use

1. Open Document Assistant. Choose an editable draft or an imported Office/PDF file.
2. For editable source, select the sentence or section you want to review. With no selection, up to 12,000 characters of the entire document may be used. For an imported Office file, only read-only grounded summarisation is offered.
3. Choose **Proofread**, **Rewrite for clarity** or **Source-grounded summary** and explicitly press **Review with local AI**.
4. The selected, installed Ollama model prepares the review locally. If it is missing or disabled, the panel explains how to enable **Settings → Offline AI** rather than silently switching to a cloud provider or downloading a model.
5. For proofreading or rewriting, inspect the suggested replacement before pressing **Apply to editable source (Undo available)**. The original content does not change during review. Approval replaces only the originally selected range, and joins the existing Undo/Redo stack. Saving a separate draft is still the user's choice.
6. For summaries, each point includes an exact source quote that the server verifies in the submitted selection or in a checksum-verified imported file. An editable source quote can be highlighted via **Find in source**. A summary is informational only: there is no Apply control.

## Explicit boundaries

- **Local-only model connection.** Ollama must be configured and explicitly enabled; its HTTP endpoint must be loopback-only. The review route is not in the hosted-server allowlist.
- **No file writes.** The API only returns a review object; it cannot save, export, modify or delete a user document.
- **No auto-edits.** The browser compares the entire original editable source with the snapshot taken before the request. A stale result is refused. An approval dialog and a native Undo entry are required for a rewrite.
- **Bounded inputs and responses.** The selected text cannot exceed 12,000 characters. Replacement lengths, evidence item counts, evidence quote lengths and the model response are capped; duplicate/invalid source ranges or mismatching SHA-256 digests are rejected.
- **Verbatim evidence.** An imported file is re-read from the user's workspace with a matching SHA-256 digest. Claims lacking an exact source quote are filtered; if no valid quotes remain, the request fails rather than inventing citations. These verified excerpts **do not prove the model's interpretation is correct**.
- **Prompt-injection protection.** The model receives the document as untrusted data, not instructions or tool calls. Responses are parsed as bounded JSON and displayed through text-only controls; no model-generated HTML/scripts or tools are executed.
- **No unnecessary source disclosure.** The backend uses only the selected text (or bounded read-only extracted text), sending it only to the chosen loopback model. Nothing is persisted in a new conversation or indexed by this operation.

## Tests

- `tests/test_document_ai.py`: session authorisation, hosted lockout, opt-in model availability, loopback validation, exact selected text, unchanged originals, stale checksums, hostile payload bounds, quote verification, actual imported Word checksum and read-only mode.
- `apps/desktop/test/document-ai-review.cjs`: pure approval and stale-source boundaries, exact selection replacement, and verified evidence matching.
- `apps/desktop/test/ui-smoke.cjs`: real browser interactions with a deterministic intercepted model response; imported summary remains read-only, editable suggestions need consent, approved changes support Undo/Redo and stale edits are refused.
- Full CI across Linux, macOS, Windows, Office, security, desktop application and browser regressions.

## Known limitations

This is not a factual verification service or a research web browser. Evidence checks verify that quotations came from the source, **not** the truth of claims. Imported documents over the bounded extracted-text limit cannot be summarised in v3: users should work from a shorter excerpt or native draft. Scanned PDFs require an independently configured OCR workflow. Very small local models can struggle with structured suggestions and may return an explicit validation error. The current interface supports one selected section at a time; multi-document citation synthesis is planned for the Research Assistant.

**Next:** finish CI and usability review, then continue Document Assistant professional publishing and offline academic support. Do not publish the Windows application until the final AutoMoto AI release phase.
