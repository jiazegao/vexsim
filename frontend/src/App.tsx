import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { ConsolePanel } from "./components/ConsolePanel";
import { Controls, SPEEDS } from "./components/Controls";
import type { Compared, FieldSource } from "./components/FieldView";
import { FieldKey, FieldView } from "./components/FieldView";
import { KeysHelp } from "./components/KeysHelp";
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
import { Playhead, usePlayheadClock } from "./playhead";
import type { Editor } from "./problems";
import { EDITORS } from "./problems";
import type { AppInfo, Preview, RunConfiguration, RunProblem, RunRecord, RunSpec, SweepTrial, WorkspaceInfo, WorkspaceItem } from "./protocol";
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
const SweepsPage = lazy(() => import("./pages/SweepsPage").then((m) => ({ default: m.SweepsPage })));
const BenchPage = lazy(() => import("./pages/BenchPage").then((m) => ({ default: m.BenchPage })));
const CalibratePage = lazy(() => import("./pages/CalibratePage").then((m) => ({ default: m.CalibratePage })));
const AnalyzePage = lazy(() => import("./pages/AnalyzePage").then((m) => ({ default: m.AnalyzePage })));
const BuildPage = lazy(() => import("./pages/BuildPage").then((m) => ({ default: m.BuildPage })));

type PageId = "simulate" | "sweeps" | "bench" | "calibrate" | "analyze" | "build";
const PAGES: [PageId, string, string][] = [
  ["simulate", "Simulate", "Run a robot on the field"],
  ["sweeps", "Sweeps", "Run saved runs many times over, and measure them"],
  ["bench", "Bench", "Benchmark scenarios: localizers and controllers over many seeds"],
  ["calibrate", "Calibrate", "Fit the simulator to a real robot's log"],
  ["analyze", "Analyze", "Motor curves, drift and odometry"],
  ["build", "Build", "Build PROS projects; check the compiler"],
];
const PAGE_IDS: readonly string[] = PAGES.map(([id]) => id);

const THEME_LABEL: Record<Theme, string> = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" };
const EDITOR_KEY = "vexsim.editor";
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

/** The form's start pose, when it's three numbers. */
function startOf(form: RunForm): Pose | null {
  const pose = [form.x, form.y, form.heading].map((text) => (text.trim() === "" ? NaN : Number(text)));
  return pose.every(Number.isFinite) ? (pose as Pose) : null;
}

