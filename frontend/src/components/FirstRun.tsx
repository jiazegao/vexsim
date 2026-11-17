import type { RunRecord, WorkspaceItem } from "../protocol";
import type { Step } from "./Steps";
import { Steps } from "./Steps";

export interface FirstSteps {
  robot: boolean; // there's a robot to run
  driven: boolean; // something has been run
  program: boolean; // there's a program, or a PROS project
  ran: boolean; // a program has been run
}

/** The steps of a first run, each done or not, from what's in the folder and its run history
 * (and the run on the page now, `running`, which isn't in the history until it ends). */
export function firstSteps(items: WorkspaceItem[], runs: RunRecord[], running: { program?: string | null } | null = null): FirstSteps {
  return {
    robot: items.some((item) => item.kind === "robot" && !item.problem),
    driven: runs.length > 0 || running !== null,
    program: items.some((item) => item.kind === "program" || item.kind === "project"),
    ran: runs.some((run) => !!run.spec.program) || !!running?.program,
  };
}

/** Where to start, in a folder that's new to vexsim (phase 15.4): make a robot, drive it, add
 * a program, run it. Each step says whether it's done; the next one has its button. It shows
 * while there's a step left and nothing is on the field, until it's put away. */
export function FirstRun(props: {
  done: FirstSteps;
  busy: boolean; // a run is starting, or a program being written
  onNewRobot: () => void;
  onDrive: () => void; // a run with no program: the keys and a gamepad drive it
  onStarter: () => void; // write the starter program, and pick it
  onRunProgram: () => void; // run the program picked (or the first there is)
  guide: { href: string; go: () => void };
  onHide: () => void;
}) {
  const { done } = props;
  const order: [keyof typeof done, Omit<Step, "key" | "state">][] = [
    ["robot", { title: "Make a robot", detail: "Its shape, its drive and its sensors, drawn from above.", action: { label: "New robot…", run: props.onNewRobot } }],
    [
      "driven",
      {
        title: "Drive it",
        detail: "Run with no program: W and S drive, A and D turn, or use a gamepad. ? lists every key.",
        action: { label: "Drive it", run: props.onDrive, disabled: !done.robot || props.busy },
      },
    ],
    [
      "program",
      {
        title: "Add a program",
        detail: "A first program to run, read and change: a short autonomous, and driver control.",
        action: { label: "Add a starter program", run: props.onStarter, disabled: props.busy },
      },
    ],
    [
      "ran",
      {
        title: "Run your program",
        detail: "Pick it under Program, then Run. After you change it, Restart runs it as it is now.",
        action: { label: "Run it", run: props.onRunProgram, disabled: !done.robot || !done.program || props.busy },
      },
    ],
  ];
  const next = order.find(([key]) => !done[key])?.[0];
  const steps: Step[] = order.map(([key, step]) => ({ key, state: done[key] ? "done" : key === next ? "next" : "todo", ...step, action: done[key] ? undefined : step.action }));
  return (
    <section className="firstrun" aria-label="Where to start" data-testid="first-run">
      <header>
        <h2>Start here</h2>
        <span className="muted small">
          Have a PROS project? Open vexsim on the folder that holds it (<code>vexsim ui path/to/folder</code>): it's built and run as it is.
        </span>
        <span className="spacer" />
        <a
          className="small"
          href={props.guide.href}
          onClick={(event) => {
            if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
            event.preventDefault();
            props.guide.go();
          }}
          data-testid="first-run-guide"
        >
          Read the guide
        </a>
        <button type="button" className="ghost small" onClick={props.onHide} title="Put this away for this folder" data-testid="first-run-hide">
          Hide
        </button>
      </header>
      <Steps steps={steps} label="Your first run, step by step" testid="first-steps" />
    </section>
  );
}
