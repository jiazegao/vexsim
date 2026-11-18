import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import type { Place } from "./address";
import { formatPlace, HOME, parsePlace } from "./address";
import { api } from "./api";
import { SimulatePage } from "./app/SimulatePage";
import type { Calibration } from "./app/shared";
import { BUSY, EDITOR_KEY, FIRST_RUN_KEY, loadEditor, loadRunOnSave, ON_SAVE_KEY, PAGE_IDS, PAGES, THEME_LABEL } from "./app/shared";
import { useAddress } from "./app/useAddress";
import { useEditors } from "./app/useEditors";
import { useKeys } from "./app/useKeys";
import { useRealLog } from "./app/useRealLog";
import { useRunForm } from "./app/useRunForm";
import { useRuns } from "./app/useRuns";
import { useWorkspace } from "./app/useWorkspace";
import { FirstRun, firstSteps } from "./components/FirstRun";
import { KeysHelp } from "./components/KeysHelp";
import { NewRobotDialog } from "./components/NewRobotDialog";
import { NewRouteDialog } from "./components/NewRouteDialog";
import { RunsList } from "./components/RunsList";
import { Sidebar } from "./components/Sidebar";
import { fileName } from "./configdoc";
import type { Layers } from "./draw";
import { hostTheme, onHostTheme } from "./host";
import { NARROW, SHORT, useMedia, usePanel } from "./layout";
import type { CalibrateTab } from "./pages/CalibratePage";
import { Playhead, usePlayheadClock } from "./playhead";
import type { Editor } from "./problems";
import type { RunProblem, WorkspaceItem } from "./protocol";
import type { RunForm } from "./runform";
import { useRoving } from "./roving";
import { emptyForm, formToSpec, sameRun } from "./runform";
import type { Theme } from "./theme";
import { applyTheme, loadTheme, nextTheme } from "./theme";

// The editors (and CodeMirror) load when a config is first opened, the pages when first shown
const ConfigEditor = lazy(() => import("./components/ConfigEditor").then((m) => ({ default: m.ConfigEditor })));
const RouteEditor = lazy(() => import("./components/RouteEditor").then((m) => ({ default: m.RouteEditor })));
const SweepsPage = lazy(() => import("./pages/SweepsPage").then((m) => ({ default: m.SweepsPage })));
const BenchPage = lazy(() => import("./pages/BenchPage").then((m) => ({ default: m.BenchPage })));
const CalibratePage = lazy(() => import("./pages/CalibratePage").then((m) => ({ default: m.CalibratePage })));
const AnalyzePage = lazy(() => import("./pages/AnalyzePage").then((m) => ({ default: m.AnalyzePage })));
const BuildPage = lazy(() => import("./pages/BuildPage").then((m) => ({ default: m.BuildPage })));
const GuidePage = lazy(() => import("./pages/GuidePage").then((m) => ({ default: m.GuidePage })));

/** The app's shell: the header and its pages, the workspace list, and whichever page is on
 * show. What each feature keeps is in a file of its own in app/: the folder (useWorkspace), the
 * run form (useRunForm), the runs (useRuns), a real robot's log (useRealLog), the editors
 * (useEditors), the address (useAddress), the keys (useKeys); the Simulate page is
 * app/SimulatePage. What several of them share is here: the page, the form, a run's problem. */
