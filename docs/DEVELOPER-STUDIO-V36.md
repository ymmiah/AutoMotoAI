# Developer Studio V36: infrastructure and configuration files

V36 checks Terraform and OpenTofu, Nix, Bicep, CUE, Dockerfiles, Kubernetes YAML and shaders (GLSL, HLSL, WGSL, Metal), and explains each problem in plain words with a line number and how to fix it. **It never deploys, applies, builds images or changes any server, cluster or cloud.**

The desktop main screen is unchanged. V36 lives in **Tools → Infrastructure & config**, on desktop, tablet and phone.

## What you see

1. **Check my config files.** Reads files only. A summary card with the shared health ring shows how many files have no problems, then one card per file, problems first. Each finding has a label (**Problem**, **Worth fixing** or **Tip**), the line, what's wrong and how to fix it.
2. **Double-check with …** (optional). When a matching validator is installed, a button runs it on a copy of that one file after you confirm. The exact command is shown with a copy button. When it isn't installed, the card shows the install command (with a copy button) or the official install link.

Advanced details lists every validator, whether it's installed, and its exact command (each with a copy button), plus the list of commands AutoMoto never runs.

## Built-in checks (no tools needed)

| File | Checks |
| --- | --- |
| Terraform `.tf`, `.tfvars` | bracket balance (comments, strings and heredocs ignored), `0.0.0.0/0` or `::/0` open to the internet, passwords or keys written into the file, `local-exec`/`remote-exec` provisioners, no `required_version` |
| `*.tfstate` | flagged as a problem because state often holds secrets. **Its contents are never read.** |
| Nix | bracket balance (including `''…''` strings), `fetchurl`/`fetchTarball`/`fetchGit` without a pinned hash, `flake.nix` without `flake.lock` |
| Bicep | bracket balance, secret-looking `param … string` without `@secure()`, registry modules (`br:`/`ts:`), secrets written into the file |
| CUE | bracket balance, no `package` line, secrets written into the file |
| Dockerfile / Containerfile | unknown instructions, FROM first, unpinned or `:latest` base images (stage names understood), final stage running as root, `ADD <url>`, `curl … \| sh`, secrets in `ENV`/`ARG` |
| Kubernetes YAML (only files with `apiVersion` and `kind`) | YAML errors with line, missing `metadata.name`, privileged containers, `hostNetwork`/`hostPID`/`hostIPC`, `hostPath` volumes, unpinned images, no resource limits, no `allowPrivilegeEscalation: false`, Secret manifests with values |
| Shaders | bracket balance; GLSL `#version` and `main()` for stage files; WGSL entry points |

Secret **values are never returned**, only the setting's name and line.

## Optional offline validators

| Validator | Files | Command |
| --- | --- | --- |
| Terraform / OpenTofu | `.tf` | `terraform fmt -check -diff -no-color <file>` (syntax and formatting; no `init`, no providers, no state) |
| Nix | `.nix` | `nix-instantiate --parse <file>` (parse only; no evaluation, no build) |
| Bicep | `.bicep` without registry modules | `bicep build --stdout <file>` |
| CUE | `.cue` | `cue vet <file>` |
| Hadolint | Dockerfile | `hadolint --no-color <file>` |
| glslang | `.vert` `.frag` `.comp` `.geom` `.tesc` `.tese` | `glslangValidator <file>` |
| naga | `.wgsl` | `naga <file>` |

**Never run:** `terraform init/plan/apply/destroy`, `tofu init/plan/apply`, `kubectl`, `helm`, `docker build/run/push`, `nix build/develop/run`, `az deployment`, `bicep publish`. There is no free-form command box.

## Safety

- Double-checks need a trusted project, your confirmation, the file's SHA-256 (refused with 409 if the file changed) and the validator's exact bytes (refused if the program changed).
- The validator sees only a temporary copy of that one file. It runs with an empty temporary home folder and a reduced environment, so cloud credentials (`AWS_*`, `AZURE_*`, `GOOGLE_*`), `KUBECONFIG`, `~/.terraformrc` and provider plugins aren't passed. `CHECKPOINT_DISABLE=1` stops Terraform's version check call. There's a 60-second limit, capped output, and one check at a time.
- Shell wrappers and executables inside project folders are refused.
- YAML is read with the safe loader, and only specific paths are looked at, so recursive aliases can't loop.

## API (local only)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/developer/studio/infra/inspect?project=` | Files, findings, counts, validators with SHA-256. Runs nothing. |
| POST | `/api/developer/studio/infra/validate` | `{project, path, validator, expected_file_sha256, expected_executable, expected_sha256, confirmed: true, accept_unsandboxed_validator: true}` |

## Tests and CI

`tests/test_developer_infra.py` covers: nothing is deployed or changed; file kinds (compose files aren't treated as Kubernetes); Terraform, Docker, Kubernetes (with exact lines), Nix, Bicep, CUE and shader findings; secret values never returned; state files never read; broken and recursive YAML; the bracket scanner; missing validators with install hints; trust, file hash and validator pinning; cloud credentials not passed to the validator; refused state files and unknown validators; registry Bicep modules; and authentication.

The **Developer Studio V36 Infrastructure and configuration acceptance** workflow runs those tests on Ubuntu and Windows (and macOS when V36 files change), then installs Terraform 1.17.2 (SHA-256 verified) and glslang on a disposable Ubuntu runner and runs real validators on good and broken files through the API, checking that no `.terraform` folder appears.

## Limitations

- Built-in checks are careful pattern and structure checks, not the real tools. A clean result doesn't prove a plan will apply or a pod will start.
- Helm templates, Kustomize overlays and HCL expressions aren't rendered.
- Real validators are proved in CI for Terraform and glslang only. Nix, Bicep, CUE, Hadolint and naga run if you install them, but AutoMoto hasn't verified them in CI.
- Validators are not OS-sandboxed. They're offline by design, but AutoMoto can't prove a third-party tool makes no network calls.

## Recovery

- **"The file changed since you looked":** press Check again, then retry.
- **A validator shows Not installed after you installed it:** restart AutoMoto so it sees the new PATH.
- **A Terraform state file was flagged:** move state to a remote backend, add `*.tfstate*` to `.gitignore`, and rotate any secrets it held.
- **Undo:** V36 never writes to your project, so there's nothing to undo. To remove the feature, revert the V36 PR.
