// The UI server's REST API (see vexsim/ui/server.py). Every request carries the session
// cookie the server set when the page was first opened with its ?token= link.

import type {
  AppInfo,
  CalibrationSetup,
  ConfigCheck,
  ConfigEdit,
  ConfigFile,
  ConfigKind,
  ConfigPatched,
  JobInfo,
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

/** A request whose 422 may carry a RunProblem (a config's issues): what it gave, or that. */
async function orProblem<T>(path: string, init: RequestInit): Promise<{ ok: T } | { problem: RunProblem }> {
  const response = await fetch(path, { credentials: "same-origin", headers: { "content-type": "application/json" }, ...init });
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
  resultFileUrl: (kind: ResultKind, id: string, name: string) => `/api/results/${kind}/${path(id)}/files/${path(name)}`,
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
  csvUrl: (id: string) => `/api/runs/${encodeURIComponent(id)}/telemetry.csv`,
  replay: (log: string, robot: string, field: string | null) =>
    request<Replay>("/api/replay", { method: "POST", body: JSON.stringify({ log, robot, field }) }),
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
      headers: { "content-type": "application/json" },
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
      headers: { "content-type": "application/json" },
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
      headers: { "content-type": "application/json" },
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
