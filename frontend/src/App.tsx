import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { Place } from "./address";
import { formatPlace, HOME, isStep, parsePlace } from "./address";
import { api } from "./api";
import { ConsolePanel } from "./components/ConsolePanel";
import { Controls, SPEEDS } from "./components/Controls";
import type { ConfigRequest } from "./components/ConfigEditor";
import type { Compared, FieldSource } from "./components/FieldView";
import { FieldKey, FieldView } from "./components/FieldView";
import { FirstRun, firstSteps } from "./components/FirstRun";
import { KeysHelp } from "./components/KeysHelp";
import { NewRobotDialog } from "./components/NewRobotDialog";
import { NewRouteDialog } from "./components/NewRouteDialog";
import { Plots } from "./components/Plots";
import { Readout } from "./components/Readout";
import { RunBar } from "./components/RunBar";
import { RunsList } from "./components/RunsList";
import { Sidebar } from "./components/Sidebar";
import { Timeline } from "./components/Timeline";
import { fileName } from "./configdoc";
import type { ControllerInput } from "./controller";
import { NEUTRAL } from "./controller";
import type { Layers } from "./draw";
import { hostTheme, onHostTheme } from "./host";
import { NARROW, SHORT, useMedia, usePanel } from "./layout";
import type { LogTape } from "./mcllog";
import type { CalibrateTab } from "./pages/CalibratePage";
import { isRobotLog, LogPlayback, logSummary } from "./mcllog";
import { Playhead, usePlayheadClock } from "./playhead";
import type { Editor } from "./problems";
import { EDITORS } from "./problems";
import type { AppInfo, NothingToPlay, Preview, ProjectRoutines, RunConfiguration, RunProblem, RunRecord, RunSpec, SweepTrial, WorkspaceInfo, WorkspaceItem } from "./protocol";
import type { Recording } from "./recording";
import { COMPARE_DASHES, forgetTelemetry, MAX_COMPARED, openLog, openRun, openWorstCase, renamed, shortName } from "./recording";
import type { RunForm } from "./runform";
import { emptyForm, formToSpec, loadForm, reconcile, saveForm, sameRun, specToForm } from "./runform";
import { isLive, SessionStore } from "./session";
import type { Pose } from "./startpose";
import { formatStart } from "./startpose";
import type { Theme } from "./theme";
import { applyTheme, loadTheme, nextTheme } from "./theme";
import { useController } from "./useController";
import { useStore } from "./useStore";
import { canRecordVideo, VideoExport } from "./video";

// The editors (and CodeMirror) load when a config is first opened, the pages when first shown
const ConfigEditor = lazy(() => import("./components/ConfigEditor").then((m) => ({ default: m.ConfigEditor })));
const RouteEditor = lazy(() => import("./components/RouteEditor").then((m) => ({ default: m.RouteEditor })));
const SweepsPage = lazy(() => import("./pages/SweepsPage").then((m) => ({ default: m.SweepsPage })));
const BenchPage = lazy(() => import("./pages/BenchPage").then((m) => ({ default: m.BenchPage })));
const CalibratePage = lazy(() => import("./pages/CalibratePage").then((m) => ({ default: m.CalibratePage })));
const AnalyzePage = lazy(() => import("./pages/AnalyzePage").then((m) => ({ default: m.AnalyzePage })));
const BuildPage = lazy(() => import("./pages/BuildPage").then((m) => ({ default: m.BuildPage })));
const GuidePage = lazy(() => import("./pages/GuidePage").then((m) => ({ default: m.GuidePage })));

type PageId = "simulate" | "sweeps" | "bench" | "calibrate" | "analyze" | "build" | "guide";
const PAGES: [PageId, string, string][] = [
  ["simulate", "Simulate", "Run a robot on the field"],
  ["sweeps", "Sweeps", "Run saved runs many times over, and measure them"],
  ["bench", "Bench", "Benchmark scenarios: localizers and controllers over many seeds"],
  ["calibrate", "Calibrate", "Fit the simulator to a real robot's log"],
  ["analyze", "Analyze", "Motor curves, drift and odometry"],
  ["build", "Build", "Build PROS projects; check the compiler"],
  ["guide", "Guide", "vexsim's guides: using it, calibrating to your robot step by step, programming"],
];
const PAGE_IDS: readonly string[] = PAGES.map(([id]) => id);

const THEME_LABEL: Record<Theme, string> = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" };
const EDITOR_KEY = "vexsim.editor";
const ON_SAVE_KEY = "vexsim.runOnSave";
const FIRST_RUN_KEY = "vexsim.firstRun:"; // and the folder: its "Start here" was put away
const STARTABLE: readonly string[] = ["running", "paused", "finished", "error", "stopped"]; // Restart can start it again
const EDITED: readonly string[] = ["robot", "field", "invalid"]; // what opens in the config editor
const BUSY: readonly string[] = ["building", "starting", "running", "paused"]; // the run is on the field
const SEEK_S = 0.5; // the arrow keys move a recorded run this far (Shift: ten times)

function loadEditor(): Editor {
  try {
    const saved = localStorage.getItem(EDITOR_KEY);
    if (saved && saved in EDITORS) return saved as Editor;
  } catch {
    // storage off: the default
  }
  return "vscode";
}

function loadRunOnSave(): boolean {
  try {
    return localStorage.getItem(ON_SAVE_KEY) === "on";
  } catch {
    return false; // storage off: not remembered
  }
}

/** The form's start pose, when it's three numbers. */
function startOf(form: RunForm): Pose | null {
  const pose = [form.x, form.y, form.heading].map((text) => (text.trim() === "" ? NaN : Number(text)));
  return pose.every(Number.isFinite) ? (pose as Pose) : null;
}

