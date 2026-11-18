import type { Dispatch, ReactNode, SetStateAction } from "react";
import { api } from "../api";
import { ConsolePanel } from "../components/ConsolePanel";
import { Controls } from "../components/Controls";
import { FieldKey, FieldView } from "../components/FieldView";
import { Plots } from "../components/Plots";
import { Readout } from "../components/Readout";
import { RunBar } from "../components/RunBar";
import { Timeline } from "../components/Timeline";
import type { Layers } from "../draw";
import type { Playhead } from "../playhead";
import type { Editor } from "../problems";
import type { RunProblem } from "../protocol";
import { COMPARE_DASHES } from "../recording";
import type { RunForm } from "../runform";
import { canRecordVideo } from "../video";
import { LogBar } from "./LogBar";
import { STARTABLE } from "./shared";
import type { RealLog } from "./useRealLog";
import type { useRunForm } from "./useRunForm";
import type { Runs } from "./useRuns";
import type { Workspace } from "./useWorkspace";

/** The Simulate page (App.tsx): the run bar and the run's controls, the field (with a real
 * robot's log beside it, when one is open) and its key, a recorded run's timeline, the
 * readings, and the panel below. What it shows is the app's: the runs (useRuns.ts), the log
 * (useRealLog.ts), the run form (useRunForm.ts). */
