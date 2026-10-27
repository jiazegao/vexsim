import type { ItemKind, WorkspaceInfo, WorkspaceItem } from "../protocol";
import type { RunForm } from "../runform";

const GROUPS: { kinds: ItemKind[]; title: string; hint: string }[] = [
  { kinds: ["robot"], title: "Robots", hint: "Click to run this robot" },
  { kinds: ["field"], title: "Fields", hint: "Click to run on this field" },
  { kinds: ["program"], title: "Python programs", hint: "Click to run this program" },
  { kinds: ["project"], title: "PROS projects", hint: "Click to build and run this project" },
  { kinds: ["input"], title: "Controller inputs", hint: "Click to drive with this recorded input" },
  { kinds: ["scenario"], title: "Benchmark scenarios", hint: "Benchmarks get their own page in a later version" },
  { kinds: ["log"], title: "Telemetry logs", hint: "Replays get their own page in a later version" },
  { kinds: ["invalid"], title: "Unreadable configs", hint: "Fix the YAML to use it" },
];

function inUse(item: WorkspaceItem, form: RunForm): boolean {
  switch (item.kind) {
    case "robot":
      return form.robot === item.path;
    case "field":
      return form.field === item.path;
    case "program":
    case "project":
      return form.program === item.path;
    case "input":
      return form.input === item.path;
    default:
      return false;
  }
}

export function Sidebar(props: {
  workspace: WorkspaceInfo | null;
  form: RunForm;
  onPick: (item: WorkspaceItem) => void;
  onRefresh: () => void;
  loading: boolean;
}) {
  const { workspace, form, onPick } = props;
  return (
    <nav className="sidebar" aria-label="Workspace" data-testid="workspace">
      <div className="sidebar-head">
        <span className="eyebrow">Workspace</span>
        <button className="ghost small" onClick={props.onRefresh} disabled={props.loading} title="Look for new and changed files">
          {props.loading ? "Scanning…" : "Refresh"}
        </button>
      </div>
      {workspace && workspace.items.length === 0 && (
        <p className="muted pad">No robot configs, programs or PROS projects in this folder yet.</p>
      )}
      {GROUPS.map((group) => {
        const items = workspace?.items.filter((item) => group.kinds.includes(item.kind)) ?? [];
        if (!items.length) return null;
        const pickable = !["scenario", "log", "invalid"].includes(group.kinds[0]);
        return (
          <section key={group.title} className="group">
            <h2>
              {group.title} <span className="count">{items.length}</span>
            </h2>
            <ul>
              {items.map((item) => {
                const selected = inUse(item, form);
                return (
                  <li key={item.kind + item.path}>
                    <button
                      className={`item${selected ? " selected" : ""}${pickable ? "" : " inert"}`}
                      data-testid={`item-${item.path}`}
                      title={`${item.path}\n${group.hint}`}
                      aria-pressed={pickable ? selected : undefined}
                      onClick={() => pickable && onPick(item)}
                    >
                      <span className="item-name">{item.name}</span>
                      <span className="item-detail">{item.problem ? "" : item.detail}</span>
                      {item.problem && (
                        <span className="item-problem">
                          <span aria-hidden="true">⚠</span> {item.problem}
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </nav>
  );
}
