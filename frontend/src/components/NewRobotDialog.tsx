import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { DRIVE_PRESETS, newRobotPath, robotFolder } from "../design";
import type { WorkspaceItem } from "../protocol";

/** "New robot…": a name, what to start from (a rectangle on one of the usual drivetrains, or
 * a copy of a robot), and where its file goes (beside the other robots). The server writes
 * the file, never over one, and the robot opens in its editor's Design view. */
export function NewRobotDialog(props: {
  robots: WorkspaceItem[];
  taken: string[]; // every path in the workspace
  onCreated: (path: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState("New robot");
  const [start, setStart] = useState("tank4"); // a drive preset, or "copy:" and a robot's path
  const [edited, setEdited] = useState<string | null>(null); // the file, if typed (else it follows the name)
  const path = edited ?? newRobotPath(robotFolder(props.robots.map((r) => r.path)), name, props.taken);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => first.current?.select(), []);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const copy = start.startsWith("copy:") ? start.slice(5) : null;
      const made = await api.newRobot({ path, name: name.trim() || "New robot", preset: copy ? "tank4" : start, source: copy });
      props.onCreated(made.path);
    } catch (problem) {
      setError((problem as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="overlay" role="presentation" onClick={props.onClose}>
      <form
        className="dialog new-robot"
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-robot-title"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && props.onClose()}
        onSubmit={(e) => {
          e.preventDefault();
          if (!busy) create();
        }}
        data-testid="new-robot-dialog"
      >
        <header>
          <h2 id="new-robot-title">New robot</h2>
        </header>
        <p className="muted small">It opens in its editor's Design view: draw its shape, pick its drive, add its mechanisms and sensors. Everything you change is written into its YAML, which you can open beside it any time.</p>
        <label className="field">
          <span>Name</span>
          <input ref={first} value={name} onChange={(e) => setName(e.target.value)} data-testid="new-robot-name" />
        </label>
        <label className="field">
          <span>Start from</span>
          <select value={start} onChange={(e) => setStart(e.target.value)} data-testid="new-robot-start">
            <optgroup label="A 15 × 15 in rectangle to draw over, on">
              {DRIVE_PRESETS.map(([id, label]) => (
                <option key={id} value={id}>
                  a {label}
                </option>
              ))}
            </optgroup>
            {props.robots.length > 0 && (
              <optgroup label="A copy of">
                {props.robots.map((robot) => (
                  <option key={robot.path} value={`copy:${robot.path}`}>
                    {robot.name}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </label>
        <label className="field">
          <span>File</span>
          <input
            value={path}
            onChange={(e) => setEdited(e.target.value)}
            spellCheck={false}
            data-testid="new-robot-path"
          />
        </label>
        {error && (
          <p className="bad small" role="alert" data-testid="new-robot-error">
            {error}
          </p>
        )}
        <div className="actions">
          <button type="button" onClick={props.onClose}>
            Cancel
          </button>
          <button type="submit" className="primary" disabled={busy || !path.trim()} data-testid="new-robot-create">
            {busy ? "Creating…" : "Create"}
          </button>
        </div>
      </form>
    </div>
  );
}
