# Developer Studio V41, V44 and V45: run, preview and local Git

This build covers three roadmap items. V41 runs your app and tests for real and shows the results. V44 shows a live preview of your app at a local address. V45 adds local Git: status, branches, staging, commits, diffs and conflicts.

All three live behind entry points that already existed. The desktop chat view looks exactly as it did before.

| Where | What you get |
| --- | --- |
| **Tools → Run my app** | Three guided steps: 1 Start your app, 2 See it live, 3 Check it works. Step 3 shows the result in one card: a small health ring (for example "3/4"), the result in plain words with the names of failing checks, and a Check again button. The expert view (every command, live output and test counts) is under Advanced details. |
| **Run app / Run tests** (editor view) | Opens Run my app and starts the detected command once you approve it. If the project has no detected command, the button asks the assistant instead, as it did before. |
| **Review → Tests** | Also shows the latest real test run, with passed, failed and skipped counts. |
| **Tools → Checkpoints (Git)** | Three guided steps: 1 See what changed (tap a file for its diff), 2 Describe it (a message is suggested), 3 Save checkpoint. A conflict becomes step 1, "Fix the disagreement", with Keep mine, Keep theirs and Keep both. The expert view (branch picker, new branch, staging, diffs, commit box, recent commits) is under Advanced details. |
| **Phone and tablet (900px and below)** | The same panels open from the Tools tab, using the existing sheet. On a tablet the sheet sits beside the chat. The test result card has the same size, spacing and alignment at every width: a 46px ring, 12px from the text, with a 36px Check again button under the result. |

## V41: real run and test results

**Detection only reads files.** It looks at `package.json` (the `dev`, `start`, `serve`, `preview` and `test` scripts, using npm, pnpm, yarn or bun to match the lockfile), `manage.py`, pytest settings or `test_*.py` files, `go.mod`, `Cargo.toml`, and an `index.html` with no `package.json` (served as a static site preview). Nothing runs during detection.

**Approval.** A command runs only when all of these hold:

- the project is trusted (changes allowed);
- you confirm the exact command in a dialog;
- the request includes `approved: true` and the `command_sha256` you were shown. If the manifest changed since you looked, the request is refused with 409.

There is no free-form command box. Only the detected list can run.

**Results.** Output streams into the panel. For tests, the studio reads the summary printed by pytest, Jest, Vitest, Mocha, Go (`-v`) and Cargo, and shows passed, failed and skipped counts plus the names of failing tests. If it can't read the counts, it says so and the full output stays visible.

**Lifecycle.**

- Each run is its own process group. Stop kills the whole tree: `killpg` on macOS and Linux, `taskkill /T` on Windows.
- Apps stop after 60 minutes and tests after 15.
- Each project can have one app and one test run at a time, with at most four runs overall.
- Every run is stopped when AutoMoto exits.
- Runs use the same reduced environment as the other studio tools. PATH excludes executables inside approved project folders, and `CI=true`, `NO_COLOR=1` and `PYTHONDONTWRITEBYTECODE=1` are set. pytest runs with `-p no:cacheprovider`, so running tests doesn't add cache files to your Git changes.

## V44: live preview on 127.0.0.1 only

- Each app gets a free port on 127.0.0.1. `HOST`, `PORT`, `BIND` and the Flask variables point to loopback. Vite, Astro, SvelteKit, Next.js, Angular and Nuxt also get explicit `--host 127.0.0.1 --port <port>` flags. Django gets `runserver 127.0.0.1:<port>`, and the static preview gets `--bind 127.0.0.1`.
- **Exposure watchdog.** While an app runs, AutoMoto keeps probing its port on this computer's network addresses. If anything other than loopback can reach it, the app is stopped straight away and the panel says "Blocked: not local". The tests cover this with a server bound to `0.0.0.0`.
- The preview URL is only shown once the app answers on 127.0.0.1. It loads in a sandboxed iframe with Reload and Open in browser buttons. The app's CSP adds `frame-src 'self' http://127.0.0.1:* http://localhost:*` and nothing else; `frame-ancestors 'none'` is unchanged.

## V45: local Git, confined to the project, never pushing

**Confinement.**

- Every Git call sets `GIT_DIR=<project>/.git` and `GIT_WORK_TREE=<project>`. Git can't climb into a parent repository: a folder inside someone else's repo shows as "not a Git repository" rather than the parent's status.
- A `.git` *file* (a worktree or submodule pointer) and a symlinked `.git` are both refused.
- Paths must be project-relative. `..`, absolute paths, leading `-` and `.git` are rejected, and you can only stage files that Git currently lists as changed.

