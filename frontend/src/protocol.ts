// Generated from vexsim/ui/protocol.py: python -m vexsim.ui.protocol frontend/src/protocol.ts
// Don't edit by hand; a test fails when this file is stale.

export type ItemKind = "robot" | "field" | "scenario" | "program" | "project" | "input" | "log" | "invalid";
export type SessionState = "building" | "starting" | "running" | "paused" | "finished" | "error" | "stopped";
export type JobState = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type ServerMessage = SessionMessage | StatusMessage | SceneMessage | FrameMessage | OverlayMessage | ConsoleMessage | BuildMessage | ErrorMessage;
export type ClientCommand = SimpleCommand | StepCommand | SpeedCommand | InputCommand;

/** Everything `vexsim run` takes that decides what is simulated. Paths are as given: relative to the working directory for the CLI, to the workspace for the UI (`resolved` makes them absolute). `start` is x, y (inches) and heading (degrees, counter-clockwise from +x). */
export interface RunSpec {
  robot: string;
  program?: string | null;
  field?: string | null;
  mode?: "autonomous" | "driver" | "match" | "skills" | null;
  start?: [number, number, number];
  seed?: number;
  noise?: "ideal" | "default" | "harsh" | null;
  input?: string | null;
  env?: Record<string, string>;
  busy_timeout?: number;
}

export interface Issue {
  severity: "error" | "warning";
  location: string;
  message: string;
}

export interface AppInfo {
  version: string;
  workspace: string;
  workspace_name: string;
  python: string;
  platform: string;
}

export interface WorkspaceItem {
  kind: ItemKind;
  path: string;
  name: string;
  detail: string;
  problem: string;
}

export interface WorkspaceInfo {
  root: string;
  name: string;
  items: WorkspaceItem[];
}

export interface SessionInfo {
  id: string;
  spec: RunSpec;
  command: string;
  state: SessionState;
  message: string | null;
  mode: string;
  created: number;
}

export interface JobInfo {
  id: string;
  kind: string;
  title: string;
  state: JobState;
  log: string[];
  log_size: number;
  result: Record<string, unknown> | null;
  error: string | null;
  created: number;
  started: number | null;
  finished: number | null;
}

export interface StartSession {
  spec: RunSpec;
  replace?: boolean;
}

export interface StartJob {
  kind: "build";
  project: string;
}

/** Why a run can't start (HTTP 422). */
export interface RunProblem {
  error: string;
  issues: Issue[];
}

export interface WheelMount {
  name: string;
  x: number;
  y: number;
  heading: number;
  diameter: number;
  type: string;
}

export interface SensorMount {
  kind: "imu" | "distance" | "gps";
  port: number;
  x: number;
  y: number;
  heading: number;
}

export interface RobotScene {
  name: string;
  footprint: [number, number];
  wheels: WheelMount[];
  sensors: SensorMount[];
}

export interface CircleObstacle {
  shape: "circle";
  x: number;
  y: number;
  radius: number;
  color: string | null;
  solid: boolean;
}

export interface PolygonObstacle {
  shape: "polygon";
  points: [number, number][];
  color: string | null;
  solid: boolean;
}

export interface PieceStyle {
  radius: number;
  color: string | null;
}

export interface FieldScene {
  name: string;
  size: [number, number];
  obstacles: (CircleObstacle | PolygonObstacle)[];
  pieces: PieceStyle[];
}

export interface SessionMessage {
  type: "session";
  session: SessionInfo;
}

export interface StatusMessage {
  type: "status";
  state: SessionState;
  message: string | null;
  mode: string;
}

/** Sent when a run starts or restarts. */
export interface SceneMessage {
  type: "scene";
  robot: RobotScene;
  field: FieldScene;
  mode: string;
  start: [number, number, number];
  seed: number;
  spec: RunSpec;
  command: string;
}

/** Where everything is, about 60 times a second while running. */
export interface FrameMessage {
  type: "frame";
  t: number;
  phase: string;
  state: SessionState;
  speed: number | null;
  rate: number;
  pose: [number, number, number];
  estimate: [number, number, number] | null;
  speed_in_s: number;
  battery: [number, number];
  wheels: [number, number, number, number][];
  distance: Record<string, number | null>;
  pieces: [number, number][];
  contacts: [number, number][];
  motors: [number, number, number, boolean][];
  lcd: string[];
  controller_screen: string[];
}

/** A Python program's chassis motion: its path and target (when they change). */
export interface OverlayMessage {
  type: "overlay";
  path: [number, number][] | null;
  target: [number, number, number | null] | null;
}

export interface ConsoleMessage {
  type: "console";
  lines: string[];
}

export interface BuildMessage {
  type: "build";
  lines: string[];
}

export interface ErrorMessage {
  type: "error";
  message: string;
  issues: Issue[];
  traceback: string | null;
}

export interface SimpleCommand {
  cmd: "pause" | "resume" | "restart" | "stop";
}

/** Advance a paused run. */
export interface StepCommand {
  cmd: "step";
  ms?: number;
}

export interface SpeedCommand {
  cmd: "speed";
  value: number;
}

/** The virtual controller's sticks (-127 to 127) and pressed buttons. */
export interface InputCommand {
  cmd: "input";
  analog: Record<string, number>;
  digital: string[];
}
