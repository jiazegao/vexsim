import { fixed, lemlibTheta, poseError } from "../pose";
import type { SessionStore } from "../session";

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

export function Readout(props: { store: SessionStore | null }) {
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
  return (
    <aside className="readout" aria-label="Readings" data-testid="readout">
      <section>
        <h3>{scene.robot.name}</h3>
        <dl>
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
    </aside>
  );
}
