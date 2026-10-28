"""Command line for AutoMoto AI v5 "Agent".

    python -m automoto                 # interactive AGENT chat (tools + approvals)
    python -m automoto --plain         # v4-style plain chat (no tools)
    python -m automoto do "goal"       # one-shot agent task
    python -m automoto serve           # web UI + API + routines on http://127.0.0.1:8765
    python -m automoto routines add NAME --every 1h --prompt "..."   (or --cron "0 8 * * 1-5")
    python -m automoto routines list | remove NAME | run NAME
    python -m automoto memory [list | add "fact" | forget ID]
    python -m automoto skills | tools | apps
    python -m automoto mcp [catalog | enable ID | disable ID]
    python -m automoto open            # open the running web UI with a fresh one-time sign-in link
    python -m automoto --workspace ~/code/proj do "fix the failing test"   (folder must be in allowed roots)
    python -m automoto status          # which AIs are configured + vision matrix
    python -m automoto ask "question" [--image shot.png] [--prefer groq]
    python -m automoto recommend "read this receipt"
"""

from __future__ import annotations

import argparse
import base64
import mimetypes
import sys
import time
from pathlib import Path

from automoto import APP_NAME, CODENAME, __version__, config


def _console():
    try:
        from rich.console import Console

        return Console()
    except ImportError:  # pragma: no cover
        return None


def _print(console, text: str, style: str | None = None) -> None:
    if console:
        console.print(text, style=style, highlight=False, markup=False)
    else:
        print(text)


def _image_part(path: str) -> dict:
    p = Path(path).expanduser()
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    data = base64.b64encode(p.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}


def cmd_status(_args) -> int:
    from automoto.router import status

    console = _console()
    st = status()
    if console:
        from rich.table import Table

        t = Table(title=f"{APP_NAME} v{__version__} — mode: {st['mode']}")
        for col in ("Provider", "Key", "Vision", "Free", "Text model", "Vision model"):
            t.add_column(col)
        for p in st["providers"]:
            t.add_row(p["label"], "✅" if p["configured"] else f"— {p['env_keys'][0]}",
                      "👁 yes" if p["supports_vision"] else "no", "yes" if p["free_tier"] else "paid",
                      p["text_model"], p["vision_model"] or "—")
        console.print(t)
    else:
        for p in st["providers"]:
            print(p["id"], p["configured"], p["supports_vision"], p["text_model"])
    if not any(p["configured"] for p in st["providers"]):
        _print(console, "No keys yet: copy .env.example to .env and add at least one key.", "yellow")
        return 1
    return 0


def cmd_recommend(args) -> int:
    from automoto.router import classify_task, recommend_provider

    task = classify_task(args.task)
    print(f"task={task} configured_pick={recommend_provider(args.task)} "
          f"overall_pick={recommend_provider(args.task, only_configured=False)}")
    return 0


def _handle_actions(console, actions) -> None:
    from automoto.desktop import execute

    for a in actions:
        label = f"{a['tool']}({', '.join(f'{k}={v!r}' for k, v in a['args'].items())})"
        _print(console, f"\n⚙  Proposed [{a['risk']}]: {label}  — {a.get('why', '')}", "cyan")
        if a["risk"] == "safe":
            res = execute(a)
        else:
            if input("   Run it? [y/N] ").strip().lower() not in ("y", "yes"):
                _print(console, "   skipped", "dim")
                continue
            res = execute(a, confirmed=True)
        _print(console, f"   → {res.get('result') or res.get('error')}", "green" if res.get("ok") else "red")


def _reply(console, ans) -> None:
    from automoto.agent import split_actions

    text, actions = split_actions(ans.text)
    if console:
        from rich.markdown import Markdown

        console.print(Markdown(text))
        hops = " → ".join(f"{t['provider']}{'' if t['ok'] else '✗'}" for t in ans.tried)
        console.print(f"[dim]{ans.provider} · {ans.model} · {ans.task} · {hops}[/dim]")
    else:
        print(text, f"\n[{ans.provider} · {ans.model}]")
    if actions:
        _handle_actions(console, actions)


