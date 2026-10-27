// The UI server's REST API (see vexsim/ui/server.py). Every request carries the server's
// token: the page was opened with it in its link (?token=...), and the server traded it for a
// cookie. A page shown inside another app (the VS Code panel) gets no cookies, so the page
// keeps the token for this tab as well, and sends it with each request.

import type {
  AppInfo,
  CalibrationSetup,
  ConfigCheck,
  ConfigEdit,
  ConfigFile,
  ConfigKind,
  ConfigPatched,
  JobInfo,
  MclLogTape,
  Preview,
  Replay,
  ResultAbout,
  ResultKind,
  RoutinePlan,
  RunConfiguration,
  RunConfigurations,
  RunDetails,
  RunProblem,
  RunRecord,
  RunSpec,
  RunUpdate,
  ScenarioInfo,
  SessionInfo,
  StartJob,
  Sweep,
  SweepsFile,
  Tape,
  Telemetry,
  WorkspaceInfo,
} from "./protocol";

const TOKEN_KEY = "vexsim.token";

function keepToken(): string | null {
  if (typeof location === "undefined") return null; // not in a page (unit tests)
  const fromUrl = new URL(location.href).searchParams.get("token");
  try {
    if (fromUrl) sessionStorage.setItem(TOKEN_KEY, fromUrl);
    else return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    // storage off: the cookie alone after a reload
  }
  return fromUrl;
}

const token = keepToken();

/** A request's headers: JSON, and the token. */
function headers(): Record<string, string> {
  return token ? { "content-type": "application/json", authorization: `Bearer ${token}` } : { "content-type": "application/json" };
}

/** One of the server's addresses with the token in it, for what can't send headers:
 * WebSockets, links and downloads. */
