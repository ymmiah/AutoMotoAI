// Small client for the AutoMoto local API (no VS Code imports, so it is unit-testable).
import { Session } from "./session";

export interface AgentEvent {
  type: string;
  step?: number;
  id?: string;
  name?: string;
  /** Plain-language step ("Reading your slides"), sent by AutoMoto 5.6.0b3+. */
  label?: string;
  /** For "plan" events: what the assistant is working with. */
  summary?: string;
  args?: Record<string, unknown>;
  reason?: string;
  ok?: boolean;
  output?: string;
  text?: string;
  error?: string;
  provider?: string;
  model?: string;
  approved?: boolean;
  [k: string]: unknown;
}

export interface TaskResult {
  status: string;
  text: string;
  provider?: string;
  model?: string;
  steps?: number;
  stopped?: string;
}

export interface RunOptions {
  workspace?: string;
  prefer?: string;
  maxSteps?: number;
  onEvent?: (ev: AgentEvent) => void;
  /** Called for every risky step; resolve true to allow it. Default: deny. */
  approve?: (ev: AgentEvent) => Promise<boolean>;
  signal?: { cancelled: boolean };
  pollMs?: number;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type FetchLike = (url: string, init?: any) => Promise<{ ok: boolean; status: number; json(): Promise<any>; text(): Promise<string> }>;

export class AutoMotoClient {
  constructor(private session: Session, private fetchImpl: FetchLike = (globalThis as any).fetch) {}

  get url(): string {
    return this.session.url;
  }

  async request<T = any>(path: string, body?: unknown, method?: string): Promise<T> {
    if (!path.startsWith("/api/")) throw new Error("bad API path");
    const res = await this.fetchImpl(this.session.url.replace(/\/$/, "") + path, {
      method: method || (body === undefined ? "GET" : "POST"),
      headers: { "X-AutoMoto-Token": this.session.token, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
      redirect: "error",
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const j = await res.json();
        detail = typeof j?.detail === "string" ? j.detail : j?.detail?.message || JSON.stringify(j?.detail ?? j);
      } catch {
        /* not JSON */
      }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as T;
  }

  health(): Promise<{ ok: boolean; version: string }> {
    return this.request("/api/health");
  }

  info(): Promise<any> {
    return this.request("/api/agent/info");
  }

  launchUrl(): Promise<string> {
    return this.request<{ url: string }>("/api/session/launch", {}).then((r) => r.url);
  }

  async settings(): Promise<any> {
    return this.request("/api/settings");
  }

  async addAllowedRoot(folder: string): Promise<string[]> {
    const s = await this.settings();
    const roots: string[] = Array.isArray(s.allowed_roots) ? s.allowed_roots : [];
    if (roots.includes(folder)) return roots;
    const out = await this.request<any>("/api/settings", { allowed_roots: [...roots, folder] }, "PUT");
    return out.allowed_roots || [];
  }

  /** Start an agent task and follow it to the end, answering approvals through ``opts.approve``. */
  async runAgent(messages: { role: string; content: unknown }[], opts: RunOptions = {}): Promise<TaskResult> {
    const start = await this.request<{ task_id: string }>("/api/agent", {
      messages,
      client: "vscode",
      workspace: opts.workspace || undefined,
      prefer: opts.prefer && opts.prefer !== "auto" ? opts.prefer : undefined,
      max_steps: opts.maxSteps,
    });
    const id = start.task_id;
    let since = 0;
    const answered = new Set<string>();
    const pollMs = opts.pollMs ?? 600;
    for (;;) {
      if (opts.signal?.cancelled) {
        await this.request(`/api/tasks/${encodeURIComponent(id)}/cancel`, {}).catch(() => undefined);
        opts.signal.cancelled = false;
      }
      const t = await this.request<any>(`/api/tasks/${encodeURIComponent(id)}?since=${since}`);
      since = t.next ?? since;
      for (const ev of (t.events || []) as AgentEvent[]) {
        opts.onEvent?.(ev);
        if (ev.type === "approval_needed" && ev.id && !answered.has(ev.id)) {
          answered.add(ev.id);
          let ok = false;
          try {
            ok = opts.approve ? await opts.approve(ev) : false;
          } catch {
            ok = false;
          }
          await this.request(`/api/tasks/${encodeURIComponent(id)}/approve`, { call_id: ev.id, approve: ok }).catch(() => undefined);
        }
      }
      if (["done", "error", "cancelled"].includes(t.status)) {
        const r = t.result || {};
        return { status: t.status, text: r.text || "", provider: r.provider, model: r.model, steps: r.steps, stopped: r.stopped };
      }
      await new Promise((res) => setTimeout(res, pollMs));
    }
  }
}

/** One-line summary of a tool call's arguments for approval prompts (never shows huge content). */
export function summariseArgs(args: Record<string, unknown> | undefined, max = 160): string {
  if (!args) return "";
  const parts = Object.entries(args).map(([k, v]) => {
    let s = typeof v === "string" ? v : JSON.stringify(v);
    if (k === "content" && typeof v === "string") s = `${v.length} chars`;
    return `${k}=${s}`;
  });
  const out = parts.join(", ").replace(/\s+/g, " ");
  return out.length > max ? out.slice(0, max - 1) + "…" : out;
}
