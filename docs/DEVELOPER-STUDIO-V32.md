# Developer Studio V32/64 — Legacy and specialist systems

**Development only.** This milestone builds on the merged, green V31 cumulative development branch. It does not authorise main-branch merges, software publication, production deployment, or modification of user projects.

## Delivered

- Authenticated, local-only source inspection for Fortran (.f90, .f95, .f03, .f08, .f, .for), COBOL (.cob, .cbl, .cpy), Ada (.adb, .ads), Pascal/Delphi (.pas, .pp, .dpr, .dpk), Assembly (.asm, .s), Visual Basic (.vb) and VBScript (.vbs).
- Bounded SHA-256 source inventory, heuristic symbol navigation, possible process/file/network risk indicators, inert fpm.toml, Alire, GNAT .gpr, Lazarus, VB project and Makefile metadata, and installed toolchain fingerprints. No project file, manifest or dependency script is evaluated during discovery.
- Tool discovery checks installed gfortran, cobc, gnatmake, fpc, nasm and vbnc without running them. Unsupported or missing toolchains are reported rather than simulated.
- Five *fixed*, independent and explicitly approved compiler operations on disposable copies of canonical sample sources: gfortran, GnuCOBOL, GNAT, Free Pascal and NASM (Linux ELF x86-64). These compile only. The generated objects are hashed as evidence and removed with the temporary workspace. No generated executable is launched.
- Visual Basic and VBScript have **inspection-only** support. Neither is compiled or executed by V32.
- The Developer Studio V32 panel displays source fingerprints, symbol heuristics, risk indicators, dialect uncertainty and toolchain status. Its Central AutoMoto Agent button drafts a review-only request; it never submits or executes it.

## Security controls and limitations

- Local API: GET /api/developer/studio/legacy/inspect and POST /api/developer/studio/legacy/compile.
- Explicit trusted project, SHA-256 of the complete bounded inventory and installed compiler, fixed task-to-tool pairing, fresh per-run consent and acknowledgement of unsandboxed compiler/network risks are required.
- No caller-defined shell, compiler arguments, paths, arbitrary source builds, package installs, network requests by Studio or deployment actions.
- Inspection limits: 150 relevant files, 192 KiB/source, 256 KiB/manifest, 8 MiB aggregate. Incomplete inventories deny compilation. Known symlinked project controls and canonical fixtures are refused.
- **Compiler execution is not isolated.** A malicious or compromised compiler can read or write host files and use the network with the user's privileges, despite source staging and SHA checks. Hashes detect changes, not safety. Real compilers must run on independently isolated disposable infrastructure for untrusted material.
- Assembly syntax/architecture is ambiguous; NASM sample uses Linux ELF64 only. .vb does not establish VB.NET vs classic VB, and .vbs is VBScript. COBOL dialects and copybooks, Ada GPR/Alire projects, Delphi/Lazarus GUI builds, Fortran fpm, assembly architecture variants and VB toolchains are **not** certified. No cross-platform real compiler support is claimed without toolchain evidence.

## Evidence and quality gate

- tests/test_developer_legacy.py: source preservation, seven file categories, inert manifests, SHA drift, symlink denial, authentication/hosted refusal, consent, fixed command allowlist, deleted outputs, no arbitrary commands, real installed toolchain integration.
- .github/workflows/developer-legacy-v32.yml: Python source/security regression tests on Ubuntu, macOS and Windows; real GFortran, GnuCOBOL, GNAT, Free Pascal and NASM compilers on disposable Ubuntu CI only.
- Browser smoke checks source display, inert Makefile, no compilation without consent, and review-only Central Agent handoff.
- All V18–V31 regression workflows, core CI, Windows app and docs must pass on the **same PR head**. Human accessibility, installed-app, toolchain provenance and unsandboxed-process review remain mandatory before verification.

**Recovery:** Close or revert the V32 development PR without changing main. Approved compilers may still cause host-side effects; back up and verify the workspace before any real compiler execution. Restore affected files from independent backups or version control.

## Primary toolchain documentation

- [GNU Fortran](https://gcc.gnu.org/fortran/)
- [GnuCOBOL](https://gnucobol.sourceforge.io/)
- [GNAT Ada](https://gcc.gnu.org/onlinedocs/gnat_ugn/)
- [Free Pascal](https://www.freepascal.org/docs.html)
- [NASM](https://www.nasm.us/docs.php)
- [Microsoft Visual Basic](https://learn.microsoft.com/en-us/dotnet/visual-basic/)
