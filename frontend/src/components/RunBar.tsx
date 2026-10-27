import { useState } from "react";
import { lemlibTheta } from "../pose";
import type { RunConfiguration, WorkspaceInfo } from "../protocol";
import type { RunForm } from "../runform";
import { MODES, NOISE, sameRun } from "../runform";

export function RunBar(props: {
  workspace: WorkspaceInfo | null;
  form: RunForm;
  onChange: (form: RunForm) => void;
  onRun: () => void;
  starting: boolean;
  configurations: RunConfiguration[];
  configFile: string;
  configError: string | null;
  onPick: (name: string) => void;
  onSave: (name: string) => Promise<string | null>; // an error, or null when saved
  onDelete: (name: string) => Promise<string | null>;
}) {
  const { workspace, form, onChange, configurations } = props;
  const items = workspace?.items ?? [];
  const of = (kind: string) => items.filter((item) => item.kind === kind);
  const set = <K extends keyof RunForm>(key: K) => (value: RunForm[K]) => onChange({ ...form, [key]: value });
  const heading = Number(form.heading);
  const theta = Number.isFinite(heading) ? lemlibTheta(heading) : null;
  const project = of("project").some((item) => item.path === form.program);

  const chosen = configurations.find((c) => c.name === form.config) ?? null;
  const changed = chosen !== null && !sameRun(form, chosen);
  const [naming, setNaming] = useState<string | null>(null); // the new configuration's name, while asking
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const act = async (work: () => Promise<string | null>) => {
    setBusy(true);
    const error = await work();
    setBusy(false);
    setMessage(error);
    return error;
  };

  return (
    <form
      className="runbar"
      onSubmit={(event) => {
        event.preventDefault();
        props.onRun();
      }}
    >
      <div className="row">
        <label className="field config" title={`Saved runs, kept in ${props.configFile}`}>
          <span>
            Saved run {changed && <em className="changed">changed</em>}
          </span>
          <select value={chosen ? chosen.name : ""} onChange={(e) => props.onPick(e.target.value)} data-testid="config">
            <option value="">{configurations.length ? "None (set it up below)" : "None saved yet"}</option>
            {configurations.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Robot</span>
          <select value={form.robot} onChange={(e) => set("robot")(e.target.value)} data-testid="robot">
            {!form.robot && <option value="">Pick a robot…</option>}
            {of("robot").map((item) => (
              <option key={item.path} value={item.path} disabled={!!item.problem}>
                {item.name}
                {item.problem ? " (has errors)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Field</span>
          <select value={form.field} onChange={(e) => set("field")(e.target.value)} data-testid="field-select">
            <option value="">Empty field (walls only)</option>
            {of("field").map((item) => (
              <option key={item.path} value={item.path} disabled={!!item.problem}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field wide">
          <span>Program</span>
          <select value={form.program} onChange={(e) => set("program")(e.target.value)} data-testid="program">
            <option value="">None: drive it with the keys or a gamepad</option>
            {of("program").length > 0 && (
              <optgroup label="Python programs">
                {of("program").map((item) => (
                  <option key={item.path} value={item.path}>
                    {item.name}
                  </option>
                ))}
              </optgroup>
            )}
            {of("project").length > 0 && (
              <optgroup label="PROS projects (built when you run them)">
                {of("project").map((item) => (
                  <option key={item.path} value={item.path}>
                    {item.name}
                    {folderOf(item.path) === "." ? "" : ` · ${folderOf(item.path)}`}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </label>
        <label className="field narrow-ish">
          <span>Mode</span>
          <select value={form.mode} onChange={(e) => set("mode")(e.target.value as RunForm["mode"])} data-testid="mode">
            <option value="">Program's default</option>
            {MODES.map((mode) => (
              <option key={mode} value={mode}>
                {mode}
              </option>
            ))}
          </select>
        </label>
        <div className="actions">
          <button type="submit" className="primary" disabled={!form.robot || props.starting} data-testid="run">
            {props.starting ? "Starting…" : "Run"}
          </button>
        </div>
      </div>
      <div className="row secondary">
        <fieldset className="start" title="Where the robot starts: inches from the field's center, heading counter-clockwise from +x. Or drag the robot on the field.">
          <legend>Start</legend>
          <label>
            x
            <input inputMode="decimal" value={form.x} onChange={(e) => set("x")(e.target.value)} aria-label="Start x (in)" />
          </label>
          <label>
            y
            <input inputMode="decimal" value={form.y} onChange={(e) => set("y")(e.target.value)} aria-label="Start y (in)" />
          </label>
          <label>
            heading
            <input inputMode="decimal" value={form.heading} onChange={(e) => set("heading")(e.target.value)} aria-label="Start heading (degrees)" />
            °
          </label>
          <span className="muted hint" title="LemLib measures theta clockwise from +y: chassis.setPose(x, y, theta)">
            = LemLib θ {theta === null ? "—" : `${+theta.toFixed(2)}°`}
          </span>
        </fieldset>
        <label className="field narrow">
          <span>Seed</span>
          <input inputMode="numeric" value={form.seed} onChange={(e) => set("seed")(e.target.value)} aria-label="Seed" />
        </label>
        <details className="more">
          <summary>More</summary>
          <div className="more-body">
            <label className="field">
              <span>Sensor noise</span>
              <select value={form.noise} onChange={(e) => set("noise")(e.target.value as RunForm["noise"])}>
                <option value="">As configured</option>
                {NOISE.map((noise) => (
                  <option key={noise} value={noise}>
                    {noise}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Recorded controller input</span>
              <select value={form.input} onChange={(e) => set("input")(e.target.value)}>
                <option value="">None</option>
                {of("input").map((item) => (
                  <option key={item.path} value={item.path}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field narrow" title="PROS projects: stop the run if one task runs this many seconds of real time without waiting (0 = never)">
              <span>Busy timeout (s){project ? "" : " · PROS"}</span>
              <input inputMode="decimal" value={form.busy} onChange={(e) => set("busy")(e.target.value)} aria-label="Busy timeout (s)" />
            </label>
            <label className="field env">
              <span>Environment for the program (KEY=VALUE per line)</span>
              <textarea rows={3} value={form.env} onChange={(e) => set("env")(e.target.value)} placeholder="VEXSIM_AUTON=Left 40" spellCheck={false} />
            </label>
          </div>
        </details>
        <span className="spacer" />
        <div className="configs" aria-label="Saved runs">
          {naming !== null ? (
            <>
              <input
                autoFocus
                value={naming}
                onChange={(e) => setNaming(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") setNaming(null);
                }}
                placeholder="Name this run"
                aria-label="Name for the saved run"
                data-testid="config-name"
                maxLength={80}
              />
              <button
                type="button"
                disabled={!naming.trim() || busy}
                data-testid="config-save-as"
                onClick={async () => {
                  const name = naming.trim();
                  if (configurations.some((c) => c.name.toLowerCase() === name.toLowerCase())) {
                    setMessage(`A saved run is already named "${name}"`);
                    return;
                  }
                  if (!(await act(() => props.onSave(name)))) setNaming(null);
                }}
              >
                Save
              </button>
              <button type="button" className="ghost" onClick={() => setNaming(null)}>
                Cancel
              </button>
            </>
          ) : confirming && chosen ? (
            <>
              <span className="small">Delete “{chosen.name}”?</span>
              <button
                type="button"
                className="danger"
                disabled={busy}
                onClick={async () => {
                  await act(() => props.onDelete(chosen.name));
                  setConfirming(false);
                }}
              >
                Delete
              </button>
              <button type="button" className="ghost" onClick={() => setConfirming(false)}>
                Keep
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                className="ghost small"
                disabled={!changed || busy || !!props.configError}
                title={chosen ? `Save these settings as “${chosen.name}”` : "Pick a saved run first"}
                onClick={() => chosen && act(() => props.onSave(chosen.name))}
              >
                Save
              </button>
              <button
                type="button"
                className="ghost small"
                disabled={!form.robot || busy || !!props.configError}
                title="Save these settings as a new run"
                data-testid="config-new"
                onClick={() => {
                  setMessage(null);
                  setNaming(chosen ? `${chosen.name} (copy)` : "");
                }}
              >
                Save as…
              </button>
              <button type="button" className="ghost small" disabled={!chosen || busy || !!props.configError} onClick={() => setConfirming(true)}>
                Delete
              </button>
            </>
          )}
        </div>
      </div>
      {(message || props.configError) && (
        <p className="config-message" role="alert">
          <span aria-hidden="true">⚠</span> {props.configError ? `${props.configError} (fix it, then refresh)` : message}
        </p>
      )}
    </form>
  );
}

/** The folder a workspace path is in ("." for the workspace itself). */
function folderOf(path: string): string {
  const at = path.lastIndexOf("/");
  return at < 0 ? "." : path.slice(0, at);
}
