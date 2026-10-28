---
name: github
description: Work with GitHub - repos, issues, PRs, Actions - via the service_api tool (token) or the gh/git CLIs.
category: services
tools: service_api
optional_apps: git, gh
env: GITHUB_TOKEN|GH_TOKEN
status: live
---
# GitHub

Reads of public repos work without a token; private data and writes need `GITHUB_TOKEN` (fine-grained PAT,
least privilege) in `.env` or a `github` key in Settings.
- Repo info: `service_api` github `/repos/OWNER/REPO`
- Issues: `/repos/OWNER/REPO/issues` with `query {state: open, per_page: 20}`; one issue: `/repos/OWNER/REPO/issues/N`
- PRs: `/repos/OWNER/REPO/pulls`, files changed: `/repos/OWNER/REPO/pulls/N/files`
- CI: `/repos/OWNER/REPO/actions/runs` with `query {per_page: 5}`; logs are easier with `run_app` `gh` `["run", "view", "ID", "--log-failed"]`
- File: `/repos/OWNER/REPO/contents/PATH` (base64 content)
- Search code: `/search/code` with `query {q: "symbol repo:OWNER/REPO"}`
- Create an issue/comment (approval): method POST `/repos/OWNER/REPO/issues` body `{title, body}`
Local repo work uses `run_app` `git` (`status`, `diff`, `add`, `commit -m`, `push` - each approved).
Never touched: secrets, deploy keys, webhooks, collaborators, deleting repos.
