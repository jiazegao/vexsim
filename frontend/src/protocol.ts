// Generated from vexsim/ui/protocol.py: python -m vexsim.ui.protocol frontend/src/protocol.ts
// Don't edit by hand; a test fails when this file is stale.

export type ItemKind = "robot" | "field" | "scenario" | "program" | "project" | "route" | "input" | "log" | "robotlog" | "mcllog" | "invalid";
export type SessionState = "building" | "starting" | "running" | "paused" | "finished" | "error" | "stopped";
export type JobState = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type ConfigKind = "robot" | "field";
export type ResultKind = "bench" | "sweeps" | "calibrations";
export type DrawColor = "violet" | "blue" | "orange" | "aqua" | "yellow" | "magenta" | "green" | "red" | "ink" | "muted";
export type Shape = ["point", number, number, DrawColor, number] | ["line", number, number, number, number, DrawColor] | ["circle", number, number, number, DrawColor] | ["ellipse", number, number, number, number, number, DrawColor] | ["pose", number, number, number, DrawColor] | ["text", number, number, string, DrawColor];
export type StartJob = BuildJob | DoctorJob | MotorCurvesJob | DriftJob | OdometryJob | BenchJob | CalibrateJob | SweepJob | RouteJob;
export type ServerMessage = SessionMessage | StatusMessage | SceneMessage | FrameMessage | OverlayMessage | DrawingsMessage | FollowingMessage | ConsoleMessage | BuildMessage | ErrorMessage | RecordedMessage;
export type ClientCommand = SimpleCommand | StepCommand | SpeedCommand | InputCommand;

/** A virtual driver that drives the robot along a log's path (`vexsim.runtime.follow`): the program's driver control, through its own sticks and drive curve. */
export interface Follow {
  log?: string | null;
  sticks?: "tank" | "arcade";
  curve?: [number, number, number] | null;
}

