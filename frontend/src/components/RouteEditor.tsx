import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { spanRange } from "../configdoc";
import { isActive, useJob } from "../jobs";
import type { RouteCheck, RouteEdit, RouteFile, RouteFunctionInfo, RouteParamInfo, RouteRun, RouteStepData, TextSpan, WorkspaceInfo } from "../protocol";
import type { Dragged, LemPose, Motion, Point, StepValue } from "../route";
import { bearing, copiedSteps, copySteps, describe, dropEdit, isMotion, MOTION_INFO, MOTIONS, newStep, OPTION_DEFAULTS, plan, relativePath, stepValue, withDrag } from "../route";
import { marksOf, RouteField } from "./RouteField";
import type { YamlEditorHandle } from "./YamlEditor";
import { YamlEditor } from "./YamlEditor";

const CHECK_DELAY_MS = 250; // after the last keystroke
const RUN_DELAY_MS = 600; // after the last edit: then the route runs headless
const FIELD_TOOLS: readonly Motion[] = ["move_to_point", "move_to_pose", "turn_to_point", "swing_to_point"];
const SNAPS = [
  ["tile", "Tiles"],
  ["half", "Half tiles"],
  ["quarter", "Quarter tiles"],
  ["inch", "Inches"],
] as const;
type Snap = (typeof SNAPS)[number][0];

interface Checked {
  text: string; // the text this is the check of
  result: RouteCheck;
}

/** A route: its steps beside its field, each step's end drawn as planned the moment it
 * changes and as simulated a moment later. The YAML stays the route: every change here is
 * written into it in place (comments and all), it has a YAML view, and Undo covers both;
 * nothing is written to the file until Save (Ctrl+S). */