export function withToken(url: string): string {
  if (!token) return url;
  return `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
}

/** The WebSocket address of the server's `path`. */
export function socketUrl(path: string): string {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return withToken(`${scheme}//${location.host}${path}`);
}

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
  const response = await fetch(path, { credentials: "same-origin", headers: headers(), ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, describe(body.detail ?? response.statusText));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export type StartResult = { session: SessionInfo } | { problem: RunProblem };

/** A request whose 422 may carry a RunProblem (a config's issues): what it gave, or that. */
async function orProblem<T>(path: string, init: RequestInit): Promise<{ ok: T } | { problem: RunProblem }> {
  const response = await fetch(path, { credentials: "same-origin", headers: headers(), ...init });
  const body = await response.json().catch(() => ({}));
  if (response.status === 422) {
    if (typeof body.error === "string") return { problem: body as RunProblem };
    return { problem: { error: describe(body.detail), issues: [] } };
  }
  if (!response.ok) throw new ApiError(response.status, describe(body.detail ?? response.statusText));
  return { ok: body as T };
}

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
const path = (...parts: string[]) => parts.map(encodeURIComponent).join("/");

export const api = {
  info: () => request<AppInfo>("/api/info"),
  workspace: () => request<WorkspaceInfo>("/api/workspace"),
  sessions: () => request<SessionInfo[]>("/api/sessions"),
  stopSession: (id: string) => request<void>(`/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" }),
  jobs: () => request<JobInfo[]>("/api/jobs"),
  /** Start a job; a RunProblem if it can't start (a broken config, a missing file). */
  startJob: (job: StartJob) => orProblem<JobInfo>("/api/jobs", post(job)),
  /** A job's log from line `since` on, its items from `itemsSince` on, and its result. */
  job: (id: string, since = 0, itemsSince = 0) => request<JobInfo>(`/api/jobs/${path(id)}?since=${since}&items_since=${itemsSince}`),
  cancelJob: (id: string) => request<JobInfo>(`/api/jobs/${path(id)}`, { method: "DELETE" }),
  results: (kind: ResultKind) => request<ResultAbout[]>(`/api/results/${kind}`),
  result: <T>(kind: ResultKind, id: string) => request<T>(`/api/results/${kind}/${path(id)}`),
  deleteResult: (kind: ResultKind, id: string) => request<void>(`/api/results/${kind}/${path(id)}`, { method: "DELETE" }),
  /** A file a job wrote in its result's folder (a report, a CSV), to open or download. */
  resultFileUrl: (kind: ResultKind, id: string, name: string) => withToken(`/api/results/${kind}/${path(id)}/files/${path(name)}`),
  benchReplay: (id: string, file: string) => request<Replay>(`/api/results/bench/${path(id)}/replay`, post({ file })),
  scenario: (scenario: string) => orProblem<ScenarioInfo>(`/api/bench/scenario?path=${encodeURIComponent(scenario)}`, { method: "GET" }),
  sweeps: () => request<SweepsFile>("/api/sweeps"),
  saveSweeps: (sweeps: Sweep[]) => request<SweepsFile>("/api/sweeps", { method: "PUT", body: JSON.stringify({ sweeps }) }),
  calibrationSetup: (robot: string) => orProblem<CalibrationSetup>(`/api/calibrate/parameters?robot=${encodeURIComponent(robot)}`, { method: "GET" }),
  routine: (robot: string, project: string, write = false) => orProblem<RoutinePlan>("/api/calibrate/routine", post({ robot, project, write })),
  setOverrides: (text: string, values: Record<string, number>) => request<ConfigPatched>("/api/config/overrides", post({ text, values })),
  configurations: () => request<RunConfigurations>("/api/configurations"),
  runs: () => request<RunRecord[]>("/api/runs"),
  run: (id: string) => request<RunDetails>(`/api/runs/${encodeURIComponent(id)}`),
  tape: (id: string) => request<Tape>(`/api/runs/${encodeURIComponent(id)}/tape`),
  telemetry: (id: string) => request<Telemetry>(`/api/runs/${encodeURIComponent(id)}/telemetry`),
  updateRun: (id: string, update: RunUpdate) =>
    request<RunRecord>(`/api/runs/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(update) }),
  deleteRun: (id: string) => request<void>(`/api/runs/${encodeURIComponent(id)}`, { method: "DELETE" }),
  csvUrl: (id: string) => withToken(`/api/runs/${encodeURIComponent(id)}/telemetry.csv`),
  replay: (log: string, robot: string, field: string | null) =>
    request<Replay>("/api/replay", { method: "POST", body: JSON.stringify({ log, robot, field }) }),
  /** An MCL log from the workspace, to play on the field; a RunProblem if it doesn't read. */
  mclLog: (log: string) => orProblem<MclLogTape>(`/api/mcllog?path=${encodeURIComponent(log)}`, { method: "GET" }),
  saveConfigurations: (configurations: RunConfiguration[]) =>
    request<RunConfigurations>("/api/configurations", { method: "PUT", body: JSON.stringify({ configurations }) }),
  config: (path: string) => request<ConfigFile>(`/api/config?path=${encodeURIComponent(path)}`),
  checkConfig: (kind: ConfigKind, text: string) =>
    request<ConfigCheck>("/api/config/check", { method: "POST", body: JSON.stringify({ kind, text }) }),
  patchConfig: (kind: ConfigKind, text: string, edits: ConfigEdit[]) =>
    request<ConfigPatched>("/api/config/patch", { method: "POST", body: JSON.stringify({ kind, text, edits }) }),

  /** Write a config opened at `version` (null: whatever is on disk); a conflict if the
   * file changed on disk since. */
  async saveConfig(path: string, text: string, version: string | null): Promise<{ version: string } | { conflict: string; version: string }> {
    const response = await fetch("/api/config", {
      method: "PUT",
      credentials: "same-origin",
      headers: headers(),
      body: JSON.stringify({ path, text, version }),
    });
    const body = await response.json().catch(() => ({}));
    if (response.status === 409) return { conflict: String(body.detail), version: String(body.version) };
    if (!response.ok) throw new ApiError(response.status, describe(body.detail ?? response.statusText));
    return { version: String(body.version) };
  },

  /** The robot and field before a run; a RunProblem if their configs don't load. */
  async preview(robot: string, field: string | null): Promise<{ preview: Preview } | { problem: RunProblem }> {
    const response = await fetch("/api/preview", {
      method: "POST",
      credentials: "same-origin",
      headers: headers(),
      body: JSON.stringify({ robot, field }),
    });
    const body = await response.json().catch(() => ({}));
    if (response.status === 422 && typeof body.error === "string") return { problem: body as RunProblem };
    if (!response.ok) throw new ApiError(response.status, describe(body.detail ?? response.statusText));
    return { preview: body as Preview };
  },

  /** Start a run (replacing any other), called `name` in the run history; a RunProblem
   * if it can't start. */
  async startSession(spec: RunSpec, name: string | null = null): Promise<StartResult> {
    const response = await fetch("/api/sessions", {
      method: "POST",
      credentials: "same-origin",
      headers: headers(),
      body: JSON.stringify({ spec, replace: true, name }),
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
  return socketUrl(`/api/sessions/${encodeURIComponent(id)}/ws`);
}

/** Hold a connection to the server while this page is open, so it knows when the app's last
 * page has closed (a server started for a window of its own then stops). It reconnects if
 * the connection drops: soon, then less often while the server is gone. */
export function stayPresent(): void {
  let wait = 1000;
  const connect = () => {
    const socket = new WebSocket(socketUrl("/api/presence"));
    socket.onopen = () => {
      wait = 1000;
    };
    socket.onclose = () => {
      setTimeout(connect, wait);
      wait = Math.min(wait * 2, 30_000);
    };
  };
  connect();
}

/** Drop ?token=... from the address bar once the server has set its cookie. */
export function forgetTokenInUrl(): void {
  const url = new URL(location.href);
  if (!url.searchParams.has("token")) return;
  url.searchParams.delete("token");
  history.replaceState(history.state, "", url.pathname + url.search + url.hash);
}
