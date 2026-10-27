// One run, as the browser sees it: the messages of its WebSocket folded into state.
//
// `apply` does the folding (and is what the tests drive); `connect` feeds it from the
// server. React views subscribe and re-read the store; they hear about frames at most
// NOTIFY_MS apart, while the field view reads the latest frame on every animation frame.

import { sessionSocketUrl } from "./api";
import type {
  ClientCommand,
  ErrorMessage,
  FrameMessage,
  OverlayMessage,
  SceneMessage,
  ServerMessage,
  SessionInfo,
  SessionState,
} from "./protocol";
import type { Problem } from "./problems";
import { compilerProblems, tracebackProblem } from "./problems";
import { Trail } from "./trail";

export const MAX_LINES = 5000;
const NOTIFY_MS = 100;

export type LineKind = "console" | "build" | "error" | "info";
export interface Line {
  kind: LineKind;
  text: string;
}

type Listener = () => void;

export class SessionStore {
  info: SessionInfo | null = null;
  state: SessionState = "starting";
  message: string | null = null;
  scene: SceneMessage | null = null;
  overlay: OverlayMessage | null = null;
  frame: FrameMessage | null = null;
  error: ErrorMessage | null = null;
  lines: Line[] = [];
  truth = new Trail();
  estimate = new Trail();
  frames = 0; // frames received, all told
  buildProblems: Problem[] = []; // the compiler's errors and warnings
  runProblems: Problem[] = []; // where the program failed
  connected = false;
  version = 0; // bumped whenever views should re-read

  private socket: WebSocket | null = null;
  private pending: ClientCommand[] = []; // sent once the socket opens
  private listeners = new Set<Listener>();
  private notifyTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;

  /** `root`: the workspace folder, to find the program's own frames in a traceback. */
  constructor(
    readonly id: string,
    readonly root = "",
  ) {}

  get problems(): Problem[] {
    return [...this.buildProblems, ...this.runProblems];
  }

  // --- state -----------------------------------------------------------------------------

  apply(message: ServerMessage): void {
    switch (message.type) {
      case "session":
        this.info = message.session;
        this.state = message.session.state;
        this.message = message.session.message;
        break;
      case "status":
        this.state = message.state;
        this.message = message.message;
        if (message.state === "finished" && message.message) this.addLines("info", [message.message]);
        break;
      case "scene":
        this.scene = message;
        this.overlay = null;
        this.frame = null;
        this.error = null;
        this.truth.clear();
        this.estimate.clear();
        this.lines = this.lines.filter((line) => line.kind === "build");
        this.runProblems = [];
        break;
      case "frame": {
        const previous = this.frame;
        if (previous && message.t < previous.t) {
          this.truth.clear();
          this.estimate.clear();
        }
        this.frame = message;
        this.frames += 1;
        this.truth.add(message.pose[0], message.pose[1]);
        if (message.estimate) this.estimate.add(message.estimate[0], message.estimate[1]);
        this.notifySoon();
        return;
      }
      case "overlay":
        this.overlay = message;
        break;
      case "console":
        this.addLines("console", message.lines);
        break;
      case "build":
        this.addLines("build", message.lines);
        this.buildProblems = merge(this.buildProblems, compilerProblems(message.lines.join("\n")));
        break;
      case "error":
        this.error = message;
        this.addLines("error", [message.message]);
        for (const issue of message.issues) {
          this.addLines("error", [`  ${issue.location || "(document)"}: ${issue.message}`]);
        }
        if (message.traceback) this.addLines("error", message.traceback.trimEnd().split("\n"));
        this.buildProblems = merge(this.buildProblems, compilerProblems(message.message));
        if (message.traceback) {
          const failed = tracebackProblem(message.traceback, this.root);
          if (failed) this.runProblems = merge(this.runProblems, [failed]);
        }
        break;
    }
    this.notify();
  }

  private addLines(kind: LineKind, texts: string[]): void {
    for (const text of texts) this.lines.push({ kind, text });
    if (this.lines.length > MAX_LINES) this.lines = this.lines.slice(-MAX_LINES);
  }

  // --- subscribers -------------------------------------------------------------------------

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getVersion = (): number => this.version;

  private notify(): void {
    if (this.notifyTimer !== null) {
      clearTimeout(this.notifyTimer);
      this.notifyTimer = null;
    }
    this.version += 1;
    for (const listener of [...this.listeners]) listener();
  }

  private notifySoon(): void {
    if (this.notifyTimer === null) {
      this.notifyTimer = setTimeout(() => {
        this.notifyTimer = null;
        this.notify();
      }, NOTIFY_MS);
    }
  }

  // --- the connection ----------------------------------------------------------------------

  connect(): void {
    if (this.closed || this.socket) return;
    const socket = new WebSocket(sessionSocketUrl(this.id));
    this.socket = socket;
    socket.onopen = () => {
      this.connected = true;
      for (const command of this.pending.splice(0)) socket.send(JSON.stringify(command));
      this.notify();
    };
    socket.onmessage = (event) => {
      try {
        this.apply(JSON.parse(event.data as string) as ServerMessage);
      } catch (error) {
        console.error("vexsim: bad message", error);
      }
    };
    socket.onclose = () => {
      this.socket = null;
      this.connected = false;
      if (!this.closed && this.state !== "stopped") {
        this.addLines("info", ["Lost the connection to vexsim; is `vexsim ui` still running?"]);
      }
      this.notify();
    };
  }

  /** Send a command now, or as soon as the connection opens. */
  send(command: ClientCommand): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(command));
    } else if (!this.closed) {
      this.pending.push(command);
    }
  }

  close(): void {
    this.closed = true;
    if (this.notifyTimer !== null) clearTimeout(this.notifyTimer);
    this.socket?.close();
    this.socket = null;
  }
}

/** `known` with the problems of `found` it doesn't have yet. */
function merge(known: Problem[], found: Problem[]): Problem[] {
  const key = (p: Problem) => `${p.severity}|${p.file}|${p.line}|${p.column}|${p.message}`;
  const seen = new Set(known.map(key));
  const fresh = found.filter((p) => !seen.has(key(p)) && seen.add(key(p)));
  return fresh.length ? [...known, ...fresh] : known;
}

/** Whether a run in this state can take pause/step/speed commands. */
export function isLive(state: SessionState): boolean {
  return state === "running" || state === "paused";
}
