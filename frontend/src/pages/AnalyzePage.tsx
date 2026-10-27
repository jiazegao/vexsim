import { useEffect, useMemo, useState } from "react";
import { driftPaths, isDifferential, motorCharts, odometryCharts, odometryPaths, parseFrictions } from "../analysis";
import { JobStatus, ProblemBox } from "../components/JobPanel";
import { LineChart } from "../components/LineChart";
import { PathChart } from "../components/PathChart";
import { isActive, useJob } from "../jobs";
import { fixed } from "../pose";
import type { Drift, MotorCurves, Odometry, RunProblem, WorkspaceInfo } from "../protocol";

type Tool = "motors" | "drift" | "odometry";
const TOOLS: [Tool, string][] = [
  ["motors", "Motor curves"],
  ["drift", "Drift in an arc"],
  ["odometry", "Odometry"],
];
const CARTRIDGES: [string, string][] = [
  ["red", "red (100 rpm)"],
  ["green", "green (200 rpm)"],
  ["blue", "blue (600 rpm)"],
];

/** `vexsim motor-curves`, `drift` and `odometry` as charts: a motor on the dynamometer, a
 * differential robot's arc across roller frictions, and the baseline localizers against the
 * truth over a scripted drive. */
export function AnalyzePage(props: { workspace: WorkspaceInfo | null; robot: string; onRobot: (path: string) => void; active: boolean }) {
  const [tool, setTool] = useState<Tool>("motors");
  const robots = useMemo(() => props.workspace?.items.filter((i) => i.kind === "robot" && !i.problem) ?? [], [props.workspace]);
  const robot = props.robot || robots[0]?.path || "";

  return (
    <div className="page" data-testid="analyze-page">
      <header className="page-head">
        <h1>Analyze</h1>
        <p className="muted">
          A motor on the simulated dynamometer, how far a robot drifts in an arc, and how the baseline localizers track a scripted drive. Same
          as <code>vexsim motor-curves</code>, <code>drift</code> and <code>odometry</code>.
        </p>
      </header>
      <div className="tabs subtabs" role="tablist">
        {TOOLS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tool === id} className={tool === id ? "on" : ""} onClick={() => setTool(id)} data-testid={`tool-${id}`}>
            {label}
          </button>
        ))}
      </div>
      <div hidden={tool !== "motors"}>
        <MotorTool active={props.active && tool === "motors"} />
      </div>
      <div hidden={tool !== "drift"}>
        <DriftTool robots={robots} robot={robot} onRobot={props.onRobot} />
      </div>
      <div hidden={tool !== "odometry"}>
        <OdometryTool robots={robots} robot={robot} onRobot={props.onRobot} />
      </div>
    </div>
  );
}

