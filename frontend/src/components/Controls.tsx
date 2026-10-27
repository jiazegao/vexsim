import { useState } from "react";
import { formatTime } from "../pose";
import type { SessionState } from "../protocol";
import type { SessionStore } from "../session";
import { isLive } from "../session";

export const SPEEDS = [0.1, 0.25, 0.5, 1, 2, 4, 8, 0]; // 0 = as fast as possible

const STATE_LABEL: Record<SessionState, string> = {
  building: "Building",
  starting: "Starting",
  running: "Running",
  paused: "Paused",
  finished: "Finished",
  error: "Error",
  stopped: "Stopped",
};

export function speedLabel(speed: number): string {
  return speed <= 0 ? "Max" : `${speed}×`;
}

export function Controls(props: {
  store: SessionStore | null;
  speed: number;
  onSpeed: (speed: number) => void;
  onStop: () => void;
  command: string | null;
}) {
  const { store } = props;
  const state = store?.state ?? null;
  const live = state !== null && isLive(state);
  const paused = state === "paused";
  const canRestart = state !== null && state !== "building" && state !== "stopped" && store?.scene !== null;
  const frame = store?.frame ?? null;

  return (
    <div className="controls" role="toolbar" aria-label="Run controls">
      <div className="buttons">
        <button
          onClick={() => store?.send({ cmd: paused ? "resume" : "pause" })}
          disabled={!live}
          data-testid="pause"
          title={paused ? "Resume (Space)" : "Pause (Space)"}
        >
          {paused ? "Resume" : "Pause"}
        </button>
        <button onClick={() => store?.send({ cmd: "step", ms: 10 })} disabled={!paused} title="Advance 10 ms (.)">
          Step
        </button>
        <button onClick={() => store?.send({ cmd: "restart" })} disabled={!canRestart} title="From the start again, same seed (R)">
          Restart
        </button>
        <button onClick={props.onStop} disabled={!store || state === "stopped"} data-testid="stop" title="Stop the run and its program">
          Stop
        </button>
        <label className="speed" title="Simulated time per real second (+ / −)">
          Speed
          <select value={props.speed} onChange={(e) => props.onSpeed(Number(e.target.value))}>
            {SPEEDS.map((speed) => (
              <option key={speed} value={speed}>
                {speedLabel(speed)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {props.command && <CopyCommand command={props.command} />}
      <div className="status" aria-live="polite">
        {state && (
          <span className={`chip state-${state}`} data-testid="status" title={store?.message ?? undefined}>
            {STATE_LABEL[state]}
          </span>
        )}
        {frame && (
          <>
            <span className="time" data-testid="sim-time" data-t={frame.t}>
              {formatTime(frame.t)}
            </span>
            <span className="muted" data-testid="phase">
              {frame.phase}
              {frame.period_left !== null && (
                <span title="Time left in this period, as field control counts it"> · {clock(frame.period_left)} left</span>
              )}
            </span>
            <span className="muted" title="Simulated seconds per real second, lately">
              {state === "running" ? `${frame.rate.toFixed(1)}× real time` : ""}
            </span>
          </>
        )}
      </div>
    </div>
  );
}

/** A match clock: 1:05, 0:09. */
function clock(seconds: number): string {
  const whole = Math.ceil(Math.max(0, seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** This run as a `vexsim run` command, for a terminal or a script. */
function CopyCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="ghost small"
      data-testid="command"
      data-command={command}
      title={`${command}\n\nCopy this run as a command`}
      onClick={() => {
        navigator.clipboard
          ?.writeText(command)
          .then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          })
          .catch(() => {});
      }}
    >
      {copied ? "Copied" : "Copy command"}
    </button>
  );
}
