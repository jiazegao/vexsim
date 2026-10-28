import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { Part } from "../configdoc";
import { fieldParts, partAtLine, robotParts, spanRange, textChange } from "../configdoc";
import { copiedPart, copyOf, copyPart, DRIVE_PRESETS, pasteEdits, shapeOf } from "../design";
import type { ConfigCheck, ConfigEdit, ConfigFile, ConfigPatched, FieldConfig, PlacedIssue, RobotConfig, TextSpan } from "../protocol";
import type { DesignTools, Tool } from "./ConfigDiagram";
import { ConfigDiagram } from "./ConfigDiagram";
import { DesignPanel } from "./DesignPanel";
import type { YamlEditorHandle } from "./YamlEditor";
import { YamlEditor } from "./YamlEditor";

const CHECK_DELAY_MS = 250; // after the last keystroke

interface Checked {
  text: string; // the text this is the check of
  result: ConfigCheck;
}

interface Drawn {
  robot: RobotConfig | null;
  field: FieldConfig | null;
}

/** A robot or field config: its YAML beside a diagram drawn from it. Typing is checked as it
 * goes, with the issues at their lines; dragging on the diagram rewrites just the numbers
 * it changes; nothing is written to the file until Save (Ctrl+S). A robot has a Design view
 * too: forms and drawing tools in place of the text, whose changes are written into it. */
