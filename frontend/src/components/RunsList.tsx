import { useState } from "react";
import { fixed, formatTime } from "../pose";
import type { RunRecord } from "../protocol";
import { COMPARE_DASHES, MAX_COMPARED, when } from "../recording";
import { DashSwatch } from "./FieldView";

const ENDED: Record<RunRecord["ended"], string> = {
  finished: "finished",
  stopped: "stopped",
  restarted: "restarted",
  error: "failed",
};

/** Every recorded run, newest first: open one to scrub it, compare it with the shown one,
 * keep it from being pruned, rename or delete it. */
export function RunsList(props: {
  runs: RunRecord[];
  shown: string | null; // the shown run's id
  compared: string[]; // the compared runs' ids, in order
  opening: string | null;
  canCompare: boolean; // a run is on the field to compare with
  onOpen: (run: RunRecord) => void;
  onCompare: (run: RunRecord) => void;
  onKeep: (run: RunRecord, kept: boolean) => void;
  onRename: (run: RunRecord, name: string) => void;
  onDelete: (run: RunRecord) => void;
}) {
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  if (props.runs.length === 0) {
    return <p className="muted pad">No runs yet. Every run is recorded here when it ends: the newest 50, and any you keep.</p>;
  }
  return (
    <ul className="runs" data-testid="runs">
      {props.runs.map((run) => {
        const shown = props.shown === run.id;
        const order = props.compared.indexOf(run.id);
        const comparing = order >= 0;
        const full = !comparing && props.compared.length >= MAX_COMPARED;
        return (
          <li key={run.id} className={shown ? "shown" : undefined} data-testid="recorded-run" data-run={run.id}>
            {renaming === run.id ? (
              <form
                className="rename"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (draft.trim()) props.onRename(run, draft.trim());
                  setRenaming(null);
                }}
              >
                <input value={draft} onChange={(e) => setDraft(e.target.value)} autoFocus aria-label="New name" onKeyDown={(e) => e.key === "Escape" && setRenaming(null)} />
                <button type="submit" className="small">
                  Save
                </button>
              </form>
            ) : (
              <button
                type="button"
                className={`item${shown ? " selected" : ""}`}
                onClick={() => props.onOpen(run)}
                disabled={props.opening === run.id}
                title={`${run.command}\n\nOpen this run to play it back`}
                data-testid="open-run"
              >
                <span className="item-name">
                  {comparing && <DashSwatch dash={COMPARE_DASHES[order]} />}
                  {run.name}
                  {run.kept && <span className="tag">kept</span>}
                </span>
                <span className="item-detail">
                  {when(run.created)} · {formatTime(run.duration)} · {ENDED[run.ended]}
                  {run.pose_error && ` · off ${fixed(run.pose_error.mean_in, 2)} in`}
                </span>
              </button>
            )}
            <div className="run-actions">
              <button
                type="button"
                className={`ghost small${comparing ? " on" : ""}`}
                aria-pressed={comparing}
                disabled={shown || full || (!comparing && !props.canCompare)}
                onClick={() => props.onCompare(run)}
                title={
                  shown
                    ? "This is the run on the field"
                    : full
                      ? `At most ${MAX_COMPARED} runs at once`
                      : "Draw this run over the one on the field, and beside it in the plots"
                }
                data-testid="compare-run"
              >
                Compare
              </button>
              <button
                type="button"
                className={`ghost small${run.kept ? " on" : ""}`}
                aria-pressed={!!run.kept}
                onClick={() => props.onKeep(run, !run.kept)}
                title="Kept runs stay; the others go once there are more than 50"
              >
                Keep
              </button>
              <button
                type="button"
                className="ghost small"
                onClick={() => {
                  setDraft(run.name);
                  setRenaming(run.id);
                }}
              >
                Rename
              </button>
              <button
                type="button"
                className={`ghost small${deleting === run.id ? " danger" : ""}`}
                onClick={() => {
                  if (deleting === run.id) {
                    setDeleting(null);
                    props.onDelete(run);
                  } else {
                    setDeleting(run.id);
                    setTimeout(() => setDeleting((id) => (id === run.id ? null : id)), 3000);
                  }
                }}
                title="Delete this run's recording"
              >
                {deleting === run.id ? "Sure?" : "Delete"}
              </button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
