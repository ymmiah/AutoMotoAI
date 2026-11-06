# AutoMoto AI 5.6.0 Beta 6 — Visual Studio v1–v5 release candidate

**Release status:** proposed; not tagged, uploaded to Partner Center, or published.

- Desktop version: `5.6.0-beta.6`
- Python engine: `5.6.0b6`
- Microsoft Store MSIX version: `5.6.6.0`
- VS Code extension: `5.6.0-beta.6`
- Windows target: x64

## Changes since the last tagged beta

- Visual Studio's editable design workflow, native canvas elements, layered exports and safe local previews.
- Layer ordering, grouping, visibility and locking; staged GIF animation timeline.
- Reopen generated artwork in the layer editor, when an editable source exists.
- Structural inspection and conservative repair suggestions.
- Individual repair checkboxes, real server validation of each selection, before-and-after previews and reversible approval.
- Advisory accessibility, spacing and readability checks.

The tool **does not** separate a flattened image into independent editable objects, guarantee aesthetic quality, or automatically modify original user photographs and logos.

## Required release gates

1. Merge the release candidate only after the CI, security, browser, Windows installer and MSIX test-install jobs all pass. Review the Visual Studio before-and-after browser screenshots.
2. Confirm all version strings and lockfiles match; check that the release tag does not exist and the Microsoft Store version `5.6.6.0` is unused for the existing product.
3. Check `MSSTORE_IDENTITY_NAME`, `MSSTORE_PUBLISHER`, `MSSTORE_PUBLISHER_DISPLAY_NAME`, and `MSSTORE_DISPLAY_NAME` are the **real** values of the existing Store product. A placeholder identity is a hard stop.
4. If approved, tag the merged commit as `v5.6.0-beta.6` and push the tag to trigger the Publish and Windows app workflows. Beta tags build artifacts; they do **not** automatically publish to marketplaces.
5. Check release artifacts and SHA-256 checksums. The `automoto-ai-msstore` artifact should contain `AutoMoto-AI-5.6.0-beta.6-Windows-x64.msixupload` and `SHA256SUMS.txt`.
6. Download and inspect the MSIX manifest identity, publisher and package version against the existing Partner Center product **before** submitting anything. Recheck the Store listing, dependency notices, privacy policy, screenshots, accessibility and AI disclosure.
7. Submit the update through Partner Center only after the maintainer explicitly approves the release. Publishing and certification are external steps; a successful GitHub build is not a Store publication.

## User-facing release text

**AutoMoto AI now includes Visual Studio:** create editable designs, adjust independent layers, animate GIF sequences and export your artwork. Inspect potential layout issues, compare proposed corrections against the original, select individual fixes and undo changes. Your original photos, logos and exact wording remain protected. Some advanced creative editing capabilities are still under development.

## Rollback

Do not retag an existing version or overwrite a previously submitted Store package. If a release fails verification, stop publication, correct the source, bump the beta and MSIX version, and build again.
