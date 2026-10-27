import type { WorkspaceInfo } from "../protocol";
import { lemlibTheta } from "../pose";
import type { RunForm } from "../runform";
import { MODES, NOISE } from "../runform";

export function RunBar(props: {
  workspace: WorkspaceInfo | null;
  form: RunForm;
  onChange: (form: RunForm) => void;
  onRun: () => void;
  starting: boolean;
}) {
  const { workspace, form, onChange } = props;
  const items = workspace?.items ?? [];
  const of = (kind: string) => items.filter((item) => item.kind === kind);
  const set = <K extends keyof RunForm>(key: K) => (value: RunForm[K]) => onChange({ ...form, [key]: value });
  const heading = Number(form.heading);
  const theta = Number.isFinite(heading) ? lemlibTheta(heading) : null;

  return (
    <form
      className="runbar"
      onSubmit={(event) => {
        event.preventDefault();
        props.onRun();
      }}
    >
      <div className="row">
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
            <option value="">None (the robot stays still)</option>
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
                    {item.name} · {folderOf(item.path)}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </label>
        <label className="field">
          <span>Mode</span>
          <select value={form.mode} onChange={(e) => set("mode")(e.target.value as RunForm["mode"])}>
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
        <fieldset className="start" title="Where the robot starts: inches from the field's center, heading counter-clockwise from +x">
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
          <input inputMode="numeric" value={form.seed} onChange={(e) => set("seed")(e.target.value)} />
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
            <label className="field env">
              <span>Environment for the program (KEY=VALUE per line)</span>
              <textarea rows={3} value={form.env} onChange={(e) => set("env")(e.target.value)} placeholder="VEXSIM_AUTON=Left 40" spellCheck={false} />
            </label>
          </div>
        </details>
      </div>
    </form>
  );
}

/** The folder a workspace path is in ("." for the workspace itself). */
function folderOf(path: string): string {
  const at = path.lastIndexOf("/");
  return at < 0 ? "." : path.slice(0, at);
}
