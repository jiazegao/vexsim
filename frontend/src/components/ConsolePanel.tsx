import type { ReactNode } from "react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Editor, Place, Problem } from "../problems";
import { embedded, HOSTS, openInHost } from "../host";
import { absolute, EDITORS, editorUrl, linkSegments, shortPath } from "../problems";
import type { RunProblem } from "../protocol";
import type { Line, SessionStore } from "../session";

type Tab = "console" | "build" | "problems" | "plots";

export function ConsolePanel(props: {
  store: SessionStore | null;
  history: string[] | null; // a recorded run's console, shown instead of the live session's
  plots: ReactNode | null; // the shown recording's plots
  problem: RunProblem | null;
  root: string;
  editor: Editor;
  onEditor: (editor: Editor) => void;
}) {
  const { store, history, problem, root, editor } = props;
  const [tab, setTab] = useState<Tab>("console");
  const lines: Line[] = history ? history.map((text) => ({ kind: "console", text })) : (store?.lines ?? []);
  const build = lines.filter((line) => line.kind === "build");
  const output = lines.filter((line) => line.kind !== "build");
  const problems = history ? [] : (store?.problems ?? []);
  const errors = problems.filter((p) => p.severity === "error").length;
  const state = store?.state;

  // While a project builds, show the build; when the run fails at a place, the problems.
  useEffect(() => {
    if (state === "building") setTab("build");
    if (state === "running") setTab("console");
  }, [state]);
  useEffect(() => {
    if (state === "error" && errors > 0) setTab("problems");
  }, [state, errors]);

  const tabButton = (name: Tab, label: string, count: number, testid?: string) => (
    <button role="tab" aria-selected={tab === name} className={tab === name ? "on" : ""} onClick={() => setTab(name)} data-testid={testid}>
      {label} {count > 0 && <span className={`count${name === "problems" && errors ? " bad" : ""}`}>{count}</span>}
    </button>
  );

  return (
    <section className="console" aria-label="Output">
      {problem && (
        <div className="problem" role="alert" data-testid="problem">
          <strong>
            <span aria-hidden="true">⚠</span> Can't run: {problem.error}
          </strong>
          {problem.issues.length > 0 && (
            <ul>
              {problem.issues.map((issue, i) => (
                <li key={i}>
                  <span className={`badge ${issue.severity}`}>{issue.severity}</span>
                  <code>{issue.location || "(document)"}</code> {issue.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="tabs" role="tablist">
        {tabButton("console", "Console", output.length)}
        {tabButton("build", "Build", build.length)}
        {tabButton("problems", "Problems", problems.length, "problems-tab")}
        {tabButton("plots", "Plots", 0, "plots-tab")}
        <span className="spacer" />
        {!embedded && (
          <label className="editor" title="Where file:line links open">
            Open files in
            <select value={editor} onChange={(e) => props.onEditor(e.target.value as Editor)}>
              {(Object.keys(EDITORS) as Editor[]).map((key) => (
                <option key={key} value={key}>
                  {EDITORS[key]}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {tab === "plots" ? (
        (props.plots ?? <div className="plots-empty">Plots of a run appear once it's recorded: when it ends, or when you open one from Runs.</div>)
      ) : tab === "problems" ? (
        <Problems problems={problems} root={root} editor={editor} />
      ) : (
        <Lines
          lines={tab === "console" ? output : build}
          root={root}
          editor={editor}
          empty={tab === "console" ? "The program's output appears here." : "Builds of PROS projects appear here."}
        />
      )}
    </section>
  );
}

/** A file:line place: a link into the editor (inside VS Code, VS Code itself), or (with no
 * editor) a button that copies it. */
export function PlaceLink(props: { place: Place; root: string; editor: Editor; children: ReactNode; testid?: string }) {
  const { place, root, editor } = props;
  const href = editorUrl(editor, root, place);
  const where = `${shortPath(root, place.file)}:${place.line}${place.column ? `:${place.column}` : ""}`;
  if (embedded) {
    const open = (event: React.MouseEvent) => {
      event.preventDefault();
      openInHost(absolute(root, place.file), place.line, place.column);
    };
    return (
      <a className="place" href={href ?? "#"} title={`Open ${where} in ${HOSTS[embedded] ?? embedded}`} data-testid={props.testid} onClick={open}>
        {props.children}
      </a>
    );
  }
  if (href) {
    return (
      <a className="place" href={href} title={`Open ${where} in ${EDITORS[editor]}`} data-testid={props.testid}>
        {props.children}
      </a>
    );
  }
  return (
    <button type="button" className="place" title={`Copy ${where}`} data-testid={props.testid} onClick={() => navigator.clipboard?.writeText(where).catch(() => {})}>
      {props.children}
    </button>
  );
}

export function Problems(props: { problems: Problem[]; root: string; editor: Editor; testid?: string }) {
  const { problems, root, editor } = props;
  if (problems.length === 0) {
    return (
      <div className="lines problems">
        <span className="muted">No problems. A failed build's errors and warnings, and where a program failed, appear here.</span>
      </div>
    );
  }
  return (
    <ul className="lines problems" data-testid={props.testid ?? "problems"}>
      {problems.map((p, i) => (
        <li key={i}>
          <span className={`badge ${p.severity}`}>{p.severity}</span>
          <PlaceLink place={p} root={root} editor={editor} testid="problem-link">
            {shortPath(root, p.file)}:{p.line}
            {p.column ? `:${p.column}` : ""}
          </PlaceLink>{" "}
          <span className="message">{p.message}</span>
        </li>
      ))}
    </ul>
  );
}

export function Lines(props: { lines: Line[]; root: string; editor: Editor; empty: string; testid?: string }) {
  const box = useRef<HTMLPreElement>(null);
  const pinned = useRef(true); // follow new lines unless scrolled up

  useLayoutEffect(() => {
    const element = box.current;
    if (element && pinned.current) element.scrollTop = element.scrollHeight;
  });

  return (
    <pre
      className="lines"
      ref={box}
      data-testid={props.testid ?? "console"}
      onScroll={(event) => {
        const element = event.currentTarget;
        pinned.current = element.scrollHeight - element.scrollTop - element.clientHeight < 24;
      }}
    >
      {props.lines.length === 0 ? (
        <span className="muted">{props.empty}</span>
      ) : (
        props.lines.map((line, i) => (
          <div key={i} className={`line ${line.kind}`}>
            {linkSegments(line.text).map((segment, j) =>
              typeof segment === "string" ? (
                segment
              ) : (
                <PlaceLink key={j} place={segment} root={props.root} editor={props.editor}>
                  {segment.text}
                </PlaceLink>
              ),
            )}
          </div>
        ))
      )}
    </pre>
  );
}
