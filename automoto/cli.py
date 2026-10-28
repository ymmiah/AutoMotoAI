"""Command line for AutoMoto AI v4.

    python -m automoto                 # interactive chat (Rich)
    python -m automoto serve           # local web UI on http://127.0.0.1:8765
    python -m automoto status          # which AIs are configured + vision matrix
    python -m automoto ask "question" [--image shot.png] [--prefer groq]
    python -m automoto recommend "read this receipt"
"""

from __future__ import annotations

import argparse
import base64
import mimetypes
import sys
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
        console.print(text, style=style, highlight=False)
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


def cmd_serve(args) -> int:
    from automoto.server import run

    run(host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="automoto", description=f"{APP_NAME} v{__version__} \"{CODENAME}\"")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("--prefer", help="provider id to try first (nim, gemini, groq, openrouter, openai, claude)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("chat", help="interactive chat (default)")
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
    handlers = {"serve": cmd_serve, "status": cmd_status, "ask": cmd_ask, "recommend": cmd_recommend}
    return handlers.get(args.cmd, cmd_chat)(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