def cmd_ask(args) -> int:
    from automoto.agent import system_prompt
    from automoto.router import AllProvidersFailed, NoProviderError, ask

    console = _console()
    content: list | str = args.question
    if args.image:
        content = [{"type": "text", "text": args.question}] + [_image_part(i) for i in args.image]
    try:
        ans = ask([{"role": "user", "content": content}], prefer=args.prefer,
                  system=system_prompt(desktop=False))
    except (NoProviderError, AllProvidersFailed) as exc:
        _print(console, f"✗ {exc}", "red")
        return 2
    _reply(console, ans)
    return 0


def cmd_chat(args) -> int:
    from automoto.agent import system_prompt
    from automoto.router import AllProvidersFailed, NoProviderError, ask

    console = _console()
    _print(console, f"🤖 {APP_NAME} v{__version__} \"{CODENAME}\" — mode {args.prefer or config.ai_provider()}. "
                    "Type /image <path> to attach, /status, /exit.", "bold green")
    history: list[dict] = []
    pending_images: list[dict] = []
    while True:
        try:
            line = input("\nyou › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("/exit", "/quit", "exit", "quit"):
            return 0
        if line == "/status":
            cmd_status(args)
            continue
        if line.startswith("/image "):
            try:
                pending_images.append(_image_part(line[7:].strip()))
                _print(console, "📎 image attached — vision AI will be used for the next message", "cyan")
            except OSError as exc:
                _print(console, f"✗ {exc}", "red")
            continue
        content: list | str = line
        if pending_images:
            content = [{"type": "text", "text": line}] + pending_images
            pending_images = []
        history.append({"role": "user", "content": content})
        try:
            ans = ask(history[-20:], prefer=args.prefer, system=system_prompt(desktop=config.desktop_enabled()))
        except (NoProviderError, AllProvidersFailed) as exc:
            _print(console, f"✗ {exc}", "red")
            history.pop()
            if isinstance(exc, NoProviderError):
                return 2
            continue
        history.append({"role": "assistant", "content": ans.text})
        _reply(console, ans)


# -- v5 agent ----------------------------------------------------------------------
def _terminal_approver(console):
    def approve(call, decision) -> bool:
        from automoto.loop import format_args

        _print(console, f"   ⚠  {call['name']} {format_args(call['args'], 300)}", "yellow")
        _print(console, f"      {decision.level}: {decision.reason}", "dim")
        try:
            ans = input("      Approve? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        return ans in ("y", "yes")
    return approve


def _event_printer(console):
    from automoto.loop import format_args

    def on_event(ev) -> None:
        t = ev["type"]
        if t == "model" and ev.get("switched"):
            _print(console, f"   ↪ switched AI: {'; '.join(ev['switched'])} → {ev['provider']}", "dim")
        elif t == "say" and ev.get("text"):
            _print(console, f"   💭 {ev['text'][:300]}", "dim")
        elif t == "tool_call":
            d = ev["decision"]
            mark = {"allow": "▶", "ask": "?", "deny": "⛔"}[d["action"]]
            _print(console, f"   {mark} {ev['name']} {format_args(ev['args'])}", "cyan")
        elif t == "tool_result":
            out = (ev.get("output") or "").strip().splitlines()
            first = out[0][:160] if out else ""
            more = f" (+{len(out) - 1} lines)" if len(out) > 1 else ""
            _print(console, f"     {'✓' if ev['ok'] else '✗'} {first}{more}", "green" if ev["ok"] else "red")
        elif t == "max_steps":
            _print(console, "   ⏹ step limit reached - summarising", "yellow")
    return on_event


def _agent(args, desktop: bool):
    from automoto.loop import Agent

    extra = []
    if not getattr(args, "no_mcp", False):
        from automoto import mcp

        extra, errors = mcp.connect_all()
        for e in errors:
            _print(_console(), f"MCP: {e}", "yellow")
    workspace = None
    if getattr(args, "workspace", None):
        from automoto import sandbox

        try:
            workspace = str(sandbox.check_root(args.workspace))
        except sandbox.SandboxError as exc:
            raise SystemExit(f"--workspace: {exc}") from None
    return Agent(desktop=desktop, extra_tools=extra, client="cli", workspace=workspace)


def _show_final(console, res) -> None:
    if console:
        from rich.markdown import Markdown

        console.print(Markdown(res.text or "(no answer)"))
        console.print(f"[dim]{res.provider} · {res.model} · {res.steps} step(s) · {res.stopped}[/dim]")
    else:
        print(res.text, f"\n[{res.provider} · {res.model} · {res.steps} steps]")


def cmd_do(args) -> int:
    console = _console()
    content: list | str = args.goal
    if args.image:
        content = [{"type": "text", "text": args.goal}] + [_image_part(i) for i in args.image]
    agent = _agent(args, desktop=config.desktop_enabled())
    res = agent.run([{"role": "user", "content": content}], approver=_terminal_approver(console),
                    on_event=_event_printer(console), prefer=args.prefer, max_steps=args.max_steps)
    _show_final(console, res)
    return 0 if res.stopped in ("done", "max_steps") else 2


def cmd_agent_chat(args) -> int:
    from automoto import policy, sandbox

    console = _console()
    agent = _agent(args, desktop=config.desktop_enabled())
    _print(console, f"🤖 {APP_NAME} v{__version__} \"{CODENAME}\" — your AI cousin. Tools: {len(agent.tools)} · "
                    f"sandbox: {sandbox.mode()} ({sandbox.root()}) · approvals: {policy.mode()}", "bold green")
    _print(console, "Ask me to do things. /image <path> attaches, /memory, /tools, /plain, /exit.", "dim")
    history: list[dict] = []
    pending_images: list[dict] = []
    while True:
        try:
            line = input("\nyou › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("/exit", "/quit", "exit", "quit"):
            return 0
        if line == "/plain":
            return cmd_chat(args)
        if line == "/status":
            cmd_status(args)
            continue
        if line == "/tools":
            from automoto.tools import text_manifest

            _print(console, text_manifest(agent.tools))
            continue
        if line == "/memory":
            for f in agent.memory.facts():
                _print(console, f"#{f['id']} {f['text']}")
            continue
        if line.startswith("/image "):
            try:
                pending_images.append(_image_part(line[7:].strip()))
                _print(console, "📎 image attached — a vision AI will be used", "cyan")
            except OSError as exc:
                _print(console, f"✗ {exc}", "red")
            continue
        content: list | str = line
        if pending_images:
            content = [{"type": "text", "text": line}] + pending_images
            pending_images = []
        history.append({"role": "user", "content": content})
        res = agent.run(history[-20:], approver=_terminal_approver(console), on_event=_event_printer(console),
                        prefer=args.prefer, max_steps=args.max_steps)
        _show_final(console, res)
        if res.stopped == "error":
            history.pop()
            if "No AI provider key" in res.text:
                return 2
            continue
        history.append({"role": "assistant", "content": res.text})


def cmd_routines(args) -> int:
    from automoto import routines

    store = routines.RoutineStore()
    console = _console()
    if args.action == "add":
        if not args.name or not args.prompt or not (args.every or args.cron):
            _print(console, "usage: routines add NAME (--every 1h | --cron '0 8 * * *') --prompt '...'", "red")
            return 2
        sched = f"every {args.every}" if args.every else args.cron
        try:
            r = store.add(args.name, sched, args.prompt)
        except routines.ScheduleError as exc:
            _print(console, f"✗ {exc}", "red")
            return 2
        _print(console, f"✓ routine '{r.name}' ({r.schedule}) saved. It runs while `python -m automoto serve` is up.", "green")
        return 0
    if args.action == "remove":
        ok = store.remove(args.name or "")
        _print(console, "✓ removed" if ok else "no such routine", "green" if ok else "red")
        return 0 if ok else 1
    if args.action == "run":
        r = store.load().get(args.name or "")
        if not r:
            _print(console, "no such routine", "red")
            return 1
        agent = _agent(args, desktop=False)
        line = routines.run_routine(r, lambda p: agent.run(p, on_event=_event_printer(console)).as_dict(), store)
        _print(console, f"[{line['status']}] {line['result']}")
        return 0
    rs = store.load()
    if not rs:
        _print(console, "No routines yet. Example: python -m automoto routines add morning --cron '0 8 * * 1-5' "
                        "--prompt 'Search the web for news about NVIDIA NIM and summarise it in 5 bullets.'")
    for r in rs.values():
        last = time.strftime("%Y-%m-%d %H:%M", time.localtime(r.last_run)) if r.last_run else "never"
        _print(console, f"• {r.name}  [{r.schedule}]  last: {last} {r.last_status}\n    {r.prompt[:120]}")
    return 0


def cmd_memory(args) -> int:
    from automoto.memory import Memory

    m = Memory()
    if args.action == "add" and args.text:
        print(m.remember(" ".join(args.text)))
    elif args.action == "forget" and args.text:
        print("forgotten" if m.forget(int(args.text[0])) else "no such memory")
    else:
        for f in m.facts():
            print(f"#{f['id']} {f['text']}")
        if not m.facts():
            print(f"(memory is empty - {m.path})")
    return 0


STATUS_MARK = {"live": "✅ live-tested", "unit": "🟡 unit-tested", "untested": "🔴 untested"}


def cmd_skills(_args) -> int:
    from automoto import skills, tools

    names = set(tools.build(desktop=config.desktop_enabled()))
    for s in skills.discover().values():
        r = s.requirements(names)
        missing = [c["name"] for c in r["checks"] if not c["ok"] and not c["optional"]]
        optional = [c["name"] for c in r["checks"] if not c["ok"] and c["optional"]]
        ready = "ready" if r["ready"] else "needs " + ", ".join(missing or ["a connector"])
        extra = f" (optional, not set up: {', '.join(optional)})" if optional else ""
        print(f"• {s.name}{' (bundled)' if s.bundled else ''} [{r['category']}] - {ready} - "
              f"{STATUS_MARK.get(r['status'], r['status'])}{extra}\n    {s.description}")
    return 0


def cmd_apps(_args) -> int:
    from automoto import apps

    for a in apps.listing():
        where = a.get("path") or "not found"
        print(f"• {a['id']:<12} {a['name']:<22} {STATUS_MARK.get(a['status'], a['status']):<16} {where}")
    return 0


def cmd_mcp(args) -> int:
    from automoto import mcp_catalog

    if args.action == "enable" and args.id:
        try:
            entry = mcp_catalog.enable(args.id)
        except KeyError:
            print(f"unknown connector '{args.id}'")
            return 1
        print(f"enabled {args.id}: {entry.get('command')} {' '.join(entry.get('args', []))}")
        print("Restart `automoto serve` (or Settings → Connectors → Reload) to connect.")
        return 0
    if args.action == "disable" and args.id:
        print("disabled" if mcp_catalog.disable(args.id) else "was not enabled")
        return 0
    for c in mcp_catalog.listing():
        miss = f"  needs env: {', '.join(c['missing_env'])}" if c["missing_env"] else ""
        print(f"{'●' if c['enabled'] else '○'} {c['id']:<14} {c['name']:<24} {c['transport']:<7}{miss}\n    {c['note']}")
    return 0


def cmd_open(_args) -> int:
    """Ask the running server for a fresh one-time link and open it (the token never appears in a URL you keep)."""
    import json
    import urllib.request
    import webbrowser

    from automoto import home

    try:
        info = json.loads((home.home() / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("No running AutoMoto server found - start it with `automoto serve`.")
        return 1
    req = urllib.request.Request(info["url"].rstrip("/") + "/api/session/launch", method="POST", data=b"{}",
                                 headers={"X-AutoMoto-Token": info["token"], "Content-Type": "application/json"})
    try:
        if not info["url"].startswith(("http://127.0.0.1:", "http://localhost:", "http://[::1]:")):
            raise OSError("session file URL is not a loopback address")
        with urllib.request.urlopen(req, timeout=5) as r:  # nosec B310 - loopback http URL checked above
            url = json.loads(r.read())["url"]
    except OSError as exc:
        print(f"Server not reachable at {info['url']}: {exc}")
        return 1
    print(f"Opening {info['url']} …")
    webbrowser.open(url)
    return 0


def cmd_tools(args) -> int:
    from automoto.tools import build, text_manifest

    print(text_manifest(build(desktop=config.desktop_enabled())))
    return 0


def cmd_serve(args) -> int:
    from automoto.server import run

    run(host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles/pipes may not be UTF-8: never crash on ✅ or →
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="automoto", description=f"{APP_NAME} v{__version__} \"{CODENAME}\"")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("--prefer", help="provider id to try first (nim, gemini, groq, openrouter, openai, claude)")
    ap.add_argument("--plain", action="store_true", help="plain chat without tools (v4 behaviour)")
    ap.add_argument("--max-steps", type=int, default=None, help="agent step limit (default AUTOMOTO_MAX_STEPS or 12)")
    ap.add_argument("--no-mcp", action="store_true", help="don't start MCP servers from mcp.json")
    ap.add_argument("--workspace", help="work in this folder (must be listed in allowed roots)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("chat", help="interactive agent chat (default)")
    d = sub.add_parser("do", help="one-shot agent task")
    d.add_argument("goal")
    d.add_argument("--image", action="append", help="attach an image (repeatable)")
    rt = sub.add_parser("routines", help="scheduled agent prompts")
    rt.add_argument("action", nargs="?", default="list", choices=["list", "add", "remove", "run"])
    rt.add_argument("name", nargs="?")
    rt.add_argument("--every", help="interval like 30m, 2h, 1d")
    rt.add_argument("--cron", help="5-field cron, e.g. '0 8 * * 1-5'")
    rt.add_argument("--prompt", help="what the agent should do")
    mm = sub.add_parser("memory", help="list / add / forget long-term memory")
    mm.add_argument("action", nargs="?", default="list", choices=["list", "add", "forget"])
    mm.add_argument("text", nargs="*")
    sub.add_parser("skills", help="list skills")
    sub.add_parser("tools", help="list agent tools and their safety level")
    sub.add_parser("apps", help="local apps AutoMoto can drive and whether they're installed")
    mc = sub.add_parser("mcp", help="connector catalog (GitHub, Notion, Figma, Canva, Drive, OneDrive, …)")
    mc.add_argument("action", nargs="?", default="catalog", choices=["catalog", "enable", "disable"])
    mc.add_argument("id", nargs="?")
    sub.add_parser("open", help="open the running web UI (fresh one-time sign-in link)")
    s = sub.add_parser("serve", help="local web UI + API")
    s.add_argument("--host", default=config.env("AUTOMOTO_HOST", "127.0.0.1"))
    s.add_argument("--port", type=int, default=int(config.env("AUTOMOTO_PORT", "8765")))
    s.add_argument("--no-browser", action="store_true")
    sub.add_parser("status", help="show providers and vision support")
    a = sub.add_parser("ask", help="one-shot question")
    a.add_argument("question")
    a.add_argument("--image", action="append", help="attach an image (repeatable)")
    r = sub.add_parser("recommend", help="which AI would handle this task")
    r.add_argument("task")
    args = ap.parse_args(argv)
    handlers = {"serve": cmd_serve, "status": cmd_status, "ask": cmd_ask, "recommend": cmd_recommend,
                "do": cmd_do, "routines": cmd_routines, "memory": cmd_memory, "skills": cmd_skills,
                "tools": cmd_tools, "apps": cmd_apps, "mcp": cmd_mcp, "open": cmd_open}
    if args.cmd in handlers:
        return handlers[args.cmd](args)
    return cmd_chat(args) if args.plain else cmd_agent_chat(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