export function RouteEditor(props: {
  path: string;
  active: boolean;
  closing: boolean; // its tab is being closed with unsaved changes: ask first
  workspace: WorkspaceInfo | null;
  onClose: () => void;
  onKeepOpen: () => void;
  onDirty: (path: string, dirty: boolean) => void;
  onSaved: (path: string) => void;
  onWatch: (path: string) => void; // run it on the Simulate page
  onOpen: (path: string) => void; // a route made from this one (a mirrored copy)
}) {
  const { path } = props;
  const [file, setFile] = useState<RouteFile | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [saved, setSaved] = useState<{ text: string; version: string } | null>(null);
  const [checked, setChecked] = useState<Checked | null>(null);
  const [shown, setShown] = useState<RouteCheck | null>(null); // the last check whose route read
  const [selected, setSelected] = useState<number | null>(null);
  const [view, setView] = useState<"steps" | "yaml">("steps");
  const [notice, setNotice] = useState<{ bad: boolean; text: string } | null>(null);
  const [conflict, setConflict] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dragged, setDragged] = useState<Dragged | null>(null);
  const [tool, setTool] = useState<Motion | null>(null);
  const [snap, setSnap] = useState<Snap>("half");
  const [run, setRun] = useState<{ text: string; result: RouteRun } | null>(null);
  const [runError, setRunError] = useState<{ text: string; message: string } | null>(null);
  const editor = useRef<YamlEditorHandle>(null);
  const textRef = useRef(text);
  textRef.current = text;
  const queue = useRef<Promise<unknown>>(Promise.resolve()); // changes, one after another
  const runFor = useRef<string | null>(null);

  const take = useCallback((forText: string, result: RouteCheck) => {
    setChecked({ text: forText, result });
    if (result.route) setShown(result);
  }, []);

  const load = useCallback(async () => {
    try {
      const opened = await api.route(path);
      setFile(opened);
      setSaved({ text: opened.text, version: opened.version });
      setText(opened.text);
      take(opened.text, opened.check);
      setLoadError(null);
    } catch (error) {
      setLoadError((error as Error).message);
    }
  }, [path, take]);
  useEffect(() => {
    load();
  }, [load]);

  // checked as it's typed
  useEffect(() => {
    if (!file || checked?.text === text) return;
    let current = true;
    const timer = setTimeout(() => {
      api
        .checkRoute(path, text)
        .then((result) => current && textRef.current === text && take(text, result))
        .catch(() => {});
    }, CHECK_DELAY_MS);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [file, path, text, checked, take]);

  const dirty = saved !== null && text !== saved.text;
  const { onDirty } = props;
  useEffect(() => onDirty(path, dirty), [onDirty, dirty, path]);

  const result = checked?.result ?? null;
  const current = checked?.text === text;
  const issues = result?.issues ?? [];
  const errors = issues.filter((i) => i.severity === "error").length;
  const route = shown?.route ?? null;
  const steps = route?.steps ?? [];
  const functions = shown?.functions ?? [];
  const stale = !current || !result?.route;

  // the simulated run: a moment after each change, the route as it is runs headless (a newer
  // change cancels it), and each step's end in it is drawn beside the plan
  const job = useJob((ended) => {
    const forText = runFor.current;
    if (forText === null) return;
    if (ended.state === "succeeded" && ended.result) setRun({ text: forText, result: ended.result as unknown as RouteRun });
    else if (ended.state === "failed") setRunError({ text: forText, message: ended.error ?? "it failed" });
  });
  const runnable = current && !!result?.route && errors === 0 && props.active;
  const { start: startJob, cancel: cancelJob } = job;
  useEffect(() => {
    if (!runnable || run?.text === text || runFor.current === text) return;
    const timer = setTimeout(() => {
      cancelJob();
      runFor.current = text;
      setRunError(null);
      startJob({ kind: "route", route: path, text, seed: 0 }).then((problem) => {
        if (problem) setRunError({ text, message: problem.error });
      });
    }, RUN_DELAY_MS);
    return () => clearTimeout(timer);
  }, [runnable, text, run, path, startJob, cancelJob]);
  useEffect(() => cancelJob, [cancelJob]); // the tab closed: its run is of no more use
  const simulated = run?.text === text ? run.result : null;
  const running = isActive(job.job?.state) && runFor.current === text;

  // the plan: each step's end as LemLib's targets say, following a drag as it goes
  const ran = useMemo(() => simulated?.steps.map((s) => (s.pose ? ([...s.pose] as unknown as LemPose) : null)) ?? [], [simulated]);
  const drawn = useMemo(() => (route ? withDrag(route, dragged) : null), [route, dragged]);
  const planned = useMemo(() => (drawn ? plan(drawn, functions, shown?.track ?? 12, ran) : []), [drawn, functions, shown, ran]);
  const marks = useMemo(() => marksOf(planned, shown?.preview ?? null), [planned, shown]);
  const fieldSize = shown?.preview?.field.size ?? [144, 144];
  const tile = fieldSize[0] / 6;
  const snapInches = { tile, half: tile / 2, quarter: tile / 4, inch: 1 }[snap];

  useEffect(() => {
    if (selected !== null && selected >= steps.length) setSelected(steps.length ? steps.length - 1 : null);
  }, [selected, steps.length]);

  /** A change the server writes into the text: made after the ones before it, on the text
   * they left. Rejects, having said why, if it can't be made. */
  const change = (edits: RouteEdit[], done: string | null = null): Promise<void> => {
    const made = queue.current.then(async () => {
      if (!file) throw new Error("not loaded");
      try {
        const base = textRef.current;
        const patched = await api.patchRoute(path, base, edits);
        if (textRef.current !== base) throw new Error("The text changed while that was being written: make the change again.");
        textRef.current = patched.text;
        editor.current?.replace(patched.text);
        setText(patched.text);
        take(patched.text, patched.check);
        setNotice(done ? { bad: false, text: done } : null);
      } catch (error) {
        setNotice({ bad: true, text: (error as Error).message });
        throw error;
      }
    });
    queue.current = made.catch(() => {});
    return made;
  };
  const set = (location: string, value: unknown, done: string | null = null) => change([{ op: "set", location, value }], done).catch(() => {});
  /** An option back to LemLib's default: taken out (if it's written). */
  const unset = (index: number, key: string) => {
    if (!(key in (steps[index]?.options ?? {})) && !(key in (steps[index]?.args ?? {}))) return;
    change([{ op: "remove", location: `steps[${index}].${key}` }]).catch(() => {});
  };

  // --- steps --------------------------------------------------------------------------------

  /** Where the robot is before step `index`, as planned. */
  const before = (index: number): LemPose => (index === 0 || !planned[index - 1] ? (route?.start ?? [0, 0, 0]) : planned[index - 1].pose);
  const insert = (value: StepValue, at: number, done: string) =>
    change([{ op: "insert", location: `steps[${at}]`, value }], done)
      .then(() => setSelected(at))
      .catch(() => {});
  const afterSelected = () => (selected === null ? steps.length : selected + 1);
  const addKind = (kind: string, fn?: RouteFunctionInfo) => {
    const at = afterSelected();
    const step = newStep(kind, before(at), fn);
    insert(stepValue(step), at, `Added step ${at + 1}: ${describe(step)}.`);
  };
  const addAt = (kind: Motion, point: Point) => {
    const at = afterSelected();
    const from = before(at);
    const target = kind === "move_to_pose" ? [point[0], point[1], Math.round(bearing([from[0], from[1]], point))] : [point[0], point[1]];
    const step = newStep(kind, from, undefined, target);
    insert(stepValue(step), at, `Added step ${at + 1}: ${describe(step)}.`);
  };
  const remove = (index: number) =>
    change([{ op: "remove", location: `steps[${index}]` }], `Took step ${index + 1} out (Undo brings it back).`)
      .then(() => setSelected(steps.length > 1 ? Math.min(index, steps.length - 2) : null))
      .catch(() => {});
  const duplicate = (index: number) => insert(stepValue(steps[index]), index + 1, `Step ${index + 2} is a copy of step ${index + 1}.`);
  const move = (from: number, to: number) => {
    if (to < 0 || to >= steps.length || from === to) return;
    change([{ op: "move", location: `steps[${from}]`, value: to }], `Moved step ${from + 1} to ${to + 1}.`)
      .then(() => setSelected(to))
      .catch(() => {});
  };
  const copy = () => {
    if (selected === null || !steps[selected]) return setNotice({ bad: false, text: "Select a step to copy first." });
    copySteps([stepValue(steps[selected])]);
    setNotice({ bad: false, text: `Copied step ${selected + 1}: Ctrl+V pastes it after the selected step, in this route or another.` });
  };
  const paste = () => {
    const copied = copiedSteps();
    if (!copied?.length) return setNotice({ bad: false, text: "Nothing's copied yet: select a step and press Ctrl+C." });
    const at = afterSelected();
    insert(copied[0], at, `Pasted it as step ${at + 1}.`);
  };
  const dropped = (d: Dragged) => {
    if (!route) return;
    setDragged(d);
    change([dropEdit(route, d)])
      .catch(() => {}) // the notice says why
      .finally(() => setDragged(null));
  };

  const save = async (version: string | null = saved?.version ?? null): Promise<boolean> => {
    setSaving(true);
    const writing = textRef.current;
    try {
      const outcome = await api.saveConfig(path, writing, version);
      if ("conflict" in outcome) {
        setConflict(true);
        return false;
      }
      setSaved({ text: writing, version: outcome.version });
      setConflict(false);
      setNotice(errors ? { bad: true, text: `Saved, with ${errors} error${errors > 1 ? "s" : ""}: it won't run until they're fixed.` } : { bad: false, text: "Saved." });
      props.onSaved(path);
      return true;
    } catch (error) {
      setNotice({ bad: true, text: `Couldn't save: ${(error as Error).message}` });
      return false;
    } finally {
      setSaving(false);
    }
  };
  const reloadFromDisk = async () => {
    const opened = await api.route(path).catch((error: Error) => {
      setNotice({ bad: true, text: error.message });
      return null;
    });
    if (!opened) return;
    editor.current?.replace(opened.text);
    setText(opened.text);
    setSaved({ text: opened.text, version: opened.version });
    take(opened.text, opened.check);
    setConflict(false);
    setNotice({ bad: false, text: "Loaded the file as it is on disk (Undo brings yours back)." });
  };
  const watch = async () => {
    if (dirty && !(await save())) return;
    props.onWatch(path);
  };
  const mirror = async (axis: "x" | "y") => {
    try {
      const made = await api.mirrorRoute(path, textRef.current, axis);
      props.onOpen(made.path);
      const across = axis === "x" ? "left and right (x = 0)" : "top and bottom (y = 0)";
      setNotice({ bad: made.notes.length > 0, text: [`Made ${made.path}, mirrored ${across}.`, ...made.notes].join(" ") });
    } catch (error) {
      setNotice({ bad: true, text: `Couldn't mirror it: ${(error as Error).message}` });
    }
  };

  // Ctrl+S anywhere on this tab (the YAML editor handles its own first)
  const saveRef = useRef(() => {});
  saveRef.current = () => {
    if (dirty && !saving) save();
  };
  useEffect(() => {
    if (!props.active) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "s") return;
      event.preventDefault();
      saveRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [props.active]);

  /** The step list's and the field's keys (not while typing in a box or the YAML). */
  const onKey = (event: React.KeyboardEvent) => {
    const target = event.target as HTMLElement;
    if (target.closest("input, select, textarea, .cm-editor")) return;
    const command = event.ctrlKey || event.metaKey;
    const key = event.key.toLowerCase();
    if (command && key === "c" && !event.shiftKey) copy();
    else if (command && key === "v" && !event.shiftKey) paste();
    else if (command && key === "d" && selected !== null) duplicate(selected);
    else if (command && key === "z") (event.shiftKey ? editor.current?.redo() : editor.current?.undo());
    else if (command && key === "y") editor.current?.redo();
    else if ((key === "delete" || key === "backspace") && selected !== null) remove(selected);
    else if (key === "arrowup" && selected !== null) (event.altKey ? move(selected, selected - 1) : setSelected(Math.max(0, selected - 1)));
    else if (key === "arrowdown" && steps.length) (event.altKey ? move(selected ?? 0, (selected ?? 0) + 1) : setSelected(Math.min(steps.length - 1, (selected ?? -1) + 1)));
    else if (key === "escape") (tool ? setTool(null) : setSelected(null));
    else return;
    event.preventDefault();
  };

  /** Where something is written, shown in the YAML view. */
  const showText = (span: TextSpan) => {
    setView("yaml");
    requestAnimationFrame(() => {
      const { from, to } = spanRange(textRef.current, span);
      editor.current?.select(from, to);
      editor.current?.focus();
    });
  };

  if (loadError) {
    return (
      <section className="config-editor" hidden={!props.active} aria-label={`Editing ${path}`}>
        <div className="banner" role="alert">
          Can't open {path}: {loadError}
          <button type="button" className="ghost small" onClick={props.onClose}>
            Close
          </button>
        </div>
      </section>
    );
  }
  const robots = props.workspace?.items.filter((i) => i.kind === "robot") ?? [];
  const fields = props.workspace?.items.filter((i) => i.kind === "field") ?? [];
  const stepIssues = (index: number) => issues.filter((i) => i.location === `steps[${index}]` || i.location.startsWith(`steps[${index}].`));
  const ends = simulated?.ended_s;
  return (
    <section className="config-editor route-editor" hidden={!props.active} aria-label={`Editing ${path}`} data-testid="route-editor" data-path={path} onKeyDown={onKey}>
      <div className="editor-bar">
        <span className="editor-path" title={path}>
          {path}
        </span>
        {!file && <span className="muted small">opening…</span>}
        <span className="view-switch" role="group" aria-label="Show">
          <button type="button" className={`small${view === "steps" ? " on" : ""}`} aria-pressed={view === "steps"} onClick={() => setView("steps")} title="Its steps, each opened into a form" data-testid="view-steps">
            Steps
          </button>
          <button type="button" className={`small${view === "yaml" ? " on" : ""}`} aria-pressed={view === "yaml"} onClick={() => setView("yaml")} title="The route's text" data-testid="view-yaml">
            YAML
          </button>
        </span>
        <span className="spacer" />
        <span className={`editor-state small${errors ? " bad" : ""}`} data-testid="route-state">
          {!current ? "checking…" : issues.length ? `${errors} error${errors === 1 ? "" : "s"}, ${issues.length - errors} warning${issues.length - errors === 1 ? "" : "s"}` : "no problems"}
          {dirty ? " · unsaved changes" : ""}
        </span>
        <button type="button" onClick={() => editor.current?.undo()} title="Undo the last change (Ctrl+Z)" data-testid="undo">
          Undo
        </button>
        <button type="button" onClick={() => editor.current?.redo()} title="Redo it (Ctrl+Shift+Z)" data-testid="redo">
          Redo
        </button>
        <button type="button" onClick={watch} disabled={!route || errors > 0 || saving} title="Run it on the Simulate page, with its timeline and plots (saving it first)" data-testid="watch">
          Watch
        </button>
        <button type="button" onClick={() => saved && editor.current?.replace(saved.text)} disabled={!dirty || saving} title="Back to the file as it was saved (Undo undoes this too)">
          Revert
        </button>
        <button type="button" className="primary" onClick={() => save()} disabled={!dirty || saving} data-testid="save-route" title="Write it to the file (Ctrl+S)">
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
      {props.closing && (
        <div className="editor-ask" role="alertdialog" aria-label="Unsaved changes">
          Save your changes to {path} before closing?
          <button type="button" className="primary small" onClick={async () => (await save()) && props.onClose()}>
            Save
          </button>
          <button type="button" className="small" onClick={props.onClose}>
            Don't save
          </button>
          <button type="button" className="ghost small" onClick={props.onKeepOpen}>
            Cancel
          </button>
        </div>
      )}
      {conflict && (
        <div className="editor-ask bad" role="alert">
          {path} changed on disk since you opened it.
          <button type="button" className="small" onClick={() => save(null)}>
            Save yours over it
          </button>
          <button type="button" className="small" onClick={reloadFromDisk}>
            Load the file's
          </button>
        </div>
      )}
      {notice && (
        <div className={`editor-notice small${notice.bad ? " bad" : ""}`} role="status" data-testid="route-notice">
          {notice.text}
        </div>
      )}
      <div className="editor-split designing">
        <div className="editor-text" hidden={view !== "yaml"}>
          {file && (
            <YamlEditor
              ref={editor}
              initial={file.text}
              issues={checked ? { text: checked.text, issues: checked.result.issues } : null}
              onChange={setText}
              onCursor={(line) => {
                const places = result?.places ?? {};
                const at = Object.entries(places).find(([key, span]) => key.startsWith("steps[") && span.line === line);
                if (at && current) setSelected(Number(at[0].slice(6, -1)));
              }}
              onSave={() => dirty && save()}
              label={`${path}, YAML`}
            />
          )}
        </div>
        {view === "steps" && (
          <div className="design-panel route-panel" data-testid="route-panel">
            {!route ? (
              <p className="muted small">{file ? "This route's YAML doesn't read, so there's nothing to show here yet: fix it in the YAML view." : "Opening…"}</p>
            ) : (
              <fieldset disabled={stale && current}>
                <RouteHead
                  path={path}
                  check={shown!}
                  robots={robots.map((r) => [r.path, r.name] as const)}
                  fields={fields.map((f) => [f.path, f.name] as const)}
                  onSet={(location, value) => set(location, value)}
                  onAdd={(location, value) => change([{ op: "add", location, value }]).catch(() => {})}
                  onRemove={(location) => change([{ op: "remove", location }]).catch(() => {})}
                />
                <section>
                  <h3>
                    Steps <span className="count">{steps.length}</span>
                  </h3>
                  <ol className="route-steps" data-testid="steps">
                    {steps.map((step, i) => {
                      const end = simulated?.steps[i];
                      const off = end?.pose && planned[i] ? Math.hypot(end.pose[0] - planned[i].pose[0], end.pose[1] - planned[i].pose[1]) : null;
                      const found = stepIssues(i);
                      const level = found.some((x) => x.severity === "error") ? " error" : found.length || marks[i]?.length ? " warning" : "";
                      return (
                        <li
                          key={i}
                          className={`design-item route-step${i === selected ? " on" : ""}${level}`}
                          data-testid={`step-${i}`}
                          data-planned={planned[i]?.pose.map((v) => v.toFixed(2)).join(",")}
                          draggable
                          onDragStart={(e) => e.dataTransfer.setData("text/x-vexsim-step", String(i))}
                          onDragOver={(e) => e.dataTransfer.types.includes("text/x-vexsim-step") && e.preventDefault()}
                          onDrop={(e) => {
                            const from = Number(e.dataTransfer.getData("text/x-vexsim-step"));
                            if (Number.isInteger(from)) move(from, i);
                          }}
                        >
                          <div className="design-item-head" onClick={() => setSelected(i === selected ? null : i)}>
                            <span className="step-number" aria-hidden="true">
                              {i + 1}
                            </span>
                            <span className="step-label">{describe(step)}</span>
                            <span className="step-end small" data-testid={`step-end-${i}`} data-pose={end?.pose?.map((v) => v.toFixed(2)).join(",") ?? ""}>
                              {!planned[i]?.known && !planned[i]?.ran ? <span title="Nothing says where it goes: it's carried on unmoved until a run says">?</span> : null}
                              {marks[i]?.length ? <span className="bad" title={`Its end hits ${marks[i].join(" and ")}`}>⚠</span> : null}
                              {end?.ended_s != null ? ` ${end.ended_s.toFixed(2)} s` : ""}
                              {off != null ? ` · ${off.toFixed(1)} in off` : ""}
                              {end?.timed_out ? <span className="bad" title="It used up its timeout"> ⏱</span> : null}
                            </span>
                          </div>
                          {i === selected && (
                            <StepForm
                              step={step}
                              index={i}
                              functions={functions}
                              issues={found.map((x) => x.message)}
                              onSet={(key, value) => set(`steps[${i}].${key}`, value)}
                              onUnset={(key) => unset(i, key)}
                              onReplace={(value) => set(`steps[${i}]`, value)}
                              onDuplicate={() => duplicate(i)}
                              onRemove={() => remove(i)}
                            />
                          )}
                        </li>
                      );
                    })}
                  </ol>
                  {!steps.length && <p className="muted small">No steps yet: add one, or pick a motion tool and click the field.</p>}
                  <AddStep functions={functions} onAdd={addKind} />
                </section>
              </fieldset>
            )}
          </div>
        )}
        <div className="route-side">
          <div className="route-tools" role="toolbar" aria-label="Field tools">
            <button type="button" className={`small${tool === null ? " on" : ""}`} aria-pressed={tool === null} onClick={() => setTool(null)} data-testid="tool-select" title="Select a step by its number; drag the start, and the selected step's target and heading">
              Select
            </button>
            {FIELD_TOOLS.map((kind) => (
              <button key={kind} type="button" className={`small${tool === kind ? " on" : ""}`} aria-pressed={tool === kind} onClick={() => setTool(tool === kind ? null : kind)} data-testid={`tool-${kind}`} title={`Click the field: a "${MOTION_INFO[kind].title.toLowerCase()}" step there`}>
                {MOTION_INFO[kind].title}
              </button>
            ))}
            <span className="view-switch route-mirror" role="group" aria-label="Mirror">
              <button type="button" className="small" onClick={() => mirror("x")} disabled={!route || stale} title="A copy for the other side of the field: mirrored left and right, across x = 0" data-testid="mirror-x">
                Mirror ↔
              </button>
              <button type="button" className="small" onClick={() => mirror("y")} disabled={!route || stale} title="A copy for the other side of the field: mirrored top and bottom, across y = 0" data-testid="mirror-y">
                Mirror ↕
              </button>
            </span>
            <label className="small">
              Snap{" "}
              <select value={snap} onChange={(e) => setSnap(e.target.value as Snap)} data-testid="route-snap">
                {SNAPS.map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <RouteField
            preview={shown?.preview ?? null}
            start={drawn?.start ?? null}
            steps={drawn?.steps ?? []}
            planned={planned}
            marks={marks}
            selected={selected}
            run={simulated}
            stale={stale}
            snap={snapInches}
            tool={tool}
            onSelect={setSelected}
            onDrag={(d) => d && setDragged(d)}
            onDrop={dropped}
            onAdd={addAt}
          />
          <p className="route-sim small" data-testid="route-sim">
            {running
              ? "Simulating… (a project's first run builds it first)"
              : runError?.text === text
                ? `Couldn't simulate it: ${runError.message}`
                : simulated
                  ? simulated.error
                    ? `Simulated: ${simulated.error}`
                    : simulated.finished && ends != null
                      ? `Simulated: done ${ends.toFixed(2)} s into the ${simulated.period_s} s autonomous period${ends > simulated.period_s ? " (too long!)" : ""}`
                      : "Simulated: some steps didn't end"
                  : errors
                    ? "It runs once its errors are fixed."
                    : "It runs a moment after each change."}
          </p>
        </div>
      </div>
      <div className="editor-foot">
        <ul className="config-problems" data-testid="route-problems">
          {issues.length === 0 ? (
            <li className="muted">{current ? "No problems." : "Checking…"}</li>
          ) : (
            issues.map((issue, i) => (
              <li key={i}>
                <span className={`badge ${issue.severity}`}>{issue.severity}</span>
                <button type="button" className="place" disabled={!issue.span || !current} onClick={() => issue.span && showText(issue.span)}>
                  {issue.location || "(document)"}
                  {issue.span ? ` (line ${issue.span.line})` : ""}
                </button>{" "}
                <span className="message">{issue.message}</span>
              </li>
            ))
          )}
        </ul>
      </div>
    </section>
  );
}

/** A number box: changes are written when it's left or Enter is pressed; empty means
 * the default (shown as its placeholder). */
function NumberBox(props: { value: number | null | undefined; label: string; placeholder?: string; whole?: boolean; onCommit: (value: number | null) => void; testid?: string; wide?: boolean }) {
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? (props.value == null ? "" : String(props.value));
  const commit = () => {
    if (draft === null) return;
    const typed = draft.trim();
    setDraft(null);
    if (typed === "") {
      if (props.value != null) props.onCommit(null);
      return;
    }
    const value = Number(typed);
    if (!Number.isFinite(value) || (props.whole && !Number.isInteger(value))) return; // back to what it was
    if (value !== props.value) props.onCommit(value);
  };
  return (
    <input
      className={props.wide ? "wide" : "num"}
      inputMode="decimal"
      aria-label={props.label}
      title={props.label}
      value={shown}
      placeholder={props.placeholder}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") setDraft(null);
      }}
      data-testid={props.testid}
    />
  );
}

