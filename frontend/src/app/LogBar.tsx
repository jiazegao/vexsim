import { logSummary } from "../mcllog";
import type { RealLog } from "./useRealLog";

/** The bar over the field while a real robot's log is open (useRealLog.ts): what it is, where it
 * starts against the run beside it, and what can be run with it: its routine, or a replay. */
export function LogBar(props: { log: RealLog; starting: boolean }) {
  const { realLog, logAlone, logAt, logShift, setLogShift, logRoutine, runLogRoutine, followable, replayChoice, setReplayWith, replayRuns, replayLog, closeRealLog } = props.log;
  const { starting } = props;
  if (!realLog) return null;
  return (
    <div className="logbar" data-testid="logbar">
      <div className="logrow">
        <span className="logname" title={realLog.tape.path}>
          {realLog.name}
        </span>
        <span className="muted small">{logSummary(realLog.tape)}</span>
        <span className="spacer" />
        <button type="button" className="ghost small" onClick={closeRealLog} title="Put the log away" aria-label={`Close ${realLog.name}`} data-testid="close-log">
          ×
        </button>
      </div>
      <div className="logrow">
        {!logAlone && (
          <label title="The moment of the run beside it when the log's first update comes: when the run began following it, or else where its program began. Nudge it to line them up.">
            <span className="small">The log starts at</span>
            <input
              type="number"
              step={0.1}
              value={logAt === null ? "" : +logAt.toFixed(2)}
              placeholder="…"
              disabled={logAt === null}
              onChange={(event) => logAt !== null && event.target.value !== "" && setLogShift(logShift + Number(event.target.value) - logAt)}
              aria-label="Moment of the run the log starts at (s)"
              data-testid="log-start"
            />
            <span className="small">s of the run</span>
          </label>
        )}
        <span className="spacer" />
        {logRoutine && (
          <button
            type="button"
            className="small"
            onClick={runLogRoutine}
            disabled={starting}
            title={`Run ${logRoutine.name}() in the simulator, in autonomous, from where its setPose puts the robot: the routine the log is of, beside it`}
            data-testid="run-log-routine"
          >
            Run {logRoutine.name}
          </button>
        )}
        {followable && (
          <label title="Replay the log in the simulator: a virtual driver drives the run's robot along the real robot's path, through its program's driver control">
            <span className="small">Replay it with</span>
            <select value={replayChoice} onChange={(event) => setReplayWith(event.target.value)} data-testid="replay-with">
              <option value="">The run set up above</option>
              {replayRuns.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {followable && (
          <button type="button" className="small" onClick={replayLog} disabled={starting} data-testid="replay-log">
            Replay
          </button>
        )}
      </div>
    </div>
  );
}
