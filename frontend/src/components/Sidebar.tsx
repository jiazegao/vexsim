import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { embedded, HOSTS, openInHost } from "../host";
import type { ItemKind, WorkspaceInfo, WorkspaceItem } from "../protocol";
import type { Editor } from "../problems";
import { absolute, EDITORS, editorUrl } from "../problems";
import type { RunForm } from "../runform";
import type { MenuAction } from "./ItemMenu";
import { ItemMenu } from "./ItemMenu";

const GROUPS: { kinds: ItemKind[]; title: string; hint: string }[] = [
  { kinds: ["robot"], title: "Robots", hint: "Click to run this robot" },
  { kinds: ["field"], title: "Fields", hint: "Click to run on this field" },
  { kinds: ["program"], title: "Python programs", hint: "Click to run this program" },
  { kinds: ["project"], title: "PROS projects", hint: "Click to build and run this project" },
  { kinds: ["route"], title: "Autonomous routes", hint: "Click to run this route in its project's autonomous()" },
  { kinds: ["input"], title: "Controller inputs", hint: "Click to drive with this recorded input" },
  { kinds: ["log"], title: "Telemetry logs", hint: "Click to play this log back, drawn with the robot and field picked above" },
  { kinds: ["robotlog"], title: "Robot logs", hint: "Click to calibrate the simulated robot with this log" },
  { kinds: ["mcllog"], title: "MCL logs", hint: "Click to play this real robot's log on the field, beside the simulator" },
  { kinds: ["scenario"], title: "Benchmark scenarios", hint: "Click to benchmark it" },
  { kinds: ["invalid"], title: "Unreadable configs", hint: "Click to open it and fix the YAML" },
];

// What a click does on pages that take the item themselves
const PAGE_HINTS: Record<string, Partial<Record<ItemKind, string>>> = {
  analyze: { robot: "Click to analyze this robot" },
  calibrate: { robot: "Click to calibrate this robot", project: "Click to add the calibration routine to this project" },
  build: { project: "Click to pick this project" },
};

function inUse(item: WorkspaceItem, form: RunForm, shownLog: string | null, mclLog: string | null): boolean {
  switch (item.kind) {
    case "robot":
      return form.robot === item.path;
    case "field":
      return form.field === item.path;
    case "program":
    case "project":
      return form.program === item.path;
    case "route":
      return form.route === item.path;
    case "input":
      return form.input === item.path;
    case "log":
      return shownLog === item.path;
    case "mcllog":
      return mclLog === item.path;
    default:
      return false;
  }
}

type Tab = "workspace" | "runs";

const CONFIGS: readonly ItemKind[] = ["robot", "field", "invalid"]; // edited in the app

/** What an item's menu offers: Edit (a config in its editor here, any other file in your
 * editor), Duplicate and Delete (files, not a project's folder). */
function itemActions(item: WorkspaceItem, root: string, editor: Editor, unsaved: boolean, act: {
  edit: () => void;
  duplicate: () => Promise<void>;
  remove: () => Promise<void>;
}): MenuAction[] {
  const folder = item.kind === "project" ? "A PROS project is a folder: copy or delete it with your file manager" : null;
  let edit: MenuAction;
  if (CONFIGS.includes(item.kind)) {
    edit = { label: "Edit", testid: `edit-${item.path}`, title: "Open it in its editor: its YAML beside a diagram you can drag", run: act.edit };
  } else {
    // a project opens at its src/main.cpp
    const file = absolute(root, item.kind === "project" ? `${item.path}/src/main.cpp` : item.path);
    if (embedded) {
      edit = { label: `Edit in ${HOSTS[embedded] ?? embedded}`, testid: `edit-${item.path}`, run: () => openInHost(file, 1, null) };
    } else {
      const href = editorUrl(editor, root, { file, line: 1, column: null });
      edit = href
        ? { label: `Edit in ${EDITORS[editor]}`, testid: `edit-${item.path}`, href }
        : { label: "Edit", testid: `edit-${item.path}`, disabled: "Pick an editor under “Open files in”, below the field, to edit it from here" };
    }
  }
  return [
    edit,
    { label: "Duplicate", testid: `duplicate-${item.path}`, title: "A copy beside it", run: act.duplicate, disabled: folder },
    {
      label: "Delete",
      testid: `delete-${item.path}`,
      run: act.remove,
      disabled: folder,
      confirm: `Delete ${item.path}?${unsaved ? " Its unsaved changes go too." : ""} It can't be undone.`,
    },
  ];
}

