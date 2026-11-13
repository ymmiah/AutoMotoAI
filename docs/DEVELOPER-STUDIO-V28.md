# AutoMoto AI Developer Studio V28/64 — Scientific Programming & Reproducibility

**Development-only milestone.** Built after V27 merged with 13/13 GitHub workflows successful. The intended outcome is meaningful research provenance and a real cross-language numerical experiment, not a demo that merely looks like a scientific execution platform.

## Implemented

**R, Julia, Octave/MATLAB-compatible source and Jupyter notebooks.** The authenticated, local-only `/api/developer/studio/science/inspect` endpoint reads a bounded input inventory: `experiment.json`, `data/measurements.csv`, canonical `experiments/compute.R`, `compute.jl`, `compute.m`, root R `renv.lock`, Julia `Project.toml`/`Manifest.toml`, optional `octave-packages.json`, and direct-child `notebooks/*.ipynb`. The scanner excludes unsafe directories and refuses linked canonical manifests/data/scripts. It never evaluates a package manifest, runs a notebook cell, calls a plotting interpreter or triggers a package installer.

**Experiment definition and independent reference.** A strict schema-version-1 `experiment.json` declares exactly one reviewed dataset, numeric `value` column, expected count/sum/mean and fixed canonical script locations. The CSV contains between two and 500 bounded finite decimal observations. Python `Decimal` independently calculates count, sum and mean before any toolchain is offered; a mismatched expected result blocks execution. Input checksums are included in an inventory SHA-256, with independent dataset/source/manifest digests. This is deterministic numerical verification, **not statistical validation of a scientific hypothesis**.

**Installed toolchains and provenance.** Rscript, R, Julia, Octave, proprietary MATLAB, Jupyter and Quarto are discovered by path/status and SHA-256 file fingerprint without execution. The local user may separately request the actual installed Rscript/Julia/Octave version. MATLAB is **discovery only**: no licence, execution, interface/API availability, statistical equivalence or runtime feature support is claimed. Notebook metadata is read from bounded Jupyter format-4 JSON, counting code cells and reporting the declared kernel; existing outputs are untrusted and no notebook is executed.

**Explicit consented reproduction.** The user can individually approve a **fixed** R, Julia or GNU Octave numerical fixture via an authenticated local API. Approval requires trusted project, per-task confirmation and acknowledgement of unsandboxed interpreter/network risk, exact source/data/manifest inventory fingerprint and toolchain executable SHA-256/path. The reviewed inputs are copied using no-follow/rehash-verified binary reads into an ephemeral directory. The fixed script prints an expected `V28_<LANG>_PASS` result. The backend independently parses count/sum/mean and marks execution `validation_failed` if it differs from the reference—even when the program exits successfully. The result records tool version output, interpreter SHA-256, package lockfile metadata SHA-256, manifest/source/dataset SHA-256, elapsed time and outcome.

**Plot evidence.** The R fixture produces a 640×400 PNG in an ephemeral `outputs/` folder. The backend validates bounded PNG bytes, records output SHA-256 and returns a preview to the Studio. The preview is not a persistent publication or proof that a figure depicts a scientifically correct model. Julia and Octave are currently numerical-only; Julia plotting ecosystems and Octave graphical backend availability are not certified.

**Existing central AutoMoto Agent.** V28 reuses the same `deployment_readiness` bridge as V1–V27 to populate a research integrity and release-review **draft**, not automatically submit or approve it. No autonomous package installation, notebook execution, remote data processing, experiment launch or deployment is granted to the Agent.

## Real CI fixtures and checks

- `tests/fixtures/v28-science/`: real immutable 5-row CSV with values 10, 20, 30, 40, 50; strict expected result **count=5, sum=150, mean=30**. R script calculates these values and draws a PNG; Julia/Octave calculate them independently using standard/built-in libraries. Synthetic project metadata declares no third-party package dependencies; do not misrepresent it as a snapshot of installed production packages.
- `tests/test_developer_science.py`: original-byte preservation, separate Decimal reference, correct SHA-256s, notebook inertness, absent/malformed manifest, altered expected result, malicious CSV/formula/NaN data, oversized inputs, symlink rejection, auth/trust/hosted denial, new/unknown API args, stale tool and data hash denial, fixed-entrypoint enforcement, and real installed interpreter numerical reproduction with image PNG validation.
- `.github/workflows/developer-science-v28.yml`: Windows/macOS/Ubuntu static/security checks; installed real R + Julia + Octave on Ubuntu for independent fixture and approval-gated API tests, including R PNG; installed Julia on macOS and Windows for actual numeric reproduction. The CI workflows may download operating-system packages and setup toolchains **only on GitHub's disposable runners**, not user machines.
- `apps/desktop/test/ui-smoke.cjs`: real browser source/CSV/notebook/manifest inventory display, no notebook execution, unchanged original sources and central Agent review-only drafting. This must be green with the full existing CI.
- Full V18–V27 language, application security, UI, package and Windows installer regression suites must remain green at the same head commit before merging into the cumulative development branch.

## Security, correctness and limitations

**A temporary project copy, source hash and controlled CLI arguments do NOT constitute OS or network sandboxing.** User-provided R, Julia and Octave source is arbitrary code. Even a fixed entrypoint can read environment variables, use network, start subprocesses, follow links, access files outside the temporary directory, change secrets or mutate the original workspace. Package loading, Julia startup behavior and interpreter binary compromise remain risks. The Studio restricts startup profiles where supported, isolates some caches, avoids package-manager calls and disallows arbitrary source filenames/CLI flags, but does not prevent malicious file/network access. Execute only independently reviewed trusted code.

The saved `renv.lock`, `Project.toml`, `Manifest.toml` and Octave metadata are hashed; their **presence or parsed declarations do not prove actual installed package versions**. V28 records installed runtime version output and all fixture inputs, but not a fully reproducible container image or formal computational environment. Scientific floating-point behavior, hardware differences, randomness, BLAS, package ABI and third-party dependency versions may affect other studies. This fixture uses simple bounded arithmetic to avoid those uncontrolled variables.

Jupyter code cells and embedded outputs are treated as untrusted metadata; the Studio cannot execute notebooks in V28. Quarto is discovered only. MATLAB is proprietary and untested by the V28 runtime acceptance. GNU Octave's overlapping numerical subset must not be treated as proof of compatibility with all MATLAB toolboxes.

**No general-purpose research editor or plotting workflow has been authorised.** Source files are still edited via the existing trusted Developer Studio editor. The fixed experiment schema is a first safe integration; adding arbitrary experiments requires new threat modelling, data provenance rules, isolation, approvals and scientific validation.

### Recovery and review

Commit or back up local source/data before allowing any external interpreter to execute. If execution causes host-side changes, restore via version control, backups and OS security controls. Revert V28 development commits without altering V1–V27 or stored user data.

V28 is **Review**, not Verified, until exact-head real R/Julia/Octave computations and graphics, Windows/macOS/Linux static security, core app, UI and packaging regression, provenance/plot accessibility checks, independent security and scientific review, and explicit human sign-off. Do not merge into `main`, trigger research publication or claim full MATLAB support.

### Official references

- [Rscript](https://stat.ethz.ch/R-manual/R-devel/library/utils/html/Rscript.html)
- [Julia command-line interface](https://docs.julialang.org/en/v1/manual/command-line-interface/)
- [GNU Octave CLI](https://docs.octave.org/latest/Command-Line-Options.html)
- [Jupyter Notebook format](https://nbformat.readthedocs.io/en/latest/format_description.html)
- [MATLAB](https://www.mathworks.com/help/matlab/)