export function App() {
  // where the address says to be (address.ts): the page and Calibrate's tab at once, the
  // editor and the run once the folder is listed
  const [arrival] = useState<Place>(() => parsePlace(location.hash) ?? HOME);
  const [arrived, setArrived] = useState(false); // it's been gone to: the address follows the app from here
  const [restoring, setRestoring] = useState(false); // the run the address names is being fetched
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceInfo | null>(null);
  const [scanning, setScanning] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<RunForm>(emptyForm);
  const [store, setStore] = useState<SessionStore | null>(null);
  const [problem, setProblem] = useState<RunProblem | null>(null);
  const [starting, setStarting] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [layers, setLayers] = useState<Layers>({ trails: true, estimate: true, beams: true, forces: true, drawings: true });
  const [hiddenDrawings, setHiddenDrawings] = useState<string[]>([]); // layers of the robot code's drawings
  const [realLog, setRealLog] = useState<LogPlayback | null>(null); // a real robot's log (MCL or vexsim's), beside the simulator
  const [logShift, setLogShift] = useState(0); // s: the log nudged later against the run beside it
  const [replayWith, setReplayWith] = useState<string | null>(null); // the saved run to replay it with ("": the form)
  const [theme, setTheme] = useState<Theme>(() => hostTheme() ?? loadTheme());
  const [preview, setPreview] = useState<Preview | null>(null);
  const [routines, setRoutines] = useState<ProjectRoutines | null>(null); // the PROS project's
  const [rescans, setRescans] = useState(0);
  const [configurations, setConfigurations] = useState<RunConfiguration[]>([]);
  const [configFile, setConfigFile] = useState(".vexsim/launch.yaml");
  const [configError, setConfigError] = useState<string | null>(null);
  const [follow, setFollow] = useState(false);
  const [onScreen, setOnScreen] = useState<ControllerInput>(NEUTRAL);
  const [editor, setEditor] = useState<Editor>(loadEditor);
  const [help, setHelp] = useState(false);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [shown, setShown] = useState<Recording | null>(null); // the recorded run on the field
  const [compared, setCompared] = useState<Recording[]>([]); // drawn over it
  const [opening, setOpening] = useState<string | null>(null); // the run (or log) being fetched
  const [closedRun, setClosedRun] = useState(false); // the ended live run was put away
  const [video, setVideo] = useState<VideoExport | null>(null);
  const [openConfigs, setOpenConfigs] = useState<string[]>([]); // configs (and routes) open in editors
  const [openRoutes, setOpenRoutes] = useState<string[]>([]); // those that are routes, in the autonomous maker
  const [designing, setDesigning] = useState<string[]>([]); // opened in their Design view
  const [newRobot, setNewRobot] = useState(false); // the "New robot…" dialog is open
  const [newRoute, setNewRoute] = useState(false); // the "New route…" dialog is open
  const [page, setPage] = useState<string>(arrival.page === "edit" ? "simulate" : arrival.page); // a PageId, or an open config's path
  const [visited, setVisited] = useState<string[]>(["simulate"]); // pages made so far (they stay)
  const [analyzeRobot, setAnalyzeRobot] = useState("");
  const [benchScenario, setBenchScenario] = useState("");
  const [calibration, setCalibration] = useState<{ robot: string; log: string; project: string; session: string; tab: CalibrateTab }>({
    robot: "",
    log: "",
    project: "",
    session: arrival.session ?? "",
    tab: arrival.tab ?? "session",
  });
  const [buildProject, setBuildProject] = useState<string | null>(null);
  const [guide, setGuide] = useState<{ doc: string; at: string | null }>({ doc: arrival.doc ?? "", at: arrival.at ?? null }); // the Guide page's document and heading
  const [runsLoaded, setRunsLoaded] = useState(false); // the run history has been read once
  const [startHidden, setStartHidden] = useState(false); // "Start here" was put away, for this folder
  const [writingStarter, setWritingStarter] = useState(false);
  const [overrideRequests, setOverrideRequests] = useState<Record<string, ConfigRequest>>({});
  const [unsaved, setUnsaved] = useState<Record<string, boolean>>({});
  const [closing, setClosing] = useState<string | null>(null); // asking before closing it
  // the shell fits its window (layout.ts): what's folded away in a short or a narrow one
  const short = useMedia(SHORT);
  const narrow = useMedia(NARROW);
  const [sidebarOpen, setSidebarOpen] = usePanel("sidebar", narrow);
  const [readoutOpen, setReadoutOpen] = usePanel("readout", narrow);
  const [bottomOpen, setBottomOpen] = usePanel("bottom", short);
  const [runbarOpen, setRunbarOpen] = useState<boolean | null>(null); // by hand; null: as the window asks
  const [runOnSave, setRunOnSave] = useState(loadRunOnSave); // a save of the run's code runs it again
  const playhead = useMemo(() => new Playhead(), []);
  usePlayheadClock(playhead);
  useStore(store);
  useEffect(() => {
    if (PAGE_IDS.includes(page)) setVisited((pages) => (pages.includes(page) ? pages : [...pages, page]));
  }, [page]);

  const root = info?.workspace ?? "";
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

  const loadConfigurations = useCallback(async () => {
    try {
      const found = await api.configurations();
      setConfigurations(found.configurations);
      setConfigFile(found.file);
      setConfigError(found.error ?? null);
    } catch (error) {
      setConfigError((error as Error).message);
    }
  }, []);

  /** List the workspace again. "changed": only if the folder isn't as it was at the last
   * listing (the server tells by its stamp, reading nothing); "fresh": read every file whatever
   * the stamps say (Refresh). The list, or null if it's as it was. */
  const stamp = useRef(""); // the folder's mark at the last listing
  const scan = useCallback(
    async (infoNow: AppInfo, restore: boolean, how: "list" | "changed" | "fresh" = "list"): Promise<WorkspaceInfo | null> => {
      if (how !== "changed") setScanning(true);
      try {
        const found = await api.workspace(how === "changed" ? stamp.current : null, how === "fresh");
        if (!found) return null;
        stamp.current = found.stamp ?? "";
        setWorkspace(found);
        setForm((current) => reconcile(restore ? (loadForm(infoNow.workspace) ?? current) : current, found.items));
        setRescans((n) => n + 1);
        await loadConfigurations();
        return found;
      } finally {
        if (how !== "changed") setScanning(false);
      }
    },
    [loadConfigurations],
  );
  // The list follows the disk: looked at again whenever the window gets the focus back (a file
  // made in your editor is there when you come back to pick it).
  useEffect(() => {
    if (!info) return;
    let last = -Infinity;
    const look = () => {
      if (document.visibilityState !== "visible" || performance.now() - last < 1000) return;
      last = performance.now();
      scan(info, false, "changed").catch(() => {}); // the list stays as it was
    };
    window.addEventListener("focus", look);
    document.addEventListener("visibilitychange", look);
    return () => {
      window.removeEventListener("focus", look);
      document.removeEventListener("visibilitychange", look);
    };
  }, [info, scan]);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);
  useEffect(() => onHostTheme(setTheme), []); // inside VS Code, its theme's colors

  useEffect(() => {
    try {
      localStorage.setItem(EDITOR_KEY, editor);
    } catch {
      // storage off: not remembered
    }
  }, [editor]);
  useEffect(() => {
    try {
      localStorage.setItem(ON_SAVE_KEY, runOnSave ? "on" : "off");
    } catch {
      // storage off: not remembered
    }
  }, [runOnSave]);

  useEffect(() => {
    (async () => {
      try {
        const about = await api.info();
        setInfo(about);
        document.title = `vexsim · ${about.workspace_name}`;
        try {
          setStartHidden(localStorage.getItem(FIRST_RUN_KEY + about.workspace) === "hidden");
        } catch {
          // storage off: it shows until its steps are done
        }
        const found = await scan(about, true);
        loadRuns();
        const running = (await api.sessions())
          .filter((s) => s.state !== "stopped")
          .sort((a, b) => b.created - a.created)[0];
        if (running) attach(running.id, 1);
        // where the address says: its editor, or its run unless one is going (the field is its).
        // Unless it has moved on meanwhile (Back, pressed before the folder was listed).
        const going = !!running && BUSY.includes(running.state);
        if (formatPlace(parsePlace(location.hash) ?? HOME) === formatPlace(arrival)) {
          if (arrival.page === "edit") goRef.current(arrival, found?.items ?? []);
          else if (arrival.run && !going) await restoreRef.current(arrival.run, running?.run_id === arrival.run, false);
        }
      } catch (error) {
        setLoadError((error as Error).message);
      } finally {
        setArrived(true);
      }
    })();
  }, [arrival, attach, scan, loadRuns]);

  // The run form is kept for the next visit, once it's been brought back from the last one (the
  // list arrives with it): saved any sooner, the empty form it starts as would replace what was kept.
  useEffect(() => {
    if (info && workspace) saveForm(info.workspace, form);
  }, [form, info, workspace]);

  // A PROS project's routines (include/custom/auton.hpp), to pick one in the run bar.
  const isProject = !!workspace?.items.some((item) => item.kind === "project" && item.path === form.program);
  useEffect(() => {
    if (!info || !isProject) {
      setRoutines(null);
      return;
    }
    let current = true;
    api
      .routines(form.program)
      .then((result) => current && setRoutines("ok" in result ? result.ok : null))
      .catch(() => current && setRoutines(null));
    return () => {
      current = false;
    };
  }, [info, isProject, form.program, rescans]);

  // The robot and field as configured, to show before a run and drag the robot's start.
  useEffect(() => {
    if (!info || !form.robot) {
      setPreview(null);
      return;
    }
    let current = true;
    api
      .preview(form.robot, form.field || null)
      .then((result) => current && setPreview("preview" in result ? result.preview : null))
      .catch(() => current && setPreview(null));
    return () => {
      current = false;
    };
  }, [info, form.robot, form.field, rescans]);

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
  // in a short window the run bar is one line once a run is on show (Edit unfolds it)
  const onShow = source.kind !== "preview" || realLog !== null;
  const runbarFolded = !(runbarOpen ?? !(short && onShow));
  const recordedLayers = useMemo(() => recording?.playback.drawnLayers() ?? [], [recording]);
  const runLayers = source.kind === "live" ? Object.keys(source.store.drawings) : recordedLayers;
  const drawnLayers = realLog ? [...new Set([...realLog.layers(), ...runLayers])] : runLayers;
  const recordingPhases = useMemo(() => recording?.playback.phases() ?? [], [recording]);

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
  const onField: Compared[] = compared.map((r, i) => ({ playback: r.playback, label: shortName(r.label), dash: COMPARE_DASHES[i] }));
  const startPose = useMemo(() => startOf(form), [form]);
  const start = startPose ? { pose: startPose, editable: !busy } : null;

  const show = useCallback(
    (next: Recording) => {
      setShown(next);
      setCompared((list) => list.filter((r) => r.key !== next.key));
      playhead.load(next.playback.start, next.playback.end);
      setProblem(null);
    },
    [playhead],
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
    [attach, speed, video],
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
  }, [attach, speed, video]);
  // Run on save: the run's files changed (its session says so, each time they do) and the
  // switch is on, so it runs again; with the switch off, the field says "Code changed".
  const changes = store?.changes ?? 0;
  useEffect(() => {
    if (runOnSave && changes > 0) void restart();
  }, [runOnSave, changes]); // eslint-disable-line react-hooks/exhaustive-deps -- only when a save lands, or the switch goes on

  const run = useCallback(async () => {
    const result = formToSpec(form);
    if ("error" in result) {
      setRunbarOpen(true); // what's wrong is in the bar
      setProblem({ error: result.error, issues: [] });
      return;
    }
    setRunbarOpen(null); // set up and run: the bar folds again where there's little room
    const chosen = configurations.find((c) => c.name === form.config);
    const name = chosen && sameRun(form, chosen) ? chosen.name : null; // as saved: its name
    await startRun(result.spec, name);
  }, [configurations, form, startRun]);

  /** A sweep's trial, run again on the field (it's deterministic: the same run). */
  const watchTrial = useCallback(
    async (trial: SweepTrial, name: string) => {
      setShown(null);
      setForm(specToForm(trial.spec));
      setPage("simulate");
      await startRun(trial.spec, name);
    },
    [startRun],
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

  const pickCalibrationRobot = useCallback((robot: string) => setCalibration((c) => ({ ...c, robot })), []);
  const pickCalibrationLog = useCallback((log: string) => setCalibration((c) => ({ ...c, log })), []);
  const pickCalibrationProject = useCallback((project: string) => setCalibration((c) => ({ ...c, project })), []);
  const pickCalibrationSession = useCallback((session: string) => setCalibration((c) => ({ ...c, session })), []);
  const pickCalibrationTab = useCallback((tab: CalibrateTab) => setCalibration((c) => ({ ...c, tab })), []);

  /** A calibration's fitted values, added to a robot config in its editor (to save there). */
  const applyOverrides = async (robot: string, overrides: Record<string, number>) => {
    openConfig(robot);
    setOverrideRequests((all) => ({ ...all, [robot]: { id: (all[robot]?.id ?? 0) + 1, overrides } }));
  };

  /** What a calibration session's fit found, written into its robot's config in its editor (to save there). */
  const applySession = async (robot: string, session: string) => {
    openConfig(robot);
    setOverrideRequests((all) => ({ ...all, [robot]: { id: (all[robot]?.id ?? 0) + 1, session } }));
  };

  /** A robot log on the field, beside the simulator (from the Calibrate page). */
  const playLog = (path: string) => {
    setPage("simulate");
    void openRealLog("robotlog", path);
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

  // --- config editors, in tabs beside Simulate ----------------------------------------------

  const openConfig = (path: string, design = false) => {
    if (design) setDesigning((list) => (list.includes(path) ? list : [...list, path]));
    setOpenConfigs((open) => (open.includes(path) ? open : [...open, path]));
    setPage(path);
  };
  /** A route, open in the autonomous maker (in a tab, as a config is). */
  const openRoute = (path: string) => {
    setOpenRoutes((open) => (open.includes(path) ? open : [...open, path]));
    setOpenConfigs((open) => (open.includes(path) ? open : [...open, path]));
    setPage(path);
  };
  /** A route "New route…" made (or a mirrored copy): listed, and open in the maker. */
  const routeCreated = async (path: string) => {
    setNewRoute(false);
    if (info) await scan(info, false);
    openRoute(path);
  };
  /** A robot "New robot…" made: picked for the next run, and open in its Design view. */
  const robotCreated = async (path: string) => {
    setNewRobot(false);
    if (info) await scan(info, false);
    setForm((current) => ({ ...current, config: "", robot: path }));
    openConfig(path, true);
  };
  /** A workspace file copied beside itself (the list shows it): the copy's path. */
  const duplicateItem = async (item: WorkspaceItem): Promise<string> => {
    const made = await api.duplicateFile(item.path);
    if (info) await scan(info, false);
    return made.path;
  };
  /** A workspace file deleted: its editor closes, if it's open, and the run bar lets it go. */
  const deleteItem = async (item: WorkspaceItem) => {
    await api.deleteFile(item.path);
    if (openConfigs.includes(item.path)) closeConfig(item.path);
    if (info) await scan(info, false);
  };
  const closeConfig = (path: string) => {
    setOpenConfigs((open) => open.filter((p) => p !== path));
    setOpenRoutes((open) => open.filter((p) => p !== path));
    setUnsaved(({ [path]: _, ...rest }) => rest);
    setClosing(null);
    setPage((current) => (current === path ? "simulate" : current));
  };
  const askToClose = (path: string) => {
    if (unsaved[path]) {
      setPage(path);
      setClosing(path);
    } else closeConfig(path);
  };
  const markUnsaved = useCallback((path: string, dirty: boolean) => {
    setUnsaved((all) => (!!all[path] === dirty ? all : { ...all, [path]: dirty }));
  }, []);
  const anyUnsaved = Object.values(unsaved).some(Boolean);
  useEffect(() => {
    if (!anyUnsaved) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault(); // the browser asks first
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [anyUnsaved]);

  /** The run form set up to run a route: its project's, with its robot, field and start (as
   * its setPose has it). */
  const routeForm = async (path: string): Promise<(current: RunForm) => RunForm> => {
    const project = path.split("/").slice(0, -2).join("/") || ".";
    const listed = await api.routines(project).catch(() => null);
    const route = listed && "ok" in listed ? listed.ok.routes?.find((r) => r.path === path) : undefined;
    const start = route?.start;
    return (current) => ({
      ...current,
      program: project,
      routine: "",
      route: path,
      mode: current.mode === "driver" ? "" : current.mode,
      ...(start ? { x: formatStart(start[0]), y: formatStart(start[1]), heading: formatStart(start[2]) } : {}),
      ...(route?.robot ? { robot: route.robot } : {}),
      ...(route ? { field: route.field ?? "" } : {}),
    });
  };
  /** A route to run: picked in the run bar. */
  const pickRoute = async (path: string) => setForm(await routeForm(path));
  /** A route (just saved in the maker) run on the Simulate page, with its timeline and plots. */
  const watchRoute = async (path: string) => {
    const next = (await routeForm(path))(form);
    setForm(next);
    setShown(null);
    setPage("simulate");
    const result = formToSpec(next);
    if ("error" in result) setProblem({ error: result.error, issues: [] });
    else await startRun(result.spec, null);
  };

  /** A workspace item clicked in the sidebar: for the page on show where it's of use there,
   * else for a run on the Simulate page. */
  const pick = (item: WorkspaceItem) => {
    if (narrow) setSidebarOpen(false); // the list was over the page: show what was picked
    if (item.kind === "invalid") {
      openConfig(item.path); // to fix it
      return;
    }
    if (item.kind === "scenario") {
      setBenchScenario(item.path);
      setPage("bench");
      return;
    }
    if (item.kind === "calsession") {
      setCalibration((c) => ({ ...c, session: item.path, tab: "session" }));
      setPage("calibrate");
      return;
    }
    if (item.kind === "mcllog") {
      setPage("simulate");
      void openRealLog("mcllog", item.path);
      return;
    }
    if (item.kind === "robotlog") {
      // a calibration test's log is a session's; any other with nothing to play is for the quick fit
      void openRealLog("robotlog", item.path, !item.detail.startsWith("calibration log"));
      return;
    }
    if (item.kind === "route") {
      setPage("simulate");
      void pickRoute(item.path);
      return;
    }
    if (page === "analyze" && item.kind === "robot") return setAnalyzeRobot(item.path);
    if (page === "calibrate" && item.kind === "robot") return setCalibration((c) => ({ ...c, robot: item.path }));
    if (page === "calibrate" && item.kind === "project") return setCalibration((c) => ({ ...c, project: item.path }));
    if (page === "build" && item.kind === "project") return setBuildProject(item.path);
    setPage("simulate");
    if (item.kind === "log") {
      openTelemetryLog(item.path);
      return;
    }
    const key = item.kind === "project" ? "program" : (item.kind as keyof RunForm);
    if (key in form && key !== "config") setForm({ ...form, [key]: item.path });
  };
  // what the page on show has picked from the sidebar, to mark there
  const picked: string[] | null =
    page === "analyze"
      ? [analyzeRobot]
      : page === "bench"
        ? [benchScenario]
        : page === "calibrate"
          ? [calibration.robot, calibration.log, calibration.project, calibration.session]
          : page === "build"
            ? [buildProject ?? ""]
            : null;

  const moveStart = useCallback((pose: Pose) => {
    setForm((current) => ({ ...current, x: formatStart(pose[0]), y: formatStart(pose[1]), heading: formatStart(pose[2]) }));
  }, []);

  const pickConfiguration = (name: string) => {
    const chosen = configurations.find((c) => c.name === name);
    setForm(chosen ? specToForm(chosen, chosen.name) : { ...form, config: "" });
    setProblem(null);
  };
  const saveConfigurations = async (next: RunConfiguration[]): Promise<string | null> => {
    try {
      const saved = await api.saveConfigurations(next);
      setConfigurations(saved.configurations);
      setConfigError(saved.error ?? null);
      return null;
    } catch (error) {
      return (error as Error).message;
    }
  };
  const saveConfiguration = async (name: string): Promise<string | null> => {
    const result = formToSpec(form);
    if ("error" in result) return result.error;
    const entry: RunConfiguration = { ...result.spec, name };
    const at = configurations.findIndex((c) => c.name === name);
    const next = at < 0 ? [...configurations, entry] : configurations.map((c, i) => (i === at ? entry : c));
    const error = await saveConfigurations(next);
    if (!error) setForm((current) => ({ ...current, config: name }));
    return error;
  };
  const deleteConfiguration = async (name: string): Promise<string | null> => {
    const error = await saveConfigurations(configurations.filter((c) => c.name !== name));
    if (!error) setForm((current) => (current.config === name ? { ...current, config: "" } : current));
    return error;
  };

  // --- a way in (phase 15.4): the guide, and a first run's steps ------------------------------

  /** A document of the guide (and a heading of it), on the Guide page. */
  const openGuide = useCallback((doc: string, at: string | null = null) => {
    setGuide({ doc, at });
    setPage("guide");
  }, []);
  /** A link to a place in the guide: its address (to open in another tab), and going there. */
  const guideLink = useCallback(
    (doc: string, at: string | null = null) => ({ href: formatPlace({ page: "guide", doc, ...(at ? { at } : {}) }), go: () => openGuide(doc, at) }),
    [openGuide],
  );
  const hideStart = () => {
    setStartHidden(true);
    try {
      if (info) localStorage.setItem(FIRST_RUN_KEY + info.workspace, "hidden");
    } catch {
      // storage off: put away until the page is opened again
    }
  };
  /** Run what the form names, but for `change`: the first run's steps. */
  const runWith = async (change: Partial<RunForm>) => {
    const next: RunForm = { ...form, config: "", routine: "", route: "", input: "", follow: "", following: false, ...change };
    setForm(next);
    const result = formToSpec(next);
    if ("error" in result) setProblem({ error: result.error, issues: [] });
    else await startRun(result.spec, null);
  };
  /** The starter program, written into the folder and picked. */
  const addStarter = async () => {
    setWritingStarter(true);
    try {
      const made = await api.starterProgram();
      if (info) await scan(info, false);
      setForm((current) => ({ ...current, config: "", program: made.path, routine: "", route: "", mode: "" }));
      setProblem(null);
    } catch (error) {
      setProblem({ error: `Couldn't add a starter program: ${(error as Error).message}`, issues: [] });
    } finally {
      setWritingStarter(false);
    }
  };
  const items = workspace?.items ?? [];
  const first = firstSteps(items, runs, store ? (spec ?? {}) : null);
  // "Start here" shows in a folder that's new to vexsim, while no run is going, until it's put away
  const startShown = !!workspace && runsLoaded && !startHidden && !busy && !realLog && !(first.robot && first.driven && first.program && first.ran);

  // --- the address keeps your place (address.ts) -------------------------------------------

  /** The address named what isn't there (a file since deleted, a run since pruned, a typo): put
   * where the app is in its place, without a step for Back to return to. */
  const correctAddress = () => {
    try {
      history.replaceState(history.state, "", location.pathname + location.search + formatPlace(placeRef.current));
    } catch {
      // an address that can't be written (a page inside another app's frame): it stays
    }
  };
  /** The recorded run the address names, on the field again: beside the session that made it,
   * if that's still there (`own`: its console is on screen already), else as it opens from the
   * run history, its setup in the form. Not while a run is `going`: the field is its. Whether
   * it's there to show. */
  const restoreRun = async (id: string, own: boolean, going: boolean): Promise<boolean> => {
    if (going) return true;
    setRestoring(true);
    try {
      const next = await openRun(id, own);
      const record = next.run;
      if (!own && record) {
        if (await leaveSession()) loadRuns();
        const saved = configurations.find((c) => c.name === record.name && sameRun(specToForm(record.spec), c));
        setForm(specToForm(record.spec, saved?.name ?? ""));
      }
      show(next);
      return true;
    } catch {
      correctAddress(); // gone from the history: the address says what's on show instead
      return false;
    } finally {
      setRestoring(false);
    }
  };
  /** Go where an address says (on arrival, and on Back and Forward); false if it names a file
   * that isn't there. `items`: the workspace's, if they were only just listed. */
  const go = (next: Place, items: WorkspaceItem[] | null): boolean => {
    if (next.page === "edit") {
      const item = (items ?? workspace?.items ?? []).find((i) => i.path === next.file);
      if (item?.kind === "route") openRoute(item.path);
      else if (item && EDITED.includes(item.kind)) openConfig(item.path);
      else {
        correctAddress(); // not there any more: the address says where the app is instead
        return false;
      }
      return true;
    }
    setPage(next.page);
    if (next.page === "calibrate") setCalibration((c) => ({ ...c, tab: next.tab ?? c.tab, session: next.session ?? c.session }));
    if (next.page === "guide") setGuide({ doc: next.doc ?? "", at: next.at ?? null });
    if (next.page === "simulate" && next.run && next.run !== recording?.run?.id) void restoreRun(next.run, false, busy);
    return true;
  };
  const goRef = useRef(go);
  goRef.current = go;
  const restoreRef = useRef(restoreRun);
  restoreRef.current = restoreRun;

  const shownRun = recording?.run?.id ?? null;
  const place: Place = useMemo(() => {
    if (!PAGE_IDS.includes(page)) return { page: "edit", file: page };
    if (page === "calibrate") return calibration.session ? { page, tab: calibration.tab, session: calibration.session } : { page, tab: calibration.tab };
    if (page === "simulate" && shownRun) return { page, run: shownRun };
    if (page === "guide") return { page, ...(guide.doc ? { doc: guide.doc } : {}), ...(guide.at ? { at: guide.at } : {}) };
    return { page: page as PageId };
  }, [page, calibration.tab, calibration.session, shownRun, guide]);
  const placeRef = useRef(place);
  placeRef.current = place;
  // The app moved: the address follows. From where the address is now, a new page, editor or
  // Calibrate tab is a step Back undoes; a run or a session on the same page just changes the
  // address where it is. Nothing is written when the address is there already: it moved first
  // (Back, Forward), and the app followed. (Written as the page is, not a moment after: by then
  // Back may have moved the address, and writing where the app was would undo it.)
  useLayoutEffect(() => {
    if (!arrived || restoring) return;
    const hash = formatPlace(place);
    if (hash === location.hash) return;
    const step = isStep(parsePlace(location.hash) ?? HOME, place);
    try {
      history[step ? "pushState" : "replaceState"](history.state, "", location.pathname + location.search + hash);
    } catch {
      // an address that can't be written (a page inside another app's frame): it stays
    }
  }, [arrived, restoring, place]);
  // The address moved (Back, Forward, or typed): the app follows.
  useEffect(() => {
    let last: string | null = null;
    let at = 0;
    const follow = (event: Event) => {
      // where this move went: a hashchange says so itself (the address may have moved on since)
      const hash = "newURL" in event ? new URL((event as HashChangeEvent).newURL).hash : location.hash;
      const now = performance.now();
      if (hash === last && now - at < 500) return; // popstate and hashchange, for one move
      last = hash;
      at = now;
      const next = parsePlace(hash) ?? HOME;
      if (formatPlace(next) !== formatPlace(placeRef.current)) goRef.current(next, null);
      else if (formatPlace(next) !== location.hash) correctAddress(); // it named nothing, or the same place another way
    };
    window.addEventListener("popstate", follow);
    window.addEventListener("hashchange", follow);
    return () => {
      window.removeEventListener("popstate", follow);
      window.removeEventListener("hashchange", follow);
    };
  }, []);

  // Keys, as in the pygame viewer: Space pause, . step, R restart, +/- speed; 1-5 what the
  // field shows; ? the list of keys. Driving keys are useController's. A recorded run: Space
  // play, arrows (Shift: farther), Home/End and , . move through it.
  const scrubbing = recording !== null || logAlone;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName ?? "";
      const typing = target?.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(tag);
      const pressingButton = tag === "BUTTON" && (event.key === " " || event.key === "Enter");
      if (event.key === "Escape" && help) setHelp(false);
      else if (event.key === "Escape" && narrow && sidebarOpen) setSidebarOpen(false); // the list, over the page
      if (event.ctrlKey || event.metaKey || event.altKey || typing || pressingButton) return;
      if (page !== "simulate" && event.key !== "?") return; // an editor's diagram has its own keys
      const index = SPEEDS.indexOf(speed);
      const toggle = (key: keyof Layers) => setLayers((l) => ({ ...l, [key]: !l[key] }));
      const seekBy = (seconds: number) => {
        event.preventDefault();
        playhead.seek(playhead.t + seconds);
      };
      switch (event.key) {
        case " ":
          if (store && state && isLive(state)) {
            event.preventDefault();
            store.send({ cmd: state === "paused" ? "resume" : "pause" });
          } else if (scrubbing) {
            event.preventDefault();
            playhead.toggle();
          }
          break;
        case ".":
          if (state === "paused") store?.send({ cmd: "step", ms: 10 });
          else if (scrubbing) seekBy(0.05);
          break;
        case ",":
          if (scrubbing) seekBy(-0.05);
          break;
        case "ArrowLeft":
        case "ArrowRight":
          if (scrubbing && !driving) seekBy((event.key === "ArrowLeft" ? -1 : 1) * SEEK_S * (event.shiftKey ? 10 : 1));
          break;
        case "Home":
          if (scrubbing) seekBy(-Infinity);
          break;
        case "End":
          if (scrubbing) seekBy(Infinity);
          break;
        case "r":
        case "R":
          void restart();
          break;
        case "+":
        case "=":
          if (index >= 0 && index < SPEEDS.length - 1) changeSpeed(SPEEDS[index + 1]);
          break;
        case "-":
        case "_":
          if (index > 0) changeSpeed(SPEEDS[index - 1]);
          break;
        case "1":
          toggle("trails");
          break;
        case "2":
          toggle("estimate");
          break;
        case "3":
          toggle("beams");
          break;
        case "4":
          toggle("forces");
          break;
        case "5":
          toggle("drawings");
          break;
        case "?":
          setHelp((open) => !open);
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [changeSpeed, driving, help, narrow, page, playhead, restart, scrubbing, setSidebarOpen, sidebarOpen, speed, state, store]);

  return (
    <div className="app">
      <header className="topbar">
        <button
          type="button"
          className={`ghost small sidebar-toggle${sidebarOpen ? " on" : ""}`}
          aria-expanded={sidebarOpen}
          aria-controls="sidebar"
          onClick={() => setSidebarOpen(!sidebarOpen)}
          title={sidebarOpen ? "Fold the workspace list away" : "The workspace list: robots, fields, programs, logs, and the runs"}
          aria-label="Workspace list"
          data-testid="sidebar-toggle"
        >
          <span aria-hidden="true">☰</span>
        </button>
        <span className="wordmark">vexsim</span>
        {info && (
          <span className="where" title={info.workspace}>
            {info.workspace_name}
          </span>
        )}
        <div className="pagetabs" role="tablist" aria-label="Pages">
          {PAGES.map(([id, label, hint]) => (
            <button key={id} role="tab" aria-selected={page === id} className={`pagetab${page === id ? " on" : ""}`} onClick={() => setPage(id)} title={hint} data-testid={`page-${id}`}>
              {label}
            </button>
          ))}
          {openConfigs.length > 0 && <span className="pagetabs-gap" aria-hidden="true" />}
          {openConfigs.map((path) => (
            <span key={path} className={`pagetab config${page === path ? " on" : ""}`}>
              <button role="tab" aria-selected={page === path} onClick={() => setPage(path)} title={path} data-testid={`page-${path}`}>
                {fileName(path)}
                {unsaved[path] && (
                  <span className="unsaved" title="Unsaved changes" aria-label="unsaved changes">
                    {" "}
                    ●
                  </span>
                )}
              </button>
              <button type="button" className="close" onClick={() => askToClose(path)} aria-label={`Close ${path}`} title="Close">
                ×
              </button>
            </span>
          ))}
        </div>
        {info && <span className="muted small version">v{info.version}</span>}
        <button className="ghost small" onClick={() => setHelp(true)} title="Every key, for running and driving (?)" data-testid="keys">
          Keys
        </button>
        <button className="ghost small" onClick={() => setTheme(nextTheme(theme))} title="Light, dark, or as your system is set">
          {THEME_LABEL[theme]}
        </button>
      </header>
      {loadError && (
        <div className="banner" role="alert">
          <span aria-hidden="true">⚠</span> Can't reach vexsim: {loadError}. Is <code>vexsim ui</code> still running? Open the link it printed.
        </div>
      )}
      <div className={`workarea${sidebarOpen ? "" : " no-sidebar"}`}>
        {sidebarOpen && narrow && <div className="scrim" onClick={() => setSidebarOpen(false)} aria-hidden="true" />}
        <Sidebar
          hidden={!sidebarOpen}
          workspace={workspace}
          form={form}
          page={page}
          picked={picked}
          onPick={pick}
          onEdit={(item) => (item.kind === "route" ? openRoute(item.path) : openConfig(item.path))}
          onDuplicate={duplicateItem}
          onDelete={deleteItem}
          unsaved={unsaved}
          editor={editor}
          onNewRobot={() => setNewRobot(true)}
          onNewRoute={() => setNewRoute(true)}
          loading={scanning}
          onRefresh={() => info && scan(info, false, "fresh")}
          shownLog={recording?.key.startsWith("log:") ? recording.key.slice(4) : null}
          realLog={realLog?.tape.path ?? null}
          runCount={runs.length}
          onRunsTab={loadRuns}
          runs={
            <RunsList
              runs={runs}
              shown={recording?.run?.id ?? null}
              compared={compared.map((r) => r.key)}
              opening={opening}
              canCompare={source.kind !== "preview"}
              onOpen={openRecorded}
              onCompare={toggleCompare}
              onKeep={(record, kept) => changeRun(record, { kept })}
              onRename={(record, name) => changeRun(record, { name })}
              onDelete={deleteRun}
            />
          }
        />
        <main className="main">
          <div className="simulate" hidden={page !== "simulate"}>
            <RunBar
              workspace={workspace}
              form={form}
              routines={routines}
              onChange={setForm}
              onRun={run}
              starting={starting}
              configurations={configurations}
              configFile={configFile}
              configError={configError}
              onPick={pickConfiguration}
              onSave={saveConfiguration}
              onDelete={deleteConfiguration}
              onNewRobot={() => setNewRobot(true)}
              folded={runbarFolded}
              onFold={short && onShow ? (folded) => setRunbarOpen(!folded) : undefined}
              runOnSave={runOnSave}
              onRunOnSave={setRunOnSave}
            />
            <Controls
              store={store}
              speed={speed}
              onSpeed={changeSpeed}
              onStop={stop}
              onRestart={restart}
              command={store?.info?.command ?? store?.scene?.command ?? recording?.run?.command ?? null}
            />
            {realLog && (
              <div className="logbar" data-testid="logbar">
                <div className="logrow">
                  <span className="logname" title={realLog.tape.path}>
                    {realLog.name}
                  </span>
                  <span className="muted small">{logSummary(realLog.tape)}</span>
                  <span className="spacer" />
                  <button type="button" className="ghost small" onClick={closeRealLog} title="Put the log away" aria-label={`Close ${realLog.name}`} data-testid="close-log">
                    ×
                  </button>
                </div>
                <div className="logrow">
                  {!logAlone && (
                    <label title="The moment of the run beside it when the log's first update comes: when the run began following it, or else where its program began. Nudge it to line them up.">
                      <span className="small">The log starts at</span>
                      <input
                        type="number"
                        step={0.1}
                        value={logAt === null ? "" : +logAt.toFixed(2)}
                        placeholder="…"
                        disabled={logAt === null}
                        onChange={(event) => logAt !== null && event.target.value !== "" && setLogShift(logShift + Number(event.target.value) - logAt)}
                        aria-label="Moment of the run the log starts at (s)"
                        data-testid="log-start"
                      />
                      <span className="small">s of the run</span>
                    </label>
                  )}
                  <span className="spacer" />
                  {logRoutine && (
                    <button
                      type="button"
                      className="small"
                      onClick={runLogRoutine}
                      disabled={starting}
                      title={`Run ${logRoutine.name}() in the simulator, in autonomous, from where its setPose puts the robot: the routine the log is of, beside it`}
                      data-testid="run-log-routine"
                    >
                      Run {logRoutine.name}
                    </button>
                  )}
                  {followable && (
                  <label title="Replay the log in the simulator: a virtual driver drives the run's robot along the real robot's path, through its program's driver control">
                    <span className="small">Replay it with</span>
                    <select value={replayChoice} onChange={(event) => setReplayWith(event.target.value)} data-testid="replay-with">
                      <option value="">The run set up above</option>
                      {replayRuns.map((c) => (
                        <option key={c.name} value={c.name}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  )}
                  {followable && (
                    <button type="button" className="small" onClick={replayLog} disabled={starting} data-testid="replay-log">
                      Replay
                    </button>
                  )}
                </div>
              </div>
            )}
            {startShown && (
              <FirstRun
                done={first}
                busy={starting || writingStarter}
                onNewRobot={() => setNewRobot(true)}
                onDrive={() => runWith({ program: "", mode: "" })}
                onStarter={addStarter}
                onRunProgram={() => runWith({ program: items.find((i) => i.path === form.program && i.kind !== "robot")?.path ?? items.find((i) => i.kind === "program")?.path ?? "", mode: "" })}
                guide={guideLink("readme")}
                onHide={hideStart}
              />
            )}
            <div className={`stage${realLog ? " paired" : ""}${readoutOpen ? "" : " no-readout"}`}>
              <div className={`fieldcol${realLog ? " paired" : ""}`}>
                <div className={realLog ? "fieldpair" : "fieldsingle"}>
                  {realLog && (
                    <div className="fieldhalf">
                      <div className="fieldlabel">
                        <b>Real robot</b> <span className="muted">its log: what its code thought and saw</span>
                      </div>
                      <FieldView
                        name="log"
                        source={{ kind: "log", log: realLog, clock: logClock, shape: source.kind === "live" ? source.store.scene : recording ? recording.playback.tape.scene : preview }}
                        compared={[]}
                        preview={null}
                        start={null}
                        onStart={moveStart}
                        layers={layers}
                        hiddenDrawings={hiddenDrawings}
                        follow={follow}
                        onFollow={setFollow}
                      />
                    </div>
                  )}
                  <div className="fieldhalf">
                    {realLog && (
                      <div className="fieldlabel">
                        <b>vexsim</b>{" "}
                        <span className="muted">
                          {recording ? recording.name : source.kind === "live" ? "the run" : "the robot as set up above"}
                          {logAt === null && !logAlone && (source.kind === "live" ? " · the log starts when the run follows it" : "")}
                        </span>
                      </div>
                    )}
                    <FieldView
                      source={source}
                      compared={onField}
                      preview={preview}
                      start={start}
                      onStart={moveStart}
                      layers={layers}
                      hiddenDrawings={hiddenDrawings}
                      follow={follow}
                      onFollow={setFollow}
                      stamp={video && recording ? recording.name : null}
                      notice={
                        store && store.changed.length > 0 && source.kind !== "preview" ? (
                          <button
                            type="button"
                            className="changed"
                            onClick={restart}
                            disabled={!STARTABLE.includes(store.state)}
                            title={`${store.changed.join(", ")} changed since this run started: what's on the field is the code as it was. Click (or Restart, R) to run it as it is now.`}
                            data-testid="code-changed"
                          >
                            <b>Code changed</b> since this run started · Restart runs it
                          </button>
                        ) : null
                      }
                      tools={
                        <button
                          type="button"
                          className={`ghost small${readoutOpen ? " on" : ""}`}
                          aria-pressed={readoutOpen}
                          onClick={() => setReadoutOpen(!readoutOpen)}
                          title="The readings beside the field: the poses, the motors, the sensors, the controller"
                          data-testid="readout-toggle"
                        >
                          Readings
                        </button>
                      }
                    />
                  </div>
                </div>
                <FieldKey
                  layers={layers}
                  onLayers={setLayers}
                  drawn={drawnLayers}
                  hidden={hiddenDrawings}
                  onHidden={setHiddenDrawings}
                  compared={compared.map((r, i) => ({ key: r.key, name: r.label, dash: COMPARE_DASHES[i] }))}
                  onUncompare={(key) => setCompared((list) => list.filter((r) => r.key !== key))}
                />
                {recording && (
                  <Timeline
                    phases={recordingPhases}
                    playhead={playhead}
                    name={recording.name}
                    run={recording.run}
                    csv={recording.run ? api.csvUrl(recording.run.id) : null}
                    video={video ? "recording" : canRecordVideo() ? "off" : "unsupported"}
                    onVideo={toggleVideo}
                    onClose={closeRecording}
                  />
                )}
                {realLog && logAlone && (
                  <Timeline
                    phases={[]}
                    playhead={playhead}
                    name={realLog.name}
                    run={null}
                    summary="the real robot's log, played alone: replay it, or open a run, to see it beside one"
                    csv={null}
                    video={null}
                    onVideo={() => {}}
                    onClose={closeRealLog}
                    closeTitle="Put the log away"
                  />
                )}
              </div>
              <div className="readout-slot" hidden={!readoutOpen}>
                <Readout source={source} driving={driving} scripted={scripted} gamepad={gamepad} onScreen={onScreen} onInput={setOnScreen} />
              </div>
            </div>
            <ConsolePanel
              store={store}
              history={recording?.console ?? null}
              plots={recording ? <Plots shown={recording} compared={compared} playhead={playhead} /> : null}
              problem={problem}
              root={root}
              editor={editor}
              onEditor={setEditor}
              open={bottomOpen}
              onOpen={setBottomOpen}
            />
          </div>
          <Suspense fallback={<p className="muted pad">Opening the editor…</p>}>
            {openConfigs.map((path) =>
              openRoutes.includes(path) ? (
                <RouteEditor
                  key={path}
                  path={path}
                  active={page === path}
                  closing={closing === path}
                  workspace={workspace}
                  onClose={() => closeConfig(path)}
                  onKeepOpen={() => setClosing(null)}
                  onDirty={markUnsaved}
                  onSaved={() => info && scan(info, false)}
                  onWatch={watchRoute}
                  onOpen={routeCreated}
                />
              ) : (
                <ConfigEditor
                  key={path}
                  path={path}
                  active={page === path}
                  closing={closing === path}
                  onClose={() => closeConfig(path)}
                  onKeepOpen={() => setClosing(null)}
                  onDirty={markUnsaved}
                  onSaved={() => info && scan(info, false)}
                  request={overrideRequests[path] ?? null}
                  design={designing.includes(path)}
                />
              ),
            )}
          </Suspense>
          <Suspense fallback={<p className="muted pad">Opening the page…</p>}>
            {visited.includes("sweeps") && (
              <div className="pagebox" hidden={page !== "sweeps"}>
                <SweepsPage configurations={configurations} onWatch={watchTrial} />
              </div>
            )}
            {visited.includes("bench") && (
              <div className="pagebox" hidden={page !== "bench"}>
                <BenchPage workspace={workspace} scenario={benchScenario} onScenario={setBenchScenario} onWorstCase={watchWorstCase} />
              </div>
            )}
            {visited.includes("calibrate") && (
              <div className="pagebox" hidden={page !== "calibrate"}>
                <CalibratePage
                  workspace={workspace}
                  robot={calibration.robot}
                  onRobot={pickCalibrationRobot}
                  log={calibration.log}
                  onLog={pickCalibrationLog}
                  project={calibration.project}
                  onProject={pickCalibrationProject}
                  session={calibration.session}
                  onSession={pickCalibrationSession}
                  tab={calibration.tab}
                  onTab={pickCalibrationTab}
                  onApply={applyOverrides}
                  onApplySession={applySession}
                  onEdit={openConfig}
                  onPlayLog={playLog}
                  onRescan={() => info && scan(info, false)}
                  guide={guideLink}
                />
              </div>
            )}
            {visited.includes("analyze") && (
              <div className="pagebox" hidden={page !== "analyze"}>
                <AnalyzePage workspace={workspace} robot={analyzeRobot || form.robot} onRobot={setAnalyzeRobot} active={page === "analyze"} />
              </div>
            )}
            {visited.includes("build") && (
              <div className="pagebox" hidden={page !== "build"}>
                <BuildPage workspace={workspace} root={root} editor={editor} project={buildProject} onProject={setBuildProject} />
              </div>
            )}
            {visited.includes("guide") && (
              <div className="pagebox guidebox" hidden={page !== "guide"}>
                <GuidePage doc={guide.doc} at={guide.at} onGo={openGuide} />
              </div>
            )}
          </Suspense>
        </main>
      </div>
      {help && <KeysHelp onClose={() => setHelp(false)} />}
      {newRoute && (
        <NewRouteDialog
          projects={workspace?.items.filter((item) => item.kind === "project") ?? []}
          robots={workspace?.items.filter((item) => item.kind === "robot") ?? []}
          fields={workspace?.items.filter((item) => item.kind === "field") ?? []}
          project={form.program}
          robot={form.robot}
          field={form.field}
          start={startPose}
          taken={workspace?.items.map((item) => item.path) ?? []}
          onCreated={routeCreated}
          onClose={() => setNewRoute(false)}
        />
      )}
      {newRobot && (
        <NewRobotDialog
          robots={workspace?.items.filter((item) => item.kind === "robot") ?? []}
          taken={workspace?.items.map((item) => item.path) ?? []}
          onCreated={robotCreated}
          onClose={() => setNewRobot(false)}
        />
      )}
    </div>
  );
}