function Row(props: { label: string; children: ReactNode; unit?: string }) {
  return (
    <div className="design-row">
      <span className="design-label">{props.label}</span>
      <span className="design-values">{props.children}</span>
      <span className="design-unit muted">{props.unit ?? ""}</span>
    </div>
  );
}

/** The route's own settings: its name, start, robot, field and the headers of its functions. */
function RouteHead(props: {
  path: string;
  check: RouteCheck;
  robots: readonly (readonly [string, string])[];
  fields: readonly (readonly [string, string])[];
  onSet: (location: string, value: unknown) => void;
  onAdd: (location: string, value: unknown) => void; // to the end of the list there
  onRemove: (location: string) => void;
}) {
  const route = props.check.route!;
  const [name, setName] = useState<string | null>(null);
  const start = route.start;
  // each number on its own, so one changed just after another doesn't put the other back
  const setStart = (i: number, value: number | null) => value !== null && props.onSet(`start[${i}]`, value);
  const listed = new Set(route.functions);
  return (
    <section>
      <h3>Route</h3>
      <Row label="Name">
        <input
          className="wide"
          aria-label="Route name"
          value={name ?? route.name}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => {
            if (name !== null && name.trim() && name !== route.name) props.onSet("name", name.trim());
            setName(null);
          }}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          data-testid="route-name"
        />
      </Row>
      <Row label="Start" unit="in, °">
        <NumberBox value={start[0]} label="Start x (in)" onCommit={(v) => setStart(0, v)} testid="route-start-x" />
        <NumberBox value={start[1]} label="Start y (in)" onCommit={(v) => setStart(1, v)} testid="route-start-y" />
        <NumberBox value={start[2]} label="Start θ (degrees clockwise from +y)" onCommit={(v) => setStart(2, v)} testid="route-start-theta" />
      </Row>
      <Row label="Robot">
        <select
          className="wide"
          value={props.check.robot_path ?? ""}
          onChange={(e) => e.target.value && props.onSet("robot", relativePath(props.path, e.target.value))}
          aria-label="Robot"
          data-testid="route-robot"
        >
          {!props.check.robot_path && <option value="">{route.robot ?? "Pick one…"}</option>}
          {props.robots.map(([path, name]) => (
            <option key={path} value={path}>
              {name}
            </option>
          ))}
        </select>
      </Row>
      <Row label="Field">
        <select
          className="wide"
          value={props.check.field_path ?? ""}
          onChange={(e) => (e.target.value ? props.onSet("field", relativePath(props.path, e.target.value)) : route.field && props.onRemove("field"))}
          aria-label="Field"
          data-testid="route-field-select"
        >
          <option value="">Empty field (walls only)</option>
          {props.fields.map(([path, name]) => (
            <option key={path} value={path}>
              {name}
            </option>
          ))}
        </select>
      </Row>
      <details className="route-headers" open={route.functions.length === 0 && props.check.headers.length > 0}>
        <summary className="small">
          The team's functions: {route.functions.length ? route.functions.map((h) => h.split("/").at(-1)).join(", ") : "none yet"}
        </summary>
        {props.check.headers.map((header) => (
          <label key={header} className="small route-header">
            <input
              type="checkbox"
              checked={listed.has(header)}
              onChange={(e) => (e.target.checked ? props.onAdd("functions", header) : props.onRemove(`functions[${route.functions.indexOf(header)}]`))}
              data-testid={`header-${header}`}
            />{" "}
            {header}
          </label>
        ))}
        {!props.check.headers.length && <p className="muted small">The project has no headers of its own under include/.</p>}
      </details>
    </section>
  );
}