export function SimulatePage(props: {
  hidden: boolean; // another page is on show (this one keeps what it has)
  ws: Workspace;
  runs: Runs;
  log: RealLog;
  form: RunForm;
  onForm: Dispatch<SetStateAction<RunForm>>;
  runForm: ReturnType<typeof useRunForm>;
  onRun: () => void;
  onNewRobot: () => void;
  runbarFolded: boolean;
  onRunbarFold?: (folded: boolean) => void; // given while the bar may fold
  runOnSave: boolean;
  onRunOnSave: (on: boolean) => void;
  firstRun: ReactNode; // "Start here", while it shows
  playhead: Playhead;
  layers: Layers;
  onLayers: Dispatch<SetStateAction<Layers>>;
  hiddenDrawings: string[];
  onHiddenDrawings: (hidden: string[]) => void;
  follow: boolean;
  onFollow: (follow: boolean) => void;
  readoutOpen: boolean;
  onReadoutOpen: (open: boolean) => void;
  bottomOpen: boolean;
  onBottomOpen: (open: boolean) => void;
  problem: RunProblem | null;
  root: string;
  editor: Editor;
  onEditor: (editor: Editor) => void;
}) {
  const { form, playhead, layers, hiddenDrawings, follow, readoutOpen, problem, root, editor } = props;
  const { workspace, configurations, configFile, configError } = props.ws;
  const { store, speed, changeSpeed, stop, restart, starting, busy, source, recording, compared, setCompared, onField, recordingPhases } = props.runs;
  const { video, toggleVideo, closeRecording, driving, scripted, gamepad, onScreen, setOnScreen } = props.runs;
  const { realLog, drawnLayers, logAt, logAlone, logClock, closeRealLog } = props.log;
  const { routines, preview, startPose, moveStart, pickConfiguration, saveConfiguration, deleteConfiguration } = props.runForm;
  const start = startPose ? { pose: startPose, editable: !busy } : null;
  return (
    <div className="simulate" hidden={props.hidden}>
      <h1 className="visually-hidden">Simulate</h1>
      <RunBar
        workspace={workspace}
        form={form}
        routines={routines}
        onChange={props.onForm}
        onRun={props.onRun}
        starting={starting}
        configurations={configurations}
        configFile={configFile}
        configError={configError}
        onPick={pickConfiguration}
        onSave={saveConfiguration}
        onDelete={deleteConfiguration}
        onNewRobot={props.onNewRobot}
        folded={props.runbarFolded}
        onFold={props.onRunbarFold}
        runOnSave={props.runOnSave}
        onRunOnSave={props.onRunOnSave}
      />
      <Controls
        store={store}
        speed={speed}
        onSpeed={changeSpeed}
        onStop={stop}
        onRestart={restart}
        command={store?.info?.command ?? store?.scene?.command ?? recording?.run?.command ?? null}
      />
      <LogBar log={props.log} starting={starting} />
      {props.firstRun}
      <div className={`stage${realLog ? " paired" : ""}${readoutOpen ? "" : " no-readout"}`}>
        <div className={`fieldcol${realLog ? " paired" : ""}`}>
          <div className={realLog ? "fieldpair" : "fieldsingle"}>
            {realLog && (
              <div className="fieldhalf">
                <div className="fieldlabel">
                  <b>Real robot</b> <span className="muted">its log: what its code thought and saw</span>
                </div>
                <FieldView
                  name="log"
                  source={{ kind: "log", log: realLog, clock: logClock, shape: source.kind === "live" ? source.store.scene : recording ? recording.playback.tape.scene : preview }}
                  compared={[]}
                  preview={null}
                  start={null}
                  onStart={moveStart}
                  layers={layers}
                  hiddenDrawings={hiddenDrawings}
                  follow={follow}
                  onFollow={props.onFollow}
                />
              </div>
            )}
            <div className="fieldhalf">
              {realLog && (
                <div className="fieldlabel">
                  <b>vexsim</b>{" "}
                  <span className="muted">
                    {recording ? recording.name : source.kind === "live" ? "the run" : "the robot as set up above"}
                    {logAt === null && !logAlone && (source.kind === "live" ? " · the log starts when the run follows it" : "")}
                  </span>
                </div>
              )}
              <FieldView
                source={source}
                compared={onField}
                preview={preview}
                start={start}
                onStart={moveStart}
                layers={layers}
                hiddenDrawings={hiddenDrawings}
                follow={follow}
                onFollow={props.onFollow}
                stamp={video && recording ? recording.name : null}
                notice={
                  store && store.changed.length > 0 && source.kind !== "preview" ? (
                    <button
                      type="button"
                      className="changed"
                      onClick={restart}
                      disabled={!STARTABLE.includes(store.state)}
                      title={`${store.changed.join(", ")} changed since this run started: what's on the field is the code as it was. Click (or Restart, R) to run it as it is now.`}
                      data-testid="code-changed"
                    >
                      <b>Code changed</b> since this run started · Restart runs it
                    </button>
                  ) : null
                }
                tools={
                  <button
                    type="button"
                    className={`ghost small${readoutOpen ? " on" : ""}`}
                    aria-pressed={readoutOpen}
                    onClick={() => props.onReadoutOpen(!readoutOpen)}
                    title="The readings beside the field: the poses, the motors, the sensors, the controller"
                    data-testid="readout-toggle"
                  >
                    Readings
                  </button>
                }
              />
            </div>
          </div>
          <FieldKey
            layers={layers}
            onLayers={props.onLayers}
            drawn={drawnLayers}
            hidden={hiddenDrawings}
            onHidden={props.onHiddenDrawings}
            compared={compared.map((r, i) => ({ key: r.key, name: r.label, dash: COMPARE_DASHES[i] }))}
            onUncompare={(key) => setCompared((list) => list.filter((r) => r.key !== key))}
          />
          {recording && (
            <Timeline
              phases={recordingPhases}
              playhead={playhead}
              name={recording.name}
              run={recording.run}
              csv={recording.run ? api.csvUrl(recording.run.id) : null}
              video={video ? "recording" : canRecordVideo() ? "off" : "unsupported"}
              onVideo={toggleVideo}
              onClose={closeRecording}
            />
          )}
          {realLog && logAlone && (
            <Timeline
              phases={[]}
              playhead={playhead}
              name={realLog.name}
              run={null}
              summary="the real robot's log, played alone: replay it, or open a run, to see it beside one"
              csv={null}
              video={null}
              onVideo={() => {}}
              onClose={closeRealLog}
              closeTitle="Put the log away"
            />
          )}
        </div>
        <div className="readout-slot" hidden={!readoutOpen}>
          <Readout source={source} driving={driving} scripted={scripted} gamepad={gamepad} onScreen={onScreen} onInput={setOnScreen} />
        </div>
      </div>
      <ConsolePanel
        store={store}
        history={recording?.console ?? null}
        plots={recording ? <Plots shown={recording} compared={compared} playhead={playhead} /> : null}
        problem={problem}
        root={root}
        editor={editor}
        onEditor={props.onEditor}
        open={props.bottomOpen}
        onOpen={props.onBottomOpen}
      />
    </div>
  );
}
