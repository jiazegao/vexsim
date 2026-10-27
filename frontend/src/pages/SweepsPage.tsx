import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { FileLink } from "../components/FileLink";
import { JobStatus, ProblemBox, ResultList } from "../components/JobPanel";
import { LineChart } from "../components/LineChart";
import { isActive, latest, useJob } from "../jobs";
import { fixed } from "../pose";
import type { ResultAbout, RunConfiguration, RunProblem, Sweep, SweepResult, SweepTrial, SweepVariation, SweepsFile } from "../protocol";
import { when } from "../recording";
import type { SweepForm } from "../sweeps";
import { emptyForm, formToSweep, missingRuns, seedsOf, sweepTable, sweepToForm, traceCharts, trialCount, trialName, variationsOf } from "../sweeps";

const NEW = ""; // the picker's value for a sweep not saved yet

/** What's on show: a saved result, or the trials of the running sweep so far. */
interface Shown {
  sweep: Sweep;
  variations: SweepVariation[];
  trials: SweepTrial[];
  step: number;
  about: ResultAbout | null;
}

/** Sweeps: saved runs run many times over (each variation of their environment
 * variables, each seed, the robot put down a little off its start), and measured. */
export function SweepsPage(props: { configurations: RunConfiguration[]; onWatch: (trial: SweepTrial, name: string) => Promise<void> }) {
  const [file, setFile] = useState<SweepsFile | null>(null);
  const [picked, setPicked] = useState<string>(NEW);
  const [form, setForm] = useState<SweepForm>(emptyForm);
  const [workers, setWorkers] = useState("");
  const [filter, setFilter] = useState("");
  const [message, setMessage] = useState<{ text: string; bad: boolean } | null>(null);
  const [problem, setProblem] = useState<RunProblem | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [saved, setSaved] = useState<ResultAbout[]>([]);
  const [shown, setShown] = useState<Shown | null>(null);

  const loadSaved = useCallback(() => {
    api
      .results("sweeps")
      .then(setSaved)
      .catch(() => {});
  }, []);
  const open = useCallback(async (id: string) => {
    try {
      const result = await api.result<SweepResult>("sweeps", id);
      setShown({ sweep: result.sweep, variations: result.variations, trials: result.trials, step: result.trace_step_s, about: result.about });
    } catch (error) {
      setMessage({ text: `Couldn't open that sweep's result: ${(error as Error).message}`, bad: true });
    }
  }, []);
  const job = useJob((ended) => {
    loadSaved();
    if (ended.state === "succeeded" && typeof ended.result?.id === "string") open(ended.result.id);
  });
  const { follow } = job;

  const choose = useCallback((name: string, sweeps: Sweep[]) => {
    const sweep = sweeps.find((s) => s.name === name);
    setPicked(sweep ? sweep.name : NEW);
    setForm(sweep ? sweepToForm(sweep) : emptyForm());
    setConfirmDelete(false);
    setMessage(null);
  }, []);

  useEffect(() => {
    loadSaved();
    api
      .sweeps()
      .then((found) => {
        setFile(found);
        if (found.sweeps.length) choose(found.sweeps[0].name, found.sweeps);
      })
      .catch((error: Error) => setMessage({ text: error.message, bad: true }));
    api
      .jobs()
      .then((jobs) => {
        const running = latest(jobs, "sweep", true);
        if (running) follow(running.id);
      })
      .catch(() => {});
  }, [loadSaved, follow, choose]);

  const sweeps = file?.sweeps ?? [];
  const checked = formToSweep(form);
  const draft = "sweep" in checked ? checked.sweep : null;
  const savedSweep = sweeps.find((s) => s.name === picked) ?? null;
  const dirty = picked === NEW ? form.name.trim() !== "" || form.runs.length > 0 : JSON.stringify(draft) !== JSON.stringify(savedSweep && formToSweepOf(savedSweep));
  const missing = draft ? missingRuns(draft, props.configurations) : [];
  const running = isActive(job.job?.state);

  // a saved result on show, else the trials of the sweep run here so far (as they come,
  // and what a cancelled or failed one got through)
  const live = !shown && job.job && job.job.state !== "succeeded" && job.job.items.length > 0 ? job.job : null;
  const liveSweep = live ? (live.params.sweep as Sweep) : null;
  const liveTrials = live ? (live.items as unknown as SweepTrial[]) : null; // the same until more come
  const liveVariations = useMemo(() => (liveSweep ? variationsOf(liveSweep) : []), [liveSweep]);
  const view: Shown | null = useMemo(() => {
    if (liveTrials && liveSweep) return { sweep: liveSweep, variations: liveVariations, trials: liveTrials, step: 0.1, about: null };
    return shown;
  }, [liveTrials, liveSweep, liveVariations, shown]);

  const save = async () => {
    if (!draft) return;
    const others = sweeps.filter((s) => s.name !== picked && s.name !== draft.name);
    const at = sweeps.findIndex((s) => s.name === picked);
    const next = at < 0 ? [...others, draft] : [...others.slice(0, at), draft, ...others.slice(at)];
    if (picked !== draft.name && sweeps.some((s) => s.name.toLowerCase() === draft.name.toLowerCase())) {
      setMessage({ text: `There's already a sweep named ${draft.name}.`, bad: true });
      return;
    }
    try {
      const result = await api.saveSweeps(next);
      setFile(result);
      setPicked(draft.name);
      setForm(sweepToForm(result.sweeps.find((s) => s.name === draft.name) ?? draft));
      setMessage({ text: `Saved in ${result.file}.`, bad: false });
    } catch (error) {
      setMessage({ text: `Couldn't save: ${(error as Error).message}`, bad: true });
    }
  };
  const remove = async () => {
    try {
      const result = await api.saveSweeps(sweeps.filter((s) => s.name !== picked));
      setFile(result);
      choose(result.sweeps[0]?.name ?? NEW, result.sweeps);
      setMessage({ text: `Deleted from ${result.file}.`, bad: false });
    } catch (error) {
      setMessage({ text: `Couldn't delete: ${(error as Error).message}`, bad: true });
    }
  };
  const run = async () => {
    if (!draft) return;
    setShown(null);
    setProblem(await job.start({ kind: "sweep", sweep: draft, workers: workers ? Math.max(1, Math.floor(Number(workers))) : null }));
  };

  const runs = props.configurations.map((c) => c.name);
  const listed = runs.filter((name) => name.toLowerCase().includes(filter.trim().toLowerCase()));
  const set = (patch: Partial<SweepForm>) => setForm((f) => ({ ...f, ...patch }));

  return (
    <div className="page" data-testid="sweeps-page">
      <header className="page-head">
        <h1>Sweeps</h1>
        <p className="muted">
          Run saved runs many times over: once per value of the environment variables you vary and per seed, with the robot put down a little
          off its start each time, as a hand does. Each run is measured by how far the robot code's pose is from the truth. Sweeps are kept in{" "}
          <code>{file?.file ?? ".vexsim/sweeps.yaml"}</code>, results in <code>.vexsim/sweeps/</code>.
        </p>
      </header>
      {file?.error && <ProblemBox problem={{ error: file.error, issues: [] }} />}
      <div className="page-split">
        <div className="page-main">
          <section className="card" data-testid="sweep-editor">
            <div className="form-row">
              <label className="field wide">
                <span>Sweep</span>
                <select value={picked} onChange={(e) => choose(e.target.value, sweeps)} data-testid="sweep-pick">
                  {sweeps.map((s) => (
                    <option key={s.name} value={s.name}>
                      {s.name}
                    </option>
                  ))}
                  <option value={NEW}>New sweep…</option>
                </select>
              </label>
              <label className="field wide">
                <span>Name</span>
                <input value={form.name} onChange={(e) => set({ name: e.target.value })} maxLength={80} data-testid="sweep-name" />
              </label>
            </div>
            <label className="field">
              <span>Description</span>
              <input value={form.description} onChange={(e) => set({ description: e.target.value })} />
            </label>
            <fieldset className="choices runs-choice">
              <legend>
                Saved runs <span className="muted small">({form.runs.length} of {runs.length})</span>
              </legend>
              <div className="choice-tools">
                <input placeholder="Filter" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter the saved runs" />
                <button type="button" className="ghost small" onClick={() => set({ runs: [...new Set([...form.runs, ...listed])] })}>
                  All
                </button>
                <button type="button" className="ghost small" onClick={() => set({ runs: form.runs.filter((r) => !listed.includes(r)) })}>
                  None
                </button>
              </div>
              <div className="choice-list">
                {listed.map((name) => (
                  <label key={name}>
                    <input
                      type="checkbox"
                      checked={form.runs.includes(name)}
                      onChange={() => set({ runs: form.runs.includes(name) ? form.runs.filter((r) => r !== name) : runs.filter((r) => r === name || form.runs.includes(r)) })}
                    />{" "}
                    {name}
                  </label>
                ))}
                {missing.map((name) => (
                  <label key={name} className="missing" title="Not in .vexsim/launch.yaml any more">
                    <input type="checkbox" checked onChange={() => set({ runs: form.runs.filter((r) => r !== name) })} /> {name} <span className="badge warning">not saved</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <fieldset className="vary">
              <legend>Vary environment variables</legend>
              {form.vary.map((row, i) => (
                <div className="form-row" key={i}>
                  <input placeholder="VARIABLE" value={row.key} onChange={(e) => set({ vary: form.vary.map((r, j) => (j === i ? { ...r, key: e.target.value } : r)) })} aria-label="Variable" data-testid="vary-key" />
                  <input
                    className="grow"
                    placeholder="values, separated by commas"
                    value={row.values}
                    onChange={(e) => set({ vary: form.vary.map((r, j) => (j === i ? { ...r, values: e.target.value } : r)) })}
                    aria-label="Values"
                    data-testid="vary-values"
                  />
                  <button type="button" className="ghost small" onClick={() => set({ vary: form.vary.filter((_, j) => j !== i) })} aria-label="Remove">
                    ×
                  </button>
                </div>
              ))}
              <button type="button" className="ghost small" onClick={() => set({ vary: [...form.vary, { key: "", values: "" }] })} data-testid="vary-add">
                Add a variable
              </button>
            </fieldset>
            <div className="form-row">
              <label className="field narrow-ish">
                <span>Seeds</span>
                <input type="number" min={1} max={1000} value={form.seeds} onChange={(e) => set({ seeds: e.target.value })} data-testid="sweep-seeds" />
              </label>
              <label className="field narrow-ish">
                <span>From seed</span>
                <input type="number" min={0} value={form.firstSeed} onChange={(e) => set({ firstSeed: e.target.value })} />
              </label>
              <fieldset className="start" title="How far off its start a hand puts the robot down: standard deviations">
                <legend>Placement error (σ)</legend>
                {(["x", "y", "heading"] as const).map((axis, i) => (
                  <label key={axis}>
                    {axis}
                    <input
                      type="number"
                      min={0}
                      step={0.1}
                      value={form.placement[i]}
                      onChange={(e) => set({ placement: form.placement.map((v, j) => (j === i ? e.target.value : v)) as [string, string, string] })}
                    />
                    {axis === "heading" ? "°" : "in"}
                  </label>
                ))}
              </fieldset>
              <label className="field narrow-ish" title="Each run stops after this long if its program hasn't finished">
                <span>Time limit (s)</span>
                <input type="number" min={1} max={3600} value={form.maxSeconds} onChange={(e) => set({ maxSeconds: e.target.value })} data-testid="sweep-seconds" />
              </label>
              <label className="field narrow-ish" title="Worker processes (default: all but one of this computer's cores)">
                <span>Workers</span>
                <input type="number" min={1} max={64} placeholder={String(Math.max(1, (navigator.hardwareConcurrency || 2) - 1))} value={workers} onChange={(e) => setWorkers(e.target.value)} />
              </label>
            </div>
            <div className="form-row actions-row">
              <span className={`small${draft ? " muted" : " bad"}`} data-testid="sweep-count">
                {"error" in checked ? checked.error : countText(draft!)}
              </span>
              <span className="spacer" />
              {picked !== NEW &&
                (confirmDelete ? (
                  <>
                    <button type="button" className="danger" onClick={remove}>
                      Delete {picked}
                    </button>
                    <button type="button" onClick={() => setConfirmDelete(false)}>
                      Keep
                    </button>
                  </>
                ) : (
                  <button type="button" className="ghost" onClick={() => setConfirmDelete(true)}>
                    Delete
                  </button>
                ))}
              <button type="button" disabled={!dirty} onClick={() => choose(picked, sweeps)}>
                Revert
              </button>
              <button type="button" disabled={!draft || !dirty} onClick={save} data-testid="sweep-save">
                Save
              </button>
              {running ? (
                <button type="button" onClick={job.cancel}>
                  Cancel
                </button>
              ) : (
                <button type="button" className="primary" disabled={!draft || missing.length > 0} onClick={run} data-testid="sweep-run">
                  Run
                </button>
              )}
            </div>
            {message && (
              <p className={`small ${message.bad ? "bad" : "muted"}`} role={message.bad ? "alert" : undefined}>
                {message.text}
              </p>
            )}
            {problem && <ProblemBox problem={problem} />}
            {job.job && job.job.state !== "succeeded" && <JobStatus job={job.job} onCancel={job.cancel} unit="trials" />}
          </section>
          {view && <SweepView shown={view} live={!!live && running} onWatch={props.onWatch} />}
        </div>
        <aside className="page-side card">
          <h2>Results</h2>
          <ResultList
            results={saved}
            shown={shown?.about?.id ?? null}
            onOpen={(about) => open(about.id)}
            onDelete={async (about) => {
              await api.deleteResult("sweeps", about.id).catch(() => {});
              if (shown?.about?.id === about.id) setShown(null);
              loadSaved();
            }}
            empty="Sweeps you run are kept here."
          />
        </aside>
      </div>
    </div>
  );
}

function plural(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

/** How many trials a sweep makes: runs × variations × seeds. */
export function countText(sweep: Sweep): string {
  const variations = variationsOf(sweep).length;
  return `${plural(sweep.runs.length, "run")} × ${plural(variations, "variation")} × ${plural(sweep.seeds ?? 3, "seed")} = ${plural(trialCount(sweep), "trial")}`;
}

/** A saved sweep as the form would give it back (for telling whether the form changed). */
function formToSweepOf(sweep: Sweep): Sweep | null {
  const checked = formToSweep(sweepToForm(sweep));
  return "sweep" in checked ? checked.sweep : null;
}

function SweepView(props: { shown: Shown; live: boolean; onWatch: (trial: SweepTrial, name: string) => Promise<void> }) {
  const { sweep, variations, trials, step, about } = props.shown;
  const labels = useMemo(() => variations.map((v) => v.label), [variations]);
  const table = useMemo(() => sweepTable(trials, sweep.runs, labels), [trials, sweep.runs, labels]);
  const seeds = useMemo(() => seedsOf(trials), [trials]);
  const [seed, setSeed] = useState<number | null>(null);
  const shownSeed = seed !== null && seeds.includes(seed) ? seed : (seeds[0] ?? sweep.first_seed ?? 0);
  const { charts, top } = useMemo(() => traceCharts(trials, sweep.runs, labels, shownSeed, step), [trials, sweep.runs, labels, shownSeed, step]);
  const yRange = useMemo((): [number, number] => [0, top], [top]);
  const [watching, setWatching] = useState<number | null>(null);
  const varied = labels.length > 1;
  const sorted = useMemo(() => [...trials].sort((a, b) => a.index - b.index), [trials]);
  const failed = trials.filter((t) => t.error);

  const watch = async (trial: SweepTrial) => {
    setWatching(trial.index);
    try {
      await props.onWatch(trial, trialName(trial, varied));
    } finally {
      setWatching(null);
    }
  };

  return (
    <section className="card" data-testid="sweep-result">
      <header className="result-head">
        <h2>{sweep.name}</h2>
        <span className="muted small">{about ? `${when(about.created)} · ${about.summary}` : props.live ? `running: ${trials.length} of ${trialCount(sweep)} trials done` : ""}</span>
        <span className="spacer" />
        {about && (
          <FileLink className="button" href={api.resultFileUrl("sweeps", about.id, "trials.csv")} name="trials.csv">
            trials.csv
          </FileLink>
        )}
      </header>
      <p className="muted small">
        Position error between the robot code's pose and the truth (inches): mean / max / at the end, averaged over the seeds
        {varied ? "; the lowest mean in each row in bold" : ""}.
      </p>
      <div className="table-scroll">
        <table className="data sweep-table" data-testid="sweep-table">
          <thead>
            <tr>
              <th>Saved run</th>
              <th className="num">Time (s)</th>
              {labels.map((label, i) => (
                <th key={label} className="num">
                  {i < 8 && <span className="dot" style={{ background: `var(--series-${i + 1})` }} aria-hidden="true" />}
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.map((row) => (
              <tr key={row.run}>
                <td>{row.run}</td>
                <td className="num">{fixed(row.seconds, 1)}</td>
                {row.cells.map((cell, i) => (
                  <td key={labels[i]} className={`num${row.best === i ? " best" : ""}`}>
                    {cell.trials === 0 ? (
                      <span className="muted">…</span>
                    ) : (
                      <>
                        {fixed(cell.mean, 1)} / {fixed(cell.max, 1)} / {fixed(cell.final, 1)}
                        {cell.unfinished > 0 && <span className="muted small"> ({cell.unfinished} unfinished)</span>}
                      </>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {failed.length > 0 && (
        <div className="problem" role="alert">
          <strong>
            <span aria-hidden="true">⚠</span> {failed.length} trial{failed.length === 1 ? "" : "s"} failed: {failed[0].error}
          </strong>
        </div>
      )}
      <div className="form-row">
        <h3>Error over time</h3>
        <label className="field narrow-ish inline">
          <span>Seed</span>
          <select value={shownSeed} onChange={(e) => setSeed(Number(e.target.value))} data-testid="sweep-seed">
            {seeds.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="charts small-multiples" data-testid="sweep-charts">
        {charts.map((c) => (
          <LineChart key={c.id} title={c.title} unit={c.unit} x={c.x} xUnit="s" series={c.series} digits={2} yRange={yRange} sync="sweep" height={140} />
        ))}
      </div>
      <details className="trials">
        <summary>
          Every trial ({trials.length}){" "}
          <span className="muted small">— watch one on the field: it runs again exactly, with its seed and placement</span>
        </summary>
        <div className="table-scroll">
          <table className="data" data-testid="sweep-trials">
            <thead>
              <tr>
                <th>Saved run</th>
                {varied && <th>Variation</th>}
                <th className="num">Seed</th>
                <th>Finished</th>
                <th className="num">Time (s)</th>
                <th className="num">Mean (in)</th>
                <th className="num">Max (in)</th>
                <th className="num">Final (in)</th>
                <th className="num">Max heading (°)</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {sorted.map((t) => (
                <tr key={t.index}>
                  <td>{t.run}</td>
                  {varied && <td>{t.variation}</td>}
                  <td className="num">{t.seed}</td>
                  <td>{t.error ? <span className="bad" title={t.error}>failed</span> : t.finished ? "yes" : "no"}</td>
                  <td className="num">{fixed(t.seconds, 1)}</td>
                  <td className="num">{fixed(t.mean_in, 2)}</td>
                  <td className="num">{fixed(t.max_in, 2)}</td>
                  <td className="num">{fixed(t.final_in, 2)}</td>
                  <td className="num">{fixed(t.max_deg, 1)}</td>
                  <td>
                    <button type="button" className="small" disabled={watching !== null} onClick={() => watch(t)} data-testid="watch-trial">
                      {watching === t.index ? "Starting…" : "Watch"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