export function App() {
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceInfo | null>(null);
  const [scanning, setScanning] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<RunForm>(emptyForm);
  const [store, setStore] = useState<SessionStore | null>(null);
  const [problem, setProblem] = useState<RunProblem | null>(null);
  const [starting, setStarting] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [layers, setLayers] = useState<Layers>({ trails: true, estimate: true, beams: true, forces: true });
  const [theme, setTheme] = useState<Theme>(loadTheme);
  const [preview, setPreview] = useState<Preview | null>(null);
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
  const [openConfigs, setOpenConfigs] = useState<string[]>([]); // configs open in editors
  const [page, setPage] = useState<string>("simulate"); // a PageId, or an open config's path
  const [visited, setVisited] = useState<string[]>(["simulate"]); // pages made so far (they stay)
  const [analyzeRobot, setAnalyzeRobot] = useState("");
  const [benchScenario, setBenchScenario] = useState("");
  const [calibration, setCalibration] = useState({ robot: "", log: "", project: "" });
  const [buildProject, setBuildProject] = useState<string | null>(null);
  const [overrideRequests, setOverrideRequests] = useState<Record<string, { id: number; overrides: Record<string, number> }>>({});
  const [unsaved, setUnsaved] = useState<Record<string, boolean>>({});
  const [closing, setClosing] = useState<string | null>(null); // asking before closing it
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

  const scan = useCallback(
    async (infoNow: AppInfo, restore: boolean) => {
      setScanning(true);
      try {
        const found = await api.workspace();
        setWorkspace(found);
        setForm((current) => reconcile(restore ? (loadForm(infoNow.workspace) ?? current) : current, found.items));
        setRescans((n) => n + 1);
        await loadConfigurations();
      } finally {
        setScanning(false);
      }
    },
    [loadConfigurations],
  );

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    try {
      localStorage.setItem(EDITOR_KEY, editor);
    } catch {
      // storage off: not remembered
    }
  }, [editor]);

  useEffect(() => {
    (async () => {
      try {
        const about = await api.info();
        setInfo(about);
        document.title = `vexsim · ${about.workspace_name}`;
        await scan(about, true);
        loadRuns();
        const running = (await api.sessions())
          .filter((s) => s.state !== "stopped")
          .sort((a, b) => b.created - a.created)[0];
        if (running) attach(running.id, 1);
      } catch (error) {
        setLoadError((error as Error).message);
      }
    })();
  }, [attach, scan, loadRuns]);

  useEffect(() => {
    if (info) saveForm(info.workspace, form);
  }, [form, info]);

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
  const scripted = !!spec?.input;
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

  const run = useCallback(async () => {
    const result = formToSpec(form);
    if ("error" in result) {
      setProblem({ error: result.error, issues: [] });
      return;
    }
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

  /** A calibration's fitted values, added to a robot config in its editor (to save there). */
  const applyOverrides = async (robot: string, overrides: Record<string, number>) => {
    openConfig(robot);
    setOverrideRequests((all) => ({ ...all, [robot]: { id: (all[robot]?.id ?? 0) + 1, overrides } }));
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

  const openConfig = (path: string) => {
    setOpenConfigs((open) => (open.includes(path) ? open : [...open, path]));
    setPage(path);
  };
  const closeConfig = (path: string) => {
    setOpenConfigs((open) => open.filter((p) => p !== path));
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

  /** A workspace item clicked in the sidebar: for the page on show where it's of use there,
   * else for a run on the Simulate page. */
  const pick = (item: WorkspaceItem) => {
    if (item.kind === "invalid") {
      openConfig(item.path); // to fix it
      return;
    }
    if (item.kind === "scenario") {
      setBenchScenario(item.path);
      setPage("bench");
      return;
    }
    if (item.kind === "robotlog") {
      setCalibration((c) => ({ ...c, log: item.path }));
      setPage("calibrate");
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
          ? [calibration.robot, calibration.log, calibration.project]
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

  // Keys, as in the pygame viewer: Space pause, . step, R restart, +/- speed; 1-4 what the
  // field shows; ? the list of keys. Driving keys are useController's. A recorded run: Space
  // play, arrows (Shift: farther), Home/End and , . move through it.
  const scrubbing = recording !== null;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName ?? "";
      const typing = target?.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(tag);
      const pressingButton = tag === "BUTTON" && (event.key === " " || event.key === "Enter");
      if (event.key === "Escape" && help) setHelp(false);
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
          if (store?.scene && state !== "stopped") store.send({ cmd: "restart" });
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
        case "?":
          setHelp((open) => !open);
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [changeSpeed, driving, help, page, playhead, scrubbing, speed, state, store]);

  return (
    <div className="app">
      <header className="topbar">
        <span className="wordmark">vexsim</span>
        {info && (
          <span className="where" title={info.workspace}>
            {info.workspace_name}
          </span>
        )}
        <span className="spacer" />
        {info && <span className="muted small">v{info.version}</span>}
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
      <div className="workarea">
        <Sidebar
          workspace={workspace}
          form={form}
          page={page}
          picked={picked}
          onPick={pick}
          onEdit={(item) => openConfig(item.path)}
          loading={scanning}
          onRefresh={() => info && scan(info, false)}
          shownLog={recording?.key.startsWith("log:") ? recording.key.slice(4) : null}
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
          <div className="simulate" hidden={page !== "simulate"}>
            <RunBar
              workspace={workspace}
              form={form}
              onChange={setForm}
              onRun={run}
              starting={starting}
              configurations={configurations}
              configFile={configFile}
              configError={configError}
              onPick={pickConfiguration}
              onSave={saveConfiguration}
              onDelete={deleteConfiguration}
            />
            <Controls
              store={store}
              speed={speed}
              onSpeed={changeSpeed}
              onStop={stop}
              command={store?.info?.command ?? store?.scene?.command ?? recording?.run?.command ?? null}
            />
            <div className="stage">
              <div className="fieldcol">
                <FieldView
                  source={source}
                  compared={onField}
                  preview={preview}
                  start={start}
                  onStart={moveStart}
                  layers={layers}
                  follow={follow}
                  onFollow={setFollow}
                  stamp={video && recording ? recording.name : null}
                />
                <FieldKey
                  layers={layers}
                  onLayers={setLayers}
                  compared={compared.map((r, i) => ({ key: r.key, name: r.label, dash: COMPARE_DASHES[i] }))}
                  onUncompare={(key) => setCompared((list) => list.filter((r) => r.key !== key))}
                />
                {recording && (
                  <Timeline
                    playback={recording.playback}
                    playhead={playhead}
                    name={recording.name}
                    run={recording.run}
                    csv={recording.run ? api.csvUrl(recording.run.id) : null}
                    video={video ? "recording" : canRecordVideo() ? "off" : "unsupported"}
                    onVideo={toggleVideo}
                    onClose={closeRecording}
                  />
                )}
              </div>
              <Readout source={source} driving={driving} scripted={scripted} gamepad={gamepad} onScreen={onScreen} onInput={setOnScreen} />
            </div>
            <ConsolePanel
              store={store}
              history={recording?.console ?? null}
              plots={recording ? <Plots shown={recording} compared={compared} playhead={playhead} /> : null}
              problem={problem}
              root={root}
              editor={editor}
              onEditor={setEditor}
            />
          </div>
          <Suspense fallback={<p className="muted pad">Opening the editor…</p>}>
            {openConfigs.map((path) => (
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
              />
            ))}
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
                  onApply={applyOverrides}
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
          </Suspense>
        </main>
      </div>
      {help && <KeysHelp onClose={() => setHelp(false)} />}
    </div>
  );
}
