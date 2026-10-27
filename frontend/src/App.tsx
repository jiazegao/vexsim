import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ConsolePanel } from "./components/ConsolePanel";
import { Controls, SPEEDS } from "./components/Controls";
import { FieldKey, FieldView } from "./components/FieldView";
import { Readout } from "./components/Readout";
import { RunBar } from "./components/RunBar";
import { Sidebar } from "./components/Sidebar";
import type { Layers } from "./draw";
import type { AppInfo, RunProblem, WorkspaceInfo, WorkspaceItem } from "./protocol";
import type { RunForm } from "./runform";
import { emptyForm, formToSpec, loadForm, reconcile, saveForm } from "./runform";
import { isLive, SessionStore } from "./session";
import type { Theme } from "./theme";
import { applyTheme, loadTheme, nextTheme } from "./theme";
import { useStore } from "./useStore";

const THEME_LABEL: Record<Theme, string> = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" };

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
  const [layers, setLayers] = useState<Layers>({ trails: true, estimate: true, beams: true });
  const [theme, setTheme] = useState<Theme>(loadTheme);
  useStore(store);

  const storeRef = useRef<SessionStore | null>(null);
  const attach = useCallback((id: string, speedNow: number) => {
    storeRef.current?.close();
    const next = new SessionStore(id);
    if (speedNow !== 1) next.send({ cmd: "speed", value: speedNow });
    next.connect();
    storeRef.current = next;
    setStore(next);
  }, []);
  useEffect(() => () => storeRef.current?.close(), []);

  const scan = useCallback(async (infoNow: AppInfo, restore: boolean) => {
    setScanning(true);
    try {
      const found = await api.workspace();
      setWorkspace(found);
      setForm((current) => reconcile(restore ? (loadForm(infoNow.workspace) ?? current) : current, found.items));
    } finally {
      setScanning(false);
    }
  }, []);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

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
      else attach(started.session.id, speed);
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
    if (key in form) setForm({ ...form, [key]: item.path });
  };

  // Keys, as in the pygame viewer: Space pause, . step, R restart, +/- speed, G T B layers
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName ?? "";
      const typing = target?.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(tag);
      const pressingButton = tag === "BUTTON" && (event.key === " " || event.key === "Enter");
      if (event.ctrlKey || event.metaKey || event.altKey || typing || pressingButton) return;
      const state = store?.state;
      const index = SPEEDS.indexOf(speed);
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
        case "g":
        case "G":
          setLayers((l) => ({ ...l, estimate: !l.estimate }));
          break;
        case "t":
        case "T":
          setLayers((l) => ({ ...l, trails: !l.trails }));
          break;
        case "b":
        case "B":
          setLayers((l) => ({ ...l, beams: !l.beams }));
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [changeSpeed, speed, store]);

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
          />
          <Controls
            store={store}
            speed={speed}
            onSpeed={changeSpeed}
            onStop={stop}
            command={store?.info?.command ?? store?.scene?.command ?? null}
          />
          <div className="stage">
            <div className="fieldcol">
              <FieldView store={store} layers={layers} />
              <FieldKey layers={layers} onLayers={setLayers} />
            </div>
            <Readout store={store} />
          </div>
          <ConsolePanel store={store} problem={problem} />
        </main>
      </div>
    </div>
  );
}
