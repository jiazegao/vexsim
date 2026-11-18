// The runs (App.tsx): the one that's going (its session: started, restarted, driven, stopped)
// and the recorded ones (the history, the one on the field, those drawn over it), and which of
// them the field shows.

import type { Dispatch, SetStateAction } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { Compared, FieldSource } from "../components/FieldView";
import type { ControllerInput } from "../controller";
import { NEUTRAL } from "../controller";
import type { Playhead } from "../playhead";
import type { RunConfiguration, RunProblem, RunRecord, RunSpec, SweepTrial } from "../protocol";
import type { Recording } from "../recording";
import { COMPARE_DASHES, forgetTelemetry, MAX_COMPARED, openLog, openRun, openWorstCase, renamed, shortName } from "../recording";
import type { RunForm } from "../runform";
import { sameRun, specToForm } from "../runform";
import { isLive, SessionStore } from "../session";
import { useController } from "../useController";
import { useStore } from "../useStore";
import { VideoExport } from "../video";
import { BUSY, STARTABLE } from "./shared";

export function useRuns(deps: {
  root: string; // the workspace's folder
  playhead: Playhead;
  form: RunForm;
  setForm: Dispatch<SetStateAction<RunForm>>;
  setProblem: (problem: RunProblem | null) => void;
  setPage: (page: string) => void;
  configurations: RunConfiguration[];
  runOnSave: boolean; // a save of the run's code runs it again
}) {
  const { root, playhead, form, setForm, setProblem, setPage, configurations, runOnSave } = deps;
  const [store, setStore] = useState<SessionStore | null>(null);
  const [starting, setStarting] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [onScreen, setOnScreen] = useState<ControllerInput>(NEUTRAL);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [runsLoaded, setRunsLoaded] = useState(false); // the run history has been read once
  const [shown, setShown] = useState<Recording | null>(null); // the recorded run on the field
  const [compared, setCompared] = useState<Recording[]>([]); // drawn over it
  const [opening, setOpening] = useState<string | null>(null); // the run (or log) being fetched
  const [closedRun, setClosedRun] = useState(false); // the ended live run was put away
  const [video, setVideo] = useState<VideoExport | null>(null);
  useStore(store);

  const rootRef = useRef(root);
  rootRef.current = root;
  const storeRef = useRef<SessionStore | null>(null);
  const attach = useCallback(
    (id: string, speedNow: number) => {
      storeRef.current?.close();
      const next = new SessionStore(id, rootRef.current);
      if (speedNow !== 1) next.send({ cmd: "speed", value: speedNow });
      next.connect();
      storeRef.current = next;
      setStore(next);
      setOnScreen(NEUTRAL);
      setShown(null); // the new run takes the field
      setClosedRun(false);
      playhead.pause();
    },
    [playhead],
  );
  /** Leave the live session (stopping it first if it's still going). */
  const leaveSession = useCallback(async () => {
    const live = storeRef.current;
    if (!live) return false;
    const going = BUSY.includes(live.state);
    if (going) await api.stopSession(live.id).catch(() => {});
    live.close();
    storeRef.current = null;
    setStore(null);
    return going;
  }, []);
  useEffect(() => () => storeRef.current?.close(), []);

  const loadRuns = useCallback(async () => {
    try {
      setRuns(await api.runs());
      setRunsLoaded(true);
    } catch {
      // the list stays as it was
    }
  }, []);

  const state = store?.state ?? null;
  const live = state !== null && isLive(state);
  const busy = BUSY.includes(state ?? "");
  const spec = store?.scene?.spec ?? store?.info?.spec ?? null;
  const scripted = !!spec?.input || !!spec?.follow; // nobody drives: a recording, or a log's path
  const driving = live && !scripted;
  const gamepad = useController(store, driving, onScreen);

  // Every run is recorded when it ends; the live run's recording then takes its place on the
  // field, to scrub.
  const recorded = store?.recorded ?? null;
  const sceneRun = store?.scene?.run_id ?? null;
  const autoOpened = useRef<string | null>(null);
  useEffect(() => {
    if (recorded) loadRuns();
  }, [recorded, loadRuns]);
  useEffect(() => {
    if (!recorded || recorded.id !== sceneRun || busy || autoOpened.current === recorded.id) return;
    autoOpened.current = recorded.id;
    let current = true;
    openRun(recorded.id, true)
      .then((recording) => {
        if (!current) return;
        setShown(recording);
        playhead.load(recording.playback.start, recording.playback.end);
      })
      .catch(() => {}); // the live run's last frame stays on the field
    return () => {
      current = false;
    };
  }, [recorded, sceneRun, busy, playhead]);

  // What the field shows: the run while it's on; afterwards its recording (or any opened one)
  // while the form names the same robot and field; otherwise the preview of what the form names.
  const formNames = (robot: string, field: string) => robot === form.robot && field === form.field;
  let source: FieldSource = { kind: "preview" };
  if (store && busy) source = { kind: "live", store };
  else if (shown && formNames(shown.robot, shown.field)) source = { kind: "recording", playback: shown.playback, playhead };
  else if (store && !closedRun && spec && formNames(spec.robot, spec.field ?? "")) source = { kind: "live", store };
  const recording = source.kind === "recording" ? shown : null;
  const recordedLayers = useMemo(() => recording?.playback.drawnLayers() ?? [], [recording]);
  const runLayers = source.kind === "live" ? Object.keys(source.store.drawings) : recordedLayers;
  const recordingPhases = useMemo(() => recording?.playback.phases() ?? [], [recording]);
  const onField: Compared[] = compared.map((r, i) => ({ playback: r.playback, label: shortName(r.label), dash: COMPARE_DASHES[i] }));

  const show = useCallback(
    (next: Recording) => {
      setShown(next);
      setCompared((list) => list.filter((r) => r.key !== next.key));
      playhead.load(next.playback.start, next.playback.end);
      setProblem(null);
    },
    [playhead, setProblem],
  );

  /** Start a run of `spec` (replacing any other), called `name` in the run history. */
  const startRun = useCallback(
    async (spec: RunSpec, name: string | null) => {
      setStarting(true);
      setProblem(null);
      video?.cancel();
      try {
        const started = await api.startSession(spec, name);
        if ("problem" in started) setProblem(started.problem);
        else {
          attach(started.session.id, speed);
          document.getElementById("field-canvas")?.focus(); // so Space pauses, not runs again
        }
      } catch (error) {
        setProblem({ error: (error as Error).message, issues: [] });
      } finally {
        setStarting(false);
      }
    },
    [attach, speed, video, setProblem],
  );

  /** The run from its start, with its code as it is now. None of its files changed since it
   * started: its own session starts it again at once. Otherwise it's checked, built and started
   * afresh, as Run would (a new session in its place); if it can't be, the run that's there stays. */
  const restarting = useRef(false);
  const restart = useCallback(async () => {
    const live = storeRef.current;
    if (!live || restarting.current || !STARTABLE.includes(live.state)) return;
    restarting.current = true;
    setProblem(null);
    video?.cancel();
    try {
      const again = await api.restartSession(live.id);
      if ("problem" in again) setProblem(again.problem);
      else if (again.session.id !== live.id) attach(again.session.id, speed);
    } catch (error) {
      setProblem({ error: (error as Error).message, issues: [] });
    } finally {
      restarting.current = false;
    }
  }, [attach, speed, video, setProblem]);
  // Run on save: the run's files changed (its session says so, each time they do) and the
  // switch is on, so it runs again; with the switch off, the field says "Code changed".
  const changes = store?.changes ?? 0;
  useEffect(() => {
    if (runOnSave && changes > 0) void restart();
  }, [runOnSave, changes]); // eslint-disable-line react-hooks/exhaustive-deps -- only when a save lands, or the switch goes on

  /** A sweep's trial, run again on the field (it's deterministic: the same run). */
  const watchTrial = useCallback(
    async (trial: SweepTrial, name: string) => {
      setShown(null);
      setForm(specToForm(trial.spec));
      setPage("simulate");
      await startRun(trial.spec, name);
    },
    [startRun, setForm, setPage],
  );

  const changeSpeed = useCallback(
    (value: number) => {
      setSpeed(value);
      store?.send({ cmd: "speed", value });
    },
    [store],
  );

  const stop = useCallback(() => {
    if (store) api.stopSession(store.id).catch(() => {});
  }, [store]);

  /** A run from the history on the field (the live one stopped), its spec in the form. */
  const openRecorded = async (record: RunRecord) => {
    setOpening(record.id);
    try {
      const next = await openRun(record.id);
      video?.cancel();
      if (await leaveSession()) loadRuns(); // the stopped run was recorded too
      const saved = configurations.find((c) => c.name === record.name && sameRun(specToForm(record.spec), c));
      setForm(specToForm(record.spec, saved?.name ?? ""));
      show(next);
    } catch (error) {
      setProblem({ error: `Couldn't open ${record.name}: ${(error as Error).message}`, issues: [] });
    } finally {
      setOpening(null);
    }
  };

  /** A telemetry log from the workspace, played back with the robot and field the form names. */
  const openTelemetryLog = async (path: string) => {
    if (!form.robot) {
      setProblem({ error: "Pick the robot this log was recorded with, then click the log again.", issues: [] });
      return;
    }
    setOpening(`log:${path}`);
    try {
      const next = await openLog(path, form.robot, form.field);
      video?.cancel();
      if (await leaveSession()) loadRuns();
      show(next);
    } catch (error) {
      setProblem({ error: `Couldn't play ${path} back: ${(error as Error).message}`, issues: [] });
    } finally {
      setOpening(null);
    }
  };

  /** A benchmark's worst case on the field, with its scenario's robot and field. */
  const watchWorstCase = async (result: string, file: string, robot: string, field: string) => {
    try {
      const next = await openWorstCase(result, file, robot, field);
      video?.cancel();
      if (await leaveSession()) loadRuns();
      setForm((current) => ({ ...current, config: "", robot, field }));
      show(next);
      setPage("simulate");
    } catch (error) {
      setProblem({ error: `Couldn't open that worst case: ${(error as Error).message}`, issues: [] });
      setPage("simulate");
    }
  };

  const toggleCompare = async (record: RunRecord) => {
    if (compared.some((r) => r.key === record.id)) {
      setCompared((list) => list.filter((r) => r.key !== record.id));
      return;
    }
    setOpening(record.id);
    try {
      const next = await openRun(record.id);
      setCompared((list) => (list.length < MAX_COMPARED && !list.some((r) => r.key === next.key) ? [...list, next] : list));
    } catch (error) {
      setProblem({ error: `Couldn't open ${record.name}: ${(error as Error).message}`, issues: [] });
    } finally {
      setOpening(null);
    }
  };

  const changeRun = async (record: RunRecord, update: { kept?: boolean; name?: string }) => {
    try {
      const saved = await api.updateRun(record.id, update);
      setRuns((list) => list.map((r) => (r.id === saved.id ? saved : r)));
      const rename = (r: Recording) => (r.key === saved.id ? renamed(r, saved) : r);
      setShown((current) => current && rename(current));
      setCompared((list) => list.map(rename));
    } catch (error) {
      setProblem({ error: `Couldn't change ${record.name}: ${(error as Error).message}`, issues: [] });
    }
  };

  const deleteRun = async (record: RunRecord) => {
    try {
      await api.deleteRun(record.id);
      forgetTelemetry(record.id);
      setRuns((list) => list.filter((r) => r.id !== record.id));
      setCompared((list) => list.filter((r) => r.key !== record.id));
      if (shown?.key === record.id) closeRecording();
    } catch (error) {
      setProblem({ error: `Couldn't delete ${record.name}: ${(error as Error).message}`, issues: [] });
    }
  };

  /** Back to the robot as the form sets it up. */
  const closeRecording = () => {
    video?.cancel();
    playhead.pause();
    setShown(null);
    setClosedRun(true);
  };

  const toggleVideo = () => {
    if (video) {
      video.cancel();
      return;
    }
    const canvas = document.getElementById("field-canvas");
    if (!(canvas instanceof HTMLCanvasElement) || !recording) return;
    const exporter = new VideoExport(canvas, playhead, `vexsim-${recording.name}`, (_saved, error) => {
      setVideo(null);
      if (error) setProblem({ error, issues: [] });
    });
    setVideo(exporter);
    exporter.start();
  };

  return {
    // the run that's going
    store,
    state,
    busy,
    spec,
    scripted,
    driving,
    gamepad,
    onScreen,
    setOnScreen,
    starting,
    speed,
    attach,
    leaveSession,
    startRun,
    restart,
    changeSpeed,
    stop,
    watchTrial,
    // the recorded ones
    runs,
    runsLoaded,
    loadRuns,
    opening,
    setOpening,
    compared,
    setCompared,
    video,
    show,
    setShown,
    openRecorded,
    openTelemetryLog,
    watchWorstCase,
    toggleCompare,
    changeRun,
    deleteRun,
    closeRecording,
    toggleVideo,
    // what the field shows
    source,
    recording,
    runLayers,
    recordingPhases,
    onField,
  };
}

export type Runs = ReturnType<typeof useRuns>;
