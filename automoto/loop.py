"""The agent loop - what makes AutoMoto an *agent* rather than a chat box.

    goal ─► AI (best available) ─► tool calls? ──no──► final answer
                 ▲                     │ yes
                 │            policy: allow / ask / deny
                 │                     │
                 └──── tool results ◄──┘   (repeat, max_steps guard)

Every step goes through ``router.ask_turn`` so failover works mid-task. Every tool call
goes through ``policy.decide`` and risky ones wait for the ``approver`` callback.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from automoto import config, policy, router
from automoto import skills as skills_mod
from automoto import tools as tools_mod
from automoto.memory import Memory

Approver = Callable[[dict[str, Any], policy.Decision], bool]
EventSink = Callable[[dict[str, Any]], None]

MAX_RESULT_CHARS = 12000


def max_steps_default() -> int:
    try:
        return max(1, min(50, int(config.env("AUTOMOTO_MAX_STEPS", "12"))))
    except ValueError:
        return 12


def deny_all(call: dict[str, Any], decision: policy.Decision) -> bool:
    return False


@dataclass
class AgentResult:
    text: str
    steps: int
    provider: str = ""
    model: str = ""
    stopped: str = "done"  # done | max_steps | cancelled | error
    events: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "steps": self.steps, "provider": self.provider, "model": self.model,
                "stopped": self.stopped}


class Agent:
    def __init__(self, *, tools: dict[str, tools_mod.Tool] | None = None, memory: Memory | None = None,
                 skills: dict[str, skills_mod.Skill] | None = None, desktop: bool = False,
                 extra_tools: list[tools_mod.Tool] | None = None, transport: Callable | None = None,
                 client: str = "cli"):
        self.memory = memory if memory is not None else Memory()
        self.skills = skills if skills is not None else skills_mod.discover()
        self.tools = tools if tools is not None else tools_mod.build(desktop=desktop, extra=extra_tools)
        self.ctx = tools_mod.ToolContext(memory=self.memory, skills=self.skills)
        self.transport = transport
        self.client = client
        self.desktop = desktop

    def system(self) -> str:
        from automoto.agent import agent_system_prompt

        return agent_system_prompt(memory=self.memory.prompt_block(), skills=skills_mod.prompt_block(self.skills),
                                   desktop=self.desktop, tool_names=list(self.tools))

    def run(self, messages: list[dict[str, Any]] | str, *, max_steps: int | None = None,
            approver: Approver = deny_all, on_event: EventSink | None = None,
            keys: dict[str, str] | None = None, prefer: str | None = None,
            cancel: threading.Event | None = None) -> AgentResult:
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        max_steps = max_steps or max_steps_default()
        events: list[dict[str, Any]] = []

        def emit(ev: dict[str, Any]) -> None:
            ev = {"t": round(time.time(), 3), **ev}
            events.append(ev)
            if on_event:
                try:
                    on_event(ev)
                except Exception:  # a UI bug must not kill the task
                    pass

        history: list[dict[str, Any]] = [{"role": "system", "content": self.system()}]
        history += [m for m in messages if m.get("role") in ("user", "assistant", "tool")]
        schemas = [t.schema() for t in self.tools.values()]
        known = set(self.tools)
        goal = next((m.get("content") for m in reversed(messages) if m.get("role") == "user"), "")
        goal_text = goal if isinstance(goal, str) else " ".join(p.get("text", "") for p in goal if isinstance(p, dict))
        last = ("", "")
        dead: set[str] = set()  # providers whose key was rejected during this run
        for step in range(1, max_steps + 1):
            if cancel is not None and cancel.is_set():
                emit({"type": "cancelled", "step": step})
                return AgentResult("Cancelled.", step - 1, *last, stopped="cancelled", events=events, history=history)
            emit({"type": "thinking", "step": step})
            try:
                kw: dict[str, Any] = {"known": known, "prefer": prefer, "keys": keys, "task_hint": goal_text,
                                      "exclude": dead}
                if self.transport:
                    kw["transport"] = self.transport
                turn = router.ask_turn(history, schemas, **kw)
            except (router.NoProviderError, router.AllProvidersFailed) as exc:
                emit({"type": "error", "step": step, "error": str(exc),
                      "tried": getattr(exc, "tried", [])})
                return AgentResult(f"✗ {exc}", step - 1, *last, stopped="error", events=events, history=history)
            last = (turn.provider, turn.model)
            failed = [t for t in turn.tried if not t.get("ok")]
            dead |= {t["provider"] for t in failed if t.get("status") in (401, 403)}
            emit({"type": "model", "step": step, "provider": turn.provider, "model": turn.model, "mode": turn.mode,
                  "switched": [f"{t['provider']}/{t['model']}: {t.get('error', '')[:80]}" for t in failed]})
            if not turn.tool_calls:
                emit({"type": "final", "step": step, "text": turn.text})
                self._journal(goal_text, turn.text, step)
                return AgentResult(turn.text, step, *last, events=events, history=history + [
                    {"role": "assistant", "content": turn.text}])
            if turn.text:
                emit({"type": "say", "step": step, "text": turn.text})
            history.append({"role": "assistant", "content": turn.text, "tool_calls": turn.tool_calls})
            for call in turn.tool_calls:
                history.append(self._run_call(call, step, approver, emit))
        # Out of steps: ask once more for a summary without tools.
        emit({"type": "max_steps", "step": max_steps})
        summary = self._summarise(history, keys=keys, prefer=prefer)
        emit({"type": "final", "step": max_steps, "text": summary})
        self._journal(goal_text, summary, max_steps)
        return AgentResult(summary, max_steps, *last, stopped="max_steps", events=events, history=history)

    # ------------------------------------------------------------------------
    def _run_call(self, call: dict[str, Any], step: int, approver: Approver, emit: EventSink) -> dict[str, Any]:
        name, args = call.get("name", ""), call.get("arguments") or {}
        base = {"role": "tool", "tool_call_id": call.get("id") or "call", "name": name}
        tool = self.tools.get(name)
        if not tool:
            emit({"type": "tool_result", "step": step, "id": base["tool_call_id"], "name": name, "ok": False,
                  "output": f"unknown tool '{name}'"})
            return {**base, "content": f"ERROR: unknown tool '{name}'. Available: {', '.join(self.tools)}"}
        decision = policy.decide(name, tool.level, args)
        emit({"type": "tool_call", "step": step, "id": base["tool_call_id"], "name": name, "args": args,
              "decision": decision.as_dict()})
        if decision.action == policy.ASK:
            emit({"type": "approval_needed", "step": step, "id": base["tool_call_id"], "name": name, "args": args,
                  "reason": decision.reason})
            ok = False
            try:
                ok = bool(approver({"id": base["tool_call_id"], "name": name, "args": args}, decision))
            except Exception:
                ok = False
            emit({"type": "approval", "step": step, "id": base["tool_call_id"], "approved": ok})
            if not ok:
                out = "DENIED by the user. Do not retry this exact call; ask or choose another approach."
                emit({"type": "tool_result", "step": step, "id": base["tool_call_id"], "name": name, "ok": False,
                      "output": "denied by user"})
                return {**base, "content": out}
        elif decision.action == policy.DENY:
            emit({"type": "tool_result", "step": step, "id": base["tool_call_id"], "name": name, "ok": False,
                  "output": f"blocked: {decision.reason}"})
            return {**base, "content": f"BLOCKED by safety policy: {decision.reason}"}
        t0 = time.monotonic()
        ok, out = tools_mod.call(tool, self.ctx, args)
        if len(out) > MAX_RESULT_CHARS:
            out = out[:MAX_RESULT_CHARS] + f"\n[…{len(out) - MAX_RESULT_CHARS} more chars]"
        emit({"type": "tool_result", "step": step, "id": base["tool_call_id"], "name": name, "ok": ok,
              "output": out[:4000], "ms": int((time.monotonic() - t0) * 1000)})
        return {**base, "content": out if ok else f"ERROR: {out}"}

    def _summarise(self, history: list[dict[str, Any]], *, keys, prefer) -> str:
        from automoto import toolcalls as tc

        msgs = tc.render_text(history) + [{"role": "user", "content":
                                           "You ran out of steps. Summarise what you did, what is left, and stop."}]
        try:
            kw: dict[str, Any] = {"keys": keys, "prefer": prefer}
            return router.ask(msgs, **kw).text
        except Exception as exc:
            return f"Stopped after the step limit ({exc.__class__.__name__} while summarising)."

    def _journal(self, goal: str, answer: str, steps: int) -> None:
        try:
            self.memory.log(self.client, f"{goal[:200]} → {answer[:300]} ({steps} steps)")
        except Exception:
            pass


def format_args(args: dict[str, Any], limit: int = 160) -> str:
    s = json.dumps(args, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + "…"
