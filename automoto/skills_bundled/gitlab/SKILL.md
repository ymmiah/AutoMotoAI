---
name: gitlab
description: Work with GitLab projects, issues and merge requests via the service_api tool or the official GitLab MCP connector.
category: services
tools: service_api
optional_apps: glab
env: GITLAB_TOKEN
status: unit
---
# GitLab

Token: `GITLAB_TOKEN` (personal access token, `read_api` for reading). Self-managed: `GITLAB_URL=https://gitlab.example.com`.
- Projects: `service_api` gitlab `/projects` with `query {search: "name", membership: true}`
- One project: `/projects/GROUP%2FPROJECT` (URL-encode the slash)
- Issues: `/projects/ID/issues?state=opened`, MRs: `/projects/ID/merge_requests?state=opened`
- Pipelines: `/projects/ID/pipelines?per_page=5`, jobs: `/projects/ID/pipelines/PID/jobs`
- Comment on an MR (approval): POST `/projects/ID/merge_requests/IID/notes` body `{body}`
Alternative: Settings → Connectors → GitLab (official MCP server, OAuth).