export function ConfigEditor(props: {
  path: string;
  active: boolean;
  closing: boolean; // its tab is being closed with unsaved changes: ask first
  onClose: () => void;
  onKeepOpen: () => void;
  onDirty: (path: string, dirty: boolean) => void;
  onSaved: (path: string) => void;
  request?: { id: number; overrides: Record<string, number> } | null; // fitted values to add
  design?: boolean; // open in the Design view (a robot just made)
}) {
  const { path } = props;
  const [file, setFile] = useState<ConfigFile | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [saved, setSaved] = useState<{ text: string; version: string } | null>(null);
  const [checked, setChecked] = useState<Checked | null>(null);
  const [drawn, setDrawn] = useState<Drawn>({ robot: null, field: null });
  const [selected, setSelected] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ bad: boolean; text: string } | null>(null);
  const [conflict, setConflict] = useState(false);
  const [saving, setSaving] = useState(false);
  const [view, setView] = useState<"design" | "yaml">(props.design ? "design" : "yaml");
  const [tool, setTool] = useState<Tool>("select");
  const [step, setStep] = useState(0.25);
  const [mirror, setMirror] = useState(false);
  const [shapePart, setShapePart] = useState<number | null>(null);
  const editor = useRef<YamlEditorHandle>(null);
  const textRef = useRef(text);
  textRef.current = text;
  const queue = useRef<Promise<unknown>>(Promise.resolve()); // changes, one after another
  const robotNow = useRef<RobotConfig | null>(null); // the latest robot read, for queued changes

  const take = useCallback((forText: string, result: ConfigCheck) => {
    setChecked({ text: forText, result });
    if (result.robot || result.field) setDrawn({ robot: result.robot ?? null, field: result.field ?? null });
    if (result.robot) robotNow.current = result.robot;
  }, []);

  const load = useCallback(async () => {
    try {
      const opened = await api.config(path);
      setFile(opened);
      setSaved({ text: opened.text, version: opened.version });
      setText(opened.text);
      take(opened.text, opened.check);
      setLoadError(null);
      return opened;
    } catch (error) {
      setLoadError((error as Error).message);
      return null;
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
        .checkConfig(file.kind, text)
        .then((result) => current && textRef.current === text && take(text, result))
        .catch(() => {});
    }, CHECK_DELAY_MS);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [file, text, checked, take]);

  // a calibration's fitted values, added under overrides (undoable), for you to look over
  const handled = useRef(0);
  const { request } = props;
  useEffect(() => {
    if (!file || !request || handled.current >= request.id || !editor.current) return;
    handled.current = request.id;
    (async () => {
      try {
        const before = textRef.current;
        const patched = await api.setOverrides(before, request.overrides);
        editor.current?.replace(patched.text);
        setText(patched.text);
        take(patched.text, patched.check);
        const change = textChange(before, patched.text);
        if (change) editor.current?.select(change.from, change.from + change.insert.length); // in view
        const count = Object.keys(request.overrides).length;
        setNotice({ bad: false, text: `Added ${count} fitted value${count === 1 ? "" : "s"} under overrides: look them over, then save (Ctrl+Z takes them out).` });
      } catch (error) {
        setNotice({ bad: true, text: `Couldn't add the fitted values: ${(error as Error).message}` });
      }
    })();
  }, [file, request, take]);

  const dirty = saved !== null && text !== saved.text;
  const { onDirty } = props;
  useEffect(() => onDirty(path, dirty), [onDirty, dirty, path]);

  const parts: Part[] = useMemo(() => (drawn.robot ? robotParts(drawn.robot) : drawn.field ? fieldParts(drawn.field) : []), [drawn]);
  const result = checked?.result ?? null;
  const issues: PlacedIssue[] = result?.issues ?? [];
  const current = checked?.text === text;
  const stale = !current || !(result?.robot || result?.field);

  const showPlace = (place: string, focus = false) => {
    const span = result?.places?.[place];
    if (!span || !current) return;
    const { from, to } = spanRange(text, span);
    editor.current?.select(from, to);
    if (focus) editor.current?.focus();
  };

  /** A change the server writes into the text: made after the ones before it, on the text
   * they left. `strict` (the Design view): one that would leave a robot's YAML unreadable
   * isn't made. Rejects, having said why, if it can't be made. */
  const change = (write: (base: string) => Promise<ConfigPatched>, strict: boolean, done: string | null | (() => string) = null): Promise<void> => {
    const made = queue.current.then(async () => {
      if (!file) throw new Error("not loaded");
      try {
        const base = textRef.current;
        const patched = await write(base);
        if (textRef.current !== base) throw new Error("The text changed while that was being written: make the change again.");
        if (strict && file.kind === "robot" && !patched.check.robot) {
          const why = patched.check.issues.find((i) => i.severity === "error");
          throw new Error(`That would leave the robot's YAML unreadable${why ? ` (${why.location ? `${why.location}: ` : ""}${why.message})` : ""}, so it wasn't made.`);
        }
        textRef.current = patched.text;
        editor.current?.replace(patched.text);
        setText(patched.text);
        take(patched.text, patched.check);
        const said = typeof done === "function" ? done() : done;
        setNotice(said ? { bad: false, text: said } : null);
      } catch (error) {
        setNotice({ bad: true, text: (error as Error).message });
        throw error;
      }
    });
    queue.current = made.catch(() => {});
    return made;
  };
  const edit = (edits: ConfigEdit[], strict = false, done: string | null = null) => change((base) => api.patchConfig(file!.kind, base, edits), strict, done);
  const putDrive = (preset: string) => {
    const label = DRIVE_PRESETS.find(([id]) => id === preset)?.[1] ?? preset;
    const done = `It has a ${label} now: new wheels and motor groups, on free ports (Undo takes them back).`;
    change((base) => api.drivePreset(base, preset), true, done).catch(() => {});
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
      const errors = (checked?.text === writing ? checked.result.issues : []).filter((i) => i.severity === "error").length;
      setNotice(
        errors
          ? { bad: true, text: `Saved, with ${errors} error${errors > 1 ? "s" : ""}: runs with it won't start until they're fixed.` }
          : { bad: false, text: "Saved." },
      );
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
    const opened = await api.config(path).catch((error: Error) => {
      setNotice({ bad: true, text: error.message });
      return null;
    });
    if (!opened) return;
    editor.current?.replace(opened.text);
    setText(opened.text);
    setSaved({ text: opened.text, version: opened.version });
    take(opened.text, opened.check);
    setConflict(false);
    setNotice({ bad: false, text: "Loaded the file as it is on disk (Ctrl+Z brings yours back)." });
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
      event.preventDefault(); // not the browser's "save page"
      saveRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [props.active]);

  const revert = () => {
    if (!saved) return;
    editor.current?.replace(saved.text);
    setNotice(null);
  };

  const errors = issues.filter((i) => i.severity === "error").length;
  const warnings = issues.length - errors;
  const kindName = file?.kind === "field" ? "field" : "robot";

  // the Design view (a robot's): its tools and which part of its shape is selected
  const designView = view === "design" && file?.kind !== "field";
  const shapeCount = drawn.robot ? shapeOf(drawn.robot.body).length : 0;
  useEffect(() => {
    if (shapePart !== null && shapePart >= shapeCount) setShapePart(null);
  }, [shapePart, shapeCount]);
  const design: DesignTools | null = designView
    ? {
        tool,
        step,
        mirror,
        part: shapePart,
        onPart: (index) => {
          setShapePart(index);
          if (index !== null) setSelected(null);
        },
        onTool: setTool,
        onStep: setStep,
        onMirror: setMirror,
      }
    : null;
  // Ctrl+C and Ctrl+V on a robot's diagram: the selected part copied, and copies of it pasted
  // (into this robot or another one open beside it), each one selected as it lands
  const copySelected = () => {
    if (!drawn.robot) return;
    const copy = copyOf(drawn.robot, designView ? shapePart : null, selected);
    if (copy === null) {
      setNotice({ bad: false, text: "Select something to copy first: a wheel, a sensor or, in the Design view, a part of the shape." });
    } else if (typeof copy === "string") {
      setNotice({ bad: true, text: copy });
    } else {
      copyPart(copy);
      setNotice({ bad: false, text: `Copied ${copy.label}: Ctrl+V pastes a copy, into this robot or another.` });
    }
  };
  const pasteCopied = () => {
    const copy = copiedPart();
    if (!copy) return setNotice({ bad: false, text: "Nothing's copied yet: select a part of a robot and press Ctrl+C." });
    if (!drawn.robot || stale) return setNotice({ bad: true, text: "The YAML doesn't read just now: fix it before pasting." });
    // worked out in its turn, from the robot the pastes before it left (names, ports, places)
    let pasted: ReturnType<typeof pasteEdits> | null = null;
    const write = (base: string) => {
      pasted = pasteEdits(robotNow.current ?? drawn.robot!, copy);
      copy.pastes += 1;
      return api.patchConfig("robot", base, pasted.edits);
    };
    change(write, designView, () => `Pasted ${pasted!.label}.`)
      .then(() => {
        setShapePart(pasted!.part);
        setSelected(pasted!.path);
      })
      .catch(() => {});
  };

  /** Where something is written, shown in the text (the YAML view, if it's not on show). */
  const showText = (span: TextSpan) => {
    const select = () => {
      const { from, to } = spanRange(textRef.current, span);
      editor.current?.select(from, to);
      editor.current?.focus();
    };
    if (!designView) return select();
    setView("yaml");
    requestAnimationFrame(select);
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
  return (
    <section className="config-editor" hidden={!props.active} aria-label={`Editing ${path}`} data-testid="config-editor" data-path={path}>
      <div className="editor-bar">
        <span className="editor-path" title={path}>
          {path}
        </span>
        <span className="muted small">{file ? `${kindName} config` : "opening…"}</span>
        {file?.kind === "robot" && (
          <span className="view-switch" role="group" aria-label="Show">
            <button type="button" className={`small${designView ? " on" : ""}`} aria-pressed={designView} onClick={() => setView("design")} title="Forms and drawing tools: what you change is written into the YAML" data-testid="view-design">
              Design
            </button>
            <button type="button" className={`small${designView ? "" : " on"}`} aria-pressed={!designView} onClick={() => setView("yaml")} title="The config's text" data-testid="view-yaml">
              YAML
            </button>
          </span>
        )}
        <span className="spacer" />
        <span className={`editor-state small${errors ? " bad" : ""}`} data-testid="config-state">
          {!current ? "checking…" : errors || warnings ? `${errors} error${errors === 1 ? "" : "s"}, ${warnings} warning${warnings === 1 ? "" : "s"}` : "no problems"}
          {dirty ? " · unsaved changes" : ""}
        </span>
        {designView && (
          <>
            <button type="button" onClick={() => editor.current?.undo()} title="Undo the last change (Ctrl+Z on the diagram)" data-testid="undo">
              Undo
            </button>
            <button type="button" onClick={() => editor.current?.redo()} title="Redo it (Ctrl+Shift+Z on the diagram)" data-testid="redo">
              Redo
            </button>
          </>
        )}
        <button type="button" onClick={revert} disabled={!dirty || saving} title="Back to the file as it was saved (Ctrl+Z undoes this too)">
          Revert
        </button>
        <button type="button" className="primary" onClick={() => save()} disabled={!dirty || saving} data-testid="save-config" title="Write it to the file (Ctrl+S)">
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
        <div className={`editor-notice small${notice.bad ? " bad" : ""}`} role="status" data-testid="config-notice">
          {notice.text}
        </div>
      )}
      <div className={`editor-split${designView ? " designing" : ""}`}>
        <div className="editor-text" hidden={designView}>
          {file && (
            <YamlEditor
              ref={editor}
              initial={file.text}
              issues={checked ? { text: checked.text, issues: checked.result.issues } : null}
              onChange={setText}
              onCursor={(line) => {
                const part = result && current ? partAtLine(parts, result.places ?? {}, line) : null;
                if (part) setSelected(part.path);
              }}
              onSave={() => dirty && save()}
              label={`${path}, YAML`}
            />
          )}
        </div>
        {designView &&
          (drawn.robot ? (
            <DesignPanel
              robot={drawn.robot}
              stale={stale}
              issues={current ? issues : []}
              selected={selected}
              onSelect={(path) => {
                setSelected(path);
                if (path) setShapePart(null);
              }}
              shapePart={shapePart}
              onShapePart={(index) => {
                setShapePart(index);
                if (index !== null) setSelected(null);
              }}
              onEdits={(edits) => edit(edits, true)}
              onPreset={putDrive}
              onProblem={(message) => setNotice({ bad: true, text: message })}
            />
          ) : (
            <div className="design-panel">
              <p className="muted small">
                {file ? (
                  <>
                    This robot's YAML doesn't read, so there's nothing to show here yet:{" "}
                    <button type="button" className="ghost small" onClick={() => setView("yaml")}>
                      fix it in the YAML view
                    </button>
                  </>
                ) : (
                  "Opening…"
                )}
              </p>
            </div>
          ))}
        <ConfigDiagram
          robot={drawn.robot}
          field={drawn.robot ? null : drawn.field}
          stale={stale}
          issues={current ? issues : []}
          selected={selected}
          onSelect={(part) => {
            setSelected(part?.path ?? null);
            if (part) showPlace(part.place);
          }}
          onEdits={(edits) => edit(edits, designView)}
          onUndo={() => editor.current?.undo()}
          onRedo={() => editor.current?.redo()}
          design={design}
          onCopy={copySelected}
          onPaste={pasteCopied}
        />
      </div>
      <div className="editor-foot">
        <ul className="config-problems" data-testid="config-problems">
          {issues.length === 0 ? (
            <li className="muted">
              {current ? (
                <>
                  No problems: <code>vexsim validate-config</code> would say OK.
                </>
              ) : (
                "Checking…"
              )}
            </li>
          ) : (
            issues.map((issue, i) => (
              <li key={i}>
                <span className={`badge ${issue.severity}`}>{issue.severity}</span>
                <button
                  type="button"
                  className="place"
                  disabled={!issue.span || !current}
                  onClick={() => issue.span && showText(issue.span)}
                >
                  {issue.location || "(document)"}
                  {issue.span ? ` (line ${issue.span.line})` : ""}
                </button>{" "}
                <span className="message">{issue.message}</span>
              </li>
            ))
          )}
        </ul>
        {result?.summary?.length ? (
          <details className="config-summary">
            <summary>Summary</summary>
            <pre>{result.summary.join("\n")}</pre>
          </details>
        ) : null}
      </div>
    </section>
  );
}
