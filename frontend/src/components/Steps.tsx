import type { ReactNode } from "react";

/** One step of a few to take in order: what it is, whether it's done, the one to take next
 * or one for later, and what to press to take it. */
export interface Step {
  key: string;
  title: string;
  state: "done" | "next" | "todo";
  detail?: ReactNode; // a line under its title: what it's for, or what it found
  action?: { label: string; run: () => void; disabled?: boolean }; // its button
  more?: { label: string; href: string; go: () => void }; // where to read about it
  onPick?: () => void; // a click on the step itself: go to its part of the page
}

const SAYS = { done: "done", next: "next", todo: "to do" } as const;

/** Steps in a row, each done, next or to do (phase 15.4): the first run's, and a calibration
 * session's. */
export function Steps(props: { steps: Step[]; label: string; testid: string }) {
  return (
    <ol className="steprow" aria-label={props.label} data-testid={props.testid}>
      {props.steps.map((step, i) => {
        const head = (
          <>
            <span className="step-mark" aria-hidden="true">
              {step.state === "done" ? "✓" : i + 1}
            </span>
            <span className="step-title">{step.title}</span>
            <span className="step-state">{SAYS[step.state]}</span>
          </>
        );
        return (
          <li key={step.key} className={`stepcard ${step.state}`} aria-current={step.state === "next" ? "step" : undefined} data-testid={`${props.testid}-${step.key}`} data-state={step.state}>
            {step.onPick ? (
              <button type="button" className="step-head" onClick={step.onPick} title="Go to this step">
                {head}
              </button>
            ) : (
              <span className="step-head">{head}</span>
            )}
            {step.detail && <span className="step-detail">{step.detail}</span>}
            {(step.action || step.more) && (
              <span className="step-foot">
                {step.action && (
                  <button type="button" className={step.state === "next" ? "primary small" : "small"} onClick={step.action.run} disabled={step.action.disabled} data-testid={`${props.testid}-${step.key}-do`}>
                    {step.action.label}
                  </button>
                )}
                {step.more && (
                  <a
                    className="small"
                    href={step.more.href}
                    onClick={(event) => {
                      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
                      event.preventDefault();
                      step.more?.go();
                    }}
                    data-testid={`${props.testid}-${step.key}-guide`}
                  >
                    {step.more.label}
                  </a>
                )}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