**No network.**

- There is no push, pull, fetch, clone or remote endpoint.
- Every call also runs with `-c protocol.allow=never`, an empty credential helper and `core.sshCommand=false`, so no transport can be used even by accident.
- Commit responses include `"pushed": false`.

**No extra programs.**

- Hooks are off (`core.hooksPath` points to the null device), as are fsmonitor, signing, the pager, the editor and external diff tools. Diffs run with `--no-ext-diff --no-textconv`.
- A repository whose own config defines filter drivers, textconv or diff commands, merge drivers, includes, `core.worktree` or a GPG program is refused with a plain explanation.

**Changes need trust.**

- Init, stage, unstage, branch, switch, resolve and commit all need a trusted project.
- Commit and resolve also need `confirmed: true`. The UI shows a confirmation that names the branch and says nothing is pushed.
- Switching branches never forces. Git refuses if uncommitted work would be lost.
- If Git has no name or email configured, the commit box asks for them and passes them for that one commit only, without changing your Git config.

**Secrets.** Files that look like secrets (`.env*` except `.env.example`, private keys, `.pem`, `.p12`, `.npmrc`, `.pypirc`, credentials files) are flagged. They can't be staged and their contents are never shown.

**Conflicts.** The conflict view reads the markers (including diff3 base sections) and shows yours and theirs side by side. For each block you choose Keep mine, Keep theirs or Keep both. Saving checks the file hasn't changed since you looked (SHA-256), writes it atomically and stages it. The commit stays blocked until every conflict is resolved.

## API (local only, closed in hosted mode)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/developer/studio/run/detect?project=` | Detected recipes, each with a `command_sha256`. Runs nothing. |
| POST | `/api/developer/studio/run/start` | `{project, recipe, command_sha256, approved: true}`. Needs a trusted project. |
| GET | `/api/developer/studio/run/status?project=&run_id=&since=` | Output since an offset, plus status, `preview_url` and test `summary`. |
| POST | `/api/developer/studio/run/stop` | `{project, run_id}`. |
| GET | `/api/developer/studio/git/status?project=` | Branch, files, counts, recent commits and identity. |
| POST | `/api/developer/studio/git/init` | `{project, confirmed: true}`. |
| GET | `/api/developer/studio/git/branches?project=` | Local branches only. |
| POST | `/api/developer/studio/git/branch` | `{project, name, switch}`. |
| POST | `/api/developer/studio/git/switch` | `{project, name}`. |
| POST | `/api/developer/studio/git/stage` | `{project, paths[], stage}`. |
| POST | `/api/developer/studio/git/commit` | `{project, message, confirmed: true, author_name?, author_email?}`. |
| GET | `/api/developer/studio/git/diff?project=&path=&staged=` | Unified diff. Untracked files appear as all-added. |
| GET | `/api/developer/studio/git/conflict?project=&path=` | Conflict blocks and the file's SHA-256. |
| POST | `/api/developer/studio/git/resolve` | `{project, path, choice or choices[], expected_sha256, confirmed: true}`. |

## Tests

`tests/test_developer_run_git.py` covers:

- **Detection.** It runs nothing and pins dev servers to loopback.
- **Approval gate.** Requests are refused without trust, without `approved`, with a stale hash or for an unknown recipe.
- **Live static preview.** The page is served on 127.0.0.1, a second app is refused, Stop closes the port, and a server on `0.0.0.0` is blocked.
- **Real pytest run.** One passing, one failing and one skipped test are counted correctly.
- **Test summary parsing.** pytest, Jest, Vitest, Go, Cargo and Mocha output.
- **CSP.**
- **Git basics.** Init, stage, commit and branches; secret, traversal and option-injection refusals; no push routes, and the network is blocked.
- **Git confinement and safety.** A parent repository isn't used, a dangerous repo config is refused, and hooks don't run.
- **Conflicts.** A full merge conflict is resolved and committed, and diff3 markers are parsed.

## Known limits

- The loopback check is a watchdog, not an OS firewall. An app that briefly listens on all interfaces is stopped within about a second, not prevented from starting.
- Commands come only from detection. Projects with unusual start scripts can still use the assistant's Run app request.
- Project virtual environments are not put on PATH, which matches the other studio tools. pytest uses the `python3`/`python` on your PATH.
- The preview needs the app to allow framing. Apps that send `X-Frame-Options: DENY` show a blank frame, so use Open in browser.
- Git LFS or other filters set in your *global* Git config still run, because that config is yours. Repository-local filters are refused.
