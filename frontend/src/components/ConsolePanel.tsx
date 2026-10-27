import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { RunProblem } from "../protocol";
import type { Line, SessionStore } from "../session";

type Tab = "console" | "build";

export function ConsolePanel(props: { store: SessionStore | null; problem: RunProblem | null }) {
  const { store, problem } = props;
  const [tab, setTab] = useState<Tab>("console");
  const lines = store?.lines ?? [];
  const build = lines.filter((line) => line.kind === "build");
  const output = lines.filter((line) => line.kind !== "build");
  const building = store?.state === "building";

  // While a project builds, show the build; when it fails, too.
  useEffect(() => {
    if (building) setTab("build");
  }, [building]);
  useEffect(() => {
    if (store?.state === "running") setTab("console");
  }, [store?.state]);

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
        <button role="tab" aria-selected={tab === "console"} className={tab === "console" ? "on" : ""} onClick={() => setTab("console")}>
          Console {output.length > 0 && <span className="count">{output.length}</span>}
        </button>
        <button role="tab" aria-selected={tab === "build"} className={tab === "build" ? "on" : ""} onClick={() => setTab("build")}>
          Build {build.length > 0 && <span className="count">{build.length}</span>}
        </button>
      </div>
      <Lines
        lines={tab === "console" ? output : build}
        empty={tab === "console" ? "The program's output appears here." : "Builds of PROS projects appear here."}
      />
    </section>
  );
}

function Lines(props: { lines: Line[]; empty: string }) {
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
      data-testid="console"
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
            {line.text}
          </div>
        ))
      )}
    </pre>
  );
}
