# AutoMoto AI — Developer Studio V13: JavaScript & TypeScript

**Milestone:** Phase 4 V13/64 — JavaScript and TypeScript. [Notion](https://app.notion.com/p/4131cc3365d6817fbecffff219756ecc).

**Branch:** feature/developer-studio-v13-js-ts-workflows; dependent on V12 PR #65. V12 was not merged to the development branch at V13's creation. V13 is a draft development PR, not a mainline release.

## Implemented

V13 introduces a local, opt-in Node.js project runtime/workflow on top of Developer Studio V1's approved-project identity and V8's executable fingerprinting and sanitised subprocess launcher. It does not run any code, build, package installation, version command or external network request during project inspection.

### Project inspector

- Bounds and parses project-root package.json (maximum 96 KiB, rejects malformed JSON and duplicate JSON keys).
- Reports declared package name, private flag, packageManager selection, package.json SHA-256, Node engine version requirement, declared dependencies, TypeScript/tsconfig presence, local node_modules directory presence and declared test/build/lint/typecheck scripts.
- Finds Node.js-relevant framework and test-tool declarations: React, Next.js, Vue, Angular, Svelte/SvelteKit, Nuxt, Vite, Astro, Express, NestJS, Vitest, Jest, Playwright.
- Detects npm, pnpm and yarn lockfiles and conflicting lockfile managers without installing packages. A declared dependency version is **not** proof of the installed version. Lockfile hashes are informational; package/dependency integrity and actual versions are not certified.
- Finds bounded local test candidate files. Symlinks, restricted directories and source files exceeding V7 limits are excluded.
- Inspects installed node, npm, pnpm and yarn executable locations and SHA-256 using the existing V8 system-tool boundary. Inspection does not run version commands; actual reported versions are available only after a separately confirmed tool-version run.
- Windows shell-script wrappers (.cmd, .bat, .ps1) are deliberately not executed in this version because shell=False alone does not give safe argv handling for batch scripts. Native installed executables may still run. npm/pnpm/yarn support is therefore conditional on supported installed native launchers.

### Actual task execution, always separately approved

The user first trusts the exact workspace and inspects it. Each task then requires a fresh UI confirmation explaining untrusted-code, filesystem and network risks, plus literal server-side approval fields and the SHA-256 hashes of both the inspected package.json and exact installed executable. V13 rechecks both immediately before starting; trust revocation prevents execution. No arbitrary URL, custom argument string, package installation, npx, npm exec, watch mode or interactive shell is exposed.

Allowed task kinds:

1. Tool version: the approved installed runtime/package manager with --version, returning its actual output. A reported runtime version is not the same as an independently certified compatibility matrix.
2. JavaScript syntax: approved Node --check on one project-local .js/.cjs/.mjs/.jsx source. This parses syntax; it does not run tests or resolve full framework/build dependencies.
3. Node unit test: approved Node --test on one project-local .test/.spec .js/.cjs/.mjs file. Runs genuine test code and may read/write arbitrary host files; no OS sandbox is claimed.
4. TypeScript check: approved Node runs an existing project-local TypeScript compiler entry point at node_modules/typescript/bin/tsc with --noEmit, --incremental false and --project tsconfig.json. This requires locally installed TypeScript and declared TypeScript dependency/tsconfig; symlinked SDK paths are not accepted by default. Some valid pnpm/symlink layouts will need explicit future support.
5. Package scripts: approve exactly one existing package.json script from test, build, lint or typecheck, with the selected matching npm, pnpm or yarn executable. npm uses --ignore-scripts --offline --no-audit --no-fund run SCRIPT; the specified script **still runs**, despite ignore-scripts, while pre/post lifecycle scripts should be skipped. pnpm and yarn do not receive a fabricated cross-manager offline flag. Package scripts may install, run other tools, read or alter files, and make network calls, so there is **no guarantee of offline execution or supply-chain isolation**.

All tasks run from the actual approved source project, with the V8 sanitised process environment, no shell=True, explicit process-group termination where supported, one active V13 run, at most 20 seconds runtime and 64 KiB combined output. Errors, timeouts and output overflow are reported. Output from external programs is untrusted and rendered as inert text. No automatic installation/build/test takes place on project opening, navigation or inspection.

V13 annotates common TypeScript compiler diagnostics (TS error code, source line/column) and simple file:line:column diagnostics when source paths can be validated. A nonzero exit status is a failed task, not a successful build. A successful build script only proves that selected command exited with 0 in that environment; it does **not** independently certify framework correctness or all generated artefacts.

**External executables are not operating-system sandboxes.** V13 cannot prevent approved project code, package scripts or transitive dependencies from modifying files, invoking shell commands, running network requests, using global package-manager configuration, or spawning other programs. V8 process-tree termination is best-effort, especially on Windows. Never run unfamiliar repositories or package scripts as a privileged user.

### API

- GET /api/developer/studio/javascript/inspect?project=... — read-only package, framework, test, scripts and toolchain SHA-256 inspection.
- POST /api/developer/studio/javascript/run — one fixed task, selected installed tool, optional project-local file or allowlisted script, exact approved executable and manifest checksums, confirmed=true and accept_unsandboxed_execution_and_write_risk=true.

Both routes require existing local-only authentication. Hosted mode remains default-denied. There are no migrations, cloud API calls, account uploads, persistent process schedules or new project settings.

### Automated and manual verification

tests/test_developer_javascript.py covers actual Node.js runtime version and syntax, real passing/failing built-in Node unit tests, an actual npm build where a supported native launcher is available, mock TypeScript command/diagnostic contract, manifest duplicate-key rejection, path and symlink controls, declared package-manager conflicts, no installation, permission and SHA revalidation, explicit confirmations, timeout and hosted access denial.

The existing Playwright browser smoke adds actual local Node test and runtime version execution with confirmation-cancel prevention, inert diagnostic output and no source modifications.

Manual acceptance remains required for an installed multi-framework matrix: real TypeScript SDK on Windows/macOS/Linux, npm/pnpm/yarn native paths, Next.js/React/Vue/Angular framework builds, large workspaces, source/diff and generated artefacts, actual runtime/version compatibility and accessibility. TypeScript compiler stub tests are **not** a substitute for a real installed TypeScript SDK. Framework-declared version metadata is not proof that packages are installed or secure.

**Release policy:** Review after automated CI evidence; Verified only after real installed SDK/framework, security and accessibility gates. No mainline merge, Microsoft Store publication or production deployment.

### Rollback

Unregister the V13 router from server.py, remove its Developer Studio UI mount, and delete the new V13 source/test files. No existing workspace state, source project file, V1–V12 function or Research Studio record needs migration. Side effects from separately approved external package scripts are not automatically reversible; inspect and restore the project using version control or backups as appropriate.

Official documentation: Node [test runner](https://nodejs.org/api/test.html), TypeScript [CLI compiler options](https://www.typescriptlang.org/docs/handbook/compiler-options.html), npm [run-script semantics](https://docs.npmjs.com/cli/v10/commands/npm-run-script).
