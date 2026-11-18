// A real robot's log beside the simulator (App.tsx): an MCL log, or a robot log of vexsim's
// logger. It plays on its own timeline, or with the run beside it; it can be replayed (a
// virtual driver follows its path), and a routine's log run beside the routine itself.

import type { Dispatch, SetStateAction } from "react";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { LogTape } from "../mcllog";
import { isRobotLog, LogPlayback } from "../mcllog";
import type { Playhead } from "../playhead";
import type { NothingToPlay, ProjectRoutines, RunConfiguration, RunProblem, RunSpec, WorkspaceInfo } from "../protocol";
import type { RunForm } from "../runform";
import { formToSpec, specToForm } from "../runform";
import type { Calibration } from "./shared";
import type { Runs } from "./useRuns";

export function useRealLog(deps: {
  runs: Runs;
  playhead: Playhead;
  form: RunForm;
  setForm: Dispatch<SetStateAction<RunForm>>;
  workspace: WorkspaceInfo | null;
  configurations: RunConfiguration[];
  routines: ProjectRoutines | null; // the run form's PROS project's
  setProblem: (problem: RunProblem | null) => void;
  setPage: (page: string) => void;
  setCalibration: Dispatch<SetStateAction<Calibration>>;
}) {
  const { runs, playhead, form, setForm, workspace, configurations, routines, setProblem, setPage, setCalibration } = deps;
  const { source, recording, recordingPhases, spec, setOpening, setShown, startRun, runLayers } = runs;
  const [realLog, setRealLog] = useState<LogPlayback | null>(null); // a real robot's log (MCL or vexsim's), beside the simulator
  const [logShift, setLogShift] = useState(0); // s: the log nudged later against the run beside it
  const [replayWith, setReplayWith] = useState<string | null>(null); // the saved run to replay it with ("": the form)
  const drawnLayers = realLog ? [...new Set([...realLog.layers(), ...runLayers])] : runLayers;

  // An MCL log beside the simulator: it plays on its own timeline, or with the run beside it
  // (live or recorded), its first update at the moment that run began following it (a replay
  // of it), else where the run's program began (after initialize), nudged by logShift.
  const follows = (run: RunSpec | null | undefined) => !!realLog && !!run?.follow?.log && run.follow.log === realLog.tape.path;
  let logAt: number | null = null; // the run's time of the log's first update; null: not yet
  if (realLog && recording) {
    const run = recording.run;
    const began = recordingPhases.find((phase) => phase.name !== "initialize" && phase.name !== "disabled");
    logAt = (follows(run?.spec) ? run?.follow_start : null) ?? began?.start ?? 0;
  } else if (realLog && source.kind === "live") {
    logAt = follows(source.store.scene?.spec ?? spec) ? source.store.following : source.store.programStart;
  }
  if (logAt !== null) logAt += logShift;
  const logAlone = !!realLog && source.kind === "preview"; // nothing beside it: its own timeline
  const liveStore = source.kind === "live" ? source.store : null;
  const logClock = (): number | null => {
    if (logAlone) return playhead.t;
    if (logAt === null) return null;
    if (recording) return playhead.t - logAt;
    const t = liveStore?.frame?.t;
    return t === undefined ? null : t - logAt;
  };
  useEffect(() => {
    if (realLog && logAlone) playhead.load(realLog.start, realLog.end, realLog.start);
  }, [realLog, logAlone, playhead]);

  /** A real robot's log beside the simulator: an MCL log, or a robot log of vexsim's logger, its
   * rays drawn from where the robot it names (a calibration log does), else the run form's, mounts
   * its distance sensors. With `orFit`, a robot log with nothing to play on the field (no pose of
   * its code's, no spot to start from: the calibration routine's log, say) opens on the Calibrate
   * page's quick fit instead, which fits any run's log. */
  const openRealLog = async (kind: "mcllog" | "robotlog", path: string, orFit = false) => {
    setOpening(`log:${path}`);
    try {
      let result: { ok: LogTape | NothingToPlay } | { problem: RunProblem } = kind === "mcllog" ? await api.mclLog(path) : await api.robotLog(path, form.robot);
      if ("ok" in result && isRobotLog(result.ok)) {
        // the robot and field it names (a calibration log does): drawn, and run beside it
        const { robot: robotName, field: fieldName } = result.ok.summary;
        const robot = robotName ? workspace?.items.find((i) => i.kind === "robot" && !i.problem && i.name === robotName) : undefined;
        const field = fieldName ? workspace?.items.find((i) => i.kind === "field" && !i.problem && i.name === fieldName) : undefined;
        if ((robot && robot.path !== form.robot) || (field && field.path !== form.field)) {
          setForm((f) => ({ ...f, ...(robot ? { robot: robot.path } : {}), ...(field ? { field: field.path } : {}) }));
        }
        if (robot && robot.path !== form.robot) result = await api.robotLog(path, robot.path);
      }
      if ("problem" in result) {
        setPage("simulate");
        setProblem(result.problem);
      } else if ("why" in result.ok) {
        // it has no path to play: a run's log for the quick fit, else why not
        if (orFit) {
          setCalibration((c) => ({ ...c, log: path, tab: "quick" }));
          setPage("calibrate");
        } else {
          setPage("simulate");
          setProblem({ error: `${path}: ${result.ok.why}`, issues: [] });
        }
      } else {
        setPage("simulate");
        setRealLog(new LogPlayback(result.ok));
        setLogShift(0);
        setReplayWith(null);
        setProblem(null);
      }
    } catch (error) {
      setPage("simulate");
      setProblem({ error: `Couldn't open ${path}: ${(error as Error).message}`, issues: [] });
    } finally {
      setOpening(null);
    }
  };

  const closeRealLog = () => {
    setRealLog(null);
    if (!recording) playhead.pause();
  };

  // A replay of the open log: a saved run (or the run form) with a virtual driver following the
  // log's path from where it starts. Saved runs that follow logs come first.
  const replayRuns = configurations.filter((c) => c.program);
  replayRuns.sort((a, b) => Number(!!b.follow) - Number(!!a.follow));
  const followers = replayRuns.filter((c) => c.follow); // saved runs made to replay logs
  const replayChoice = replayWith ?? (followers.find((c) => c.name === form.config) ?? followers.find((c) => c.program === form.program) ?? followers[0])?.name ?? "";
  const replayLog = async () => {
    if (!realLog) return;
    const chosen = configurations.find((c) => c.name === replayChoice) ?? null;
    let base: RunSpec;
    if (chosen) base = chosen;
    else {
      const result = formToSpec(form);
      if ("error" in result) {
        setProblem({ error: result.error, issues: [] });
        return;
      }
      base = result.spec;
    }
    const { name: _, ...rest } = base as RunConfiguration;
    const replay: RunSpec = {
      ...rest,
      start: realLog.tape.summary.start,
      input: null,
      follow: { log: realLog.tape.path, sticks: base.follow?.sticks ?? "tank", curve: base.follow?.curve ?? null },
    };
    setShown(null);
    setLogShift(0);
    setForm(specToForm(replay, chosen?.name ?? ""));
    await startRun(replay, `${chosen ? chosen.name : "Replay"} · ${realLog.name}`);
  };
  // A log the code's pose plays can be replayed (a calibration log's odometry can't: its program
  // has no driver control to steer)
  const followable = !!realLog && !(isRobotLog(realLog.tape) && realLog.tape.summary.pose === "odometry");

  // A routine's robot log beside the routine itself, run in the simulator: the run form's PROS
  // project's routine of the log's name (Left 40 is left40()), from where its setPose puts the robot.
  const squash = (name: string) => name.toLowerCase().replace(/[^a-z0-9]/g, "");
  const logged = realLog && isRobotLog(realLog.tape) ? realLog.tape.summary.routine : null;
  const logRoutine =
    logged && routines?.found ? (routines.routines.find((r) => squash(r.name) === squash(logged) || squash(r.name.split("::").at(-1) ?? "") === squash(logged)) ?? null) : null;
  const runLogRoutine = async () => {
    if (!realLog || !logRoutine) return;
    const at = logRoutine.start ? { x: String(logRoutine.start[0]), y: String(logRoutine.start[1]), heading: String(logRoutine.start[2]) } : {};
    const next: RunForm = { ...form, config: "", routine: logRoutine.name, route: "", mode: "autonomous", input: "", follow: "", following: false, ...at };
    const result = formToSpec(next);
    if ("error" in result) {
      setProblem({ error: result.error, issues: [] });
      return;
    }
    setShown(null);
    setLogShift(0);
    setForm(next);
    await startRun(result.spec, `${logRoutine.name} · beside ${realLog.name}`);
  };

  /** A robot log on the field, beside the simulator (from the Calibrate page). */
  const playLog = (path: string) => {
    setPage("simulate");
    void openRealLog("robotlog", path);
  };

  return {
    realLog,
    drawnLayers,
    logAt,
    logAlone,
    logClock,
    logShift,
    setLogShift,
    replayRuns,
    replayChoice,
    setReplayWith,
    followable,
    logRoutine,
    openRealLog,
    closeRealLog,
    replayLog,
    runLogRoutine,
    playLog,
  };
}

export type RealLog = ReturnType<typeof useRealLog>;