export function App() {
  // where the address says to be (address.ts): the page and Calibrate's tab at once, the
  // editor and the run once the folder is listed
  const [arrival] = useState<Place>(() => parsePlace(location.hash) ?? HOME);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<RunForm>(emptyForm);
  const [problem, setProblem] = useState<RunProblem | null>(null);
  const [layers, setLayers] = useState<Layers>({ trails: true, estimate: true, beams: true, forces: true, drawings: true });
  const [hiddenDrawings, setHiddenDrawings] = useState<string[]>([]); // layers of the robot code's drawings
  const [theme, setTheme] = useState<Theme>(() => hostTheme() ?? loadTheme());
  const [follow, setFollow] = useState(false);
  const [editor, setEditor] = useState<Editor>(loadEditor);
  const [help, setHelp] = useState(false);
  const [page, setPage] = useState<string>(arrival.page === "edit" ? "simulate" : arrival.page); // a PageId, or an open config's path
  const [visited, setVisited] = useState<string[]>(["simulate"]); // pages made so far (they stay)
  const [analyzeRobot, setAnalyzeRobot] = useState("");
  const [benchScenario, setBenchScenario] = useState("");
  const [calibration, setCalibration] = useState<Calibration>({
    robot: "",
    log: "",
    project: "",
    session: arrival.session ?? "",
    tab: arrival.tab ?? "session",
  });
  const [buildProject, setBuildProject] = useState<string | null>(null);
  const [guide, setGuide] = useState<{ doc: string; at: string | null }>({ doc: arrival.doc ?? "", at: arrival.at ?? null }); // the Guide page's document and heading
  const [startHidden, setStartHidden] = useState(false); // "Start here" was put away, for this folder
  const [writingStarter, setWritingStarter] = useState(false);
  // the shell fits its window (layout.ts): what's folded away in a short or a narrow one
  const short = useMedia(SHORT);
  const narrow = useMedia(NARROW);
  const [sidebarOpen, setSidebarOpen] = usePanel("sidebar", narrow);
  const [readoutOpen, setReadoutOpen] = usePanel("readout", narrow);
  const [bottomOpen, setBottomOpen] = usePanel("bottom", short);
  const [runbarOpen, setRunbarOpen] = useState<boolean | null>(null); // by hand; null: as the window asks
  const [runOnSave, setRunOnSave] = useState(loadRunOnSave); // a save of the run's code runs it again
  // each of these is one stop for Tab, the arrow keys moving within it (roving.ts)
  const pageTabs = useRoving<HTMLDivElement>('[role="tab"]');
  const fileTabs = useRoving<HTMLDivElement>("button");
  const appTools = useRoving<HTMLDivElement>("button");
  const playhead = useMemo(() => new Playhead(), []);
  usePlayheadClock(playhead);
  useEffect(() => {
    if (PAGE_IDS.includes(page)) setVisited((pages) => (pages.includes(page) ? pages : [...pages, page]));
  }, [page]);

  // what each feature keeps (app/)
  const ws = useWorkspace(setForm);
  const { info, workspace, scan, configurations } = ws;
  const root = info?.workspace ?? "";
  const runForm = useRunForm({ form, setForm, ws, setProblem });
  const runs = useRuns({ root, playhead, form, setForm, setProblem, setPage, configurations, runOnSave });
  const { store, busy, spec, source, recording, startRun, loadRuns, attach } = runs;
  const log = useRealLog({ runs, playhead, form, setForm, workspace, configurations, routines: runForm.routines, setProblem, setPage, setCalibration });
  const { realLog, openRealLog } = log;
  const editors = useEditors({ ws, setForm, setPage });
  const { openConfig, openRoute, openConfigs, unsaved } = editors;
  const { setArrived, goRef, restoreRef } = useAddress({ page, setPage, calibration, setCalibration, guide, setGuide, workspace, configurations, setForm, runs, openConfig, openRoute });

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

  const { setInfo } = ws;
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
  }, [arrival, attach, scan, loadRuns, setInfo, setArrived, goRef, restoreRef]);

  // in a short window the run bar is one line once a run is on show (Edit unfolds it)
  const onShow = source.kind !== "preview" || realLog !== null;
  const runbarFolded = !(runbarOpen ?? !(short && onShow));

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

  /** A route (just saved in the maker) run on the Simulate page, with its timeline and plots. */
  const watchRoute = async (path: string) => {
    const next = (await runForm.routeForm(path))(form);
    setForm(next);
    runs.setShown(null);
    setPage("simulate");
    const result = formToSpec(next);
    if ("error" in result) setProblem({ error: result.error, issues: [] });
    else await startRun(result.spec, null);
  };

  const pickCalibrationRobot = useCallback((robot: string) => setCalibration((c) => ({ ...c, robot })), []);
  const pickCalibrationLog = useCallback((log: string) => setCalibration((c) => ({ ...c, log })), []);
  const pickCalibrationProject = useCallback((project: string) => setCalibration((c) => ({ ...c, project })), []);
  const pickCalibrationSession = useCallback((session: string) => setCalibration((c) => ({ ...c, session })), []);
  const pickCalibrationTab = useCallback((tab: CalibrateTab) => setCalibration((c) => ({ ...c, tab })), []);

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
      void runForm.pickRoute(item.path);
      return;
    }
    if (page === "analyze" && item.kind === "robot") return setAnalyzeRobot(item.path);
    if (page === "calibrate" && item.kind === "robot") return setCalibration((c) => ({ ...c, robot: item.path }));
    if (page === "calibrate" && item.kind === "project") return setCalibration((c) => ({ ...c, project: item.path }));
    if (page === "build" && item.kind === "project") return setBuildProject(item.path);
    setPage("simulate");
    if (item.kind === "log") {
      runs.openTelemetryLog(item.path);
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
  const first = firstSteps(items, runs.runs, store ? (spec ?? {}) : null);
  // "Start here" shows in a folder that's new to vexsim, while no run is going, until it's put away
  const startShown = !!workspace && runs.runsLoaded && !startHidden && !busy && !realLog && !(first.robot && first.driven && first.program && first.ran);

  useKeys({
    help,
    setHelp,
    narrow,
    sidebarOpen,
    setSidebarOpen,
    page,
    speed: runs.speed,
    changeSpeed: runs.changeSpeed,
    store,
    state: runs.state,
    scrubbing: recording !== null || log.logAlone,
    driving: runs.driving,
    playhead,
    restart: runs.restart,
    setLayers,
  });

  /** To the Run button, past everything before it (the skip link's): or, with no robot to
   * run yet, to the first thing to set. */
  const skipToRun = (event: { preventDefault: () => void }) => {
    event.preventDefault(); // not a place in the address
    setPage("simulate");
    requestAnimationFrame(() => {
      const run = document.getElementById("run") as HTMLButtonElement | null;
      (run && !run.disabled ? run : document.querySelector<HTMLElement>(".runbar select, .runbar button:not(:disabled)"))?.focus();
    });
  };

  return (
    <div className="app">
      <a className="skip" href="#run" onClick={skipToRun} data-testid="skip-to-run">
        Skip to Run
      </a>
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
        <div className="pagetabs">
          <div className="pagetabs-pages" role="tablist" aria-label="Pages" {...pageTabs.props}>
            {PAGES.map(([id, label, hint]) => (
              <button key={id} role="tab" aria-selected={page === id} className={`pagetab${page === id ? " on" : ""}`} onClick={() => setPage(id)} title={hint} data-testid={`page-${id}`}>
                {label}
              </button>
            ))}
          </div>
          {openConfigs.length > 0 && <span className="pagetabs-gap" aria-hidden="true" />}
          {openConfigs.length > 0 && (
            // the files open in editors: each a button to its editor, and one to close it
            <div className="pagetabs-files" role="toolbar" aria-label="Open files" {...fileTabs.props}>
              {openConfigs.map((path) => (
                <span key={path} className={`pagetab config${page === path ? " on" : ""}`}>
                  <button type="button" aria-current={page === path ? "page" : undefined} onClick={() => setPage(path)} title={path} data-testid={`page-${path}`}>
                    {fileName(path)}
                    {unsaved[path] && (
                      <span className="unsaved" title="Unsaved changes" aria-label="unsaved changes">
                        {" "}
                        ●
                      </span>
                    )}
                  </button>
                  <button type="button" className="close" onClick={() => editors.askToClose(path)} aria-label={`Close ${path}`} title="Close">
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
        {info && <span className="muted small version">v{info.version}</span>}
        <div className="topbar-tools" role="toolbar" aria-label="The app" {...appTools.props}>
          <button className="ghost small" onClick={() => setHelp(true)} title="Every key, for running and driving (?)" data-testid="keys">
            Keys
          </button>
          <button className="ghost small" onClick={() => setTheme(nextTheme(theme))} title="Light, dark, or as your system is set">
            {THEME_LABEL[theme]}
          </button>
        </div>
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
          onDuplicate={editors.duplicateItem}
          onDelete={editors.deleteItem}
          unsaved={unsaved}
          editor={editor}
          onNewRobot={() => editors.setNewRobot(true)}
          onNewRoute={() => editors.setNewRoute(true)}
          loading={ws.scanning}
          onRefresh={() => info && scan(info, false, "fresh")}
          shownLog={recording?.key.startsWith("log:") ? recording.key.slice(4) : null}
          realLog={realLog?.tape.path ?? null}
          runCount={runs.runs.length}
          onRunsTab={loadRuns}
          runs={
            <RunsList
              runs={runs.runs}
              shown={recording?.run?.id ?? null}
              compared={runs.compared.map((r) => r.key)}
              opening={runs.opening}
              canCompare={source.kind !== "preview"}
              onOpen={runs.openRecorded}
              onCompare={runs.toggleCompare}
              onKeep={(record, kept) => runs.changeRun(record, { kept })}
              onRename={(record, name) => runs.changeRun(record, { name })}
              onDelete={runs.deleteRun}
            />
          }
        />
        <main className="main">
          <SimulatePage
            hidden={page !== "simulate"}
            ws={ws}
            runs={runs}
            log={log}
            form={form}
            onForm={setForm}
            runForm={runForm}
            onRun={run}
            onNewRobot={() => editors.setNewRobot(true)}
            runbarFolded={runbarFolded}
            onRunbarFold={short && onShow ? (folded) => setRunbarOpen(!folded) : undefined}
            runOnSave={runOnSave}
            onRunOnSave={setRunOnSave}
            firstRun={
              startShown && (
                <FirstRun
                  done={first}
                  busy={runs.starting || writingStarter}
                  onNewRobot={() => editors.setNewRobot(true)}
                  onDrive={() => runWith({ program: "", mode: "" })}
                  onStarter={addStarter}
                  onRunProgram={() => runWith({ program: items.find((i) => i.path === form.program && i.kind !== "robot")?.path ?? items.find((i) => i.kind === "program")?.path ?? "", mode: "" })}
                  guide={guideLink("readme")}
                  onHide={hideStart}
                />
              )
            }
            playhead={playhead}
            layers={layers}
            onLayers={setLayers}
            hiddenDrawings={hiddenDrawings}
            onHiddenDrawings={setHiddenDrawings}
            follow={follow}
            onFollow={setFollow}
            readoutOpen={readoutOpen}
            onReadoutOpen={setReadoutOpen}
            bottomOpen={bottomOpen}
            onBottomOpen={setBottomOpen}
            problem={problem}
            root={root}
            editor={editor}
            onEditor={setEditor}
          />
          <Suspense fallback={<p className="muted pad">Opening the editor…</p>}>
            {openConfigs.map((path) =>
              editors.openRoutes.includes(path) ? (
                <RouteEditor
                  key={path}
                  path={path}
                  active={page === path}
                  closing={editors.closing === path}
                  workspace={workspace}
                  onClose={() => editors.closeConfig(path)}
                  onKeepOpen={() => editors.setClosing(null)}
                  onDirty={editors.markUnsaved}
                  onSaved={() => info && scan(info, false)}
                  onWatch={watchRoute}
                  onOpen={editors.routeCreated}
                />
              ) : (
                <ConfigEditor
                  key={path}
                  path={path}
                  active={page === path}
                  closing={editors.closing === path}
                  onClose={() => editors.closeConfig(path)}
                  onKeepOpen={() => editors.setClosing(null)}
                  onDirty={editors.markUnsaved}
                  onSaved={() => info && scan(info, false)}
                  request={editors.overrideRequests[path] ?? null}
                  design={editors.designing.includes(path)}
                />
              ),
            )}
          </Suspense>
          <Suspense fallback={<p className="muted pad">Opening the page…</p>}>
            {visited.includes("sweeps") && (
              <div className="pagebox" hidden={page !== "sweeps"}>
                <SweepsPage configurations={configurations} onWatch={runs.watchTrial} />
              </div>
            )}
            {visited.includes("bench") && (
              <div className="pagebox" hidden={page !== "bench"}>
                <BenchPage workspace={workspace} scenario={benchScenario} onScenario={setBenchScenario} onWorstCase={runs.watchWorstCase} />
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
                  onApply={editors.applyOverrides}
                  onApplySession={editors.applySession}
                  onEdit={openConfig}
                  onPlayLog={log.playLog}
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
      {editors.newRoute && (
        <NewRouteDialog
          projects={workspace?.items.filter((item) => item.kind === "project") ?? []}
          robots={workspace?.items.filter((item) => item.kind === "robot") ?? []}
          fields={workspace?.items.filter((item) => item.kind === "field") ?? []}
          project={form.program}
          robot={form.robot}
          field={form.field}
          start={runForm.startPose}
          taken={workspace?.items.map((item) => item.path) ?? []}
          onCreated={editors.routeCreated}
          onClose={() => editors.setNewRoute(false)}
        />
      )}
      {editors.newRobot && (
        <NewRobotDialog
          robots={workspace?.items.filter((item) => item.kind === "robot") ?? []}
          taken={workspace?.items.map((item) => item.path) ?? []}
          onCreated={editors.robotCreated}
          onClose={() => editors.setNewRobot(false)}
        />
      )}
    </div>
  );
}
