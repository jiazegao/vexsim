import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { WorkspaceItem } from "../protocol";
import { newRoutePath } from "../route";

/** "New route…": a name, the PROS project it's for (it goes in its routes/ folder), and the
 * robot and field it's drawn and run with. It starts where the run bar's start is, and opens
 * in the autonomous maker with no steps yet. The server writes the file, never over one. */
export function NewRouteDialog(props: {
  projects: WorkspaceItem[];
  robots: WorkspaceItem[];
  fields: WorkspaceItem[];
  project: string; // the run bar's, to start with
  robot: string;
  field: string;
  start: [number, number, number] | null; // the run bar's: x, y, heading (vexsim's)
  taken: string[]; // every path in the workspace
  onCreated: (path: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState("New route");
  const [project, setProject] = useState(props.projects.some((p) => p.path === props.project) ? props.project : (props.projects[0]?.path ?? ""));
  const [robot, setRobot] = useState(props.robot || (props.robots[0]?.path ?? ""));
  const [field, setField] = useState(props.field);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => first.current?.select(), []);
  const start = props.start ?? [0, 0, 90];

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const made = await api.newRoute({ project, name: name.trim() || "New route", robot: robot || null, field: field || null, start });
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
        className="dialog new-robot new-route"
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-route-title"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && props.onClose()}
        onSubmit={(e) => {
          e.preventDefault();
          if (!busy) create();
        }}
        data-testid="new-route-dialog"
      >
        <header>
          <h2 id="new-route-title">New route</h2>
        </header>
        <p className="muted small">
          An autonomous route for a project that uses LemLib: its motions, pauses and the team's own functions, one step after another. It opens in the autonomous maker, starting where the run bar's start is (
          {start.map((v) => Number(v.toFixed(2))).join(", ")}): drag it on the field to move it.
        </p>
        <label className="field">
          <span>Name</span>
          <input ref={first} value={name} onChange={(e) => setName(e.target.value)} data-testid="new-route-name" />
        </label>
        <label className="field">
          <span>Project</span>
          <select value={project} onChange={(e) => setProject(e.target.value)} data-testid="new-route-project">
            {props.projects.map((p) => (
              <option key={p.path} value={p.path}>
                {props.projects.some((q) => q !== p && q.name === p.name) ? `${p.name} · ${p.path}` : p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Robot</span>
          <select value={robot} onChange={(e) => setRobot(e.target.value)} data-testid="new-route-robot">
            {!robot && <option value="">Pick one…</option>}
            {props.robots.map((r) => (
              <option key={r.path} value={r.path}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Field</span>
          <select value={field} onChange={(e) => setField(e.target.value)} data-testid="new-route-field">
            <option value="">Empty field (walls only)</option>
            {props.fields.map((f) => (
              <option key={f.path} value={f.path}>
                {f.name}
              </option>
            ))}
          </select>
        </label>
        <p className="muted small" data-testid="new-route-path">
          {project ? newRoutePath(project, name, props.taken) : "Pick a project"}
        </p>
        {error && (
          <p className="bad small" role="alert" data-testid="new-route-error">
            {error}
          </p>
        )}
        <div className="actions">
          <button type="button" onClick={props.onClose}>
            Cancel
          </button>
          <button type="submit" className="primary" disabled={busy || !project} data-testid="new-route-create">
            {busy ? "Creating…" : "Create"}
          </button>
        </div>
      </form>
    </div>
  );
}
