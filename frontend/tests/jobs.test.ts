import { describe, expect, it } from "vitest";
import { fraction, isActive, latest, merge } from "../src/jobs";
import type { JobInfo } from "../src/protocol";

function info(patch: Partial<JobInfo>): JobInfo {
  return {
    id: "job1",
    kind: "sweep",
    title: "Sweep",
    params: {},
    state: "running",
    log: [],
    log_size: 0,
    progress: null,
    items: [],
    items_size: 0,
    result: null,
    error: null,
    created: 1,
    started: 1,
    finished: null,
    ...patch,
  };
}

describe("following a job", () => {
  it("adds each poll's lines and items to what came before", () => {
    const first = merge(null, info({ log: ["a", "b"], items: [{ n: 1 }], progress: [1, 4] }), 0, 0);
    const second = merge(first, info({ log: ["c"], items: [{ n: 2 }, { n: 3 }], progress: [3, 4] }), 2, 1);
    expect(second.log).toEqual(["a", "b", "c"]);
    expect(second.items).toEqual([{ n: 1 }, { n: 2 }, { n: 3 }]);
    expect(fraction(second)).toBe(0.75);
    const done = merge(second, info({ state: "succeeded", result: { id: "r" } }), 3, 3);
    expect([done.state, done.result, done.log.length]).toEqual(["succeeded", { id: "r" }, 3]);
    const quiet = merge(second, info({ params: { again: true } }), 3, 3); // nothing new came
    expect([quiet.log, quiet.items, quiet.params]).toEqual([second.log, second.items, second.params]);
    expect(quiet.log === second.log && quiet.items === second.items && quiet.params === second.params).toBe(true);
    const other = merge(done, info({ id: "job2", log: ["x"] }), 3, 3);
    expect(other.log).toEqual(["x"]); // another job starts afresh
  });

  it("picks up the newest job of a kind, a running one first", () => {
    const jobs = [
      info({ id: "old", state: "succeeded", created: 5 }),
      info({ id: "running", state: "running", created: 2 }),
      info({ id: "bench", kind: "bench", created: 9 }),
    ];
    expect(latest(jobs, "sweep")?.id).toBe("running");
    expect(latest(jobs.slice(0, 1), "sweep", true)).toBeNull();
    expect(latest(jobs, "build")).toBeNull();
    expect([isActive("queued"), isActive("running"), isActive("failed"), isActive(null)]).toEqual([true, true, false, false]);
    expect(fraction(merge(null, info({}), 0, 0))).toBeNull();
  });
});