function MotorTool(props: { active: boolean }) {
  const [cartridge, setCartridge] = useState("green");
  const [volts, setVolts] = useState("12.8");
  const [problem, setProblem] = useState<RunProblem | null>(null);
  const job = useJob();
  const run = async () => setProblem(await job.start({ kind: "motor_curves", cartridge: cartridge as "green", supply_voltage: Number(volts) }));
  const { start } = job;
  const shown = job.job;
  useEffect(() => {
    if (props.active && !shown) start({ kind: "motor_curves" }).then(setProblem); // something to look at
  }, [props.active, shown, start]);
  const result = shown?.state === "succeeded" ? (shown.result as unknown as MotorCurves) : null;
  const charts = useMemo(() => (result ? motorCharts(result) : []), [result]);
  return (
    <section className="card">
      <div className="form-row">
        <label className="field">
          <span>Cartridge</span>
          <select value={cartridge} onChange={(e) => setCartridge(e.target.value)} data-testid="cartridge">
            {CARTRIDGES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Battery (V)</span>
          <input type="number" min={6} max={14} step={0.1} value={volts} onChange={(e) => setVolts(e.target.value)} />
        </label>
        <button type="button" className="primary" onClick={run} disabled={isActive(shown?.state) || !(Number(volts) >= 6 && Number(volts) <= 14)} data-testid="run-motors">
          Show
        </button>
      </div>
      <ProblemBox problem={problem} />
      {shown?.state !== "succeeded" && <JobStatus job={shown} onCancel={job.cancel} />}
      {result && (
        <>
          <p className="muted small">
            A {result.cartridge} cartridge at {result.supply_voltage} V: what <code>move_velocity</code> at full speed and <code>move_voltage(12000)</code>{" "}
            give, from stalled to free running.
          </p>
          <div className="charts" data-testid="motor-charts">
            {charts.map((c) => (
              <LineChart key={c.id} title={c.title} unit={c.unit} x={c.x} xUnit="rpm" series={c.series} digits={c.digits} refs={c.refs} sync="motor-curves" testid={`chart-${c.id}`} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function RobotSelect(props: { robots: { path: string; name: string; detail: string }[]; robot: string; onRobot: (path: string) => void; usable?: (detail: string) => boolean; why?: string }) {
  return (
    <label className="field wide">
      <span>Robot</span>
      <select value={props.robot} onChange={(e) => props.onRobot(e.target.value)} data-testid="analyze-robot">
        {props.robots.length === 0 && <option value="">No robot configs in this workspace</option>}
        {props.robots.map((r) => {
          const usable = props.usable ? props.usable(r.detail) : true;
          return (
            <option key={r.path} value={r.path} disabled={!usable}>
              {r.name} ({r.path}){usable ? "" : ` — ${props.why}`}
            </option>
          );
        })}
      </select>
    </label>
  );
}

function DriftTool(props: { robots: WorkspaceInfo["items"]; robot: string; onRobot: (path: string) => void }) {
  const [left, setLeft] = useState("100");
  const [right, setRight] = useState("40");
  const [seconds, setSeconds] = useState("1.5");
  const [frictions, setFrictions] = useState("0.4, 0.2, 0.1");
  const [problem, setProblem] = useState<RunProblem | null>(null);
  const job = useJob();
  const differential = props.robots.filter(isDifferential);
  const robot = differential.some((r) => r.path === props.robot) ? props.robot : (differential[0]?.path ?? "");
  const mus = parseFrictions(frictions);
  const valid = robot && mus && [left, right].every((v) => Math.abs(Number(v)) <= 100) && Number(seconds) > 0 && Number(seconds) <= 10;
  const run = async () =>
    setProblem(
      await job.start({ kind: "drift", robot, left: Number(left) / 100, right: Number(right) / 100, seconds: Number(seconds), lateral_mu: mus ?? undefined }),
    );
  const shown = job.job;
  const result = shown?.state === "succeeded" ? (shown.result as unknown as Drift) : null;
  const paths = useMemo(() => (result ? driftPaths(result) : []), [result]);
  return (
    <section className="card">
      <div className="form-row">
        <RobotSelect robots={props.robots} robot={robot} onRobot={props.onRobot} usable={(detail) => detail.startsWith("differential")} why="not a differential drive" />
        <label className="field narrow-ish">
          <span>Left (% of top speed)</span>
          <input type="number" min={-100} max={100} value={left} onChange={(e) => setLeft(e.target.value)} />
        </label>
        <label className="field narrow-ish">
          <span>Right (% of top speed)</span>
          <input type="number" min={-100} max={100} value={right} onChange={(e) => setRight(e.target.value)} />
        </label>
        <label className="field narrow-ish">
          <span>For (s)</span>
          <input type="number" min={0.1} max={10} step={0.1} value={seconds} onChange={(e) => setSeconds(e.target.value)} />
        </label>
        <label className="field" title="The omni wheels' roller friction (wheel.omni.lateral_mu): up to three values to compare">
          <span>Roller friction</span>
          <input value={frictions} onChange={(e) => setFrictions(e.target.value)} aria-invalid={!mus} />
        </label>
        <button type="button" className="primary" onClick={run} disabled={!valid || isActive(shown?.state)} data-testid="run-drift">
          Drive
        </button>
      </div>
      <ProblemBox problem={problem} />
      {shown?.state !== "succeeded" && <JobStatus job={shown} onCancel={job.cancel} />}
      {result && (
        <div className="analysis">
          <PathChart
            title={`Left ${Math.round(result.left * 100)}%, right ${Math.round(result.right * 100)}% for ${result.seconds} s`}
            paths={paths}
            start={[0, 0]}
            testid="drift-chart"
            note={<p className="muted small">Solid: where the robot really went. Dashed: where its drive-encoder odometry thinks it went.</p>}
          />
          <table className="data" data-testid="drift-table">
            <thead>
              <tr>
                <th>Roller friction</th>
                <th className="num">Ends at (in)</th>
                <th className="num">Odometry off by (in)</th>
              </tr>
            </thead>
            <tbody>
              {result.runs.map((run) => {
                const end = run.true.at(-1) ?? [0, 0];
                return (
                  <tr key={run.lateral_mu}>
                    <td>{run.lateral_mu}</td>
                    <td className="num">
                      {fixed(end[0], 1)}, {fixed(end[1], 1)}
                    </td>
                    <td className="num">{fixed(run.final_error_in, 1)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function OdometryTool(props: { robots: WorkspaceInfo["items"]; robot: string; onRobot: (path: string) => void }) {
  const [script, setScript] = useState<"gentle" | "aggressive">("aggressive");
  const [noise, setNoise] = useState("");
  const [seed, setSeed] = useState("0");
  const [problem, setProblem] = useState<RunProblem | null>(null);
  const job = useJob();
  const robot = props.robot;
  const run = async () =>
    setProblem(await job.start({ kind: "odometry", robot, script, noise: (noise || null) as "ideal" | null, seed: Math.max(0, Math.floor(Number(seed) || 0)) }));
  const shown = job.job;
  const result = shown?.state === "succeeded" ? (shown.result as unknown as Odometry) : null;
  const paths = useMemo(() => (result ? odometryPaths(result) : []), [result]);
  const charts = useMemo(() => (result ? odometryCharts(result) : []), [result]);
  return (
    <section className="card">
      <div className="form-row">
        <RobotSelect robots={props.robots} robot={robot} onRobot={props.onRobot} />
        <label className="field">
          <span>Drive</span>
          <select value={script} onChange={(e) => setScript(e.target.value as "gentle")}>
            <option value="aggressive">aggressive: fast turns</option>
            <option value="gentle">gentle</option>
          </select>
        </label>
        <label className="field">
          <span>Sensor noise</span>
          <select value={noise} onChange={(e) => setNoise(e.target.value)}>
            <option value="">as configured</option>
            <option value="ideal">ideal (none)</option>
            <option value="default">default</option>
            <option value="harsh">harsh</option>
          </select>
        </label>
        <label className="field narrow-ish">
          <span>Seed</span>
          <input type="number" min={0} step={1} value={seed} onChange={(e) => setSeed(e.target.value)} />
        </label>
        <button type="button" className="primary" onClick={run} disabled={!robot || isActive(shown?.state)} data-testid="run-odometry">
          Drive
        </button>
      </div>
      <ProblemBox problem={problem} />
      {shown?.state !== "succeeded" && <JobStatus job={shown} onCancel={job.cancel} />}
      {result && (
        <>
          <div className="analysis">
            <PathChart title="Where it went, and where each localizer thinks it went" paths={paths} start={[result.truth[0][0], result.truth[0][1]]} testid="odometry-chart" />
            <div className="charts one">
              {charts.map((c) => (
                <LineChart key={c.id} title={c.title} unit={c.unit} x={c.x} xUnit="s" series={c.series} digits={c.digits} sync="odometry" height={150} testid={`chart-${c.id}`} />
              ))}
            </div>
          </div>
          <table className="data" data-testid="odometry-table">
            <thead>
              <tr>
                <th>Localizer</th>
                <th className="num">Final error (in)</th>
                <th className="num">Final heading error (°)</th>
                <th className="num">Worst (in)</th>
              </tr>
            </thead>
            <tbody>
              {result.estimates.map((e) => (
                <tr key={e.name}>
                  <td>{e.name}</td>
                  <td className="num">{fixed(e.final_in, 2)}</td>
                  <td className="num">{fixed(e.final_deg, 2)}</td>
                  <td className="num">{fixed(e.worst_in, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
