import type { Phase } from "../playback";
import type { Playhead } from "../playhead";
import { usePlayhead } from "../playhead";
import { fixed, formatTime } from "../pose";
import type { RunRecord } from "../protocol";

export const PLAY_SPEEDS = [0.25, 0.5, 1, 2, 4];

const ENDED: Record<RunRecord["ended"], string> = {
  finished: "finished",
  stopped: "stopped",
  restarted: "restarted",
  error: "failed",
};

/** One line about a recorded run: how it ended, how long, how far off its code was. */
export function runSummary(run: RunRecord): string {
  const parts = [ENDED[run.ended], formatTime(run.duration)];
  if (run.pose_error) parts.push(`off by ${fixed(run.pose_error.mean_in, 2)} in on average`);
  return parts.join(" · ");
}

/** Play, pause and scrub a recorded run (or a robot's log); its phases under the scrubber,
 * its exports beside. */
export function Timeline(props: {
  phases: Phase[];
  playhead: Playhead;
  name: string;
  run: RunRecord | null;
  summary?: string; // about it, when it isn't a run
  csv: string | null; // the telemetry as CSV, to download
  video: "off" | "recording" | "unsupported" | null; // null: no video of it
  onVideo: () => void; // start recording a video, or cancel it
  onClose: () => void;
  closeTitle?: string;
}) {
  const { phases, playhead } = props;
  usePlayhead(playhead);
  const { start, end, t, playing } = playhead;
  const span = Math.max(1e-9, end - start);
  const share = (seconds: number) => `${(seconds / span) * 100}%`;

  return (
    <section className="timeline" aria-label="Recorded run" data-testid="timeline">
      <div className="timeline-row">
        <button type="button" className="play" onClick={() => playhead.toggle()} data-testid="play" title={playing ? "Pause (Space)" : "Play (Space)"}>
          {playing ? "Pause" : "Play"}
        </button>
        <button type="button" onClick={() => playhead.seek(start)} title="Back to the start (Home)">
          To start
        </button>
        <div className="scrub">
          <input
            type="range"
            min={start}
            max={end}
            step="any"
            value={t}
            onChange={(event) => playhead.seek(Number(event.target.value))}
            onKeyDown={(event) => {
              const by = { ArrowLeft: -0.5, ArrowDown: -0.5, ArrowRight: 0.5, ArrowUp: 0.5, PageDown: -5, PageUp: 5 }[event.key];
              if (by === undefined) return; // Home and End work as they are
              event.preventDefault();
              playhead.seek(t + by * (event.shiftKey ? 10 : 1));
            }}
            aria-label="Time in the run"
            aria-valuetext={formatTime(t)}
            data-testid="scrubber"
          />
          <div className="phases">
            {phases.map((phase) => (
              <button
                type="button"
                key={`${phase.name}${phase.start}`}
                style={{ left: share(phase.start - start), width: share(phase.end - phase.start) }}
                onClick={() => playhead.seek(phase.start)}
                title={`${phase.name}: ${formatTime(phase.start)} to ${formatTime(phase.end)}`}
                tabIndex={-1}
              >
                {(phase.end - phase.start) / span > 0.08 ? phase.name : ""}
              </button>
            ))}
          </div>
        </div>
        <span className="time" data-testid="playhead-time" data-t={t.toFixed(3)}>
          {formatTime(t)}
        </span>
        <span className="muted small">of {formatTime(end)}</span>
        <label className="speed" title="Playback speed">
          Speed
          <select value={playhead.speed} onChange={(event) => playhead.setSpeed(Number(event.target.value))}>
            {PLAY_SPEEDS.map((speed) => (
              <option key={speed} value={speed}>
                {speed}×
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="timeline-row secondary">
        <span className="run-name" title={props.name} data-testid="shown-run">
          {props.name}
        </span>
        {props.run ? <span className="muted small">{runSummary(props.run)}</span> : props.summary && <span className="muted small">{props.summary}</span>}
        <span className="spacer" />
        {props.csv && (
          <a className="button ghost small" href={props.csv} download title="The run's telemetry, every 10 ms, as a spreadsheet">
            CSV
          </a>
        )}
        {props.video !== null && (
          <button
            type="button"
            className={`ghost small${props.video === "recording" ? " on" : ""}`}
            onClick={props.onVideo}
            disabled={props.video === "unsupported"}
            data-testid="video"
            title={
              props.video === "unsupported"
                ? "This browser can't record video"
                : props.video === "recording"
                  ? "Stop without saving"
                  : "Play the run from the start and save the field as a WebM video, at this speed"
            }
          >
            {props.video === "recording" ? "Cancel video" : "Video"}
          </button>
        )}
        <button type="button" className="ghost small" onClick={props.onClose} title={props.closeTitle ?? "Back to the robot as the run form sets it up"} data-testid="close-run">
          Close
        </button>
      </div>
    </section>
  );
}
