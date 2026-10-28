# Security — AutoMoto AI v5 "Agent"

This file describes what the code in this repo **actually does**, including its limits.

## API keys (BYOK)
- No keys are baked in. You add your own in `.env` (git-ignored), or per tab in the web UI.
- Placeholder values from `.env.example` are ignored.
- Keys typed into the web UI's 🔑 Keys dialog live in `sessionStorage` only. They vanish when the tab
  closes, and they are sent only to your local AutoMoto server, for the request or agent task that uses them.
- During an agent task, BYOK keys are held only by the running thread. They are never written to the task
  record, its events, the memory database or logs, and they are dropped when the run ends (tests check this).
- Keys are never returned by `/api/status`. Shell commands run with every `*KEY*`, `*TOKEN*`, `*SECRET*`,
  `*PASSWORD*` and `*AUTH*` environment variable removed, so a command cannot read your keys.
- The mobile app stores keys in the iOS Keychain / Android Keystore (`flutter_secure_storage`).

## Local server
- Binds to `127.0.0.1:8765` by default.
- Browser calls must carry a per-launch session token injected into the served page, so other websites
  cannot drive your local API. No CORS is enabled.
- Listening on a network interface is refused unless `AUTOMOTO_API_TOKEN` is set. Remote clients must send
  `Authorization: Bearer <token>`. Anyone with that token can start agent tasks and approve them, so use it
  only on a trusted network or a VPN such as Tailscale.
- Desktop tools and screen capture are only offered to clients on the same computer.

## Agent sandbox
- Every file tool resolves its path (following symlinks) and refuses anything outside the workspace
  (default `~/.automoto/workspace`). There is **no tool that can write or delete outside the workspace**.
- `run_shell` runs with the workspace as cwd, a timeout (`AUTOMOTO_SHELL_TIMEOUT`, default 60 s), a
  process-tree kill on timeout, secret-free environment variables and no stdin.
- **Limit:** the local runner is *not* OS-level isolation. An approved command could still reach files
  outside the workspace by indirect means. The policy blocks the obvious cases (below) and every shell command
  needs your approval. For real isolation use `AUTOMOTO_SANDBOX=docker`. That runs each command in a
  throwaway container with `--network none`, 512 MB RAM, 1 CPU, 256 PIDs, and only the workspace mounted.

## Approval policy
- **safe** calls run automatically: reads, web search/fetch, memory, skills, and writes in `scratch/`.
- **risky** calls wait for you (Approve/Deny card or `y/N`): shell, writes elsewhere in the workspace,
  overwrites, desktop actions, `forget`, and MCP tools that aren't trusted. In the web UI, an approval
  left unanswered for 10 minutes counts as denied.
- **blocked** calls can never be approved: paths outside the workspace; `sudo`, `su`, `mkfs`, `dd of=`,
  `shutdown`/`reboot`, `diskpart`, `crontab`, `reg add/delete`, `setx`, piping `curl`/`wget` into a shell;
  and, in the local runner, destructive commands (`rm`, `del`, `mv`, `chmod`, `Remove-Item`…) that reference
  `~`, `..`, `$HOME`, `%USERPROFILE%` or absolute paths.
- `AUTOMOTO_APPROVAL=auto` approves risky calls without asking. Use it only with the Docker sandbox.
  `readonly` denies all risky calls. Routines run unattended, so their risky calls are auto-denied unless you
  list the tool in `AUTOMOTO_AUTO_APPROVE`.

## Network (SSRF guard)
- `fetch_url` and `web_search` allow only `http(s)` on ports 80, 443, 8080 and 8443, with no credentials in URLs.
- Every resolved address must be public. Loopback, private, link-local (including cloud metadata at `169.254.169.254`),
  CGNAT, multicast, reserved, documentation and benchmark ranges are refused. IPv6 forms that embed IPv4
  (IPv4-mapped, IPv4-compatible, NAT64, 6to4, Teredo) are decoded and the embedded IPv4 address is checked.
- The connection is pinned to the IP that passed the check, which closes the DNS-rebinding window. TLS still
  verifies the hostname. Redirects are followed manually and each hop is re-checked. Responses are capped at 2 MB.
- `AUTOMOTO_NET_ALLOW_CIDRS` lets you allow-list ranges for fake-IP DNS proxies (e.g. Clash's `198.18.0.0/15`).
  Loopback, link-local and unspecified addresses can never be allow-listed, and ranges wider than /8 are ignored.

## Prompt injection
Web pages, files and MCP results can contain instructions aimed at the AI. AutoMoto's defence is
structural: whatever the model decides, risky actions still need your approval and blocked actions never run.
Read approval cards before you approve, especially after the agent has fetched web content.

## MCP servers
MCP servers are programs you choose to run (from `mcp.json`) with your user's permissions. Their tools are
risky (approval required) unless you set `"trust": true`. Only add servers you trust.

## Desktop actions
- Only tools from a fixed list. The GUI tools need `pyautogui` with its fail-safe on (move the mouse into a corner to abort).
- In v4 plain-chat mode, proposed actions still need Run / `y`, and `run_command` stays off unless
  `AUTOMOTO_ALLOW_SHELL=1`.
- Use AutoMoto only on machines you own or are authorised to automate.

## Reporting a vulnerability
Please open a private security advisory on GitHub
(<https://github.com/ymmiah/AutoMotoAI/security/advisories/new>) rather than a public issue.
