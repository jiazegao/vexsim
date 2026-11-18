// What the app's shell (App.tsx) and its parts (the files beside this one) share: the pages,
// what's kept in the browser, and which of a run's states mean what.

import type { CalibrateTab } from "../pages/CalibratePage";
import type { Editor } from "../problems";
import { EDITORS } from "../problems";
import type { RunForm } from "../runform";
import type { Pose } from "../startpose";
import type { Theme } from "../theme";

export type PageId = "simulate" | "sweeps" | "bench" | "calibrate" | "analyze" | "build" | "guide";
export const PAGES: [PageId, string, string][] = [
  ["simulate", "Simulate", "Run a robot on the field"],
  ["sweeps", "Sweeps", "Run saved runs many times over, and measure them"],
  ["bench", "Bench", "Benchmark scenarios: localizers and controllers over many seeds"],
  ["calibrate", "Calibrate", "Fit the simulator to a real robot's log"],
  ["analyze", "Analyze", "Motor curves, drift and odometry"],
  ["build", "Build", "Build PROS projects; check the compiler"],
  ["guide", "Guide", "vexsim's guides: using it, calibrating to your robot step by step, programming"],
];
export const PAGE_IDS: readonly string[] = PAGES.map(([id]) => id);

export const THEME_LABEL: Record<Theme, string> = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" };
export const EDITOR_KEY = "vexsim.editor";
export const ON_SAVE_KEY = "vexsim.runOnSave";
export const FIRST_RUN_KEY = "vexsim.firstRun:"; // and the folder: its "Start here" was put away
export const STARTABLE: readonly string[] = ["running", "paused", "finished", "error", "stopped"]; // Restart can start it again
export const EDITED: readonly string[] = ["robot", "field", "invalid"]; // what opens in the config editor
export const BUSY: readonly string[] = ["building", "starting", "running", "paused"]; // the run is on the field
export const SEEK_S = 0.5; // the arrow keys move a recorded run this far (Shift: ten times)

export function loadEditor(): Editor {
  try {
    const saved = localStorage.getItem(EDITOR_KEY);
    if (saved && saved in EDITORS) return saved as Editor;
  } catch {
    // storage off: the default
  }
  return "vscode";
}

export function loadRunOnSave(): boolean {
  try {
    return localStorage.getItem(ON_SAVE_KEY) === "on";
  } catch {
    return false; // storage off: not remembered
  }
}

/** The form's start pose, when it's three numbers. */
export function startOf(form: RunForm): Pose | null {
  const pose = [form.x, form.y, form.heading].map((text) => (text.trim() === "" ? NaN : Number(text)));
  return pose.every(Number.isFinite) ? (pose as Pose) : null;
}

/** What the Calibrate page has picked: its robot, a log, a project, a session, and its tab. */
export interface Calibration {
  robot: string;
  log: string;
  project: string;
  session: string;
  tab: CalibrateTab;
}
