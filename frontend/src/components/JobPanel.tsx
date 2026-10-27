import { useEffect, useState } from "react";
import type { JobView } from "../jobs";
import { fraction, isActive } from "../jobs";
import type { ResultAbout, RunProblem } from "../protocol";
import { when } from "../recording";

const STATES: Record<string, { label: string; chip: string }> = {
  queued: { label: "Waiting", chip: "state-running" },
  running: { label: "Running", chip: "state-running" },
  succeeded: { label: "Done", chip: "state-finished" },
  failed: { label: "Failed", chip: "state-error" },
  cancelled: { label: "Cancelled", chip: "" },
};

/** How long, as people say it. */
export function duration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${String(Math.round(seconds - minutes * 60)).padStart(2, "0")} s`;
}

/** Whole seconds since the page opened, while `on`: re-renders a clock. */
function useClock(on: boolean): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!on) return;
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, [on]);
  return now;
}

/** A job's state, progress and log, with a button to cancel it while it runs. */
export function JobStatus(props: { job: JobView | null; onCancel: () => void; unit?: string; log?: boolean }) {
  const { job } = props;
  const active = isActive(job?.state);
  const now = useClock(active);
  if (!job) return null;
  const state = STATES[job.state] ?? { label: job.state, chip: "" };
  const part = fraction(job);
  const elapsed = job.started ? (job.finished ?? Math.max(now, job.started)) - job.started : 0;
  const last = job.log.at(-1);
  return (
    <div className="job" data-testid="job" data-state={job.state}>
      <div className="job-row">
        <span className={`chip ${state.chip}`}>{state.label}</span>
        {job.progress && (
          <span className="num" data-testid="job-progress">
            {job.progress[0]} of {job.progress[1]} {props.unit ?? ""}
          </span>
        )}
        {part !== null && (
          <span className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(part * 100)}>
            <span style={{ width: `${part * 100}%` }} />
          </span>
        )}
        {job.started && <span className="muted small num">{duration(elapsed)}</span>}
        {active && last && <span className="muted small job-last">{last}</span>}
        <span className="spacer" />
        {active && (
          <button type="button" className="small" onClick={props.onCancel} data-testid="job-cancel">
            Cancel
          </button>
        )}
      </div>
      {job.state === "failed" && job.error && (
        <div className="problem" role="alert" data-testid="job-error">
          <strong>
            <span aria-hidden="true">⚠</span> {job.error}
          </strong>
        </div>
      )}
      {props.log !== false && job.log.length > 0 && (
        <details className="job-log">
          <summary>Log ({job.log.length} lines)</summary>
          <pre className="lines">{job.log.join("\n")}</pre>
        </details>
      )}
    </div>
  );
}

/** Saved results of a page's jobs, newest first: open one, or delete it. */
export function ResultList(props: { results: ResultAbout[]; shown: string | null; onOpen: (about: ResultAbout) => void; onDelete: (about: ResultAbout) => void; empty: string }) {
  const [confirming, setConfirming] = useState<string | null>(null);
  if (props.results.length === 0) return <p className="muted small">{props.empty}</p>;
  return (
    <ul className="results" data-testid="results">
      {props.results.map((about) => (
        <li key={about.id} className={props.shown === about.id ? "shown" : undefined}>
          <button type="button" className="item" onClick={() => props.onOpen(about)} aria-pressed={props.shown === about.id} data-testid="result">
            <span className="item-name">{about.title}</span>
            <span className="item-detail">
              {when(about.created)} · {about.summary}
            </span>
          </button>
          {confirming === about.id ? (
            <span className="run-actions">
              <button type="button" className="ghost small danger" onClick={() => props.onDelete(about)}>
                Delete
              </button>
              <button type="button" className="ghost small" onClick={() => setConfirming(null)}>
                Keep
              </button>
            </span>
          ) : (
            <button type="button" className="ghost small" title="Delete this result" onClick={() => setConfirming(about.id)}>
              ×
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Why something can't run: the error, and a config's issues where they are. */
export function ProblemBox(props: { problem: RunProblem | null }) {
  if (!props.problem) return null;
  return (
    <div className="problem" role="alert" data-testid="page-problem">
      <strong>
        <span aria-hidden="true">⚠</span> {props.problem.error}
      </strong>
      {props.problem.issues.length > 0 && (
        <ul>
          {props.problem.issues.map((issue, i) => (
            <li key={i}>
              <span className={`badge ${issue.severity}`}>{issue.severity}</span> <code>{issue.location || "(document)"}</code> {issue.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
