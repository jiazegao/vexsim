import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { RoutesExport } from "../protocol";

const STATES: Record<string, string> = { new: "new", changed: "changes", unchanged: "as it is" };

/** "Export…": a project's routes written into it as routines. First what it would write (each
 * file new, changed or as it is, with the change), then, on Export, written: only the files
 * that change. */
export function ExportDialog(props: { project: string; onClose: () => void; onExported: (done: RoutesExport) => void }) {
  const [plan, setPlan] = useState<RoutesExport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => box.current?.focus(), []); // for Escape
  useEffect(() => {
    let current = true;
    api
      .planExport(props.project)
      .then((found) => current && setPlan(found))
      .catch((problem: Error) => current && setError(problem.message));
    return () => {
      current = false;
    };
  }, [props.project]);
  const changes = plan?.files.some((f) => f.state !== "unchanged") ?? false;
  const write = async () => {
    setBusy(true);
    setError(null);
    try {
      props.onExported(await api.exportRoutes(props.project));
    } catch (problem) {
      setError((problem as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="overlay" role="presentation" onClick={props.onClose}>
      <div
        ref={box}
        tabIndex={-1}
        className="dialog export-routes"
        role="dialog"
        aria-modal="true"
        aria-labelledby="export-title"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          e.stopPropagation(); // not the route's keys, behind it
          if (e.key === "Escape") props.onClose();
        }}
        data-testid="export-dialog"
      >
        <header>
          <h2 id="export-title">Export the routes to {props.project}</h2>
        </header>
        <p className="muted small">
          Each of the project's routes becomes a routine, for the robot: in <code>src/vexsim_autons.cpp</code>, which vexsim writes whole, declared in <code>include/custom/auton.hpp</code>, where vexsim's routine list and the team's
          selector can call it. Each step is the call the route made, so the routine drives as the route did.
        </p>
        {!plan && !error && <p className="muted small">Looking at the project…</p>}
        {plan && (
          <>
            <h3>Routines</h3>
            <ul className="export-list" data-testid="export-routines">
              {plan.routines.map((r) => (
                <li key={r.name}>
                  <code>{r.name}()</code> <span className="muted">from {r.route}</span>
                </li>
              ))}
            </ul>
            {plan.left_out.length > 0 && (
              <>
                <h3>Left out</h3>
                <ul className="export-list bad" data-testid="export-left-out">
                  {plan.left_out.map((why) => (
                    <li key={why}>{why}</li>
                  ))}
                </ul>
              </>
            )}
            <h3>Files</h3>
            <ul className="export-list" data-testid="export-files">
              {plan.files.map((f) => (
                <li key={f.path} data-testid={`export-file-${f.path}`} data-state={f.state}>
                  <span className={`export-state ${f.state}`}>{STATES[f.state] ?? f.state}</span> <code>{f.path}</code>
                  {f.diff && (
                    <details>
                      <summary className="small">{f.state === "new" ? "Its text" : "The change"}</summary>
                      <pre className="export-diff">
                        {f.diff.split("\n").map((line, i) => (
                          <span key={i} className={line.startsWith("+") && !line.startsWith("+++") ? "added" : line.startsWith("-") && !line.startsWith("---") ? "removed" : undefined}>
                            {line}
                            {"\n"}
                          </span>
                        ))}
                      </pre>
                    </details>
                  )}
                </li>
              ))}
            </ul>
            {plan.notes.map((note) => (
              <p key={note} className="small">
                {note}
              </p>
            ))}
          </>
        )}
        {error && (
          <p className="bad small" role="alert" data-testid="export-error">
            {error}
          </p>
        )}
        <div className="actions">
          <button type="button" onClick={props.onClose}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={!plan || !changes || busy} onClick={write} data-testid="export-write">
            {busy ? "Exporting…" : plan && !changes ? "Up to date" : "Export"}
          </button>
        </div>
      </div>
    </div>
  );
}