/** The workspace's files, to pick from, and the recorded runs. */
export function Sidebar(props: {
  workspace: WorkspaceInfo | null;
  form: RunForm;
  page: string; // the page on show: some take what's clicked themselves
  picked: string[] | null; // what that page has picked (null: the run form's picks show)
  onPick: (item: WorkspaceItem) => void;
  onEdit: (item: WorkspaceItem) => void; // open a robot or field config in its editor
  onDuplicate: (item: WorkspaceItem) => Promise<string>; // a copy beside it: its path
  onDelete: (item: WorkspaceItem) => Promise<void>;
  unsaved: Record<string, boolean>; // configs with changes not saved, in their editors
  editor: Editor; // where files that aren't configs are edited
  onNewRobot: () => void;
  onRefresh: () => void;
  loading: boolean;
  shownLog: string | null; // the telemetry log being played back
  mclLog: string | null; // the MCL log open beside the simulator
  runs: ReactNode; // the Runs tab
  runCount: number;
  onRunsTab: () => void; // the Runs tab was opened: time to look for new runs
}) {
  const { workspace, form, onPick } = props;
  const [tab, setTab] = useState<Tab>("workspace");
  const [menu, setMenu] = useState<{ item: WorkspaceItem; at: { x: number; y: number }; id: number } | null>(null);
  const [fresh, setFresh] = useState<string | null>(null); // just made: shown, and lit up a moment
  const opened = useRef(0);
  // a menu closes itself, not one opened since (its action still going when another opened)
  const closeMenu = useCallback((id: number) => setMenu((open) => (open?.id === id ? null : open)), []);
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!fresh) return;
    list.current?.querySelector(`[data-testid="item-${CSS.escape(fresh)}"]`)?.scrollIntoView({ block: "nearest" });
    const timer = setTimeout(() => setFresh(null), 2500);
    return () => clearTimeout(timer);
  }, [fresh, workspace]);
  /** The menu, at the pointer (a right-click) or, from the keyboard or its ⋯ button, below
   * the item. */
  const openMenu = (item: WorkspaceItem, event: React.MouseEvent) => {
    event.preventDefault();
    const box = (event.currentTarget as HTMLElement).getBoundingClientRect();
    const pointer = event.type === "contextmenu" && (event.clientX || event.clientY);
    const at = pointer ? { x: event.clientX, y: event.clientY } : { x: box.left, y: box.bottom };
    setMenu((open) => (event.type === "click" && open?.item.path === item.path ? null : { item, at, id: ++opened.current }));
  };
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
        <div ref={list}>
          {workspace && workspace.items.length === 0 && (
            <p className="muted pad">No robot configs, programs or PROS projects in this folder yet.</p>
          )}
          {workspace && !workspace.items.some((item) => item.kind === "robot") && (
            <section className="group">
              <h2>
                Robots{" "}
                <button type="button" className="ghost small group-action" onClick={props.onNewRobot} data-testid="new-robot">
                  New…
                </button>
              </h2>
            </section>
          )}
          {GROUPS.map((group) => {
            const items = workspace?.items.filter((item) => group.kinds.includes(item.kind)) ?? [];
            if (!items.length) return null;
            const hint = PAGE_HINTS[props.page]?.[group.kinds[0]] ?? group.hint;
            return (
              <section key={group.title} className="group">
                <h2>
                  {group.title} <span className="count">{items.length}</span>
                  {group.kinds[0] === "robot" && (
                    <button type="button" className="ghost small group-action" onClick={props.onNewRobot} title="Make a robot: draw it, pick its drive and sensors" data-testid="new-robot">
                      New…
                    </button>
                  )}
                </h2>
                <ul>
                  {items.map((item) => {
                    const selected = props.picked ? props.picked.includes(item.path) : inUse(item, form, props.shownLog, props.mclLog);
                    return (
                      <li key={item.kind + item.path} className="with-menu" onContextMenu={(e) => openMenu(item, e)}>
                        <button
                          className={`item${selected ? " selected" : ""}${fresh === item.path ? " fresh" : ""}`}
                          data-testid={`item-${item.path}`}
                          title={`${item.path}\n${hint}\nRight-click for Edit, Duplicate and Delete`}
                          aria-pressed={selected}
                          onClick={() => onPick(item)}
                        >
                          <span className="item-name">{item.name}</span>
                          <span className="item-detail">{item.problem ? "" : item.detail}</span>
                          {item.problem && (
                            <span className="item-problem">
                              <span aria-hidden="true">⚠</span> {item.problem}
                            </span>
                          )}
                        </button>
                        <button
                          type="button"
                          className="ghost small item-more"
                          onClick={(e) => openMenu(item, e)}
                          title="Edit, duplicate or delete it (or right-click it)"
                          aria-label={`More for ${item.name}`}
                          aria-haspopup="menu"
                          aria-expanded={menu?.item.path === item.path}
                          data-menu-trigger=""
                          data-testid={`menu-${item.path}`}
                        >
                          ⋯
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}
        </div>
      )}
      {menu && (
        <ItemMenu
          key={menu.id}
          label={`${menu.item.name}: what to do with it`}
          at={menu.at}
          onClose={() => closeMenu(menu.id)}
          actions={itemActions(menu.item, workspace?.root ?? "", props.editor, !!props.unsaved[menu.item.path], {
            edit: () => props.onEdit(menu.item),
            duplicate: async () => setFresh(await props.onDuplicate(menu.item)),
            remove: () => props.onDelete(menu.item),
          })}
        />
      )}
    </nav>
  );
}
