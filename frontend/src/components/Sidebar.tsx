import type { ReactNode } from "react";
import { useState } from "react";
import type { ItemKind, WorkspaceInfo, WorkspaceItem } from "../protocol";
import type { RunForm } from "../runform";

const GROUPS: { kinds: ItemKind[]; title: string; hint: string }[] = [
  { kinds: ["robot"], title: "Robots", hint: "Click to run this robot" },
  { kinds: ["field"], title: "Fields", hint: "Click to run on this field" },
  { kinds: ["program"], title: "Python programs", hint: "Click to run this program" },
  { kinds: ["project"], title: "PROS projects", hint: "Click to build and run this project" },
  { kinds: ["input"], title: "Controller inputs", hint: "Click to drive with this recorded input" },
  { kinds: ["log"], title: "Telemetry logs", hint: "Click to play this log back, drawn with the robot and field picked above" },
  { kinds: ["scenario"], title: "Benchmark scenarios", hint: "Benchmarks get their own page in a later version" },
  { kinds: ["invalid"], title: "Unreadable configs", hint: "Click to open it and fix the YAML" },
];

function inUse(item: WorkspaceItem, form: RunForm, shownLog: string | null): boolean {
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
    case "log":
      return shownLog === item.path;
    default:
      return false;
  }
}

type Tab = "workspace" | "runs";

/** The workspace's files, to pick from, and the recorded runs. */
export function Sidebar(props: {
  workspace: WorkspaceInfo | null;
  form: RunForm;
  onPick: (item: WorkspaceItem) => void;
  onEdit: (item: WorkspaceItem) => void; // open a robot or field config in its editor
  onRefresh: () => void;
  loading: boolean;
  shownLog: string | null; // the telemetry log being played back
  runs: ReactNode; // the Runs tab
  runCount: number;
  onRunsTab: () => void; // the Runs tab was opened: time to look for new runs
}) {
  const { workspace, form, onPick } = props;
  const [tab, setTab] = useState<Tab>("workspace");
  const choose = (next: Tab) => {
    setTab(next);
    if (next === "runs") props.onRunsTab();
  };
  return (
    <nav className="sidebar" aria-label="Workspace and runs" data-testid="workspace">
      <div className="sidebar-head" role="tablist">
        <button role="tab" aria-selected={tab === "workspace"} className={tab === "workspace" ? "on" : ""} onClick={() => choose("workspace")} data-testid="tab-workspace">
          Workspace
        </button>
        <button role="tab" aria-selected={tab === "runs"} className={tab === "runs" ? "on" : ""} onClick={() => choose("runs")} data-testid="tab-runs">
          Runs {props.runCount > 0 && <span className="count">{props.runCount}</span>}
        </button>
        <span className="spacer" />
        {tab === "workspace" && (
          <button className="ghost small" onClick={props.onRefresh} disabled={props.loading} title="Look for new and changed files">
            {props.loading ? "Scanning…" : "Refresh"}
          </button>
        )}
      </div>
      {tab === "runs" ? (
        props.runs
      ) : (
        <>
          {workspace && workspace.items.length === 0 && (
            <p className="muted pad">No robot configs, programs or PROS projects in this folder yet.</p>
          )}
          {GROUPS.map((group) => {
            const items = workspace?.items.filter((item) => group.kinds.includes(item.kind)) ?? [];
            if (!items.length) return null;
            const pickable = group.kinds[0] !== "scenario";
            const editable = ["robot", "field"].includes(group.kinds[0]);
            return (
              <section key={group.title} className="group">
                <h2>
                  {group.title} <span className="count">{items.length}</span>
                </h2>
                <ul>
                  {items.map((item) => {
                    const selected = inUse(item, form, props.shownLog);
                    return (
                      <li key={item.kind + item.path} className={editable ? "editable" : undefined}>
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
                        {editable && (
                          <button
                            type="button"
                            className="ghost small item-edit"
                            onClick={() => props.onEdit(item)}
                            title={`Edit ${item.path}: its YAML beside a diagram you can drag`}
                            data-testid={`edit-${item.path}`}
                          >
                            Edit
                          </button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}
        </>
      )}
    </nav>
  );
}
