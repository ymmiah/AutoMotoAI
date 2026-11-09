# AutoMoto AI Research Studio V8 — Portable Encrypted Recovery and Resilience

**Extra hardening milestone beyond the agreed V1–V7 roadmap.** V8 is a development change stacked on V7's unmerged PR #49. It does **not** merge V7, publish AutoMoto, approve academic claims or submit a Microsoft Store package.

## Purpose

V7 supports private source-verified recovery on one installation, with a known limitation: an archive stored on the same machine is not an off-device backup. V8 adds a deliberate operator-controlled **encrypted portable recovery path** that can be saved separately and inspected on a fresh installation.

V8 uses the audited V7 recovery bundle as the sole export source. A new portable archive is never created from client-provided quotes, claims or unverified source data.

## Supported workflow

1. Finish and save a source-verified V3 comparison, optionally with V5 reviewed AI evidence and a V6 hand-off.
2. Use **Research Studio → V7** to run source-integrity checks and explicitly create a V7 private recovery snapshot.
3. In **V8**, select that existing snapshot, enter and confirm a **unique 16+ character passphrase**, acknowledge that the password cannot be recovered and choose **Create encrypted copy**.
4. Select the new \`.amrc8\` capsule and **Download**. This fetches authenticated ciphertext only, using the existing local session/CSRF context. The user must independently save a copy to an external drive or another protected device and verify it there. Merely downloading does not establish that a separate copy exists.
5. On a different AutoMoto installation, select the downloaded \`.amrc8\` file, enter the original passphrase and click **Inspect and authenticate**. The server validates the AES-GCM authentication tag, the original V7 JSON record, exact ZIP member list, archive SHA-256, per-file hashes, uncompressed size caps and type restrictions **without importing files into application state**.
6. After reviewing the presented source roles, exact paths and digests, explicitly authorise **Stage verified file copies**. The exact file SHA-256 must still match the inspected capsule. The server **decrypts and fully revalidates** on this second request; it never relies on a previous UI result.
7. The new installation creates only a fresh private staging directory with safe generated member filenames and a detailed manifest mapping each file to its original logical path. No source, project, report, review, original upload, document or studio hand-off is overwritten, merged or marked publishable.

## Cryptography and format

- \`cryptography\`'s authenticated **AES-256-GCM**, with a new 96-bit nonce for each encryption and a 128-bit per-export random salt.
- **scrypt** password derivation with N=32768, r=8, p=1 and a 256-bit derived key. Minimum 16 characters; maximum 256 UTF-8 passphrase bytes. Password strength still depends on the user's chosen secret.
- Versioned fixed 8-byte file magic \`AMRC8\`, followed by a 16-byte salt, 12-byte nonce and AES-GCM ciphertext/tag. Header and format context are included in authenticated associated data.
- Inside the ciphertext: a bounded 4-byte metadata size, original V7 metadata bytes (private provenance and source names) and original, validated V7 ZIP archive bytes. Nothing is silently re-extracted by the LLM.
- **No bespoke ciphers**; no authenticated plaintext paths are placed in the file name, public URI or unencrypted export metadata.
- **No remote key escrow, cloud upload, remote connector, password hint, password recovery or plaintext auto-publication.** Lost passwords mean lost recovery access.

The encryption file and locally created sidecar are stored in the authenticated private workspace under \`artifacts/research/recovery/portable/\`. Sidecars contain only creation time, ciphertext digest and file count. Downloads use a no-cache encrypted application/octet-stream response.

## API

| Route | Operation |
| --- | --- |
| \`POST /api/research/studio/portable/create\` | Verify selected V7 backup and create a fresh encrypted capsule after owner acknowledgement |
| \`GET /api/research/studio/portable/list\` | List privately saved encrypted capsules |
| \`GET /api/research/studio/portable/download?path=...&sha256=...\` | Authenticated download, exact private-path allowlist and matching current SHA-256 |
| \`POST /api/research/studio/portable/inspect\` | Bounded multipart ciphertext upload + passphrase, read-only cryptographic and archive inspection |
| \`POST /api/research/studio/portable/stage\` | Separate owner approval, **exact uploaded SHA-256 match** and fully repeated decrypt-and-verify before isolated staging |

All routes stay **local-only and authenticated**; the hosted allowlist remains default-deny. The app shell attaches session/CSRF headers to requests, while the browser sets multipart boundaries. The server checks authentication before parsing multipart bodies, checks declared Content-Length before accepting large uploads and bounds actual file reads regardless of misleading client headers.

V8 retains V7's original archive constraints: maximum 14 file members, 16 MiB per member, 40 MiB aggregate source data, and a bounded 40 MiB-scale capsule. At most 16 private encrypted exports are listed and supported per local workspace. Additional copies, full-device recovery or very large archives require an independently designed backup policy.

## Security and operational limitations

- A weak or reused password can be guessed **offline** by someone who obtains an encrypted capsule. Scrypt increases guessing cost but cannot fix weak user secrets. Prefer an independently stored, randomly generated passphrase of high entropy.
- A malicious file with a forged manifest cannot silently bypass verification: even after correct decryption, the original archive and every file's hash, path roster, size and ZIP compression are checked before any extraction. But checksums alone cannot certify the scientific veracity or copyright permissions of the recovered data.
- An attacker with control of the user's operating system, decrypted application memory or the passphrase can bypass these protections; no recovery design can secure a fully compromised host.
- Passwords are submitted only to the local app for encryption/decryption, are never deliberately persisted or logged, and are cleared from the UI after successful create or stage. Runtime memory cannot be guaranteed to be instantly zeroised by Python or JavaScript.
- Cross-machine import preserves original path **as manifest data only**. It never uses imported paths as extraction targets, and never auto-approves claims, merges projects, publishes research or invokes models.
- Successful download is not proof of an off-device copy; the owner must test that backup on an independent device, validate a restore and store the passphrase securely.
- ZIP import and multipart parsing remain deliberately bounded. Archive extraction occurs only into new private quarantine folder paths with generated safe names.

## Verification and acceptance

\`\`\`bash
python -m pytest -q tests/test_research_portable.py tests/test_research_acceptance.py
python -m pytest -q
cd apps/desktop && npm run test:ui
\`\`\`

The exact development commit must pass Python 3.10/3.13 on Ubuntu, macOS and Windows, desktop and installer builds, security, Office, browser UI, Docker and docs. QA should attempt wrong passwords, altered ciphertext bytes, unknown magic/version, forged extra members, symlinked metadata, tampered digests, missing consent, malformed uploads, cancelled transfers and second-installation staging with independent clean workspaces.

**Manual gates not certified by CI:** independently saved external copy, real-device disaster-recovery drill, readability/keyboard/screen-reader checks, academic and citation source review, threat model revalidation and a separate release-authorisation record. The Microsoft Store remains deferred.