/** "Add": a motion, a pause or one of the team's functions, after the selected step. */
function AddStep(props: { functions: readonly RouteFunctionInfo[]; onAdd: (kind: string, fn?: RouteFunctionInfo) => void }) {
  const byHeader = new Map<string, RouteFunctionInfo[]>();
  for (const fn of props.functions) byHeader.set(fn.header, [...(byHeader.get(fn.header) ?? []), fn]);
  return (
    <select
      className="route-add"
      value=""
      aria-label="Add a step"
      onChange={(e) => {
        const [kind, name] = e.target.value.split(":");
        if (kind) props.onAdd(kind, props.functions.find((f) => f.name === name));
      }}
      data-testid="add-step"
    >
      <option value="">Add a step…</option>
      <optgroup label="LemLib motions">
        {MOTIONS.map((kind) => (
          <option key={kind} value={kind}>
            {MOTION_INFO[kind].title}
          </option>
        ))}
      </optgroup>
      <optgroup label="Pauses">
        <option value="wait">Wait (ms)</option>
        <option value="wait_until">Wait until the motion is this far along</option>
        <option value="wait_until_done">Wait until the motion is done</option>
      </optgroup>
      {[...byHeader].map(([header, list]) => (
        <optgroup key={header} label={header}>
          {list.map((fn) => (
            <option key={fn.name} value={`call:${fn.name}`} title={fn.declaration}>
              {fn.name}()
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

/** The selected step's form: everything it says, each written in place as it changes. */
function StepForm(props: {
  step: RouteStepData;
  index: number;
  functions: readonly RouteFunctionInfo[];
  issues: string[];
  onSet: (key: string, value: unknown) => void;
  onUnset: (key: string) => void;
  onReplace: (value: StepValue) => void;
  onDuplicate: () => void;
  onRemove: () => void;
}) {
  const { step, index } = props;
  const id = (key: string) => `step-${index}-${key}`;
  let body: ReactNode = null;
  if (isMotion(step.kind)) {
    const info = MOTION_INFO[step.kind];
    const target = step.target;
    const setTarget = (i: number, value: number | null) => value !== null && props.onSet(info.target === "heading" ? step.kind : `${step.kind}[${i}]`, value);
    const option = (key: string) => step.options[key];
    const number = (key: string, label: string, whole = false) => (
      <Row label={label} key={key}>
        <NumberBox
          value={typeof option(key) === "number" ? (option(key) as number) : null}
          label={`${label} (empty: LemLib's ${OPTION_DEFAULTS[key]})`}
          placeholder={String(OPTION_DEFAULTS[key])}
          whole={whole}
          onCommit={(v) => (v === null ? props.onUnset(key) : props.onSet(key, v))}
          testid={id(key)}
        />
      </Row>
    );
    body = (
      <>
        <Row label={info.target === "heading" ? "Heading" : info.target === "pose" ? "Pose" : "Point"} unit={info.target === "heading" ? "°" : "in"}>
          {info.target !== "heading" && (
            <>
              <NumberBox value={target[0]} label="x (in)" onCommit={(v) => setTarget(0, v)} testid={id("x")} />
              <NumberBox value={target[1]} label="y (in)" onCommit={(v) => setTarget(1, v)} testid={id("y")} />
            </>
          )}
          {info.target !== "point" && <NumberBox value={info.target === "pose" ? target[2] : target[0]} label="θ (degrees clockwise from +y)" onCommit={(v) => setTarget(info.target === "pose" ? 2 : 0, v)} testid={id("theta")} />}
        </Row>
        {info.swing && (
          <Row label="Locked side">
            <select value={step.side ?? "left"} onChange={(e) => props.onSet("locked_side", e.target.value)} data-testid={id("side")} aria-label="Locked side">
              <option value="left">left</option>
              <option value="right">right</option>
            </select>
          </Row>
        )}
        <Row label="Timeout" unit="ms">
          <NumberBox value={step.timeout} label="Timeout (ms)" whole onCommit={(v) => v !== null && props.onSet("timeout", v)} testid={id("timeout")} />
        </Row>
        {info.options.map((key) => {
          if (key === "forwards")
            return (
              <Row label="Drives" key={key}>
                <select value={option(key) === false ? "back" : "ahead"} onChange={(e) => (e.target.value === "back" ? props.onSet(key, false) : props.onUnset(key))} data-testid={id(key)} aria-label="Drives">
                  <option value="ahead">forwards</option>
                  <option value="back">backwards</option>
                </select>
              </Row>
            );
          if (key === "direction")
            return (
              <Row label="Turns" key={key}>
                <select value={String(option(key) ?? "auto")} onChange={(e) => (e.target.value === "auto" ? props.onUnset(key) : props.onSet(key, e.target.value))} data-testid={id(key)} aria-label="Turns">
                  <option value="auto">the short way (auto)</option>
                  <option value="cw">clockwise</option>
                  <option value="ccw">counter-clockwise</option>
                </select>
              </Row>
            );
          const labels: Record<string, string> = { max_speed: "Max speed", min_speed: "Min speed", early_exit: "Exit early", lead: "Lead", horizontal_drift: "Drift" };
          return number(key, labels[key] ?? key, (key === "max_speed" || key === "min_speed") && !!info.wholeSpeeds);
        })}
        <Row label="Then">
          <select value={option("async") === false ? "wait" : "go"} onChange={(e) => (e.target.value === "wait" ? props.onSet("async", false) : props.onUnset("async"))} data-testid={id("async")} aria-label="Then">
            <option value="go">goes on at once (async)</option>
            <option value="wait">waits until it's done</option>
          </select>
        </Row>
      </>
    );
  } else if (step.kind === "wait" || step.kind === "wait_until") {
    body = (
      <Row label={step.kind === "wait" ? "Wait" : "Until"} unit={step.kind === "wait" ? "ms" : "in (° for a turn)"}>
        <NumberBox value={step.target[0]} label={step.kind === "wait" ? "Wait (ms)" : "Until this far along"} whole={step.kind === "wait"} onCommit={(v) => v !== null && props.onSet(step.kind, v)} testid={id("value")} />
      </Row>
    );
  } else if (step.kind === "call") {
    body = <CallForm step={step} index={index} functions={props.functions} onSet={props.onSet} onUnset={props.onUnset} onReplace={props.onReplace} />;
  }
  return (
    <div className="route-form" data-testid={`step-form-${index}`}>
      {body}
      {props.issues.map((message, i) => (
        <p key={i} className="bad small">
          {message}
        </p>
      ))}
      <div className="route-form-actions">
        <button type="button" className="small" onClick={props.onDuplicate} title="A copy of it after it (Ctrl+D)" data-testid={`duplicate-step-${index}`}>
          Duplicate
        </button>
        <button type="button" className="small danger" onClick={props.onRemove} title="Take it out (Delete)" data-testid={`remove-step-${index}`}>
          Delete
        </button>
      </div>
    </div>
  );
}

/** A call's function and arguments: each left empty takes its default. */
function CallForm(props: {
  step: RouteStepData;
  index: number;
  functions: readonly RouteFunctionInfo[];
  onSet: (key: string, value: unknown) => void;
  onUnset: (key: string) => void;
  onReplace: (value: StepValue) => void;
}) {
  const { step, index } = props;
  const fn = props.functions.find((f) => f.name === step.function);
  const id = (key: string) => `step-${index}-${key}`;
  const argument = (param: RouteParamInfo) => {
    const given = step.args[param.name];
    const key = `args.${param.name}`;
    const unset = () => (param.name in step.args ? props.onUnset(key) : undefined);
    const placeholder = param.default ?? "";
    if (param.kind === "bool" || param.kind === "enum") {
      const choices = param.kind === "bool" ? ["true", "false"] : param.values;
      return (
        <select value={given === undefined ? "" : String(given)} onChange={(e) => (e.target.value === "" ? unset() : props.onSet(key, param.kind === "bool" ? e.target.value === "true" : e.target.value))} aria-label={param.name} data-testid={id(`arg-${param.name}`)}>
          <option value="">{param.default !== null ? `default (${param.default})` : "pick one…"}</option>
          {choices?.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      );
    }
    return (
      <NumberBox
        value={typeof given === "number" ? given : null}
        label={`${param.name} (${param.type})${param.default !== null ? `, empty: ${param.default}` : ""}`}
        placeholder={placeholder}
        whole={param.kind === "integer"}
        onCommit={(v) => (v === null ? unset() : props.onSet(key, v))}
        testid={id(`arg-${param.name}`)}
      />
    );
  };
  return (
    <>
      <Row label="Function">
        <select
          className="wide"
          value={step.function ?? ""}
          onChange={(e) => {
            const picked = props.functions.find((f) => f.name === e.target.value);
            if (picked) props.onReplace(stepValue(newStep("call", [0, 0, 0], picked)));
          }}
          aria-label="Function"
          data-testid={id("function")}
        >
          {!fn && <option value={step.function ?? ""}>{step.function}() (not in the headers)</option>}
          {props.functions.map((f) => (
            <option key={f.name} value={f.name}>
              {f.name}()
            </option>
          ))}
        </select>
      </Row>
      {fn && (
        <>
          <p className="muted small route-declaration" title={`${fn.header}, line ${fn.line}`}>
            <code>{fn.declaration}</code>
          </p>
          {fn.params.map((param) => (
            <Row key={param.name} label={param.name}>
              {argument(param)}
            </Row>
          ))}
          <p className="muted small">
            {fn.hint
              ? `The plan follows it as ${fn.hint.motion}(${fn.hint.args.join(", ")}), as its vexsim: comment says.`
              : fn.hint_problem
                ? fn.hint_problem
                : `The plan can't tell where it goes: a // vexsim: comment above its declaration would say (drive(inches), turn_by(degrees), arc(radius, degrees), point(x, y), pose(x, y, theta) or none).`}
          </p>
        </>
      )}
    </>
  );
}