/** Everything `vexsim run` takes that decides what is simulated. Paths are as given: relative to the working directory for the CLI, to the workspace for the UI (`resolved` makes them absolute). `start` is x, y (inches) and heading (degrees, counter-clockwise from +x). */
export interface RunSpec {
  robot: string;
  program?: string | null;
  routine?: string | null;
  route?: string | null;
  field?: string | null;
  mode?: "autonomous" | "driver" | "match" | "skills" | null;
  start?: [number, number, number];
  seed?: number;
  noise?: "ideal" | "default" | "harsh" | null;
  input?: string | null;
  follow?: Follow | null;
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
  pages: number;
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

/** A long task (`GET /api/jobs/{id}?since=n&items_since=k`): its log from line n on, its items (parts of its result that came early) from k on, and once it's done, its result. Listed jobs (`GET /api/jobs`) carry neither, nor their result. */
export interface JobInfo {
  id: string;
  kind: string;
  title: string;
  params: Record<string, unknown>;
  state: JobState;
  log: string[];
  log_size: number;
  progress: [number, number] | null;
  items: Record<string, unknown>[];
  items_size: number;
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

/** `vexsim build`. */
export interface BuildJob {
  kind: "build";
  project: string;
  debug?: boolean;
}

/** `vexsim doctor`: is there a compiler that builds and runs PROS projects? */
export interface DoctorJob {
  kind: "doctor";
}

/** `vexsim motor-curves`; its result is a `MotorCurves`. */
export interface MotorCurvesJob {
  kind: "motor_curves";
  cartridge?: "red" | "green" | "blue";
  supply_voltage?: number;
  points?: number;
}

/** `vexsim drift`; its result is a `Drift`. */
export interface DriftJob {
  kind: "drift";
  robot: string;
  left?: number;
  right?: number;
  seconds?: number;
  lateral_mu?: number[];
}

/** `vexsim odometry`; its result is an `Odometry`. */
export interface OdometryJob {
  kind: "odometry";
  robot: string;
  script?: "gentle" | "aggressive";
  noise?: "ideal" | "default" | "harsh" | null;
  seed?: number;
}

/** `vexsim bench`; its result is the id of a `BenchResult`. */
export interface BenchJob {
  kind: "bench";
  scenario: string;
  seeds?: number;
  first_seed?: number;
  workers?: number | null;
  localizers?: string[] | null;
  controllers?: string[] | null;
  worst_cases?: boolean;
}

/** `vexsim calibrate`; its result is the id of a `CalibrationResult`. */
export interface CalibrateJob {
  kind: "calibrate";
  robot: string;
  log: string;
  fit?: string[] | null;
  compare_only?: boolean;
  max_iterations?: number;
  workers?: number | null;
}

/** A sweep, as .vexsim/sweeps.yaml keeps it. */
export interface Sweep {
  name: string;
  description?: string;
  runs: string[];
  vary?: Record<string, string[]>;
  seeds?: number;
  first_seed?: number;
  placement_sd?: [number, number, number];
  max_seconds?: number;
}

/** A sweep (saved or not); its result is the id of a `SweepResult`. */
export interface SweepJob {
  kind: "sweep";
  sweep: Sweep;
  workers?: number | null;
}

/** A route run headless (`vexsim route run`); its result is a `RouteRun`. */
export interface RouteJob {
  kind: "route";
  route: string;
  seed?: number;
  noise?: "ideal" | "default" | "harsh" | null;
}

/** Where a step of a route ended in a run (LemLib's convention: x, y in inches, theta in degrees clockwise from +y); times are seconds into the autonomous period. */
export interface RouteStepEnd {
  number: number;
  kind: string;
  label: string;
  started_s: number | null;
  ended_s: number | null;
  duration_s: number | null;
  pose: [number, number, number] | null;
  lemlib: [number, number, number] | null;
  timed_out: boolean | null;
}

/** A route run headless: where each step ended. */
export interface RouteRun {
  name: string;
  error: string | null;
  started: boolean;
  finished: boolean;
  ended_s: number | null;
  period_s: number;
  steps: RouteStepEnd[];
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
  routine?: string | null;
  route?: string | null;
  field?: string | null;
  mode?: "autonomous" | "driver" | "match" | "skills" | null;
  start?: [number, number, number];
  seed?: number;
  noise?: "ideal" | "default" | "harsh" | null;
  input?: string | null;
  follow?: Follow | null;
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
  outline?: [number, number][][] | null;
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

/** What the robot code has drawn (`vexsim::draw_*`, `bot.draw`), by layer: sent when it changes. */
export interface DrawingsMessage {
  type: "drawings";
  layers: Record<string, Shape[]>;
}

/** A run that follows a log (`RunSpec.follow`) began to: `start` is the moment of the run that goes with the log's first update. */
export interface FollowingMessage {
  type: "following";
  start: number;
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
  follow_start?: number | null;
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
  drawings?: [number, Record<string, Shape[]>][];
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

/** How a robot's MCL ran, by its log. */
export interface MclLogSummary {
  updates: number;
  duration_s: number;
  sensors: number;
  particles: number;
  start: [number, number, number];
  interval_ms: [number, number, number] | null;
  no_reading_pct: number | null;
  spread_in: [number, number];
}

/** A robot's MCL log (`vexsim.mcllog`), to play on the field: where its code thought it was, update by update, and what it saw, drawn as the robot code's drawings are. There's no truth: only the real robot knew where it was. */
export interface MclLogTape {
  name: string;
  path: string;
  summary: MclLogSummary;
  times: number[];
  estimate: [number, number, number][];
  drawings: [number, Record<string, Shape[]>][];
}

/** A PROS project's routine (`vexsim.bridge.routines`): a function its include/custom/auton.hpp declares that takes no arguments. */
export interface RoutineInfo {
  name: string;
  line: number;
  source: string | null;
  start: [number, number, number] | null;
}

export interface NotRoutineInfo {
  name: string;
  line: number;
  why: string;
}

/** A route in a PROS project's routes/ folder (`vexsim.app.routes`), to run it. */
export interface RouteInfo {
  path: string;
  name: string;
  robot: string | null;
  field: string | null;
  start: [number, number, number] | null;
  problem: string | null;
}

/** A PROS project's routines, to pick one for a run, and its routes. */
export interface ProjectRoutines {
  header: string;
  found: boolean;
  routines: RoutineInfo[];
  others: NotRoutineInfo[];
  routes?: RouteInfo[];
}

export interface RobotConfig {
  version?: 1;
  name?: string | null;
  body: BodyConfig;
  drivetrain: DrivetrainConfig;
  mechanisms?: Record<string, MechanismConfig>;
  sensors?: (ImuConfig | RotationConfig | DistanceConfig | GpsConfig)[];
  overrides?: Record<string, boolean | number | string>;
}

export interface BodyConfig {
  mass_kg: number;
  inertia_kgm2?: "auto" | number;
  footprint_in?: [number, number] | null;
  shape?: (RectPart | CirclePart | OutlinePart)[] | null;
  cg_in: [number, number, number];
  battery?: "v5_default";
}

/** A rectangle in the robot's shape. */
export interface RectPart {
  type: "rect";
  pos_in?: [number, number];
  size_in: [number, number];
  heading_deg?: number;
}

/** A circle in the robot's shape. */
export interface CirclePart {
  type: "circle";
  pos_in?: [number, number];
  diameter_in: number;
}

/** A closed outline in the robot's shape: straight edges from point to point, and from the last point back to the first. Its edges mustn't cross. */
export interface OutlinePart {
  type: "outline";
  points_in: [number, number][];
}

export interface DrivetrainConfig {
  type: "differential" | "xdrive" | "mecanum" | "hdrive";
  wheels: WheelConfig[];
  gearing: Record<string, GearGroupConfig>;
}

export interface WheelConfig {
  name: string;
  pos_in: [number, number];
  heading_deg?: number;
  type: "omni" | "traction" | "mecanum";
  diameter_in: number;
  drop_in?: number;
  roller_angle_deg?: number | null;
}

export interface GearGroupConfig {
  motors: number[];
  cartridge: "red" | "green" | "blue";
  ratio?: string | number;
  wheels: string[];
}

/** Motors that drive something other than the wheels: a lift, an intake, an arm. The mechanism is one rotating output (a lift's spool, a roller, an arm's pivot) geared to its motors. Load values are at that output; positions are output degrees from where it starts, positive in its motors' positive direction (a negative port is reversed, as in the drive's gearing groups). */
export interface MechanismConfig {
  motors: number[];
  cartridge: "red" | "green" | "blue";
  ratio?: string | number;
  inertia_kgm2?: number;
  load_torque_nm?: number;
  friction_nm?: number;
  range_deg?: [number, number] | null;
}

export interface TrackingWheelConfig {
  pos_in: [number, number];
  heading_deg?: number;
  diameter_in: number;
}

export interface ImuConfig {
  type: "imu";
  port: number;
  pos_in?: [number, number];
  mount_yaw_deg?: number;
  noise?: "ideal" | "default" | "harsh";
  scale_error?: number | null;
}

export interface RotationConfig {
  type: "rotation";
  port: number;
  reversed?: boolean;
  tracking_wheel?: TrackingWheelConfig | null;
  noise?: "ideal" | "default" | "harsh";
}

export interface DistanceConfig {
  type: "distance";
  port: number;
  pos_in: [number, number];
  heading_deg?: number;
  height_in?: number | null;
  noise?: "ideal" | "default" | "harsh";
}

export interface GpsConfig {
  type: "gps";
  port: number;
  pos_in: [number, number];
  mount_yaw_deg?: number;
  noise?: "ideal" | "default" | "harsh";
}

export interface FieldConfig {
  version?: 1;
  name?: string;
  size_in?: [number, number];
  elements?: (ObstacleConfig | PieceConfig)[];
}

/** A fixed field element. The robot and pieces can't pass through it unless it's low enough to drive over (`solid: false`); a distance sensor sees it unless the sensor's beam is above its `height_in`. */
export interface ObstacleConfig {
  type: "obstacle";
  name?: string | null;
  shape: "rect" | "circle";
  pos_in: [number, number];
  size_in?: [number, number] | null;
  diameter_in?: number | null;
  heading_deg?: number;
  height_in?: number | null;
  solid?: boolean;
  color?: string | null;
}

/** A movable game piece, modeled as a disc that slides on the tiles. */
export interface PieceConfig {
  type: "piece";
  name?: string | null;
  pos_in: [number, number];
  diameter_in: number;
  mass_kg: number;
  friction?: number;
  restitution?: number;
  color?: string | null;
}

/** Where something is written in a config: 1-based lines and columns, the end just past its last character. */
export interface TextSpan {
  line: number;
  column: number;
  end_line: number;
  end_column: number;
}

export interface PlacedIssue {
  severity: "error" | "warning";
  location: string;
  message: string;
  span: TextSpan | null;
}

/** A config's text, checked as `vexsim validate-config` would: its issues where they're written, and when it parses, the config itself (`robot` or `field`), its summary, and where each part the editor's diagram draws is written (`sensors[1]`, `elements[3]`). */
export interface ConfigCheck {
  issues: PlacedIssue[];
  robot?: RobotConfig | null;
  field?: FieldConfig | null;
  summary?: string[];
  places?: Record<string, TextSpan>;
}

/** A robot or field config, opened for editing. `version` is of the bytes on disk. */
export interface ConfigFile {
  path: string;
  kind: ConfigKind;
  text: string;
  version: string;
  check: ConfigCheck;
}

export interface ConfigCheckRequest {
  kind: ConfigKind;
  text: string;
}

/** Write `value` where `location` is: one number, or a list of them (`pos_in`), as a drag on the diagram does. With an `op` (the Design view's forms and tools): `set` any value there (a word, a number, a list, a mapping; a missing key is added), `add` it to the end of the list there, `remove` the item or key there, or `rename` the key there to `value`. */
export interface ConfigEdit {
  location: string;
  value?: unknown;
  op?: "set" | "add" | "remove" | "rename" | null;
}

export interface ConfigPatchRequest {
  kind: ConfigKind;
  text: string;
  edits: ConfigEdit[];
}

/** The text with the edits made in place (nothing else in it changed), checked. */
export interface ConfigPatched {
  text: string;
  check: ConfigCheck;
}

/** Write a config. `version`: the one it was opened at; the save is refused (409) if the file has changed since. None overwrites whatever is there. */
export interface ConfigSave {
  path: string;
  text: string;
  version?: string | null;
}

export interface ConfigSaved {
  version: string;
}

/** Make a robot config at `path` (in the workspace; never over a file): a rectangle to draw over on a `preset` drivetrain (tank4, tank6, xdrive, mecanum, hdrive), or a copy of the robot at `source`, named `name`. */
export interface NewRobotRequest {
  path: string;
  name: string;
  preset?: string;
  source?: string | null;
}

export interface NewRobot {
  path: string;
}

/** Put a drivetrain preset on a robot config's text: its wheels in the robot's box, its motors on free ports. The answer is a ConfigPatched. */
export interface ConfigDriveRequest {
  text: string;
  preset: string;
}

/** A file in the workspace, by its path there: one to copy (`POST /api/files/duplicate`, which answers with the copy's), or the copy. */
export interface WorkspaceFile {
  path: string;
}

export interface MotorCurve {
  command: string;
  label: string;
  speed_rpm: number[];
  torque_nm: number[];
  current_a: number[];
  power_w: number[];
}

/** A motor on the simulated dynamometer, under each command. */
export interface MotorCurves {
  cartridge: string;
  supply_voltage: number;
  current_limit_a: number;
  curves: MotorCurve[];
}

export interface DriftRun {
  lateral_mu: number;
  true: [number, number][];
  odometry: [number, number][];
  final_error_in: number;
}

/** An arc at fixed side speeds, for each roller friction: the true path against what drive-encoder odometry believes. */
export interface Drift {
  left: number;
  right: number;
  seconds: number;
  runs: DriftRun[];
}

export interface OdometryEstimate {
  name: string;
  path: [number, number, number][];
  position_error_in: number[];
  heading_error_deg: number[];
  final_in: number;
  final_deg: number;
  worst_in: number;
}

/** A scripted drive, and each baseline localizer's estimate against the truth. */
export interface Odometry {
  script: string;
  noise: string | null;
  seed: number;
  time_s: number[];
  truth: [number, number, number][];
  estimates: OdometryEstimate[];
}

/** A saved result of a benchmark, a sweep or a calibration (`GET /api/results/{kind}`). */
export interface ResultAbout {
  id: string;
  kind: ResultKind;
  title: string;
  created: number;
  summary: string;
}

export interface ScenarioController {
  name: string;
  kind: string;
  project: string | null;
}

/** A benchmark scenario, described (`GET /api/bench/scenario?path=`). */
export interface ScenarioInfo {
  name: string;
  description: string;
  path: string;
  robot: string;
  field: string | null;
  task: string;
  tolerance_in: number | null;
  time_limit_s: number;
  noise: string | null;
  disturbances: string[];
  randomized: string[];
  localizers: string[];
  controllers: ScenarioController[];
}

export interface Metric {
  key: string;
  label: string;
}

export interface Combination {
  localizer: string;
  controller: string;
}

export interface Stats {
  mean: number;
  median: number;
  p95: number;
  max: number;
}

export interface BenchSummary {
  localizer: string;
  controller: string;
  trials: number;
  success_rate: number | null;
  timeouts: number;
  stats: Record<string, Stats | null>;
}

export interface WorstCase {
  localizer: string;
  controller: string;
  seed: number;
  file: string;
}

/** A benchmark's result (`GET /api/results/bench/{id}`). `rows` are the trials, as trials.csv has them. */
export interface BenchResult {
  about: ResultAbout;
  scenario: ScenarioInfo;
  first_seed: number;
  seeds: number;
  workers: number;
  wall_time_s: number;
  metrics: Metric[];
  combos: Combination[];
  summary: BenchSummary[];
  rows: Record<string, unknown>[];
  worst: WorstCase[];
  report: string | null;
  files: string[];
  command: string;
}

export interface ResultReplayRequest {
  file: string;
}

/** The workspace's sweeps (`.vexsim/sweeps.yaml`); `error` if that file can't be read. */
export interface SweepsFile {
  file: string;
  sweeps: Sweep[];
  error?: string | null;
}

export interface SaveSweeps {
  sweeps: Sweep[];
}

export interface SweepVariation {
  label: string;
  env: Record<string, string>;
}

/** One run of a sweep: what ran (`spec`, to run it again exactly), whether its program finished, and how far the robot code's pose was from the truth (None without one). */
export interface SweepTrial {
  index: number;
  run: string;
  variation: string;
  env: Record<string, string>;
  seed: number;
  start: [number, number, number];
  spec: RunSpec;
  finished: boolean;
  error: string | null;
  seconds: number | null;
  end: [number, number, number] | null;
  end_estimate: [number, number, number] | null;
  mean_in: number | null;
  max_in: number | null;
  final_in: number | null;
  max_deg: number | null;
  trace: (number | null)[];
  wall_s: number;
}

/** A sweep's result (`GET /api/results/sweeps/{id}`); live, its trials arrive one by one as the job's items. */
export interface SweepResult {
  about: ResultAbout;
  sweep: Sweep;
  variations: SweepVariation[];
  trace_step_s: number;
  workers: number;
  wall_time_s: number;
  trials: SweepTrial[];
  files: string[];
}

export interface FitParameter {
  name: string;
  value: number;
  overridden: boolean;
}

/** What a fit adjusts unless told otherwise (`GET /api/calibrate/parameters?robot=`). */
export interface CalibrationSetup {
  robot: string;
  parameters: FitParameter[];
}

export interface RoutineRequest {
  robot: string;
  project: string;
  write?: boolean;
}

export interface RoutineFile {
  path: string;
  state: "new" | "same" | "different";
}

export interface RoutineStep {
  name: string;
  start_s: number;
  seconds: number;
}

/** The calibration routine in a PROS project (`POST /api/calibrate/routine`). */
export interface RoutinePlan {
  project: string;
  files: RoutineFile[];
  seconds: number;
  steps: RoutineStep[];
}

export interface LogFacts {
  rows: number;
  seconds: number;
  found: string;
  skipped_lines: number;
  ignored_motors: number[];
}

export interface FittedParameter {
  name: string;
  before: number;
  after: number;
  uncertainty: number;
}

export interface DirectParameter {
  name: string;
  before: number | null;
  after: number;
}

export interface RmsGroup {
  group: string;
  unit: string;
  before: number | null;
  after: number;
}

export interface PanelSeries {
  name: string;
  values: (number | null)[];
}

export interface CalibrationPanel {
  title: string;
  unit: string;
  time_s: number[];
  series: PanelSeries[];
}

/** A calibration's result (`GET /api/results/calibrations/{id}`). */
export interface CalibrationResult {
  about: ResultAbout;
  robot: string;
  log: string;
  log_facts: LogFacts;
  compare_only: boolean;
  parameters: FittedParameter[];
  direct: DirectParameter[];
  rms: RmsGroup[];
  overrides: Record<string, number>;
  replays: number;
  panels: CalibrationPanel[];
  files: string[];
}

/** Set `overrides` in a robot config's text (`POST /api/config/overrides`). */
export interface ConfigOverridesRequest {
  text: string;
  values: Record<string, number>;
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
