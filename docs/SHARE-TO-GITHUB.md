# Share to GitHub or GitLab

Developer Studio → **Tools → Share to GitHub or GitLab** sends your checkpoints (commits) to GitHub or
GitLab, and brings in new ones from there. It works with the account you connected in
[Connect GitHub or GitLab](GIT-SIGN-IN.md). Nothing is sent until you press **Share**.

## The four steps

1. **Connect your account.** If you aren't signed in yet, the button opens Connect GitHub or GitLab.
2. **Pick where to share.** Type the repository as `owner/name`, or paste its web address. If the
   project already points at a GitHub or GitLab repository, it's filled in for you. You can also
   change the branch name on the website. This choice is saved in AutoMoto's own data folder, never
   in the project's `.git/config`.
3. **Check what will be shared.** AutoMoto lists every checkpoint (short ID, message, author) and every
   file that would be sent, and checks them all (see below). If something is wrong, it says exactly what
   and where, in plain words.
4. **Share.** One click, after a final confirmation that repeats exactly what will happen. When it's
   done you get links to the branch and to "Ask for a review" on the website.

**Get latest** (below the steps) looks for new checkpoints on the website and lists them. Nothing
changes until you press **Bring them in** (a fast-forward) or, if both sides changed, **Combine both**
(a merge; conflicts go to Checkpoints, where you pick what to keep).

## What is checked before anything is sent

Every outgoing checkpoint is scanned, not only the latest files. A password added in one checkpoint
and deleted in the next is still caught, because it would still be on the website.

| Check | What happens |
| --- | --- |
| Passwords and keys in added lines (GitHub, GitLab, AWS, Google, Slack, Stripe, AI-service and Hugging Face keys, private keys, JWTs, passwords inside web addresses, long random values assigned to names like `password` or `api_key`) | **Blocked.** It shows the file and line, with the value hidden. |
| Your own sign-in token, in any form | **Blocked.** |
| `.env` files (except `.env.example`, `.sample`, `.template`, `.dist`), `*.pem`, `*.key`, `id_rsa` and similar | **Blocked.** |
| Automatic-job (CI) files: `.github/workflows/`, `.github/actions/`, `action.yml`, `.gitlab-ci.yml`, `.gitlab/ci/`, CircleCI, Azure Pipelines, Jenkins, Travis | **Blocked.** These can run code on the website and read its secrets, so you share them yourself after checking. |
| Files over 95 MB | **Blocked** (websites refuse files over 100 MB). Over 50 MB gets a warning. |
| Submodules | **Blocked.** |
| Sharing to the main (default) branch or a protected branch | **Amber warning**, with a one-click "Share as a new branch" instead. |
| The website has checkpoints you don't have | **Blocked** until you press Get latest. AutoMoto never force-pushes. |

GitHub push protection and GitLab secret push protection stay on as a second check on the website.
AutoMoto never offers a way around them.

### Which tokens can share

**GitHub classic tokens (`ghp_…`) are blocked for sharing.** They reach every repository you own, so
a mistake or a leak is much worse. Use a fine-grained token (`github_pat_…`) limited to the
repositories you pick, with **Contents: Read and write**. Connect GitHub or GitLab pre-fills this.
GitLab tokens need the `write_repository` scope.

## If sharing fails: share it yourself

Any failure (sign-in ended, no permission, protected branch, someone shared first, no internet, the
website found a secret, or anything else) shows a card with:

- a plain-words headline and what to do next, with a button for the easy fix where there is one (Connect
  again, Get latest, Share as a new branch, Try again);
- your checkpoints saved as a **`.patch` file** in `Documents/AutoMoto/patches/` (and a **`.bundle`**
  too when there are pictures or other binary files, or the patch would be very large);
- numbered steps for **Windows (PowerShell), Mac or Linux (Terminal)**. Each command has a copy button,
  and paths are quoted correctly for that system. Pick another system if you'll share from a different
  computer.

The `.patch` is secret-scanned before it is saved. If it contains anything that looks like a secret,
no file is made. The steps never include your token: Git asks you to sign in through your browser (Git
Credential Manager) when you run them.

You can also press **Share it myself (save a .patch file)** at any time.

## Why the token can't leak through Git

- AutoMoto never writes the token to `.git/config`, a remote address, a file, a command line, or the
  environment of any long-running program.
- For each push, fetch or branch lookup, Git gets a **single-use credential helper** for that one
  command (`-c credential.helper=…`, which is never saved). The helper asks a small server on
  `127.0.0.1` that exists only for that command. That server answers **once**, only within **60
  seconds**, only to the holder of a one-time code, and only for the **exact host and repository**.
- Git runs with your global and system Git settings ignored, no hooks, no proxy, no redirects, HTTPS only,
  and only to an allowlisted host (`github.com`, `gitlab.com` or a GitLab server you added).
- **Repositories whose own settings redirect traffic or credentials are refused**: `url.*.insteadOf` and
  `pushInsteadOf`, `credential.*`, `http.*` (proxies, extra headers, certificates), `remote.*.pushurl`,
  `receivepack`/`uploadpack`, `core.sshCommand`, `core.gitProxy`, `core.askPass`, `protocol.*`,
  `submodule.*`, LFS settings, and the V45 list (filters, merge drivers, includes and so on). Shallow
  copies are refused too.
- Your branch is pushed as `<exact commit>:refs/heads/<branch>`, without `+`, `--force` or tags.
  If anything changed between the check and your click (a new checkpoint, another branch, the website
  moved on), the click is refused and the check runs again.
- Get latest fetches into AutoMoto's own reference (`refs/automoto/remotes/<branch>`), not into your
  branches or remote settings.
- Text from the website and from other people's checkpoints (repository names, commit messages, Git's
  `remote:` lines) is treated as untrusted: control and escape characters are stripped, secrets are
  hidden, and it's shown as plain text only.

## Audit log

Every remote action (pick a repository, check, share, get latest, bring in, fallback) is written to
`remote-audit.jsonl` in AutoMoto's data folder: the time, action, result, host, repository, branch
and counts. It never contains a token. `GET /api/developer/studio/remote/audit` returns the latest
entries.

## For developers

- Engine: `automoto/developer_remote.py` (API under `/api/developer/studio/remote/`: `status`, `target`,
  `plan`, `share`, `fetch`, `pull`, `fallback`, `audit`). All endpoints are local-only and need the
  session token. The project must be trusted.
- Credential helper: `automoto/git_credential.py`. It imports nothing from AutoMoto and only talks to
  `http://127.0.0.1:<port>/credential`.
- Secret scanner: `automoto/secretscan.py`, which is shared.
- UI: `automoto/web/static/developer-share.js`. It doesn't use `innerHTML` or browser storage.
- Tests: `tests/test_developer_remote.py` runs a real `git http-backend` behind Basic auth on
  127.0.0.1 and injects failures for every fallback path (401, 403, protected branch, push protection,
  refused connection, dropped connection, server garbage, non-fast-forward, expired and classic
  tokens). It checks that the token never appears in `.git` (config, reflog, objects), the server repository,
  logs, the audit file, the patch or API answers. `apps/desktop/test/share.cjs` is the browser test.
- `AUTOMOTO_PATCH_DIR` (real environment only, never a project `.env`) moves the patches folder.
- Not in this version: opening pull or merge requests, CI status and merging. Those are later PRs.
