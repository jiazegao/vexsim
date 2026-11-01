import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { JobStatus, ProblemBox, ResultList } from "../../components/JobPanel";
import { isActive, latest, useJob } from "../../jobs";
import type { AutonCheckResult, EndFound, PassMarks, ResultAbout, RunProblem, WorkspaceInfo } from "../../protocol";
import { when } from "../../recording";
import { figure, NeedsMatplotlib } from "./SessionPanel";

const EXAMPLE_END = "front-left: 23.5 from -x, 40 from +y; back-right: 35.25 from -x, 52 from +y";
const PLOTS: Record<string, string> = {
  "paths.png": "The real run's path (the code's pose) and the simulated ones, on the field",
  "apart.png": "How far apart they were through the routine, against the distance mark",
  "readings.png": "The IMU's turn, each side's wheel travel and the distance readings, real against simulated",
};

function problemOf(error: unknown): RunProblem {
  return { error: (error as Error).message, issues: [] };
}

/** Where one real run ended, as the student types its tape marks: read as they go. */
function EndInput(props: { robot: string; field: string; log: string; value: string; onChange: (text: string) => void }) {
  const [found, setFound] = useState<EndFound | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const { robot, field, value } = props;
  useEffect(() => {
    if (!value.trim() || !robot || !field) {
      setFound(null);
      setProblem(null);
      return;
    }
    let current = true;
    const timer = setTimeout(async () => {
      const result = await api.endFound(robot, field, value).catch((error) => ({ problem: problemOf(error) }));
      if (!current) return;
      if ("ok" in result) {
        setFound(result.ok);
        setProblem(null);
      } else {
        setFound(null);
        setProblem(result.problem.error);
      }
    }, 300);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [robot, field, value]);
  return (
    <label className="field grow end-input">
      <span>
        Where <code>{props.log.split("/").at(-1)}</code> ended: two corners' tape marks, each from an x wall and a y wall
      </span>
      <input value={props.value} onChange={(e) => props.onChange(e.target.value)} placeholder={EXAMPLE_END} spellCheck={false} data-testid="check-end" />
      {found && (
        <span className={`small ${found.warning ? "warning-text" : "muted"}`} data-testid="check-end-found">
          It ended at {found.x}, {found.y} in, heading {found.heading}°{found.warning ? `: ${found.warning}` : ""}
        </span>
      )}
      {problem && <span className="small warning-text">{problem}</span>}
    </label>
  );
}

/** The autonomous check (`vexsim calibration check-auton`): a routine's real runs, their ends
 * measured with tape, against the same routine in the calibrated simulator, at the team's pass marks. */
export function AutonCheck(props: { workspace: WorkspaceInfo | null; robot: string; onRobot: (path: string) => void; onPlayLog: (path: string) => void }) {
  const items = props.workspace?.items ?? [];
  const robots = useMemo(() => items.filter((i) => i.kind === "robot" && !i.problem), [items]);
  const fields = useMemo(() => items.filter((i) => i.kind === "field" && !i.problem), [items]);
  const projects = useMemo(() => items.filter((i) => i.kind === "project"), [items]);
  // a routine's logs (the competition code's), not the calibration program's
  const logs = useMemo(() => items.filter((i) => i.kind === "robotlog" && !i.detail.startsWith("calibration log")), [items]);
  const robot = props.robot || robots[0]?.path || "";
  const [field, setField] = useState("");
  const [project, setProject] = useState("");
  const fieldPath = field || fields[0]?.path || "";
  const projectPath = project || projects.find((p) => p.detail.includes("LemLib"))?.path || projects[0]?.path || "";
  const [chosen, setChosen] = useState<string[]>([]);
  const [ends, setEnds] = useState<Record<string, string>>({});
  const [seeds, setSeeds] = useState("3");
  const [marks, setMarks] = useState<PassMarks | null>(null);
  const [distance, setDistance] = useState("");
  const [heading, setHeading] = useState("");
  const [marksProblem, setMarksProblem] = useState<RunProblem | null>(null);
  const [problem, setProblem] = useState<RunProblem | null>(null);
  const [saved, setSaved] = useState<ResultAbout[]>([]);
  const [shown, setShown] = useState<AutonCheckResult | null>(null);

  const loadMarks = useCallback(async () => {
    try {
      const found = await api.passMarks();
      setMarks(found);
      setDistance(String(found.max_distance_in));
      setHeading(String(found.max_heading_deg));
    } catch {
      setMarks(null);
    }
  }, []);
  const loadSaved = useCallback(() => {
    api
      .results("checks")
      .then(setSaved)
      .catch(() => {});
  }, []);
  const open = useCallback(async (id: string) => {
    try {
      setShown(await api.result<AutonCheckResult>("checks", id));
    } catch (error) {
      setProblem({ error: `Couldn't open that check: ${(error as Error).message}`, issues: [] });
    }
  }, []);
  const job = useJob((ended) => {
    loadSaved();
    if (ended.state === "succeeded" && typeof ended.result?.id === "string") open(ended.result.id);
  });
  const { follow } = job;
  useEffect(() => {
    loadMarks();
    loadSaved();
    api
      .jobs()
      .then((jobs) => {
        const running = latest(jobs, "calibration_check", true);
        if (running) follow(running.id);
      })
      .catch(() => {});
  }, [loadMarks, loadSaved, follow]);

  const saveMarks = async () => {
    const result = await api.savePassMarks(Number(distance), Number(heading)).catch((error) => ({ problem: problemOf(error) }));
    if ("ok" in result) {
      setMarks(result.ok);
      setMarksProblem(null);
    } else setMarksProblem(result.problem);
  };
  const changedMarks = marks !== null && (Number(distance) !== marks.max_distance_in || Number(heading) !== marks.max_heading_deg);
  const ready = chosen.length > 0 && chosen.every((log) => (ends[log] ?? "").trim());
  const running = isActive(job.job?.state);
  const run = async () => {
    setShown(null);
    const count = Math.floor(Number(seeds));
    setProblem(
      await job.start({
        kind: "calibration_check",
        robot,
        field: fieldPath,
        program: projectPath,
        logs: chosen,
        ends: chosen.map((log) => ends[log] ?? ""),
        seeds: count >= 1 && count <= 10 ? count : 3,
        max_distance_in: changedMarks ? Number(distance) : null,
        max_heading_deg: changedMarks ? Number(heading) : null,
      }),
    );
  };

  return (
    <div className="page-split" data-testid="auton-check">
      <div className="page-main">
        <p className="muted">
          Does the calibrated simulator drive your autonomous as the real robot does? Run a routine on the real robot (its code logging with
          vexsim's logger), tape two of its corners where it stops and measure them from the walls; vexsim runs the same routine from where its
          code set its pose, a few times, and compares where it ended and its code's pose through the run. Same as{" "}
          <code>vexsim calibration check-auton</code> (the guide's section 8).
        </p>
        <section className="card" data-testid="pass-marks">
          <h2>The pass marks</h2>
          <div className="form-row">
            <label className="field narrow-ish">
              <span>Distance (in)</span>
              <input type="number" min={0.1} step={0.25} value={distance} onChange={(e) => setDistance(e.target.value)} data-testid="mark-distance" />
            </label>
            <label className="field narrow-ish">
              <span>Heading (°)</span>
              <input type="number" min={0.1} step={0.5} value={heading} onChange={(e) => setHeading(e.target.value)} data-testid="mark-heading" />
            </label>
            <button type="button" disabled={!changedMarks || !(Number(distance) > 0 && Number(heading) > 0)} onClick={saveMarks} data-testid="marks-save">
              Save as the team's
            </button>
            {marks && <span className="muted small">Now: {marks.source}.</span>}
          </div>
          {marks?.warnings.map((w, i) => (
            <p key={i} className="small warning-text">
              ⚠ {w}
            </p>
          ))}
          <p className="muted small">
            The team's go in <code>.vexsim/calibration.yaml</code>. Marks finer than a tape measure tells (0.5 in, 1°) can fail a run on how it was measured; a
            routine that ends a few degrees differently each time needs a wider heading mark.
          </p>
          <ProblemBox problem={marksProblem} />
        </section>
        <section className="card" data-testid="check-runs">
          <h2>The real runs</h2>
          <div className="form-row">
            <label className="field grow">
              <span>Robot (as calibrated)</span>
              <select value={robot} onChange={(e) => props.onRobot(e.target.value)} data-testid="check-robot">
                {robots.map((r) => (
                  <option key={r.path} value={r.path}>
                    {r.name} ({r.path})
                  </option>
                ))}
              </select>
            </label>
            <label className="field grow">
              <span>Field, as it was</span>
              <select value={fieldPath} onChange={(e) => setField(e.target.value)} data-testid="check-field">
                {fields.map((f) => (
                  <option key={f.path} value={f.path}>
                    {f.name} ({f.path})
                  </option>
                ))}
              </select>
            </label>
            <label className="field grow">
              <span>The PROS project the robot ran</span>
              <select value={projectPath} onChange={(e) => setProject(e.target.value)} data-testid="check-program">
                {projects.length === 0 && <option value="">No PROS projects in this workspace</option>}
                {projects.map((p) => (
                  <option key={p.path} value={p.path}>
                    {p.name} ({p.path})
                  </option>
                ))}
              </select>
            </label>
          </div>
          {logs.length === 0 ? (
            <p className="muted">No routine's robot logs in this workspace yet: copy them from the brain's card into it (they're listed under Robot logs).</p>
          ) : (
            <fieldset className="choices stack">
              <legend>Its logs (one routine's)</legend>
              {logs.map((log) => {
                const on = chosen.includes(log.path);
                return (
                  <div key={log.path} className="check-log">
                    <label>
                      <input type="checkbox" checked={on} onChange={() => setChosen(on ? chosen.filter((p) => p !== log.path) : [...chosen, log.path])} data-testid="check-log" />{" "}
                      <code>{log.path}</code> <span className="muted small">{log.detail}</span>
                    </label>
                    {on && <EndInput robot={robot} field={fieldPath} log={log.path} value={ends[log.path] ?? ""} onChange={(text) => setEnds({ ...ends, [log.path]: text })} />}
                  </div>
                );
              })}
            </fieldset>
          )}
          <div className="form-row">
            <label className="field narrow-ish">
              <span>Simulated runs</span>
              <input type="number" min={1} max={10} value={seeds} onChange={(e) => setSeeds(e.target.value)} />
            </label>
            <span className="spacer" />
            {running ? (
              <button type="button" onClick={job.cancel}>
                Cancel
              </button>
            ) : (
              <button type="button" className="primary" disabled={!ready || !robot || !fieldPath || !projectPath} onClick={run} data-testid="check-run">
                Check it
              </button>
            )}
          </div>
          <ProblemBox problem={problem} />
          {job.job && job.job.state !== "succeeded" && <JobStatus job={job.job} onCancel={job.cancel} />}
        </section>
        {shown && <CheckView result={shown} onPlayLog={props.onPlayLog} />}
      </div>
      <aside className="page-side card">
        <h2>Checks</h2>
        <ResultList
          results={saved}
          shown={shown?.about.id ?? null}
          onOpen={(about) => open(about.id)}
          onDelete={async (about) => {
            await api.deleteResult("checks", about.id).catch(() => {});
            if (shown?.about.id === about.id) setShown(null);
            loadSaved();
          }}
          empty="Checks you run are kept here."
        />
      </aside>
    </div>
  );
}

/** A check's verdict: each real run against the simulated ones, and the plots of where they part. */
function CheckView(props: { result: AutonCheckResult; onPlayLog: (path: string) => void }) {
  const { result } = props;
  const m = result.marks;
  const file = (name: string) => api.resultFileUrl("checks", result.about.id, name);
  return (
    <section className="card" data-testid="check-result">
      <header className="result-head">
        <h2>{result.about.title}</h2>
        <span className="muted small">
          {when(result.about.created)} · {result.robot} · {result.program}
        </span>
      </header>
      <div className={`verdict ${result.passed ? "good" : "bad"}`} data-testid="check-verdict">
        <strong>
          {result.passed ? "Passed" : "Failed"}: the simulated {result.routine} {result.passed ? "matches" : "doesn't match"} the real one, at {m.max_distance_in} in and{" "}
          {m.max_heading_deg}° ({m.source}).
        </strong>
        {result.failures.length > 0 && (
          <ul className="small">
            {result.failures.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        )}
      </div>
      {result.warnings.map((w, i) => (
        <p key={i} className="small warning-text">
          ⚠ {w}
        </p>
      ))}
      <table className="data compact" data-testid="check-table">
        <thead>
          <tr>
            <th>Real run</th>
            <th className="num">Ended at (measured)</th>
            <th className="num">From the simulated end</th>
            <th className="num">Through the run (RMS)</th>
            <th className="num">First over the mark</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {result.runs.map((run) => (
            <tr key={run.log}>
              <td>
                <code>{run.log.split("/").at(-1)}</code>
              </td>
              <td className="num">{run.measured ? `${figure(run.measured[0])}, ${figure(run.measured[1])} in, ${figure(run.measured[2])}°` : "—"}</td>
              <td className="num">{run.end_off ? `${run.end_off[0].toFixed(2)} in, ${run.end_off[1] >= 0 ? "+" : ""}${run.end_off[1].toFixed(1)}°` : "—"}</td>
              <td className="num">{run.run_rms_in === null ? "—" : `${run.run_rms_in.toFixed(2)} in`}</td>
              <td className="num">{run.parted_s === null ? "never" : `${run.parted_s.toFixed(1)} s`}</td>
              <td>
                <button type="button" className="ghost small" onClick={() => props.onPlayLog(run.log)} title="Play the log on the field, beside its routine run in the simulator" data-testid="check-play">
                  Play
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {result.sim_end && (
        <p className="muted small">
          The simulated runs ended at {figure(result.sim_end[0])}, {figure(result.sim_end[1])} in, {figure(result.sim_end[2])}° (their mean
          {result.sim_spread ? `; up to ${result.sim_spread[0].toFixed(1)} in and ${result.sim_spread[1].toFixed(1)}° apart` : ""}).
        </p>
      )}
      {result.plots.length === 0 && <NeedsMatplotlib what="The plots" then="check it again" />}
      <div className="report-plots">
        {result.plots.map((name) => (
          <figure key={name}>
            <a href={file(name)} target="_blank" rel="noreferrer">
              <img src={file(name)} alt={PLOTS[name] ?? name} loading="lazy" />
            </a>
            <figcaption className="muted small">{PLOTS[name] ?? name}</figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}
