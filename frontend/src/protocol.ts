// Generated from vexsim/ui/protocol.py: python -m vexsim.ui.protocol frontend/src/protocol.ts
// Don't edit by hand; a test fails when this file is stale.

export type ItemKind = "robot" | "field" | "scenario" | "program" | "project" | "input" | "log" | "invalid";
export type SessionState = "building" | "starting" | "running" | "paused" | "finished" | "error" | "stopped";
export type JobState = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type ServerMessage = SessionMessage | StatusMessage | SceneMessage | FrameMessage | OverlayMessage | ConsoleMessage | BuildMessage | ErrorMessage | RecordedMessage;
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
  run_id: string | null;
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
  name?: string | null;
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

export interface PreviewRequest {
  robot: string;
  field?: string | null;
}

/** A robot and a field before any run, to show them and drag the robot to its start. */
export interface Preview {
  robot: RobotScene;
  field: FieldScene;
  pieces: [number, number][];
}

/** A named run, kept in the workspace's .vexsim/launch.yaml. */
export interface RunConfiguration {
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
  name: string;
}

export interface RunConfigurations {
  file: string;
  configurations: RunConfiguration[];
  error?: string | null;
}

export interface SaveConfigurations {
  configurations: RunConfiguration[];
}

export interface WheelMount {
  name: string;
  x: number;
  y: number;
  heading: number;
  diameter: number;
  type: string;
  roller: number;
}

export interface SensorMount {
  kind: "imu" | "distance" | "gps";
  port: number;
  x: number;
  y: number;
  heading: number;
}

export interface MechanismMount {
  name: string;
  range: [number, number] | null;
}

export interface RobotScene {
  name: string;
  footprint: [number, number];
  wheels: WheelMount[];
  sensors: SensorMount[];
  mechanisms: MechanismMount[];
}

export interface CircleObstacle {
  shape: "circle";
  name: string;
  x: number;
  y: number;
  radius: number;
  color: string | null;
  solid: boolean;
}

export interface PolygonObstacle {
  shape: "polygon";
  name: string;
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

/** What doesn't move in a run: the robot and field, and what was asked for. */
export interface Scene {
  robot: RobotScene;
  field: FieldScene;
  mode: string;
  start: [number, number, number];
  seed: number;
  spec: RunSpec;
  command: string;
  run_id: string | null;
}

/** Sent when a run starts or restarts. */
export interface SceneMessage {
  robot: RobotScene;
  field: FieldScene;
  mode: string;
  start: [number, number, number];
  seed: number;
  spec: RunSpec;
  command: string;
  run_id: string | null;
  type: "scene";
}

export interface ControllerState {
  analog: Record<string, number>;
  digital: string[];
}

/** Where everything is at one moment (a recorded run's tape keeps these). */
export interface FrameState {
  t: number;
  phase: string;
  pose: [number, number, number];
  estimate: [number, number, number] | null;
  speed_in_s: number;
  battery: [number, number];
  wheels: [number, number, number, number, number][];
  distance: Record<string, number | null>;
  pieces: [number, number][];
  contacts: [number, number][];
  motors: [number, number, number, boolean][];
  controller: ControllerState;
  imu: Record<string, [number, number] | null>;
  gps: Record<string, [number, number, number, number, boolean] | null>;
  mechanisms: number[];
  period_left: number | null;
}

/** Where everything is, about 60 times a second while running. */
export interface FrameMessage {
  t: number;
  phase: string;
  pose: [number, number, number];
  estimate: [number, number, number] | null;
  speed_in_s: number;
  battery: [number, number];
  wheels: [number, number, number, number, number][];
  distance: Record<string, number | null>;
  pieces: [number, number][];
  contacts: [number, number][];
  motors: [number, number, number, boolean][];
  controller: ControllerState;
  imu: Record<string, [number, number] | null>;
  gps: Record<string, [number, number, number, number, boolean] | null>;
  mechanisms: number[];
  period_left: number | null;
  type: "frame";
  state: SessionState;
  speed: number | null;
  rate: number;
  lcd: string[];
  controller_screen: string[];
}

/** A Python program's chassis motion: its path and target. */
export interface Overlay {
  path: [number, number][] | null;
  target: [number, number, number | null] | null;
}

/** Sent when the motion's path or target changes. */
export interface OverlayMessage {
  path: [number, number][] | null;
  target: [number, number, number | null] | null;
  type: "overlay";
}

/** How far the robot code's pose was from the true one (see `Recorder.pose_error`). */
export interface PoseErrorSummary {
  mean_in: number;
  max_in: number;
  max_at_s: number;
  final_in: number;
  mean_deg: number;
  max_deg: number;
}

/** A recorded run, as its run.json has it. */
export interface RunRecord {
  id: string;
  name: string;
  created: number;
  spec: RunSpec;
  command: string;
  mode: string;
  robot: string;
  field: string;
  duration: number;
  ended: "finished" | "stopped" | "restarted" | "error";
  message: string | null;
  pose_error: PoseErrorSummary | null;
  samples: number;
  kept?: boolean;
}

/** A run ended (finished, stopped, restarted, failed) and was recorded. */
export interface RecordedMessage {
  type: "recorded";
  run: RunRecord;
}

/** When what changes seldom changed: [time, the new value]. */
export interface TapeEvents {
  overlay: [number, Overlay][];
  lcd: [number, string[]][];
  controller_screen: [number, string[]][];
}

/** A recorded run to scrub: its scene, and a frame every 50 ms of simulated time. */
export interface Tape {
  scene: Scene;
  samples: FrameState[];
  events: TapeEvents;
}

/** A run's 10 ms telemetry log as columns (at most 5000 rows), for plots: the log's columns (time_s, x_in, motor1_current_a, ...) plus error_in and error_deg, the robot code's pose error; and when each phase begins. */
export interface Telemetry {
  columns: Record<string, (number | null)[]>;
  phases: [number, string][];
}

export interface RunDetails {
  run: RunRecord;
  console: string[];
}

export interface RunUpdate {
  kept?: boolean | null;
  name?: string | null;
}

/** Open a telemetry log (vexsim run --record) from the workspace, drawn with a robot. */
export interface ReplayRequest {
  log: string;
  robot: string;
  field?: string | null;
}

export interface Replay {
  name: string;
  tape: Tape;
  telemetry: Telemetry;
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
