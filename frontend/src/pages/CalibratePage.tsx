import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { calibrationCharts, uncertainty } from "../calibration";
import { JobStatus, ProblemBox, ResultList } from "../components/JobPanel";
import { LineChart } from "../components/LineChart";
import { isActive, latest, useJob } from "../jobs";
import { fixed } from "../pose";
import type { CalibrationResult, FitParameter, ResultAbout, RoutinePlan, RunProblem, WorkspaceInfo } from "../protocol";
import { when } from "../recording";

/** `vexsim calibration-routine` and `vexsim calibrate`: put the routine in a PROS project
 * for the real robot to drive and log; then fit the simulator's parameters to the log. */
export function CalibratePage(props: {
  workspace: WorkspaceInfo | null;
  robot: string;
  onRobot: (path: string) => void;
  log: string;
  onLog: (path: string) => void;
  project: string;
  onProject: (path: string) => void;
  onApply: (robot: string, values: Record<string, number>) => Promise<void>;
}) {
  const items = props.workspace?.items ?? [];
  const robots = useMemo(() => items.filter((i) => i.kind === "robot" && !i.problem), [items]);
  const projects = useMemo(() => items.filter((i) => i.kind === "project"), [items]);
  const logs = useMemo(() => items.filter((i) => i.kind === "robotlog"), [items]);
  const robot = props.robot || robots[0]?.path || "";
  const project = props.project || projects.find((p) => p.name === "calibration")?.path || projects[0]?.path || "";
  const log = props.log || logs[0]?.path || "";
  const { onRobot, onLog, onProject } = props;
  useEffect(() => {
    // what's picked by default, marked in the sidebar too
    if (robot && !props.robot) onRobot(robot);
    if (log && !props.log) onLog(log);
    if (project && !props.project) onProject(project);
  }, [robot, log, project, props.robot, props.log, props.project, onRobot, onLog, onProject]);

  const [plan, setPlan] = useState<RoutinePlan | null>(null);
  const [planProblem, setPlanProblem] = useState<RunProblem | null>(null);
  const [wrote, setWrote] = useState<string | null>(null);
  const [parameters, setParameters] = useState<FitParameter[]>([]);
  const [chosen, setChosen] = useState<string[]>([]);
  const [compareOnly, setCompareOnly] = useState(false);
  const [iterations, setIterations] = useState("12");
  const [problem, setProblem] = useState<RunProblem | null>(null);
  const [saved, setSaved] = useState<ResultAbout[]>([]);
  const [shown, setShown] = useState<CalibrationResult | null>(null);

  const loadSaved = useCallback(() => {
    api
      .results("calibrations")
      .then(setSaved)
      .catch(() => {});
  }, []);
  const open = useCallback(async (id: string) => {
    try {
      setShown(await api.result<CalibrationResult>("calibrations", id));
    } catch (error) {
      setProblem({ error: `Couldn't open that calibration: ${(error as Error).message}`, issues: [] });
    }
  }, []);
  const job = useJob((ended) => {
    loadSaved();
    if (ended.state === "succeeded" && typeof ended.result?.id === "string") open(ended.result.id);
  });
  const { follow } = job;
  useEffect(() => {
    loadSaved();
    api
      .jobs()
      .then((jobs) => {
        const running = latest(jobs, "calibrate", true);
        if (running) follow(running.id);
      })
      .catch(() => {});
  }, [loadSaved, follow]);

  const loadPlan = useCallback(async (write: boolean) => {
    if (!robot || !project) return;
    const found = await api.routine(robot, project, write).catch((error: Error) => ({ problem: { error: error.message, issues: [] } }));
    if ("problem" in found) {
      setPlan(null);
      setPlanProblem(found.problem);
    } else {
      setPlan(found.ok);
      setPlanProblem(null);
      if (write) setWrote(`Added to ${found.ok.project}.`);
    }
  }, [robot, project]);
  useEffect(() => {
    setWrote(null);
    loadPlan(false);
  }, [loadPlan]);

  useEffect(() => {
    if (!robot) return;
    let current = true;
    api
      .calibrationSetup(robot)
      .then((found) => {
        if (!current || "problem" in found) return;
        setParameters(found.ok.parameters);
        setChosen(found.ok.parameters.map((p) => p.name));
      })
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [robot]);

  const running = isActive(job.job?.state);
  const maxIterations = Math.floor(Number(iterations));
  const run = async () => {
    setShown(null);
    setProblem(
      await job.start({
        kind: "calibrate",
        robot,
        log,
        fit: chosen.length === parameters.length ? null : chosen,
        compare_only: compareOnly,
        max_iterations: maxIterations >= 1 && maxIterations <= 100 ? maxIterations : 12,
      }),
    );
  };
  const changes = plan?.files.filter((f) => f.state !== "same") ?? [];

  return (
    <div className="page" data-testid="calibrate-page">
      <header className="page-head">
        <h1>Calibrate</h1>
        <p className="muted">
          Make the simulated robot behave like the real one: the real robot drives a short routine while it logs what its motors and sensors
          read, and the simulator's parameters are fitted until its replay of the routine matches the log. Same as{" "}
          <code>vexsim calibration-routine</code> and <code>vexsim calibrate</code>; results are kept in <code>.vexsim/calibrations/</code>.
        </p>
      </header>
      <div className="page-split">
        <div className="page-main">
          <section className="card" data-testid="routine">
            <h2>1. Log the routine on the robot</h2>
            <div className="form-row">
              <label className="field wide">
                <span>Robot</span>
                <select value={robot} onChange={(e) => props.onRobot(e.target.value)} data-testid="calibrate-robot">
                  {robots.length === 0 && <option value="">No robot configs in this workspace</option>}
                  {robots.map((r) => (
                    <option key={r.path} value={r.path}>
                      {r.name} ({r.path})
                    </option>
                  ))}
                </select>
              </label>
              <label className="field wide">
                <span>Its PROS project</span>
                <select value={project} onChange={(e) => props.onProject(e.target.value)} data-testid="calibrate-project">
                  {projects.length === 0 && <option value="">No PROS projects in this workspace</option>}
                  {projects.map((p) => (
                    <option key={p.path} value={p.path}>
                      {p.name} ({p.path})
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <ProblemBox problem={planProblem} />
            {plan && (
              <>
                <p>
                  The routine drives {plan.steps.length} maneuvers in {plan.seconds} s (plus the IMU's calibration) and needs about 3 × 3 m of
                  open floor. Adding it to the project writes:
                </p>
                <ul className="files" data-testid="routine-files">
                  {plan.files.map((f) => (
                    <li key={f.path}>
                      <code>{f.path}</code>{" "}
                      <span className={`badge${f.state === "different" ? " warning" : ""}`}>
                        {f.state === "new" ? "new" : f.state === "same" ? "already there" : "replaces what's there"}
                      </span>
                    </li>
                  ))}
                </ul>
                <details>
                  <summary>The maneuvers</summary>
                  <table className="data compact">
                    <thead>
                      <tr>
                        <th>Maneuver</th>
                        <th className="num">From (s)</th>
                        <th className="num">For (s)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {plan.steps.map((step, i) => (
                        <tr key={i}>
                          <td>{step.name}</td>
                          <td className="num">{fixed(step.start_s, 1)}</td>
                          <td className="num">{fixed(step.seconds, 1)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
                <div className="form-row">
                  <button type="button" disabled={changes.length === 0} onClick={() => loadPlan(true)} data-testid="write-routine">
                    {changes.length === 0 ? "The routine is in the project" : `Add the routine to ${plan.project}`}
                  </button>
                  {wrote && <span className="muted small">{wrote}</span>}
                </div>
                <ol className="steps muted">
                  <li>
                    Call <code>vexsim_calibration::run();</code> from <code>autonomous()</code> (include <code>vexsim_calibration.hpp</code>), build
                    and upload the project, and run autonomous with the robot on open floor.
                  </li>
                  <li>
                    Copy <code>/usd/vexsim_log.csv</code> from the SD card into this workspace, or save the terminal's output to a <code>.txt</code>{" "}
                    file here (the log is printed there too). Then fit it below.
                  </li>
                </ol>
              </>
            )}
          </section>
          <section className="card" data-testid="fit">
            <h2>2. Fit the simulator to the log</h2>
            <div className="form-row">
              <label className="field wide">
                <span>Robot log</span>
                <select value={log} onChange={(e) => props.onLog(e.target.value)} data-testid="calibrate-log">
                  {logs.length === 0 && <option value="">No robot logs in this workspace yet</option>}
                  {logs.map((l) => (
                    <option key={l.path} value={l.path}>
                      {l.name} ({l.path})
                    </option>
                  ))}
                </select>
              </label>
              <label className="field narrow-ish">
                <span>Iterations, at most</span>
                <input type="number" min={1} max={100} value={iterations} onChange={(e) => setIterations(e.target.value)} disabled={compareOnly} />
              </label>
            </div>
            <fieldset className="choices" disabled={compareOnly}>
              <legend>Parameters to fit (values now)</legend>
              {parameters.map((p) => (
                <label key={p.name}>
                  <input type="checkbox" checked={chosen.includes(p.name)} onChange={() => setChosen(chosen.includes(p.name) ? chosen.filter((n) => n !== p.name) : [...chosen, p.name])} />{" "}
                  <code>{p.name}</code> <span className="muted small">{+p.value.toPrecision(4)}{p.overridden ? ", from the config" : ""}</span>
                </label>
              ))}
            </fieldset>
            <div className="form-row">
              <label className="check" title="Replay the log with the robot as configured, and fit nothing">
                <input type="checkbox" checked={compareOnly} onChange={(e) => setCompareOnly(e.target.checked)} /> Only compare (fit nothing)
              </label>
              <span className="spacer" />
              {running ? (
                <button type="button" onClick={job.cancel}>
                  Cancel
                </button>
              ) : (
                <button type="button" className="primary" disabled={!robot || !log || (!compareOnly && chosen.length === 0)} onClick={run} data-testid="calibrate-run">
                  {compareOnly ? "Compare" : "Fit"}
                </button>
              )}
            </div>
            <ProblemBox problem={problem} />
            {job.job && job.job.state !== "succeeded" && <JobStatus job={job.job} onCancel={job.cancel} />}
          </section>
          {shown && <CalibrationView result={shown} onApply={props.onApply} />}
        </div>
        <aside className="page-side card">
          <h2>Calibrations</h2>
          <ResultList
            results={saved}
            shown={shown?.about.id ?? null}
            onOpen={(about) => open(about.id)}
            onDelete={async (about) => {
              await api.deleteResult("calibrations", about.id).catch(() => {});
              if (shown?.about.id === about.id) setShown(null);
              loadSaved();
            }}
            empty="Fits you run are kept here."
          />
        </aside>
      </div>
    </div>
  );
}

function CalibrationView(props: { result: CalibrationResult; onApply: (robot: string, values: Record<string, number>) => Promise<void> }) {
  const { result } = props;
  const charts = useMemo(() => calibrationCharts(result), [result]);
  const [applying, setApplying] = useState(false);
  const facts = result.log_facts;
  const file = (name: string) => api.resultFileUrl("calibrations", result.about.id, name);
  const count = Object.keys(result.overrides).length;
  return (
    <section className="card" data-testid="calibration-result">
      <header className="result-head">
        <h2>{result.about.title}</h2>
        <span className="muted small">
          {when(result.about.created)} · {result.about.summary}
        </span>
        <span className="spacer" />
        {result.files.map((name) => (
          <a key={name} className="button" href={file(name)} download>
            {name}
          </a>
        ))}
      </header>
      <p className="muted small">
        {result.log}: {facts.rows} rows ({fixed(facts.seconds, 1)} s): {facts.found}
        {facts.skipped_lines > 0 && `; ${facts.skipped_lines} malformed lines skipped`}
        {facts.ignored_motors.length > 0 && `; motors ${facts.ignored_motors.join(", ")} aren't in the drivetrain, so they're left out`}.
      </p>
      {(result.parameters.length > 0 || result.direct.length > 0) && (
        <table className="data" data-testid="fitted">
          <thead>
            <tr>
              <th>Parameter</th>
              <th className="num">Before</th>
              <th className="num">Fitted</th>
              <th>How sure</th>
            </tr>
          </thead>
          <tbody>
            {result.parameters.map((p) => (
              <tr key={p.name}>
                <td>
                  <code>{p.name}</code>
                </td>
                <td className="num">{+p.before.toPrecision(4)}</td>
                <td className="num">
                  <b>{+p.after.toPrecision(4)}</b>
                </td>
                <td className={p.uncertainty < 0.5 ? undefined : "muted"}>{uncertainty(p.uncertainty)}</td>
              </tr>
            ))}
            {result.direct.map((p) => (
              <tr key={p.name}>
                <td>
                  <code>{p.name}</code>
                </td>
                <td className="num">{p.before === null ? "—" : +p.before.toPrecision(4)}</td>
                <td className="num">
                  <b>{+p.after.toPrecision(4)}</b>
                </td>
                <td className="muted">from the battery's voltage against its current</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <table className="data" data-testid="rms">
        <thead>
          <tr>
            <th>Simulated against logged (RMS difference)</th>
            {!result.compare_only && <th className="num">Before</th>}
            <th className="num">{result.compare_only ? "Now" : "After"}</th>
          </tr>
        </thead>
        <tbody>
          {result.rms.map((r) => (
            <tr key={r.group}>
              <td>
                {r.group} <span className="muted small">({r.unit})</span>
              </td>
              {!result.compare_only && <td className="num">{r.before === null ? "—" : +r.before.toPrecision(3)}</td>}
              <td className="num">{+r.after.toPrecision(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {count > 0 && (
        <div className="form-row">
          <button
            type="button"
            className="primary"
            disabled={applying}
            onClick={async () => {
              setApplying(true);
              try {
                await props.onApply(result.robot, result.overrides);
              } finally {
                setApplying(false);
              }
            }}
            data-testid="apply-overrides"
          >
            Add the fitted values to {result.robot.split("/").at(-1)}
          </button>
          <span className="muted small">Opens the robot's config with them under overrides, to look over and save.</span>
        </div>
      )}
      <div className="charts" data-testid="calibration-charts">
        {charts.map((c) => (
          <LineChart key={c.id} title={c.title} unit={c.unit} x={c.x} xUnit="s" series={c.series} digits={c.digits} sync="calibration" height={150} />
        ))}
      </div>
    </section>
  );
}
