import type { WorkspaceInfo } from "../protocol";
import { AutonCheck } from "./calibrate/AutonCheck";
import { QuickFit } from "./calibrate/QuickFit";
import { SessionPanel } from "./calibrate/SessionPanel";

export type CalibrateTab = "session" | "check" | "quick";
const TABS: [CalibrateTab, string, string][] = [
  ["session", "Session", "A calibration session on your field: plan it, run its program on the robot, collect and fit its logs"],
  ["check", "Autonomous check", "Your real autonomous against the calibrated simulator, at your pass marks"],
  ["quick", "Quick fit", "One run of a drive routine on open floor, fitted: the wheels' grip and rolling only"],
];

/** Calibrating the simulator to a real robot (phase 14): a session of tests on the field, the
 * autonomous check, and the quick fit from one run; docs/calibration_guide.md walks through it. */
export function CalibratePage(props: {
  workspace: WorkspaceInfo | null;
  robot: string;
  onRobot: (path: string) => void;
  log: string;
  onLog: (path: string) => void;
  project: string;
  onProject: (path: string) => void;
  session: string;
  onSession: (path: string) => void;
  tab: CalibrateTab;
  onTab: (tab: CalibrateTab) => void;
  onApply: (robot: string, values: Record<string, number>) => Promise<void>;
  onApplySession: (robot: string, session: string) => void;
  onEdit: (path: string) => void;
  onPlayLog: (path: string) => void;
  onRescan: () => void;
}) {
  const { tab } = props;
  return (
    <div className="page" data-testid="calibrate-page">
      <header className="page-head">
        <h1>Calibrate</h1>
        <p className="muted">
          Make the simulated robot behave like the real one. A session tests each part of the robot on your field, from a program of its own, and
          the logs it saves are fitted into the robot's config; then your real autonomous is checked against the simulator. The calibration guide (
          <code>docs/calibration_guide.md</code>) walks through it, step by step.
        </p>
      </header>
      <div className="tabs page-tabs" role="tablist">
        {TABS.map(([id, label, hint]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} title={hint} onClick={() => props.onTab(id)} data-testid={`calibrate-tab-${id}`}>
            {label}
          </button>
        ))}
      </div>
      <div hidden={tab !== "session"}>
        <SessionPanel
          workspace={props.workspace}
          robot={props.robot}
          onRobot={props.onRobot}
          session={props.session}
          onSession={props.onSession}
          onApplySession={props.onApplySession}
          onEdit={props.onEdit}
          onPlayLog={props.onPlayLog}
          onRescan={props.onRescan}
        />
      </div>
      <div hidden={tab !== "check"}>
        <AutonCheck workspace={props.workspace} robot={props.robot} onRobot={props.onRobot} onPlayLog={props.onPlayLog} />
      </div>
      <div hidden={tab !== "quick"}>
        <QuickFit
          workspace={props.workspace}
          robot={props.robot}
          onRobot={props.onRobot}
          log={props.log}
          onLog={props.onLog}
          project={props.project}
          onProject={props.onProject}
          onApply={props.onApply}
        />
      </div>
    </div>
  );
}
