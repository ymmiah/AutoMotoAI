# Publishing AutoMoto AI (for Yasin)

Everything here is free. The GitHub Release is already automated; the stores need **one-time accounts and
tokens that only you can create**. Once the secrets exist, pushing a tag publishes everywhere.

## 0. How a release works

```bash
# bump the version everywhere (automoto/__init__.py, pyproject.toml, apps/vscode/package.json + package-lock.json,
# apps/desktop/*), update CHANGELOG.md, commit, then:
git tag v5.5.0 && git push origin v5.5.0
```

The **Publish** workflow (`.github/workflows/publish.yml`) then:

| Step | Runs when | Skips with a notice when |
|---|---|---|
| Build + test the `.vsix`, upload as artifact | always | — |
| VS Code Marketplace | repo secret `VSCE_PAT` exists | not set |
| Open VSX (VSCodium, Cursor, Gitpod…) | repo secret `OVSX_PAT` exists | not set |
| Build sdist + wheel, `twine check` | always | — |
| PyPI (trusted publishing, no token) | repo **variable** `PYPI_PUBLISH` = `true` | not set |

| Attach the `.vsix`, wheel and sdist to the tag's GitHub Release (a draft) and write the notes | every `v*` tag | — |

The **Windows app** workflow (`.github/workflows/desktop.yml`) builds and smoke-tests the installers (not
code-signed), builds the **Microsoft Store package** (`automoto-ai-msstore` artifact, see
[Windows distribution](WINDOWS-DISTRIBUTION.md)), and on a tag attaches the installers plus `latest.json` and
`SHA256SUMS.txt` to the release.

**Release file names** (from 5.6.0 Beta 4 on; older releases keep their names):

| File | For |
|---|---|
| `AutoMoto-AI-Setup-<version>-Windows-x64.exe` (+ `.sig`) | Windows, most people |
| `AutoMoto-AI-<version>-Windows-x64.msi` (+ `.sig`) | Windows, IT / all users |
| `AutoMoto-AI-<version>-VSCode.vsix` | VS Code |
| `automoto_ai-<pep440>-py3-none-any.whl`, `automoto_ai-<pep440>.tar.gz` | pip (names pip needs) |
| `latest.json`, `SHA256SUMS.txt` | the app's updater; checksums |

The notes start with a **"Which file do I need?"** table, then the CHANGELOG section and the SHA-256 of every
file (`scripts/ci/release_notes.py`; the names are defined there too). The release stays a **draft** until you
publish it. For a beta, copy its `latest.json` to `packaging/updater/beta.json` afterwards.

## 1. VS Code Marketplace (free)

1. Sign in at <https://dev.azure.com> with a Microsoft account (create an organisation if asked — free).
2. *User settings → Personal access tokens → New token*:
   * Organization: **All accessible organizations** (important — otherwise publishing fails with 401)
   * Scopes: *Custom defined → Marketplace → **Manage***
   * Expiry: up to 1 year (put a reminder in your calendar)
3. Create the publisher at <https://marketplace.visualstudio.com/manage> → *Create publisher* → ID **`ymmiah`**
   (must match `"publisher"` in `apps/vscode/package.json`).
4. GitHub → repo *Settings → Secrets and variables → Actions → New repository secret*: `VSCE_PAT` = the token.
5. Manual alternative: `cd apps/vscode && npx vsce login ymmiah && npx vsce publish --no-dependencies`.

## 2. Open VSX (free)

1. Sign in at <https://open-vsx.org> with GitHub.
2. Profile → link an **Eclipse Foundation** account and sign the *Publisher Agreement* (free, one form).
3. *Settings → Access Tokens → Generate new token*.
4. Create the namespace once: `npx ovsx create-namespace ymmiah -p <token>`.
5. Repo secret `OVSX_PAT` = the token. (Optionally claim the namespace as verified via an issue on
   github.com/EclipseFdn/open-vsx.org.)

## 3. PyPI (optional, free, no token stored)

1. Create an account at <https://pypi.org> and turn on 2FA.
2. *Your projects → Publishing → Add a new pending publisher* → GitHub:
   owner `ymmiah`, repository `AutoMotoAI`, workflow `publish.yml`, environment `pypi`, project name `automoto-ai`.
3. GitHub → *Settings → Environments → New environment* `pypi` (optionally require your approval).
4. *Settings → Secrets and variables → Actions → Variables* → `PYPI_PUBLISH` = `true`.
5. Next tag push uploads the sdist and wheel; people can then `pip install automoto-ai`.

## 4. Check before you tag

```bash
python -m pytest -q
bandit -q -r automoto -ll && pip-audit -r requirements.txt
cd apps/vscode && npm ci && npm run lint && npm run test:unit && npm run package && npm audit --audit-level=moderate
python -m build && twine check dist/*
```

## Notes

* Store listings use `apps/vscode/README.md`, `CHANGELOG.md`, `LICENSE` and `media/icon.png`.
* Marketplace versions can't be reused — bump the version for every publish.
* Never paste tokens into code, issues or chat; only into GitHub secrets. Revoke a leaked token at once
  (Azure DevOps → Personal access tokens / Open VSX → Access Tokens).
