import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { ConsolePanel } from "./components/ConsolePanel";
import { Controls, SPEEDS } from "./components/Controls";
import { FieldKey, FieldView } from "./components/FieldView";
import { KeysHelp } from "./components/KeysHelp";
import { Readout } from "./components/Readout";
import { RunBar } from "./components/RunBar";
import { Sidebar } from "./components/Sidebar";
import type { ControllerInput } from "./controller";
import { NEUTRAL } from "./controller";
import type { Layers } from "./draw";
import type { Editor } from "./problems";
import { EDITORS } from "./problems";
import type { AppInfo, Preview, RunConfiguration, RunProblem, WorkspaceInfo, WorkspaceItem } from "./protocol";
import type { RunForm } from "./runform";
import { emptyForm, formToSpec, loadForm, reconcile, saveForm, specToForm } from "./runform";
import { isLive, SessionStore } from "./session";
import type { Pose } from "./startpose";
import { formatStart } from "./startpose";
import type { Theme } from "./theme";
import { applyTheme, loadTheme, nextTheme } from "./theme";
import { useController } from "./useController";
import { useStore } from "./useStore";

const THEME_LABEL: Record<Theme, string> = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" };
const EDITOR_KEY = "vexsim.editor";
const BUSY: readonly string[] = ["building", "starting", "running", "paused"]; // the run is on the field

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
  useStore(store);

  const root = info?.workspace ?? "";
  const rootRef = useRef(root);
  rootRef.current = root;
  const storeRef = useRef<SessionStore | null>(null);
  const attach = useCallback((id: string, speedNow: number) => {
    storeRef.current?.close();
    const next = new SessionStore(id, rootRef.current);
    if (speedNow !== 1) next.send({ cmd: "speed", value: speedNow });
    next.connect();
    storeRef.current = next;
    setStore(next);
    setOnScreen(NEUTRAL);
  }, []);
  useEffect(() => () => storeRef.current?.close(), []);

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
        const running = (await api.sessions())
          .filter((s) => s.state !== "stopped")
          .sort((a, b) => b.created - a.created)[0];
        if (running) attach(running.id, 1);
      } catch (error) {
        setLoadError((error as Error).message);
      }
    })();
  }, [attach, scan]);

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
  const spec = store?.scene?.spec ?? store?.info?.spec ?? null;
  const scripted = !!spec?.input;
  const driving = live && !scripted;
  const gamepad = useController(store, driving, onScreen);
  // The field shows the run while it's on, and afterwards while the form names the same
  // robot and field; otherwise the preview of what the form names.
  const showRun =
    !!store && (BUSY.includes(state ?? "") || (!!spec && spec.robot === form.robot && (spec.field ?? "") === form.field));
  const startPose = useMemo(() => startOf(form), [form]);
  const start = startPose ? { pose: startPose, editable: !BUSY.includes(state ?? "") } : null;

  const run = useCallback(async () => {
    const result = formToSpec(form);
    if ("error" in result) {
      setProblem({ error: result.error, issues: [] });
      return;
    }
    setStarting(true);
    setProblem(null);
    try {
      const started = await api.startSession(result.spec);
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
  }, [attach, form, speed]);

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

  const pick = (item: WorkspaceItem) => {
    const key = item.kind === "project" ? "program" : (item.kind as keyof RunForm);
    if (key in form && key !== "config") setForm({ ...form, [key]: item.path });
  };

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
  // field shows; ? the list of keys. Driving keys are useController's.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName ?? "";
      const typing = target?.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(tag);
      const pressingButton = tag === "BUTTON" && (event.key === " " || event.key === "Enter");
      if (event.key === "Escape" && help) setHelp(false);
      if (event.ctrlKey || event.metaKey || event.altKey || typing || pressingButton) return;
      const index = SPEEDS.indexOf(speed);
      const toggle = (key: keyof Layers) => setLayers((l) => ({ ...l, [key]: !l[key] }));
      switch (event.key) {
        case " ":
          if (store && state && isLive(state)) {
            event.preventDefault();
            store.send({ cmd: state === "paused" ? "resume" : "pause" });
          }
          break;
        case ".":
          if (state === "paused") store?.send({ cmd: "step", ms: 10 });
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
  }, [changeSpeed, help, speed, state, store]);

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
        <Sidebar workspace={workspace} form={form} onPick={pick} loading={scanning} onRefresh={() => info && scan(info, false)} />
        <main className="main">
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
          <Controls store={store} speed={speed} onSpeed={changeSpeed} onStop={stop} command={store?.info?.command ?? store?.scene?.command ?? null} />
          <div className="stage">
            <div className="fieldcol">
              <FieldView
                store={store}
                showRun={showRun}
                preview={preview}
                start={start}
                onStart={moveStart}
                layers={layers}
                follow={follow}
                onFollow={setFollow}
              />
              <FieldKey layers={layers} onLayers={setLayers} />
            </div>
            <Readout store={showRun ? store : null} driving={driving} scripted={scripted} gamepad={gamepad} onScreen={onScreen} onInput={setOnScreen} />
          </div>
          <ConsolePanel store={store} problem={problem} root={root} editor={editor} onEditor={setEditor} />
        </main>
      </div>
      {help && <KeysHelp onClose={() => setHelp(false)} />}
    </div>
  );
}
