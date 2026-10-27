// A recorded run opened in the browser: a run from the history (.vexsim/runs) or a
// telemetry log from the workspace, ready to scrub, compare and plot.

import { api } from "./api";
import { Playback } from "./playback";
import type { RunRecord, Telemetry } from "./protocol";

export interface Recording {
  key: string; // the run's id, or "log:" and the log's path
  name: string;
  label: string; // the name and when it was made, to tell runs of the same name apart
  run: RunRecord | null; // null: a telemetry log from the workspace
  playback: Playback;
  telemetry: Telemetry | null; // a log's comes with it; a run's is fetched for the plots
  console: string[] | null; // null: the live session's own console shows instead
  robot: string; // the robot and field the run form names while this is shown
  field: string;
}

/** A run from the history. `own`: the live session's run, whose console is already on screen. */
export async function openRun(id: string, own = false): Promise<Recording> {
  const [details, tape] = await Promise.all([api.run(id), api.tape(id)]);
  const { run } = details;
  return {
    key: run.id,
    name: run.name,
    label: `${when(run.created)} ${run.name}`,
    run,
    playback: new Playback(tape),
    telemetry: null,
    console: own ? null : details.console,
    robot: run.spec.robot,
    field: run.spec.field ?? "",
  };
}

/** A telemetry log (vexsim run --record) from the workspace, drawn with `robot` on `field`. */
export async function openLog(log: string, robot: string, field: string): Promise<Recording> {
  const replay = await api.replay(log, robot, field || null);
  return {
    key: `log:${log}`,
    name: replay.name,
    label: replay.name,
    run: null,
    playback: new Playback(replay.tape),
    telemetry: replay.telemetry,
    console: [],
    robot,
    field,
  };
}

/** A benchmark's worst case (a telemetry log in its result), drawn with the scenario's
 * robot on its field. */
export async function openWorstCase(result: string, file: string, robot: string, field: string): Promise<Recording> {
  const replay = await api.benchReplay(result, file);
  return {
    key: `bench:${result}/${file}`,
    name: replay.name,
    label: replay.name,
    run: null,
    playback: new Playback(replay.tape),
    telemetry: replay.telemetry,
    console: [],
    robot,
    field,
  };
}

/** When a run was made: the time today (to the second: runs come quickly), the day and
 * time before. */
export function when(created: number, now = Date.now()): string {
  const date = new Date(created * 1000);
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  if (new Date(now).toDateString() === date.toDateString()) return time;
  return `${date.toLocaleDateString([], { month: "short", day: "numeric" })} ${time}`;
}

/** A recording with a new name (and label). */
export function renamed(recording: Recording, run: RunRecord): Recording {
  return { ...recording, run, name: run.name, label: `${when(run.created)} ${run.name}` };
}

/** The telemetry of each recording, fetched once (a run's), or as it came (a log's). */
const fetched = new Map<string, Promise<Telemetry>>();

export function telemetryOf(recording: Recording): Promise<Telemetry> {
  if (recording.telemetry) return Promise.resolve(recording.telemetry);
  let pending = fetched.get(recording.key);
  if (!pending) {
    pending = api.telemetry(recording.key);
    pending.catch(() => fetched.delete(recording.key)); // try again next time
    fetched.set(recording.key, pending);
  }
  return pending;
}

export function forgetTelemetry(key: string): void {
  fetched.delete(key);
}

// --- compared runs ---------------------------------------------------------------------------

/** Runs drawn over the shown one, at most. */
export const MAX_COMPARED = 3;

/** How each compared run is drawn, in order: in grey ink, told apart by the dashes of its
 * line (on the field and in the plots) and by its name. Hues are taken: the field already
 * uses as many as stay distinct for every kind of color vision. */
export const COMPARE_DASHES: readonly (readonly number[])[] = [
  [8, 5],
  [2, 4],
  [10, 4, 2, 4],
];

/** A name short enough to label a robot on the field. */
export function shortName(name: string, max = 28): string {
  return name.length > max ? `${name.slice(0, max - 1)}…` : name;
}
