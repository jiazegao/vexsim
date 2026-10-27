// Long tasks (builds, benchmarks, sweeps, calibrations, analyses) as a page follows them:
// polled while they run, their log and items (parts of the result that come early)
// fetched a piece at a time.

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "./api";
import type { JobInfo, JobState, RunProblem, StartJob } from "./protocol";

export const POLL_MS = 400;

export interface JobView {
  id: string;
  kind: string;
  title: string;
  params: Record<string, unknown>;
  state: JobState;
  log: string[];
  items: Record<string, unknown>[];
  progress: [number, number] | null;
  result: Record<string, unknown> | null;
  error: string | null;
  created: number;
  started: number | null;
  finished: number | null;
}

export function isActive(state: JobState | undefined | null): boolean {
  return state === "queued" || state === "running";
}

/** What's known of a job after a poll that asked for its log from `since` and its items
 * from `itemsSince` (what was known up to there, then what came). What didn't change stays
 * the same object, so what's drawn from it isn't drawn again. */
export function merge(known: JobView | null, info: JobInfo, since: number, itemsSince: number): JobView {
  const same = known !== null && known.id === info.id;
  const log = !same ? [...info.log] : info.log.length || since !== known.log.length ? [...known.log.slice(0, since), ...info.log] : known.log;
  const items = !same ? [...info.items] : info.items.length || itemsSince !== known.items.length ? [...known.items.slice(0, itemsSince), ...info.items] : known.items;
  return {
    id: info.id,
    kind: info.kind,
    title: info.title,
    params: same ? known.params : info.params,
    state: info.state,
    log,
    items,
    progress: info.progress ?? null,
    result: info.result ?? (same ? known.result : null),
    error: info.error ?? null,
    created: info.created,
    started: info.started ?? null,
    finished: info.finished ?? null,
  };
}

/** The newest job of a kind (to pick up after the page was reloaded), active ones first. */
export function latest(jobs: JobInfo[], kind: string, onlyActive = false): JobInfo | null {
  const mine = jobs.filter((j) => j.kind === kind && (!onlyActive || isActive(j.state)));
  mine.sort((a, b) => Number(isActive(b.state)) - Number(isActive(a.state)) || b.created - a.created);
  return mine[0] ?? null;
}

/** How far along a job is, as a fraction (null: it doesn't say). */
export function fraction(job: JobView | null): number | null {
  if (!job?.progress) return null;
  const [done, total] = job.progress;
  return total > 0 ? Math.min(1, done / total) : null;
}

export interface JobControl {
  job: JobView | null;
  /** Start a job and follow it; a problem (shown by the page) if it can't start. */
  start: (request: StartJob) => Promise<RunProblem | null>;
  /** Follow a job that's already there (one started before the page was reloaded). */
  follow: (id: string) => void;
  cancel: () => void;
  /** Forget the job (it goes on if it's running). */
  clear: () => void;
}

/** One job at a time, followed until it ends. `onEnd` hears how it ended. */
export function useJob(onEnd?: (job: JobView) => void): JobControl {
  const [job, setJob] = useState<JobView | null>(null);
  const current = useRef<JobView | null>(null);
  const following = useRef<string | null>(null);
  const ended = useRef(onEnd);
  ended.current = onEnd;

  const poll = useCallback(async (id: string) => {
    while (following.current === id) {
      const known = current.current?.id === id ? current.current : null;
      const since = known?.log.length ?? 0;
      const itemsSince = known?.items.length ?? 0;
      let next: JobView;
      try {
        next = merge(known, await api.job(id, since, itemsSince), since, itemsSince);
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 404)) {
          await new Promise((resolve) => setTimeout(resolve, POLL_MS * 3)); // the server may be busy
          continue;
        }
        if (!known) {
          following.current = null; // gone before it was ever seen
          return;
        }
        next = { ...known, state: "failed", error: "This job is gone: vexsim ui was restarted while it ran." };
      }
      if (following.current !== id) return;
      current.current = next;
      setJob(next);
      if (!isActive(next.state)) {
        following.current = null;
        ended.current?.(next);
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    }
  }, []);

  const follow = useCallback(
    (id: string) => {
      if (following.current === id) return;
      following.current = id;
      poll(id);
    },
    [poll],
  );

  const start = useCallback(
    async (request: StartJob): Promise<RunProblem | null> => {
      const started = await api.startJob(request).catch((error: Error) => ({ problem: { error: error.message, issues: [] } }));
      if ("problem" in started) return started.problem;
      const view = merge(null, started.ok, 0, 0);
      current.current = view;
      setJob(view);
      following.current = null;
      if (isActive(view.state)) follow(view.id);
      else ended.current?.(view);
      return null;
    },
    [follow],
  );

  const cancel = useCallback(() => {
    const id = current.current?.id;
    if (id && isActive(current.current?.state)) api.cancelJob(id).catch(() => {});
  }, []);

  const clear = useCallback(() => {
    following.current = null;
    current.current = null;
    setJob(null);
  }, []);

  useEffect(
    () => () => {
      following.current = null; // stop polling when the page goes
    },
    [],
  );

  return { job, start, follow, cancel, clear };
}
