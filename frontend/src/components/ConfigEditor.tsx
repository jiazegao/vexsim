import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { Part } from "../configdoc";
import { fieldParts, partAtLine, robotParts, spanRange } from "../configdoc";
import type { ConfigCheck, ConfigEdit, ConfigFile, FieldConfig, PlacedIssue, RobotConfig } from "../protocol";
import { ConfigDiagram } from "./ConfigDiagram";
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
 * it changes; nothing is written to the file until Save (Ctrl+S). */
export function ConfigEditor(props: {
  path: string;
  active: boolean;
  closing: boolean; // its tab is being closed with unsaved changes: ask first
  onClose: () => void;
  onKeepOpen: () => void;
  onDirty: (path: string, dirty: boolean) => void;
  onSaved: (path: string) => void;
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
  const editor = useRef<YamlEditorHandle>(null);
  const textRef = useRef(text);
  textRef.current = text;

  const take = useCallback((forText: string, result: ConfigCheck) => {
    setChecked({ text: forText, result });
    if (result.robot || result.field) setDrawn({ robot: result.robot ?? null, field: result.field ?? null });
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

  const edit = async (edits: ConfigEdit[]) => {
    if (!file) throw new Error("not loaded");
    try {
      const base = textRef.current;
      const patched = await api.patchConfig(file.kind, base, edits);
      if (textRef.current !== base) throw new Error("The text changed while that was being written: drag it again.");
      editor.current?.replace(patched.text);
      setText(patched.text);
      take(patched.text, patched.check);
      setNotice(null);
    } catch (error) {
      setNotice({ bad: true, text: (error as Error).message });
      throw error;
    }
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
        <span className="spacer" />
        <span className={`editor-state small${errors ? " bad" : ""}`} data-testid="config-state">
          {!current ? "checking…" : errors || warnings ? `${errors} error${errors === 1 ? "" : "s"}, ${warnings} warning${warnings === 1 ? "" : "s"}` : "no problems"}
          {dirty ? " · unsaved changes" : ""}
        </span>
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
      <div className="editor-split">
        <div className="editor-text">
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
          onEdits={edit}
          onUndo={() => editor.current?.undo()}
          onRedo={() => editor.current?.redo()}
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
                  onClick={() => {
                    if (!issue.span) return;
                    const { from, to } = spanRange(text, issue.span);
                    editor.current?.select(from, to);
                    editor.current?.focus();
                  }}
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
