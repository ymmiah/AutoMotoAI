# Developer Studio V31/64 — Haskell, OCaml, Common Lisp, Scheme and Prolog

**Development-only milestone.** Built from V30 on the cumulative development branch. Nothing in this change authorises merging to main, publishing, installation on a customer device or deployment.

## Delivered

The authenticated, local-only GET /api/developer/studio/logic/inspect?project=... endpoint performs a bounded non-executing read of Haskell (.hs/.lhs), OCaml (.ml/.mli), Common Lisp (.lisp/.lsp/.cl), Scheme (.scm/.ss) and recognised Prolog (.pl) source. A Perl .pl file is not labelled Prolog unless a Prolog-looking rule/directive is present. Prolog facts without that syntax can remain unclassified.

Discovery records SHA-256 fingerprints, heuristic source declarations, potential unsafe-code signals and metadata for Cabal/Stack, Dune/Opam, ASDF and Prolog pack manifests. It does NOT execute project scripts, Lisp reader macros, macros, Prolog directives or external tools. It does not fetch packages, run compilers, resolve dependency graphs or verify semantic references. Limits: 140 relevant files, 192 KiB per source, 512 KiB per manifest and 8 MiB in total. A truncated scan denies execution; symlinked canonical fixture or project-control files are refused.

Installed executable evidence includes runghc, GHC, Cabal, Stack, OCaml, Dune, Opam, SBCL, CLISP, Guile and SWI-Prolog. Paths and checksums are obtained without running binaries.

The authenticated POST /api/developer/studio/logic/run allows five fixed actions only, on canonical dependency-free fixtures:

| Fixture | Pinned tool | Exact fixed arguments |
| --- | --- | --- |
| Haskell | runghc | test/v31_fixture.hs |
| OCaml | ocaml | -noinit test/v31_fixture.ml |
| Common Lisp | sbcl | --noinform --no-sysinit --no-userinit --script test/v31_fixture.lisp |
| Scheme | guile | --no-auto-compile -s test/v31_fixture.scm |
| Prolog | swipl | -q -f none -s test/v31_fixture.pl -g main -t halt |

Each action requires an explicitly trusted local project, exact project and executable SHA-256, complete inventory, fresh confirmed consent and an unsandboxed network/host risk acknowledgement. Only the SHA-verified fixture file is copied to a private temporary working folder. Successful outcome requires a real zero exit code AND the corresponding V31_*_PASS 42 output marker. No arbitrary command lines, general project builds, source writes, package installers or automatic Agent actions are admitted.

Developer Studio contains a new V31 panel with source fingerprints, risk and availability feedback, keyboard-native controls, accessible status messages, and a button to *draft* a review-only request for the **existing central AutoMoto Agent**. It never submits that Agent task automatically or increases Agent privileges.

## Security boundary

**Temporary staging is not an OS, filesystem or network sandbox.** Even fixed scripts and installed interpreters can access host files, user secrets, startup hooks, the network and binaries outside the temporary copy. Hashes detect changes but do not certify safety, prove no network activity, guarantee provenance or prevent compromised interpreters. Execution on untrusted source requires an independently isolated environment. Treat parser results and inferred declarations as unverified data, not instructions.

No general Cabal/Stack compilation, Dune builds, ASDF project loading, Scheme package management, Prolog package resolution, LSP semantic navigation, debugger support, or native Windows/macOS compilation is certified here.

## Testing and acceptance

- tests/test_developer_logic.py covers read-only source preservation, source/manifests, ambiguous .pl classification, malicious ASDF non-evaluation, consent and trust, checksum drift, rejected symlinks, hosted/auth denial, fixed CLI validation, bad markers and an opt-in real interpreter path.
- .github/workflows/developer-logic-v31.yml performs V31 static auth/source/security tests on Windows, macOS and Ubuntu, and executes five real toolchain fixtures plus consented API acceptance on disposable Ubuntu runners.
- Full prior Developer Studio V18–V30, core CI, Windows app, docs and browser smoke workflows must also pass on the **exact PR head**. CI status is distinct from required accessibility, supply-chain, installed OS and human security review.

**Recovery:** Revert the V31 branch changes without touching main, customer accounts or data. Back up user projects before any independently approved external interpreter execution; restore affected files from version control or a backup if a runtime creates unintended side effects.

## Reference manuals

- [GHC runghc](https://downloads.haskell.org/ghc/latest/docs/users_guide/runghc.html)
- [OCaml manual](https://ocaml.org/manual/)
- [SBCL manual](https://www.sbcl.org/manual/)
- [GNU Guile](https://www.gnu.org/software/guile/manual/)
- [SWI-Prolog](https://www.swi-prolog.org/pldoc/man?section=cmdline)
