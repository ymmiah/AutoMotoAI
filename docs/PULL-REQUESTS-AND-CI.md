# Ask for a review and Checks on GitHub or GitLab

Developer Studio → **Tools → Ask for a review** opens a **draft** pull request (GitHub) or merge request
(GitLab) from a branch you already shared, then shows whether the website's automatic checks passed, in the
same small health ring as **Run my app**. It lives in Tools only, so the desktop main screen is unchanged; on
phones and tablets it opens from the Tools tab.

AutoMoto **never merges**. There is no merge, approve or close button and no code for it. The reviewer decides on
the website.

## The four steps

1. **Your shared branch.** Shows the branch and repository you picked in *Share to GitHub or GitLab*. If the
   branch isn't on the website yet, it sends you to Share first.
2. **Write the request.** *Write it for me* fills in a title and a description from your checkpoint messages,
   marked "Written from your checkpoint messages. Change anything before you send it." Every word is editable.
   You can change the branch it goes into (the main branch by default). *Open as a draft* is ticked by default.
   Nothing is sent yet.
3. **Ask for a review.** A confirm dialog shows exactly what will be sent: draft or not, `branch → main`, the
   repository, the title and the description. Only your click sends it. If a review for this branch is already
   open, AutoMoto shows that one instead of making a second.
4. **Checks on GitHub (or GitLab).** One card holds the 46px ring ("5/6"), the result in plain words, the names of
   checks that didn't pass and **Check again**. The card has the same measurements on phone, tablet and desktop.
   *What it said* shows a failing check's message or log tail as plain text, with a copy button. *Open checks on
   GitHub* opens the website. This step only reads: nothing is re-run or changed.

## What is read and sent

| Action | GitHub | GitLab |
| --- | --- | --- |
| Is the branch shared? | `GET /repos/{o}/{r}/branches/{b}` | `GET /projects/:id/repository/branches/:b` |
| Already open? | `GET /repos/{o}/{r}/pulls?head=o:b&state=open` | `GET /projects/:id/merge_requests?source_branch=b&state=opened` |
| Prefill text | `GET /repos/{o}/{r}/compare/base...b` | `GET /projects/:id/repository/compare` |
| **Ask for a review** (click only) | `POST /repos/{o}/{r}/pulls` with `draft: true`, `maintainer_can_modify: false` | `POST /projects/:id/merge_requests`, title prefixed `Draft:` |
| Checks | check runs, or GitHub Actions jobs when the token can't read check runs, plus commit statuses | latest pipeline for the commit and its jobs |
| What it said | check run output, or the Actions job's step list | job log (last 200 lines) |

### Permissions

- **GitHub fine-grained token:** *Pull requests: Read and write* (to open the draft), *Commit statuses: Read*
  and *Actions: Read* (for checks). These are already on the pre-filled token page from *Connect GitHub or
  GitLab*. Fine-grained tokens can't be given GitHub's *Checks* permission, so on private repositories AutoMoto
  reads GitHub Actions jobs instead of check runs. GitHub Actions job logs sit behind a redirect to another host,
  which AutoMoto never follows, so it shows the job's steps and a link to the full log.
- **GitHub classic tokens** are not used here either, the same as for sharing.
- **GitLab:** reading checks needs `read_api`, which you gave at sign-in. Opening a merge request needs `api`,
  because GitLab has nothing smaller. AutoMoto asks for it **only when you first ask for a review**. It explains
  why and gives you a copyable link to a token page with `read_user, read_api, write_repository, api` ticked, which
  you paste into *Connect GitHub or GitLab*. A project access token limited to one project also works.

## Safety

- **Tokens stay in the OS keychain.** Each call reads the token from the keychain, sends it only in the
  `Authorization` (or `PRIVATE-TOKEN`) header to the allowlisted HTTPS API host with redirects off, and never puts
  it in an answer, the page, a log, the audit file or a command.
- **Click-bound.** The preview returns an `action_sha256` bound to the project, provider, host, repository, base,
  branch and the branch's exact commit on the website. *Ask for a review* re-reads the branch and refuses if
  anything changed ("Look at the new preview"). Previews are single-use and expire after 10 minutes.
- **Untrusted text.** Everything from the website (titles, commit messages, check and job names, summaries,
  logs, error messages, links) has control and escape characters removed (including right-to-left overrides and
  GitLab log section markers), is redacted for secrets and capped. The UI only uses `textContent`. Links are
  passed on only when they are `https` on the signed-in host; other CI links show just their host name. Prompt-
  injection text in a check name or log is shown as text and never run or sent to the assistant.
- **Audit.** `review_preview`, `review_open`, `checks` and `review_fallback` go to `remote-audit.jsonl` with
  facts only (no titles, no tokens).

## If it fails: ask for a review yourself

Any error (401, 403, 422, rate limit, network, missing GitLab `api` scope, branch not shared, server error)
opens a **"do it yourself"** card with Windows, Mac and Linux tabs. Every command, link, title and
description has a copy button:

1. The compare page (`…/compare/main...branch?expand=1`) or GitLab's new merge request page, as a link and as
   copyable text.
2. The command to open it from a terminal:
   - Windows (PowerShell): `Start-Process "https://github.com/OWNER/REPO/compare/main...my-branch?expand=1"`
   - Mac: `open 'https://github.com/OWNER/REPO/compare/main...my-branch?expand=1'`
   - Linux: `xdg-open 'https://github.com/OWNER/REPO/compare/main...my-branch?expand=1'`
3. The title and description to paste.
4. How to make it a draft on the website, and a reminder not to press Merge.
5. The same draft with the command-line tools, if you use them (they sign you in through the browser):
   - `gh pr create --repo OWNER/REPO --base main --head my-branch --draft --title "…" --body "…"`
   - `glab mr create --repo GROUP/REPO --source-branch my-branch --target-branch main --draft --title "…" --description "…"`

Titles are quoted for each shell (PowerShell escapes `` ` ``, `"` and `$`; Mac and Linux use single quotes),
so nothing in a title can run as a command. If the branch isn't shared yet, the first step sends you to
*Share to GitHub or GitLab*, which has its own `.patch` fallback.

## For developers

- Engine: `automoto/developer_pulls.py`, router `/api/developer/studio/remote/review/`: `GET status`,
  `POST preview`, `POST open`, `GET checks`, `GET details`, `POST fallback`. All are local-only, need the session
  token, and work on trusted projects only. It reuses the PR 3 target, account and redaction helpers from
  `automoto/developer_remote.py`.
- UI: `automoto/web/static/developer-pulls.js` (Tools card `review`, root `#dsReviewRoot`). The ring comes from
  `ring()` in `developer-beginner.js` and the card uses the shared `.dsb-check` styles.
- Tests: `tests/test_developer_pulls.py` (a fake GitHub/GitLab API with 401/403/422/5xx/rate-limit/scope injection,
  prompt-injection text, token-in-log redaction, per-OS quoting, and a check that no merge call is ever made) and
  `apps/desktop/test/review.cjs` (steps, ring geometry on desktop/tablet/phone, plain-text rendering, copy buttons,
  the confirm dialog and the fallback).
