# AutoMoto AI — Developer Studio V16: PHP, Composer & WordPress Security

**Milestone:** [V16 / 64 — PHP and WordPress](https://app.notion.com/p/4131cc3365d68149b17ff60434b27b5). **Base:** development branch including V15 SQL/data/GraphQL and the shared central AutoMoto Agent bridge. V16 is a separate draft feature, not a release or mainline deployment.

## Implemented

A bounded, local-only PHP/WordPress inspection tool built on Developer Studio V1–V15, preserving the existing V2 checksum-guarded editor, V8 installed executable fingerprinting and V13 bounded subprocess launch. No new models, third-party agents or unrequested network services.

### PHP, Composer and WordPress inspection

Read existing project-local composer.json (96 KiB maximum) with duplicate-key rejection. Report declared PHP engine requirements, Laravel, Symfony, PHPUnit, PHPStan, Psalm and WordPress Composer dependencies. Detect up to 50 approved local PHP files and opening-comment WordPress plugin headers, named hooks, activation/deactivation callbacks, and selected lexical security hazards, including raw superglobal echo, PHP eval and unserialisation, low-confidence database query patterns and Ajax callback review. Each finding is source-labelled and advisory; the scanner does not understand all PHP scopes, tokens, vulnerabilities or WordPress semantics.

Discover installed system PHP/Composer executable paths with SHA-256 and no execution. Shell wrapper scripts such as CMD, BAT and PS1 are refused, so native Windows Composer wrappers may be unavailable until separately supported. No dependencies are installed, no plugin is activated and no PHP is executed during inspection.

### Safe WordPress repair preview

V16 offers an intentionally narrow, deterministic **copy-only** source repair for exactly one literal notice output form in a real WordPress plugin:

    echo $_GET['notice'];

The preview suggests a missing-key guard, WordPress unslashing, text sanitisation and HTML escaping:

    echo isset( $_GET['notice'] ) ? esc_html( sanitize_text_field( wp_unslash( $_GET['notice'] ) ) ) : '';

It returns original/patched SHA-256 and validates named hook declarations before and after, while preserving other source bytes, settings and header metadata. No file is written by the preview, and a nonmatching or ambiguous input is rejected rather than guessed. The user can review and apply the exact proposed text through the existing V2 editor, whose trusted-workspace permission, original-file SHA-256 and atomic-write safeguards remain mandatory. The code is specific to plain HTML text output; it must **not** be reused blindly for HTML attributes, JavaScript, redirects or other contexts.

The test suite uses an actual WordPress-style plugin with action/filter/activation registration and a persisted option; it exercises the V2 guard, applies the proposed change with explicit user-style consent, and, when system PHP is available, performs real PHP syntax validation and runs the plugin against test-only WordPress function stubs to verify hook and setting preservation and that malicious HTML is not echoed. This is an authentic PHP runtime test under mocked WordPress APIs, **not** a full installed WordPress/real database or browser penetration test. No existing user-owned WordPress plugin is silently modified.

### Explicitly authorised PHP tooling

The user must trust the exact local project, inspect it, select an installed SHA-pinned executable and separately approve each run. The server checks the saved Composer manifest hash, selected PHP source hash when linting, executable binary fingerprint and workspace trust immediately before execution. Commands are fixed for:

- PHP --version / Composer --version.
- PHP -l on one approved project-local PHP source.
- Composer validate --no-plugins (no installation).
- Existing project-local PHPUnit, PHPStan and Psalm entry points when present as non-symlinked PHP source. No auto installation or remote retrieval.

The V13/V8 runner provides a bounded 20-second timeout, maximum 64 KiB combined output, sanitised process environment, best-effort process-group termination and a single concurrent V16 run. External PHP/Composer code can **still execute arbitrary user-level processes, write files, access network or read secrets**; this is not an OS container or network sandbox and neither the IDE nor the Agent can certify package safety. A clean PHP lint is evidence of syntax only, not a security audit. Actual tool compatibility depends on installed versions and project requirements.

### Central AutoMoto Agent deployment rule

V16 does **not** introduce a separate assistant. The existing global shared Agent bridge serves Document Assistant, Research Studio, Spreadsheet/Invoice/Financial/Commercial workflows, Visual Studio and Developer Studio. V16 exposes a release-readiness control that opens and pre-fills the existing shared Agent hand-off with action deployment_readiness. The user must independently confirm before any central Agent task/conversation is created. That hand-off is traceable, auto-denies risky tool actions and is **review only**. It neither deploys nor authorises any automatic release.

**Rule for every future Studio:** No product build, export, review or source scan is to be represented as a completed deployment. Actual deployment must have a central Agent readiness record, verified tests and rollback plan, plus separate authorised human deployment approval. V16 adds no deployment endpoint, so it does not claim to enforce a gate over all existing external CI/CD infrastructure or publication routes. Upstream deployment admission checks remain a separate integration task.

### API

- GET /api/developer/studio/php/inspect?project=... — read-only Composer, WordPress plugin and PHP system tool discovery.
- POST /api/developer/studio/php/patch-preview — checksum-pinned, copy-only, narrow plugin XSS remediation.
- POST /api/developer/studio/php/run — one approved fixed PHP/Composer task and explicit risk acknowledgement.

All are authenticated local-only; hosted mode is denied. No new database schema, new permissions, persistent AI memory, automatic source writes, platform deployment, public GitHub release or Microsoft Store upload.

## Verification and remaining release gates

tests/test_developer_php.py covers real plugin hooks/settings, source checksum and guarded V2 save, PHP syntax and stubbed runtime when installed, malicious HTML output, Composer validation, path/link denial, manifest corruption, version and fingerprint trust, consent and hosted access denial. Playwright browser smoke opens a WordPress-style plugin, inspects warnings, previews a secure fix without writing it and routes readiness through the **same** central Agent panel.

Cross-platform exact-head CI must pass Python 3.10/3.13 on Linux/macOS/Windows, UI, security, Docker, VS Code, Office and installers plus the separate Windows desktop/docs builds. Real WordPress test matrix, actual PHPUnit/PHPStan/Psalm and Composer versions, compatibility with PHP 8.1–8.5 where available, end-to-end SAST/DAST for real plugins, nonces/capabilities, full deployment checks, screen-reader/keyboard operation and human security sign-off remain outstanding. Tests skip genuine PHP runtime behaviour if a native PHP executable is absent. Do not call a skipped test verified.

**Status:** Review when automated CI is verified; Verified only after manual risk, installed-runtime, plugin and deployment acceptance. No mainline merge, publication or deployment.

## Rollback

Unregister the new V16 PHP router in server.py, remove the PHP panel mount and V16 files. Existing Studios, the shared central Agent, V1–V15 workflows, source files, project trust records and user data remain unchanged. Any separately approved edits made via V2 must be restored from the user's version control or private recovery; preview-only actions require no rollback.
