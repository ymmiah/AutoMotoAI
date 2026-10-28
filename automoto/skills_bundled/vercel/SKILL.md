---
name: vercel
description: Inspect and deploy Vercel projects - deployments, logs, domains - via service_api (VERCEL_TOKEN) or the Vercel CLI.
category: services
tools: service_api
optional_apps: vercel
env: VERCEL_TOKEN
status: unit
---
# Vercel

Token: `VERCEL_TOKEN` (Account Settings → Tokens; scope it to one team if you can).
- Projects: `service_api` vercel `/v9/projects`
- Deployments: `/v6/deployments` with `query {projectId: "...", limit: 5}`; one: `/v13/deployments/ID`
- Build logs: `/v3/deployments/ID/events`
- Deploy from the working folder (approval): `run_app` `vercel` `["deploy", "--yes"]` (production: add `--prod`, confirm with the user).
Environment variables and tokens are never read or changed by the agent.
Alternative: Settings → Connectors → Vercel (official MCP, OAuth).
