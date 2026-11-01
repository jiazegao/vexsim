import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { JobStatus, ProblemBox } from "../../components/JobPanel";
import { isActive, latest, useJob } from "../../jobs";
import type { CalibrationProgram, CalibrationSessionState, ProgramPlan, RunProblem, SessionReport, SessionRun, WorkspaceInfo } from "../../protocol";

const PROGRAM = "calibration/vexsim_calibration"; // where the guide puts the program
const PRACTICE = "calibration/practice";
const PLAYS = new Set(["drive", "push", "spin"]); // tests that start on a spot: played by odometry

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** Today, as a session's folder is named (calibration/2026-11-07). */
export function todaysSession(): string {
  const d = new Date();
  return `calibration/${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** A value as the report gives it: four figures, or "—". */
export function figure(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (value === 0) return "0";
  return Math.abs(value) >= 100 ? value.toFixed(0) : String(+value.toPrecision(4));
}

function problemOf(error: unknown): RunProblem {
  return { error: (error as Error).message, issues: [] };
}

/** A calibration session in the app, as the guide goes (docs/calibration_guide.md): the robot and
 * field, the plan and its program, the session's logs (from the card, a folder, USB, or a practice in
 * vexsim), each test's runs, and the fit with its report, to apply to the robot's config. */
export function SessionPanel(props: {
  workspace: WorkspaceInfo | null;
  robot: string;
  onRobot: (path: string) => void;
  session: string;
  onSession: (path: string) => void;
  onApplySession: (robot: string, session: string) => void;
  onEdit: (path: string) => void;
  onPlayLog: (path: string) => void;
  onRescan: () => void;
}) {
  const items = props.workspace?.items ?? [];
  const robots = useMemo(() => items.filter((i) => i.kind === "robot"), [items]);
  const fields = useMemo(() => items.filter((i) => i.kind === "field" && !i.problem), [items]);
  const sessions = useMemo(() => items.filter((i) => i.kind === "calsession"), [items]);
  const robot = props.robot || robots.find((r) => !r.problem)?.path || "";
  const robotItem = robots.find((r) => r.path === robot) ?? null;
  const session = props.session || todaysSession();
  const { onRobot, onSession, onRescan } = props;
  useEffect(() => {
    if (robot && !props.robot) onRobot(robot);
  }, [robot, props.robot, onRobot]);

  const [field, setField] = useState("");
  const [folder, setFolder] = useState(PROGRAM);
  const [margin, setMargin] = useState("6");
  const [program, setProgram] = useState<CalibrationProgram | null>(null);
  const [programProblem, setProgramProblem] = useState<RunProblem | null>(null);
  const [state, setState] = useState<CalibrationSessionState | null>(null);
  const [sessionProblem, setSessionProblem] = useState<RunProblem | null>(null);
  const [collectFrom, setCollectFrom] = useState("");
  const [collected, setCollected] = useState<string[] | null>(null);
  const [practiceTests, setPracticeTests] = useState<string[] | null>(null); // null: every one
  const [unlike, setUnlike] = useState(true);
  const [practicePath, setPracticePath] = useState(PRACTICE);
  const [version, setVersion] = useState(0); // the plan's maps and the report's plots, drawn again
  const [busy, setBusy] = useState(false);

  // the session's field: the one its logs name, else the first
  const named = state?.field ? fields.find((f) => f.name === state.field)?.path : undefined;
  const fieldPath = field || named || fields[0]?.path || "";

  const loadProgram = useCallback(async () => {
    if (!folder.trim()) return setProgram(null);
    const found = await api.calibrationProgram(folder.trim()).catch((error) => ({ problem: problemOf(error) }));
    if ("ok" in found) setProgram(found.ok);
    else setProgram(null);
  }, [folder]);
  useEffect(() => {
    loadProgram();
  }, [loadProgram]);

  const loadSession = useCallback(async () => {
    const found = await api.calibrationSession(session, robot).catch((error) => ({ problem: problemOf(error) }));
    if ("ok" in found) {
      setState(found.ok);
      setSessionProblem(null);
    } else {
      setState(null);
      setSessionProblem(found.problem);
    }
  }, [session, robot]);
  useEffect(() => {
    setCollected(null);
    loadSession();
  }, [loadSession]);

  const programJob = useJob((ended) => {
    loadProgram();
    setVersion((v) => v + 1);
    if (ended.state === "succeeded") onRescan();
  });
  const practiceJob = useJob((ended) => {
    if (ended.state === "succeeded") {
      onSession(practicePath);
      onRescan();
    }
    loadSession();
  });
  const usbJob = useJob(() => {
    loadSession();
    onRescan();
  });
  const fitJob = useJob(() => {
    loadSession();
    setVersion((v) => v + 1);
    onRescan();
  });
  const followProgram = programJob.follow;
  const followPractice = practiceJob.follow;
  const followUsb = usbJob.follow;
  const followFit = fitJob.follow;
  useEffect(() => {
    // pick up jobs that were running when the page was reloaded
    api
      .jobs()
      .then((jobs) => {
        for (const [kind, follow] of [
          ["calibration_program", followProgram],
          ["calibration_practice", followPractice],
          ["calibration_usb", followUsb],
          ["calibration_fit", followFit],
        ] as const) {
          const running = latest(jobs, kind, true);
          if (running) follow(running.id);
        }
      })
      .catch(() => {});
  }, [followProgram, followPractice, followUsb, followFit]);
  // while listening over USB, each log shows as it comes
  const usbLines = usbJob.job?.log.length ?? 0;
  useEffect(() => {
    if (usbLines > 1) loadSession();
  }, [usbLines, loadSession]);

  const writeProgram = async () => {
    setProgramProblem(
      await programJob.start({ kind: "calibration_program", robot, field: fieldPath, folder: folder.trim(), margin: Number(margin) > 0 ? Number(margin) : 6 }),
    );
  };
  const practice = async () => {
    const tests = practiceTests ?? program?.plan?.tests.map((t) => t.key) ?? null;
    setSessionProblem(
      await practiceJob.start({ kind: "calibration_practice", robot, field: fieldPath, program: folder.trim(), session: practicePath.trim(), tests, unlike }),
    );
  };
  const collect = async (from: string | null) => {
    setBusy(true);
    setCollected(null);
    try {
      const found = await api.collectSession(session, from, robot);
      if ("problem" in found) setSessionProblem(found.problem);
      else {
        setState(found.ok.state);
        setSessionProblem(null);
        const head = `${found.ok.added} new run${found.ok.added === 1 ? "" : "s"} from ${found.ok.card}`;
        setCollected([head, ...found.ok.messages]);
        if (!props.session) onSession(session);
        onRescan();
      }
    } catch (error) {
      setSessionProblem(problemOf(error));
    } finally {
      setBusy(false);
    }
  };
  const listen = async () => {
    setSessionProblem(await usbJob.start({ kind: "calibration_usb", session }));
    if (!props.session) onSession(session);
  };
  const fit = async () => {
    setSessionProblem(await fitJob.start({ kind: "calibration_fit", robot, session, field: fieldPath || null }));
  };
  const setUse = async (run: SessionRun, use: boolean) => {
    const found = await api.setRunUse(session, run.file, use, robot).catch((error) => ({ problem: problemOf(error) }));
    if ("ok" in found) setState(found.ok);
    else setSessionProblem(found.problem);
  };

  const plan = program?.plan ?? null;
  const writing = isActive(programJob.job?.state);
  const listening = isActive(usbJob.job?.state);
  const practicing = isActive(practiceJob.job?.state);
  const fitting = isActive(fitJob.job?.state);

  return (
    <div className="page-split" data-testid="session-panel">
      <div className="page-main">
        <section className="card" data-testid="session-setup">
          <h2>1. The robot and the field</h2>
          <p className="muted small">
            The tests measure what a ruler can't, and build on what the robot's config already says: describe it carefully first (its weight,
            outline, wheels and sensors), and check the field's config against your field (the guide's section 3).
          </p>
          <div className="form-row">
            <label className="field grow">
              <span>Robot</span>
              <select value={robot} onChange={(e) => props.onRobot(e.target.value)} data-testid="session-robot">
                {robots.length === 0 && <option value="">No robot configs in this workspace</option>}
                {robots.map((r) => (
                  <option key={r.path} value={r.path} disabled={!!r.problem}>
                    {r.name} ({r.path})
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="small" disabled={!robot} onClick={() => props.onEdit(robot)} data-testid="session-edit-robot">
              Edit
            </button>
            <label className="field grow">
              <span>Field, with its elements where they'll be</span>
              <select value={fieldPath} onChange={(e) => setField(e.target.value)} data-testid="session-field">
                {fields.length === 0 && <option value="">No field configs in this workspace</option>}
                {fields.map((f) => (
                  <option key={f.path} value={f.path}>
                    {f.name} ({f.path})
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="small" disabled={!fieldPath} onClick={() => props.onEdit(fieldPath)}>
              Edit
            </button>
          </div>
          {robotItem?.problem && <ProblemBox problem={{ error: `${robotItem.path}: ${robotItem.problem}`, issues: [] }} />}
        </section>

        <section className="card" data-testid="session-program">
          <h2>2. Plan the session, and write its program</h2>
          <p className="muted small">
            vexsim simulates each driving test many times, as the robot might really be, and finds a spot on the field where every run stays clear
            of the walls and the elements. Then it writes the program for the robot and that plan into a PROS project of its own, for a spare slot
            on the brain. Same as <code>vexsim calibration program</code>.
          </p>
          <div className="form-row">
            <label className="field grow">
              <span>The program's folder (a PROS project)</span>
              <input value={folder} onChange={(e) => setFolder(e.target.value)} spellCheck={false} data-testid="program-folder" />
            </label>
            <label className="field narrow-ish" title="Room to keep between each test and the walls and elements">
              <span>Room (in)</span>
              <input type="number" min={1} max={24} step={0.5} value={margin} onChange={(e) => setMargin(e.target.value)} />
            </label>
            <span className="spacer" />
            {writing ? (
              <button type="button" onClick={programJob.cancel}>
                Cancel
              </button>
            ) : (
              <button type="button" className="primary" disabled={!robot || !fieldPath || !folder.trim()} onClick={writeProgram} data-testid="program-write">
                {program?.written ? "Plan and write it again" : "Plan and write the program"}
              </button>
            )}
          </div>
          <ProblemBox problem={programProblem} />
          {programJob.job && programJob.job.state !== "succeeded" && <JobStatus job={programJob.job} onCancel={programJob.cancel} />}
          {program?.written && <ProgramSteps program={program} />}
          {plan && program && <PlanView plan={plan} version={version} />}
        </section>

        <section className="card" data-testid="session-collect">
          <h2>3. Run the session, and collect its logs</h2>
          <p className="muted small">
            Run each test from the program's menu on the robot, in order (the guide's section 5): each saves a log to the brain's SD card. Then put the
            card in this computer and collect them into the session's folder. Same as <code>vexsim calibration collect</code>.
          </p>
          <div className="form-row">
            <label className="field grow">
              <span>The session's folder</span>
              <input list="calibration-sessions" value={session} onChange={(e) => props.onSession(e.target.value)} spellCheck={false} data-testid="session-path" />
              <datalist id="calibration-sessions">
                {sessions.map((s) => (
                  <option key={s.path} value={s.path}>
                    {s.detail}
                  </option>
                ))}
              </datalist>
            </label>
          </div>
          <div className="form-row">
            <button type="button" className="primary" disabled={busy || listening} onClick={() => collect(null)} data-testid="collect-card">
              Collect from the card
            </button>
            <label className="field grow">
              <span>Or from a folder (a copy of the card, say)</span>
              <input value={collectFrom} onChange={(e) => setCollectFrom(e.target.value)} placeholder="E:\  or  /Volumes/NO NAME" spellCheck={false} data-testid="collect-from" />
            </label>
            <button type="button" disabled={busy || listening || !collectFrom.trim()} onClick={() => collect(collectFrom.trim())} data-testid="collect-folder">
              Collect
            </button>
            {listening ? (
              <button type="button" onClick={usbJob.cancel} data-testid="usb-stop">
                Stop listening
              </button>
            ) : (
              <button
                type="button"
                disabled={busy}
                onClick={listen}
                title="No card in the brain: the program prints each log over the USB cable as it ends. Run this from the folder the PROS terminal works in, the brain plugged into this computer, and leave it listening for the whole session."
                data-testid="usb-start"
              >
                Over USB…
              </button>
            )}
          </div>
          {collected && (
            <ul className="files small" data-testid="collected">
              {collected.map((line, i) => (
                <li key={i} className={i === 0 ? undefined : "muted"}>
                  {line}
                </li>
              ))}
            </ul>
          )}
          {usbJob.job && <JobStatus job={usbJob.job} onCancel={usbJob.cancel} />}
          <details className="practice" data-testid="practice">
            <summary>Practice in vexsim first</summary>
            <p className="muted small">
              The simulated student runs the program on the simulated robot, test by test, as you will on the real one: the same screens, the
              same spots. Its logs go into a practice session of their own, to collect, look over and fit before the field. It needs the program
              written above.
            </p>
            {plan && (
              <fieldset className="choices">
                <legend>Tests to run</legend>
                {plan.tests.map((t) => {
                  const chosen = practiceTests === null || practiceTests.includes(t.key);
                  return (
                    <label key={t.key}>
                      <input
                        type="checkbox"
                        checked={chosen}
                        onChange={() => {
                          const all = plan.tests.map((x) => x.key);
                          const now = practiceTests ?? all;
                          setPracticeTests(chosen ? now.filter((k) => k !== t.key) : all.filter((k) => k === t.key || now.includes(k)));
                        }}
                      />{" "}
                      {t.number}. {t.title}
                    </label>
                  );
                })}
              </fieldset>
            )}
            <label className="check" title="Wheels about 1.5% smaller, the IMU 0.25% further off, grippier or slipperier wheels, voltage held to rated speed and the real distance sensors: as a real robot is">
              <input type="checkbox" checked={unlike} onChange={(e) => setUnlike(e.target.checked)} /> The simulated robot not quite as its config says,
              as a real robot is: for the fit to find something
            </label>
            <div className="form-row">
              <label className="field grow">
                <span>The practice session's folder</span>
                <input value={practicePath} onChange={(e) => setPracticePath(e.target.value)} spellCheck={false} data-testid="practice-path" />
              </label>
              {practicing ? (
                <button type="button" onClick={practiceJob.cancel}>
                  Cancel
                </button>
              ) : (
                <button
                  type="button"
                  disabled={!program?.written || !practicePath.trim() || (practiceTests !== null && practiceTests.length === 0)}
                  onClick={practice}
                  data-testid="practice-run"
                >
                  Practice
                </button>
              )}
            </div>
            {practiceJob.job && <JobStatus job={practiceJob.job} onCancel={practiceJob.cancel} unit="tests" />}
          </details>
          <ProblemBox problem={sessionProblem} />
        </section>

        <section className="card" data-testid="session-runs">
          <h2>
            4. Each test's runs{" "}
            {state?.practice && (
              <span className="chip" title="The simulated student's runs, not a robot's">
                practice
              </span>
            )}
          </h2>
          <RunsTable state={state} plan={plan} onUse={setUse} onPlay={props.onPlayLog} />
        </section>

        <section className="card" data-testid="session-fit">
          <h2>5. Fit the session</h2>
          <p className="muted small">
            vexsim fits each test into what it measures, in order, each fit using what the ones before it found: the motors, the IMU, the wheels'
            size, the drive's grip and rolling (one driving run held out, to check the result), the tracking wheels, the distance sensors. A few
            minutes. Same as <code>vexsim calibrate ROBOT SESSION</code>.
          </p>
          <div className="form-row">
            {fitting ? (
              <button type="button" onClick={fitJob.cancel}>
                Cancel
              </button>
            ) : (
              <button type="button" className="primary" disabled={!robot || !state?.runs.length} onClick={fit} data-testid="session-fit-run">
                {state?.report ? "Fit it again" : "Fit the session"}
              </button>
            )}
            {state?.report && <span className="muted small">Fitted {state.report.fitted}, to {state.report.robot_file}.</span>}
          </div>
          {fitJob.job && fitJob.job.state !== "succeeded" && <JobStatus job={fitJob.job} onCancel={fitJob.cancel} />}
          {state?.report && <ReportView report={state.report} session={state.path} version={version} onApply={() => props.onApplySession(state.report!.robot_file, state.path)} />}
        </section>
      </div>
      <aside className="page-side card">
        <h2>Sessions</h2>
        {sessions.length === 0 ? (
          <p className="muted small">Sessions you collect are listed here (each a folder with its session.yaml).</p>
        ) : (
          <ul className="results" data-testid="sessions">
            {sessions.map((s) => (
              <li key={s.path} className={s.path === session ? "shown" : undefined}>
                <button type="button" className="item" onClick={() => props.onSession(s.path)} aria-pressed={s.path === session} data-testid="session">
                  <span className="item-name">{s.path}</span>
                  <span className="item-detail">{s.detail}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <button type="button" className="small" onClick={() => props.onSession(todaysSession())} title="A new session, named by today's date">
          New session
        </button>
      </aside>
    </div>
  );
}

/** What vexsim draws with matplotlib (the `viz` extra), and how to get it. */
export function NeedsMatplotlib(props: { what: string; then: string }) {
  return (
    <p className="muted small" data-testid="needs-matplotlib">
      {props.what} need matplotlib: <code>python -m pip install -e ".[viz]"</code> in the vexsim folder, then {props.then}.
    </p>
  );
}

/** How to put the written program on the robot, with the PROS CLI. */
function ProgramSteps(props: { program: CalibrationProgram }) {
  const { program } = props;
  return (
    <div className="program-steps" data-testid="program-steps">
      {!program.pros_project && (
        <div className="verdict" data-testid="not-pros">
          <strong>{program.folder} isn't a PROS project yet.</strong> The program runs in vexsim (Practice, below), but to put it on the robot, make it
          a PROS project first, in the PROS terminal, then write the program again:
          <pre className="snippet">{`pros c n ${program.folder}`}</pre>
        </div>
      )}
      <p className="muted small">On the robot, in the PROS terminal, the brain plugged in with USB: it goes in slot 8, beside your competition program.</p>
      <pre className="snippet">{`cd ${program.folder}\npros make\npros upload --slot 8`}</pre>
    </div>
  );
}

/** The session's tests as the program's menu has them: what each takes, where it goes, its map. */
function PlanView(props: { plan: ProgramPlan; version: number }) {
  const { plan } = props;
  return (
    <div className="plan" data-testid="plan">
      <p className="muted small">
        {plan.robot} on {plan.field}, {plan.margin_in} in of room around each test. Clear the game pieces off the field: the plan leaves them out.
      </p>
      <table className="data compact" data-testid="plan-tests">
        <thead>
          <tr>
            <th className="num">#</th>
            <th>Test</th>
            <th className="num">Runs</th>
            <th>Where</th>
            <th>Map</th>
          </tr>
        </thead>
        <tbody>
          {plan.tests.map((t) => (
            <tr key={t.key}>
              <td className="num">{t.number}</td>
              <td>
                {t.title}
                {t.scale !== null && <span className="muted small"> (at {Math.round(t.scale * 100)}% speed: there's less room)</span>}
              </td>
              <td className="num">{t.runs}</td>
              <td className="small">
                {t.place.length ? t.place.map((line, i) => <div key={i}>{line}</div>) : <span className="muted">{t.kind === "on_hand" ? "anywhere: on its side, or by hand" : ""}</span>}
              </td>
              <td>
                {t.map && (
                  <a href={api.imageUrl(t.map, String(props.version))} target="_blank" rel="noreferrer" title="The map, to print">
                    <img className="map-thumb" src={api.imageUrl(t.map, String(props.version))} alt={`Map ${t.number}: ${t.title}`} loading="lazy" />
                  </a>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {plan.tests.some((t) => t.place.length > 0 && !t.map) && <NeedsMatplotlib what="The maps" then="plan and write the program again" />}
      {plan.missing.length > 0 && (
        <div className="problem" role="alert">
          <strong>Left out, with no room on this field:</strong>{" "}
          {plan.missing.map((m) => `${m.title}${m.blocked_by.length ? ` (in the way: ${m.blocked_by.join(", ")})` : ""}`).join("; ")}. Check the field's
          config: an element in the wrong place takes up room it doesn't have.
        </div>
      )}
    </div>
  );
}

/** Each test's runs: how each ended, what it measured, whether the fit uses it; tests not run yet. */
function RunsTable(props: { state: CalibrationSessionState | null; plan: ProgramPlan | null; onUse: (run: SessionRun, use: boolean) => void; onPlay: (path: string) => void }) {
  const { state, plan } = props;
  const tests = plan?.tests ?? [];
  const runs = state?.runs ?? [];
  if (runs.length === 0 && tests.length === 0) return <p className="muted">No runs yet: collect them above.</p>;
  // the plan's order, then any test it doesn't have
  const keys = [...tests.map((t) => t.key), ...runs.map((r) => r.test).filter((k, i, all) => all.indexOf(k) === i && !tests.some((t) => t.key === k))];
  const title = (key: string) => tests.find((t) => t.key === key)?.title ?? key.replace(/_/g, " ");
  const kind = (key: string) => tests.find((t) => t.key === key)?.kind ?? (key === "device_check" || key.startsWith("imu") || key === "free_spin" ? "on_hand" : "drive");
  return (
    <table className="data compact" data-testid="runs-table">
      <thead>
        <tr>
          <th>Test</th>
          <th>Log</th>
          <th>What it measured</th>
          <th title="Whether the fit uses it">Use</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {keys.map((key) => {
          const mine = runs.filter((r) => r.test === key);
          const wanted = tests.find((t) => t.key === key)?.runs ?? mine.length;
          const good = mine.filter((r) => r.use).length;
          if (mine.length === 0)
            return (
              <tr key={key} className="muted">
                <td>{title(key)}</td>
                <td colSpan={4}>not run yet{wanted > 1 ? ` (${wanted} runs)` : ""}</td>
              </tr>
            );
          return mine.map((run, i) => (
            <tr key={run.file} data-testid="session-run">
              {i === 0 && (
                <td rowSpan={mine.length}>
                  {title(key)}
                  <div className={`small ${good >= wanted ? "muted" : "warning-text"}`}>
                    {good} of {wanted} used
                  </div>
                </td>
              )}
              <td className="small">
                <code>{run.file}</code>
              </td>
              <td className="small">
                <span className={run.quality === "good" ? undefined : "warning-text"}>{run.result}</span>
                {run.quality !== "good" && <div className="warning-text">left out: {run.quality}</div>}
                {run.warnings.map((w, k) => (
                  <div key={k} className="muted">
                    ⚠ {w}
                  </div>
                ))}
              </td>
              <td>
                <input type="checkbox" checked={run.use} onChange={(e) => props.onUse(run, e.target.checked)} aria-label={`Use ${run.file}`} />
              </td>
              <td>
                {PLAYS.has(kind(key)) && state && (
                  <button type="button" className="ghost small" onClick={() => props.onPlay(`${state.path}/runs/${run.file}`)} title="Play it on the field, from its spot, by odometry">
                    Play
                  </button>
                )}
              </td>
            </tr>
          ));
        })}
      </tbody>
    </table>
  );
}

/** A session's fit, as its report says it: does the held-out run match, what Apply writes, each step. */
function ReportView(props: { report: SessionReport; session: string; version: number; onApply: () => void }) {
  const { report } = props;
  const [copied, setCopied] = useState(false);
  const held = report.held_out;
  const image = (file: string) => api.imageUrl(`${props.session}/report/${file}`, `${report.fitted}-${props.version}`);
  return (
    <div className="report" data-testid="session-report">
      {held ? (
        <div className={`verdict ${held.matches ? "good" : "bad"}`} data-testid="held-out">
          <strong>
            The held-out run ({held.run}), which the fit didn't use, {held.matches ? "matches" : "doesn't match"} within the sensors' noise.
          </strong>{" "}
          <span className="small">
            {held.groups.map((g) => `${g.group} ${figure(g.rms)} ${g.unit} (noise ${figure(g.noise)})`).join(" · ")}
          </span>
        </div>
      ) : (
        <p className="muted">No driving run was held out to check the fit (it takes two or more).</p>
      )}
      {report.warnings.length > 0 && (
        <ul className="warnings small">
          {report.warnings.map((w, i) => (
            <li key={i}>⚠ {w}</li>
          ))}
        </ul>
      )}
      <h3>What Apply writes into {report.robot_file}</h3>
      {report.changes.length === 0 ? (
        <p className="muted">Nothing: the logs agree with the config as it is.</p>
      ) : (
        <>
          <table className="data compact" data-testid="session-changes">
            <tbody>
              {report.changes.map((c) => (
                <tr key={c.location}>
                  <td>
                    <code>{c.location}</code>
                  </td>
                  <td className="num">{Array.isArray(c.value) ? c.value.map(figure).join(", ") : figure(c.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="form-row">
            <button type="button" className="primary" onClick={props.onApply} data-testid="session-apply">
              Apply them to {report.robot_file.split("/").at(-1)}
            </button>
            <span className="muted small">Opens the config with them written in (its comments kept), to look over and save.</span>
          </div>
        </>
      )}
      {report.drive_section && (
        <div className="drive-fit">
          <h3>Drive model, for routes made in vexsim's autonomous maker</h3>
          <p className="muted small">{report.drive}. For a route to drive the real robot with it, add this line to the route:</p>
          <div className="form-row">
            <code className="snippet">{report.drive_section}</code>
            <button
              type="button"
              className="small"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(report.drive_section ?? "");
                  setCopied(true);
                } catch {
                  setCopied(false);
                }
              }}
            >
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
      )}
      {report.steps.map((step, n) => (
        <details key={step.name} className="step" open={step.values.length > 0}>
          <summary>
            <b>
              {n + 1}. {step.name}
            </b>{" "}
            {step.skipped ? <span className="muted small">skipped: {step.skipped}</span> : <span className="muted small">from {step.runs.join(", ")}</span>}
          </summary>
          {step.values.length > 0 && (
            <table className="data compact">
              <thead>
                <tr>
                  <th>Value</th>
                  <th className="num">Before</th>
                  <th className="num">After</th>
                  <th className="num">Known to</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {step.values.map((v) => (
                  <tr key={v.key}>
                    <td>
                      <code>{v.key}</code>
                    </td>
                    <td className="num">{figure(v.before)}</td>
                    <td className="num">
                      <b>{figure(v.after)}</b>
                    </td>
                    <td className="num">{v.uncertainty === null ? "?" : `±${figure(v.uncertainty)}`}</td>
                    <td className={`small${v.why_not ? " muted" : ""}`}>{v.why_not ? v.why_not.replace(/^not written: /, "not written: ") : "written"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {step.rms.length > 0 && (
            <p className="small muted">
              Simulated against logged, before → after: {step.rms.map((r) => `${r.group} ${figure(r.before)} → ${figure(r.after)} ${r.unit}`).join(", ")}
            </p>
          )}
          {[...step.notes, ...step.warnings].length > 0 && (
            <ul className="small">
              {step.notes.map((note, i) => (
                <li key={`n${i}`}>{note}</li>
              ))}
              {step.warnings.map((w, i) => (
                <li key={`w${i}`} className="warning-text">
                  ⚠ {w}
                </li>
              ))}
            </ul>
          )}
        </details>
      ))}
      {report.plots.length === 0 && <NeedsMatplotlib what="The report's plots" then="fit the session again" />}
      {report.plots.length > 0 && (
        <div className="report-plots" data-testid="session-plots">
          {report.plots.map((p) => (
            <figure key={p.file}>
              <a href={image(p.file)} target="_blank" rel="noreferrer">
                <img src={image(p.file)} alt={p.title} loading="lazy" />
              </a>
              <figcaption className="muted small">{p.title}</figcaption>
            </figure>
          ))}
        </div>
      )}
    </div>
  );
}
