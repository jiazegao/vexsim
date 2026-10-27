// The UI server's REST API (see vexsim/ui/server.py). Every request carries the session
// cookie the server set when the page was first opened with its ?token= link.

import type {
  AppInfo,
  JobInfo,
  Preview,
  RunConfiguration,
  RunConfigurations,
  RunProblem,
  RunSpec,
  SessionInfo,
  WorkspaceInfo,
} from "./protocol";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI's validation errors: [{loc: [...], msg: "..."}]
    return detail
      .map((d) => {
        const item = d as { loc?: unknown[]; msg?: string };
        const where = (item.loc ?? []).filter((p) => p !== "body").join(".");
        return where ? `${where}: ${item.msg}` : String(item.msg);
      })
      .join("; ");
  }
  return "request failed";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, describe(body.detail ?? response.statusText));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export type StartResult = { session: SessionInfo } | { problem: RunProblem };

export const api = {
  info: () => request<AppInfo>("/api/info"),
  workspace: () => request<WorkspaceInfo>("/api/workspace"),
  sessions: () => request<SessionInfo[]>("/api/sessions"),
  stopSession: (id: string) => request<void>(`/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" }),
  jobs: () => request<JobInfo[]>("/api/jobs"),
  configurations: () => request<RunConfigurations>("/api/configurations"),
  saveConfigurations: (configurations: RunConfiguration[]) =>
    request<RunConfigurations>("/api/configurations", { method: "PUT", body: JSON.stringify({ configurations }) }),

  /** The robot and field before a run; a RunProblem if their configs don't load. */
  async preview(robot: string, field: string | null): Promise<{ preview: Preview } | { problem: RunProblem }> {
    const response = await fetch("/api/preview", {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ robot, field }),
    });
    const body = await response.json().catch(() => ({}));
    if (response.status === 422 && typeof body.error === "string") return { problem: body as RunProblem };
    if (!response.ok) throw new ApiError(response.status, describe(body.detail ?? response.statusText));
    return { preview: body as Preview };
  },

  /** Start a run (replacing any other); a RunProblem if it can't start. */
  async startSession(spec: RunSpec): Promise<StartResult> {
    const response = await fetch("/api/sessions", {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ spec, replace: true }),
    });
    const body = await response.json().catch(() => ({}));
    if (response.status === 422) {
      if (typeof body.error === "string") return { problem: body as RunProblem };
      return { problem: { error: describe(body.detail), issues: [] } };
    }
    if (!response.ok) throw new ApiError(response.status, describe(body.detail ?? response.statusText));
    return { session: body as SessionInfo };
  },
};

/** The WebSocket address of a session's messages. */
export function sessionSocketUrl(id: string): string {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/api/sessions/${encodeURIComponent(id)}/ws`;
}

/** Drop ?token=... from the address bar once the server has set its cookie. */
export function forgetTokenInUrl(): void {
  const url = new URL(location.href);
  if (!url.searchParams.has("token")) return;
  url.searchParams.delete("token");
  history.replaceState(history.state, "", url.pathname + url.search + url.hash);
}
