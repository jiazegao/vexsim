import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { comboLabel, ecdfCharts, meanP95, percent, summaryOf, xUnitOf } from "../bench";
import { JobStatus, ProblemBox, ResultList } from "../components/JobPanel";
import { LineChart } from "../components/LineChart";
import { isActive, latest, useJob } from "../jobs";
import { fixed } from "../pose";
import type { BenchResult, ResultAbout, RunProblem, ScenarioInfo, WorkspaceInfo } from "../protocol";
import { when } from "../recording";

/** `vexsim bench`: a scenario run for many seeds with each localizer and controller it
 * compares; how often each combination succeeds and how well, and each one's worst trial
 * to watch on the field. */
export function BenchPage(props: {
  workspace: WorkspaceInfo | null;
  scenario: string;
  onScenario: (path: string) => void;
  onWorstCase: (result: string, file: string, robot: string, field: string) => Promise<void>;
}) {
  const scenarios = useMemo(() => props.workspace?.items.filter((i) => i.kind === "scenario") ?? [], [props.workspace]);
  const path = props.scenario || scenarios[0]?.path || "";
  const { onScenario } = props;
  useEffect(() => {
    if (path && !props.scenario) onScenario(path); // marked in the sidebar too
  }, [path, props.scenario, onScenario]);
  const [info, setInfo] = useState<ScenarioInfo | null>(null);
  const [scenarioProblem, setScenarioProblem] = useState<RunProblem | null>(null);
  const [seeds, setSeeds] = useState("20");
  const [firstSeed, setFirstSeed] = useState("0");
  const [workers, setWorkers] = useState("");
  const [localizers, setLocalizers] = useState<string[]>([]);
  const [controllers, setControllers] = useState<string[]>([]);
  const [worst, setWorst] = useState(true);
  const [problem, setProblem] = useState<RunProblem | null>(null);
  const [saved, setSaved] = useState<ResultAbout[]>([]);
  const [shown, setShown] = useState<BenchResult | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadSaved = useCallback(() => {
    api
      .results("bench")
      .then(setSaved)
      .catch(() => {});
  }, []);
  const open = useCallback(async (id: string) => {
    try {
      setShown(await api.result<BenchResult>("bench", id));
      setLoadError(null);
    } catch (error) {
      setLoadError(`Couldn't open that benchmark: ${(error as Error).message}`);
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
        const running = latest(jobs, "bench", true);
        if (running) follow(running.id);
      })
      .catch(() => {});
  }, [loadSaved, follow]);

  useEffect(() => {
    if (!path) return;
    let current = true;
    setInfo(null);
    setScenarioProblem(null);
    api
      .scenario(path)
      .then((found) => {
        if (!current) return;
        if ("problem" in found) setScenarioProblem(found.problem);
        else {
          setInfo(found.ok);
          setLocalizers(found.ok.localizers);
          setControllers(found.ok.controllers.map((c) => c.name));
        }
      })
      .catch((error: Error) => current && setScenarioProblem({ error: error.message, issues: [] }));
    return () => {
      current = false;
    };
  }, [path]);

  const running = isActive(job.job?.state);
  const count = Math.floor(Number(seeds));
  const valid = info && count >= 1 && count <= 1000 && localizers.length > 0 && controllers.length > 0 && Number(firstSeed) >= 0;
  const run = async () => {
    if (!info) return;
    const all = (chosen: string[], every: string[]) => (chosen.length === every.length ? null : chosen);
    setProblem(
      await job.start({
        kind: "bench",
        scenario: path,
        seeds: count,
        first_seed: Math.floor(Number(firstSeed) || 0),
        workers: workers ? Math.max(1, Math.floor(Number(workers))) : null,
        localizers: all(localizers, info.localizers),
        controllers: all(
          controllers,
          info.controllers.map((c) => c.name),
        ),
        worst_cases: worst,
      }),
    );
  };
  const toggle = (list: string[], name: string) => (list.includes(name) ? list.filter((n) => n !== name) : [...list, name]);
  // a PROS-project controller localizes itself: one combination; the others, one per localizer
  const combos = info ? info.controllers.filter((c) => controllers.includes(c.name)).reduce((n, c) => n + (c.kind === "pros" ? 1 : localizers.length), 0) : 0;
  const trials = count > 0 ? count * combos : 0;

  return (
    <div className="page" data-testid="bench-page">
      <header className="page-head">
        <h1>Bench</h1>
        <p className="muted">
          Run a scenario for many seeds with each localizer and controller it compares. Same as <code>vexsim bench</code>; results are kept in{" "}
          <code>.vexsim/bench/</code>.
        </p>
      </header>
      <div className="page-split">
        <div className="page-main">
          <section className="card">
            <div className="form-row">
              <label className="field wide">
                <span>Scenario</span>
                <select value={path} onChange={(e) => props.onScenario(e.target.value)} data-testid="bench-scenario">
                  {scenarios.length === 0 && <option value="">No benchmark scenarios in this workspace</option>}
                  {scenarios.map((s) => (
                    <option key={s.path} value={s.path}>
                      {s.name} ({s.path})
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {scenarioProblem && <ProblemBox problem={scenarioProblem} />}
            {info && (
              <div className="scenario" data-testid="scenario-info">
                <p>{info.description}</p>
                <dl className="facts">
                  <dt>Task</dt>
                  <dd>
                    {info.task}, within {info.time_limit_s} s
                  </dd>
                  <dt>Robot</dt>
                  <dd>
                    {info.robot}
                    {info.field ? ` on ${info.field}` : ""}
                    {info.noise ? `, ${info.noise} sensor noise` : ""}
                  </dd>
                  {info.disturbances.length > 0 && (
                    <>
                      <dt>What goes wrong</dt>
                      <dd>{info.disturbances.join("; ")}</dd>
                    </>
                  )}
                  {info.randomized.length > 0 && (
                    <>
                      <dt>Each seed varies</dt>
                      <dd>{info.randomized.join("; ")}</dd>
                    </>
                  )}
                </dl>
                <div className="form-row">
                  <fieldset className="choices">
                    <legend>Localizers</legend>
                    {info.localizers.map((name) => (
                      <label key={name}>
                        <input type="checkbox" checked={localizers.includes(name)} onChange={() => setLocalizers(toggle(localizers, name))} /> {name}
                      </label>
                    ))}
                  </fieldset>
                  <fieldset className="choices">
                    <legend>Controllers</legend>
                    {info.controllers.map((c) => (
                      <label key={c.name} title={c.project ? `PROS project ${c.project}` : c.kind}>
                        <input type="checkbox" checked={controllers.includes(c.name)} onChange={() => setControllers(toggle(controllers, c.name))} /> {c.name}
                      </label>
                    ))}
                  </fieldset>
                </div>
                <div className="form-row">
                  <label className="field narrow-ish">
                    <span>Seeds</span>
                    <input type="number" min={1} max={1000} value={seeds} onChange={(e) => setSeeds(e.target.value)} data-testid="bench-seeds" />
                  </label>
                  <label className="field narrow-ish">
                    <span>From seed</span>
                    <input type="number" min={0} value={firstSeed} onChange={(e) => setFirstSeed(e.target.value)} />
                  </label>
                  <label className="field narrow-ish" title="Worker processes (default: all but one of this computer's cores)">
                    <span>Workers</span>
                    <input type="number" min={1} max={64} placeholder={String(Math.max(1, (navigator.hardwareConcurrency || 2) - 1))} value={workers} onChange={(e) => setWorkers(e.target.value)} />
                  </label>
                  <label className="check" title="Run each combination's worst trial again with full telemetry, to watch on the field">
                    <input type="checkbox" checked={worst} onChange={(e) => setWorst(e.target.checked)} /> Keep the worst cases
                  </label>
                  <span className="spacer" />
                  <span className="muted small num">{trials > 0 ? `${trials} trials` : ""}</span>
                  {running ? (
                    <button type="button" onClick={job.cancel} data-testid="bench-cancel">
                      Cancel
                    </button>
                  ) : (
                    <button type="button" className="primary" onClick={run} disabled={!valid} data-testid="bench-run">
                      Run
                    </button>
                  )}
                </div>
              </div>
            )}
            {problem && <ProblemBox problem={problem} />}
            {job.job && job.job.state !== "succeeded" && <JobStatus job={job.job} onCancel={job.cancel} unit="trials" />}
          </section>
          {loadError && <ProblemBox problem={{ error: loadError, issues: [] }} />}
          {shown && <BenchView result={shown} onWorstCase={props.onWorstCase} />}
        </div>
        <aside className="page-side card">
          <h2>Benchmarks</h2>
          <ResultList
            results={saved}
            shown={shown?.about.id ?? null}
            onOpen={(about) => open(about.id)}
            onDelete={async (about) => {
              await api.deleteResult("bench", about.id).catch(() => {});
              if (shown?.about.id === about.id) setShown(null);
              loadSaved();
            }}
            empty="Benchmarks you run are kept here."
          />
        </aside>
      </div>
    </div>
  );
}

function BenchView(props: { result: BenchResult; onWorstCase: (result: string, file: string, robot: string, field: string) => Promise<void> }) {
  const { result } = props;
  const charts = useMemo(() => ecdfCharts(result), [result]);
  const [watching, setWatching] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const file = (name: string) => api.resultFileUrl("bench", result.about.id, name);
  return (
    <section className="card" data-testid="bench-result">
      <header className="result-head">
        <h2>{result.about.title}</h2>
        <span className="muted small">
          {when(result.about.created)} · {result.about.summary}
        </span>
        <span className="spacer" />
        {result.report && (
          <a className="button" href={file(result.report)} target="_blank" rel="noreferrer" data-testid="bench-report">
            Open the report
          </a>
        )}
        {result.files
          .filter((name) => name.endsWith(".csv") && !name.startsWith("worst_"))
          .map((name) => (
            <a key={name} className="button" href={file(name)} download>
              {name}
            </a>
          ))}
      </header>
      <table className="data" data-testid="bench-summary">
        <thead>
          <tr>
            <th>Localizer / controller</th>
            <th className="num">Succeeded</th>
            <th className="num" title="Mean / 95th percentile">
              Final error (in)
            </th>
            <th className="num" title="Mean / 95th percentile">
              Localization error (in)
            </th>
            <th className="num">Time (s)</th>
            <th className="num">Path RMS (in)</th>
          </tr>
        </thead>
        <tbody>
          {result.combos.map((c, i) => {
            const s = summaryOf(result, c);
            return (
              <tr key={comboLabel(c)}>
                <td>
                  {i < 8 && <span className="dot" style={{ background: `var(--series-${i + 1})` }} aria-hidden="true" />}
                  {comboLabel(c)}
                </td>
                <td className="num">
                  {percent(s?.success_rate)}
                  {s && s.timeouts > 0 ? <span className="muted small"> ({s.timeouts} timed out)</span> : null}
                </td>
                <td className="num">{meanP95(s?.stats.final_error_in)}</td>
                <td className="num">{meanP95(s?.stats.loc_error_final_in)}</td>
                <td className="num">{fixed(s?.stats.completion_time_s?.mean, 2)}</td>
                <td className="num">{fixed(s?.stats.path_rms_in?.mean, 2)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="muted small">
        Errors are the mean / the 95th percentile over {result.seeds} seeds. The charts show, for each value, the share of trials that did at
        least that well: further left and higher is better.
      </p>
      <div className="charts" data-testid="bench-charts">
        {charts.map((c) => (
          <LineChart key={c.id} title={c.title} unit={c.unit} x={c.x} xUnit={xUnitOf(c)} series={c.series} digits={2} refs={c.refs} stepped yRange={[0, 1]} testid={`ecdf-${c.id}`} />
        ))}
      </div>
      {result.worst.length > 0 && (
        <>
          <h3>Worst cases</h3>
          <ul className="worst" data-testid="worst-cases">
            {result.worst.map((w) => {
              const key = `${w.localizer}/${w.controller}`;
              return (
                <li key={key}>
                  <span>
                    {comboLabel(w)}: seed {w.seed}
                  </span>
                  <button
                    type="button"
                    className="small"
                    disabled={watching !== null}
                    onClick={async () => {
                      setWatching(key);
                      try {
                        await props.onWorstCase(result.about.id, w.file, result.scenario.robot, result.scenario.field ?? "");
                      } finally {
                        setWatching(null);
                      }
                    }}
                    data-testid="watch-worst"
                  >
                    {watching === key ? "Opening…" : "Watch on the field"}
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      )}
      <p className="command">
        <code>{result.command}</code>{" "}
        <button
          type="button"
          className="ghost small"
          onClick={() =>
            navigator.clipboard?.writeText(result.command).then(
              () => setCopied(true),
              () => {},
            )
          }
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </p>
    </section>
  );
}
