import type { ControllerInput } from "../controller";
import { fixed, lemlibTheta, poseError } from "../pose";
import type { SessionStore } from "../session";
import { ControllerPad } from "./ControllerPad";

function PoseRows(props: { pose: readonly [number, number, number] }) {
  const [x, y, heading] = props.pose;
  return (
    <>
      <dt>x, y</dt>
      <dd className="num">
        {fixed(x)}, {fixed(y)} in
      </dd>
      <dt>heading</dt>
      <dd className="num" title="Counter-clockwise from +x">
        {fixed(heading)}°
      </dd>
      <dt title="Clockwise from +y, as chassis.getPose().theta">LemLib θ</dt>
      <dd className="num">{fixed(lemlibTheta(heading))}°</dd>
    </>
  );
}

export function Readout(props: {
  store: SessionStore | null;
  driving: boolean; // the controller takes your input now
  scripted: boolean; // a recorded input file drives instead
  gamepad: string | null;
  onScreen: ControllerInput;
  onInput: (input: ControllerInput) => void;
}) {
  const frame = props.store?.frame ?? null;
  const scene = props.store?.scene ?? null;
  if (!frame || !scene) {
    return (
      <aside className="readout" aria-label="Readings">
        <p className="muted">Readings appear here once a run starts.</p>
      </aside>
    );
  }
  const error = frame.estimate ? poseError(frame.estimate, frame.pose) : null;
  const sensors = scene.robot.sensors.filter((s) => s.kind === "distance");
  const imus = Object.entries(frame.imu);
  const gpss = Object.entries(frame.gps);
  const mechanisms = scene.robot.mechanisms;
  const driverMode = scene.mode === "driver" || scene.mode === "match";
  const controller = (
    <section>
      <h3>Controller</h3>
      <ControllerPad state={frame.controller} onScreen={props.onScreen} onInput={props.onInput} enabled={props.driving} />
      <p className="muted small">
        {props.scripted
          ? "Recorded input drives this run."
          : props.driving
            ? `Keys W A S D and the arrows drive${props.gamepad ? `; so does ${shorten(props.gamepad)}` : ", or plug in a gamepad"}. ? lists every key.`
            : "Drive while a run is live."}
      </p>
    </section>
  );
  return (
    <aside className="readout" aria-label="Readings" data-testid="readout">
      <section>
        <h3>{scene.robot.name}</h3>
        <dl data-testid="true-pose" data-x={frame.pose[0]} data-y={frame.pose[1]} data-heading={frame.pose[2]}>
          <PoseRows pose={frame.pose} />
          <dt>speed</dt>
          <dd className="num">{fixed(frame.speed_in_s)} in/s</dd>
          <dt>battery</dt>
          <dd className="num">
            {fixed(frame.battery[0], 2)} V · {fixed(frame.battery[1] * 100, 0)}%
          </dd>
        </dl>
      </section>
      <section>
        <h3>
          <i className="swatch line dashed estimate" /> Where its code thinks it is
        </h3>
        {frame.estimate ? (
          <dl>
            <PoseRows pose={frame.estimate} />
            <dt>off by</dt>
            <dd className="num" data-testid="pose-error">
              {fixed(error![0], 2)} in · {fixed(error![1])}°
            </dd>
          </dl>
        ) : (
          <p className="muted small">No estimate yet: the code hasn't reported a pose.</p>
        )}
      </section>
      {driverMode && controller}
      {frame.motors.length > 0 && (
        <section>
          <h3>Motors</h3>
          <table className="motors">
            <thead>
              <tr>
                <th>port</th>
                <th>current</th>
                <th>temp</th>
              </tr>
            </thead>
            <tbody>
              {frame.motors.map(([port, amps, temp, hot]) => (
                <tr key={port} className={hot ? "hot" : undefined}>
                  <td>{port}</td>
                  <td className="num">{fixed(amps, 2)} A</td>
                  <td className="num">
                    {fixed(temp, 0)} °C{hot ? " · hot" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {mechanisms.length > 0 && (
        <section>
          <h3>Mechanisms</h3>
          <dl>
            {mechanisms.map((m, i) => [
              <dt key={`n${m.name}`}>{m.name}</dt>,
              <dd key={`v${m.name}`} className="num" title={m.range ? `Hard stops at ${m.range[0]}° and ${m.range[1]}°` : "No hard stops"}>
                {fixed(frame.mechanisms[i], 1)}°
              </dd>,
            ])}
          </dl>
        </section>
      )}
      {(imus.length > 0 || gpss.length > 0) && (
        <section>
          <h3>Inertial and GPS sensors</h3>
          <dl>
            {imus.map(([port, reading]) => [
              <dt key={`i${port}`}>IMU {port}</dt>,
              <dd key={`iv${port}`} className="num" title="get_heading() (clockwise, 0-360) and get_rotation()">
                {reading ? `${fixed(reading[0])}° · ${fixed(reading[1])}°` : "calibrating"}
              </dd>,
            ])}
            {gpss.map(([port, reading]) => [
              <dt key={`g${port}`}>GPS {port}</dt>,
              <dd key={`gv${port}`} className="num" title="Position (in), heading (clockwise from +y), its own error estimate; * when it reads the field strip">
                {reading ? `${fixed(reading[0])}, ${fixed(reading[1])} · ${fixed(reading[2])}° ±${fixed(reading[3], 2)}${reading[4] ? " *" : ""}` : "no reading yet"}
              </dd>,
            ])}
          </dl>
        </section>
      )}
      {sensors.length > 0 && (
        <section>
          <h3>
            <i className="swatch line beam" /> Distance sensors
          </h3>
          <dl>
            {sensors.map((s) => {
              const mm = frame.distance[String(s.port)];
              return [
                <dt key={`p${s.port}`}>port {s.port}</dt>,
                <dd key={`v${s.port}`} className="num">
                  {mm === null || mm === undefined ? "nothing" : `${mm} mm`}
                </dd>,
              ];
            })}
          </dl>
        </section>
      )}
      {frame.lcd.some((line) => line.trim()) && (
        <section>
          <h3>Brain screen</h3>
          <pre className="screen">{frame.lcd.join("\n")}</pre>
        </section>
      )}
      {frame.controller_screen.some((line) => line.trim()) && (
        <section>
          <h3>Controller screen</h3>
          <pre className="screen">{frame.controller_screen.join("\n")}</pre>
        </section>
      )}
      {!driverMode && controller}
    </aside>
  );
}

function shorten(name: string): string {
  const plain = name.replace(/\s*\(.*\)\s*/g, " ").trim();
  return plain.length > 40 ? `${plain.slice(0, 38)}…` : plain || "a gamepad";
}
