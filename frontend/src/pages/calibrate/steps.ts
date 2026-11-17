// A calibration session's five steps, each done, next or to do (phase 15.4): from the robot and
// field picked, the program written into its folder, the session's runs and its report. The
// Session tab shows them in a row above its cards; each links to its section of the guide.

import type { CalibrationSessionState, ProgramPlan } from "../../protocol";

export const GUIDE = "calibration_guide"; // the document the steps link into

/** The steps in order: its card on the page (by test id), its title, its section of the guide. */
export const SESSION_STEPS = [
  { key: "setup", card: "session-setup", title: "Robot and field", at: "3-describe-the-robot" },
  { key: "program", card: "session-program", title: "Plan and program", at: "4-make-the-program-and-put-it-on-the-robot" },
  { key: "collect", card: "session-collect", title: "Run and collect", at: "5-the-session" },
  { key: "runs", card: "session-runs", title: "Check the runs", at: "61-collect-the-logs" },
  { key: "fit", card: "session-fit", title: "Fit and apply", at: "62-fit-them" },
] as const;

export type SessionStepKey = (typeof SESSION_STEPS)[number]["key"];

export interface SessionStepState {
  key: SessionStepKey;
  state: "done" | "next" | "todo";
  detail: string;
}

/** Each step's state, and what it has to say for itself. */
export function sessionSteps(robot: string, field: string, plan: ProgramPlan | null, session: CalibrationSessionState | null): SessionStepState[] {
  const runs = session?.runs ?? [];
  const good = runs.filter((run) => run.use && run.quality === "good");
  const tests = plan?.tests.map((test) => test.key) ?? [...new Set(runs.map((run) => run.test))];
  const covered = tests.filter((test) => good.some((run) => run.test === test));
  const count = (n: number, what: string) => `${n} ${what}${n === 1 ? "" : "s"}`;
  const found: [SessionStepKey, boolean, string][] = [
    ["setup", !!robot && !!field, robot && field ? "Picked. Its config is what the tests build on: measure it in first" : "Pick the robot, and the field it's on"],
    ["program", plan !== null, plan ? `${count(plan.tests.length, "test")} planned, the program written` : "Where each test goes on your field, and the program that runs them"],
    ["collect", runs.length > 0, runs.length ? `${count(runs.length, "run")} collected${session?.practice ? " (practice)" : ""}` : "Run each test on the robot, then bring its logs in"],
    [
      "runs",
      tests.length > 0 && covered.length === tests.length,
      runs.length ? `${covered.length} of ${count(tests.length, "test")} ${covered.length === 1 ? "has" : "have"} a good run` : "Which runs are good enough to fit",
    ],
    ["fit", !!session?.report, session?.report ? `Fitted ${session.report.fitted}: read the report, then Apply` : "A few minutes: what each test measured, into the robot's config"],
  ];
  const next = found.find(([, done]) => !done)?.[0];
  return found.map(([key, done, detail]) => ({ key, state: done ? "done" : key === next ? "next" : "todo", detail }));
}
