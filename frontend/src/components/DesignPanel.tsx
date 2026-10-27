import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import type { PortUser, ShapePart } from "../design";
import {
  CARTRIDGE_RPM,
  DRIVE_PRESETS,
  describePart,
  describeUser,
  isFootprint,
  mirroredPart,
  nameProblem,
  newGroup,
  newMechanism,
  newSensor,
  newWheel,
  outlineProblem,
  PORTS,
  partEdits,
  portMap,
  ratioValue,
  readPorts,
  readRatio,
  removeWheelEdits,
  renameWheelEdits,
  sensorName,
  shapeOf,
  shown,
  wheelTypeEdits,
} from "../design";
import type { ConfigEdit, PlacedIssue, RobotConfig, WheelConfig } from "../protocol";

type Sensor = NonNullable<RobotConfig["sensors"]>[number];
type SensorType = Sensor["type"];
/** Makes a change: the edits `make` returns, or the reason it throws, said in the editor. */
type Act = (make: () => ConfigEdit[]) => Promise<void>;

const set = (location: string, value: unknown): ConfigEdit => ({ location, op: "set", value });
const remove = (location: string): ConfigEdit => ({ location, op: "remove" });

const DRIVE_TYPES: readonly (readonly [RobotConfig["drivetrain"]["type"], string])[] = [
  ["differential", "Tank (differential)"],
  ["xdrive", "X-drive"],
  ["mecanum", "Mecanum"],
  ["hdrive", "H-drive"],
];
const WHEEL_TYPES: readonly WheelConfig["type"][] = ["omni", "traction", "mecanum"];
const SIDES: readonly string[] = ["left", "right"]; // a tank drive's or an H-drive's motor groups
const CARTRIDGES = ["red", "green", "blue"] as const;
const NOISE = ["ideal", "default", "harsh"] as const;
const SENSOR_TYPES: readonly (readonly [SensorType, string])[] = [
  ["imu", "IMU"],
  ["rotation", "Tracking wheel"],
  ["distance", "Distance sensor"],
  ["gps", "GPS"],
];

/** The Design view's forms: the robot's body and shape, its drive (wheels and motor
 * groups), mechanisms and sensors, and what's on each port. Each change is a few edits the
 * server writes into the YAML where they belong, so the text (and its comments) stays the
 * robot; the forms show what it says. */
export function DesignPanel(props: {
  robot: RobotConfig;
  stale: boolean; // the YAML doesn't read just now: this is how it last did
  issues: PlacedIssue[];
  selected: string | null; // the wheel, sensor or CG ("body") selected on the diagram
  onSelect: (path: string | null) => void;
  shapePart: number | null; // the part of the shape selected
  onShapePart: (index: number | null) => void;
  onEdits: (edits: ConfigEdit[]) => Promise<void>; // rejects, having said why, if they can't be made
  onPreset: (preset: string) => void;
  onProblem: (message: string) => void;
}) {
  const { robot } = props;
  const box = useRef<HTMLDivElement>(null);

  const act: Act = async (make) => {
    let edits: ConfigEdit[];
    try {
      edits = make();
    } catch (problem) {
      props.onProblem((problem as Error).message);
      throw problem;
    }
    if (edits.length) await props.onEdits(edits);
  };
  /** For buttons and lists: what went wrong is said in the editor. */
  const run = (make: () => ConfigEdit[], then?: () => void) => {
    act(make)
      .then(then)
      .catch(() => {});
  };

  // what's selected on the diagram, in view here
  const { selected } = props;
  useEffect(() => {
    if (!selected) return;
    const path = selected.replace(/\.tracking_wheel$/, "");
    box.current?.querySelector(`[data-path="${CSS.escape(path)}"]`)?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  const flag = (path: string): string => {
    const found = props.issues.filter((i) => i.location === path || i.location.startsWith(`${path}.`) || i.location.startsWith(`${path}[`));
    return found.some((i) => i.severity === "error") ? " error" : found.length ? " warning" : "";
  };
  const isOn = (path: string) => selected === path || !!selected?.startsWith(`${path}.`);
  const item = (path: string, base = "design-item") => `${base}${flag(path)}${isOn(path) ? " on" : ""}`;
  const pick = (path: string) => {
    if (selected !== path) props.onSelect(path);
  };

  const ports = portMap(robot);
  const clashes = [...ports.values()].filter((users) => users.length > 1).length;
  const wheels = robot.drivetrain.wheels;
  const wheelNames = wheels.map((w) => w.name);
  const groups = Object.entries(robot.drivetrain.gearing);
  const sided = robot.drivetrain.type === "differential" || robot.drivetrain.type === "hdrive"; // left and right
  const mechanisms = Object.entries(robot.mechanisms ?? {});
  const sensors = robot.sensors ?? [];
  const mecanum = wheels.some((w) => w.type === "mecanum");

  return (
    <div className="design-panel" ref={box} data-testid="design-panel">
      {props.stale && (
        <p className="design-stale small" role="status">
          The YAML doesn't read just now, so this is how it last did. Undo, or fix the text in the YAML view.
        </p>
      )}
      <fieldset disabled={props.stale}>
        <section>
          <h3>Robot</h3>
          <Row label="Name">
            <Entry value={robot.name ?? ""} label="Robot name" wide onCommit={(text) => act(() => (text ? [set("name", text)] : [remove("name")]))} testid="robot-name" />
          </Row>
        </section>

        <section className={item("body", "")} data-path="body" onFocus={() => pick("body")}>
          <h3>Body</h3>
          <Row label="Mass" unit="kg">
            <Num label="Mass (kg)" value={robot.body.mass_kg} positive act={act} onSet={(v) => [set("body.mass_kg", v)]} testid="body-mass" />
          </Row>
          <Row label="Inertia" unit="kg·m²" title="How hard the robot is to turn. auto: as if its mass were spread evenly over its shape">
            <Entry
              value={typeof robot.body.inertia_kgm2 === "number" ? shown(robot.body.inertia_kgm2) : "auto"}
              label="Inertia (kg·m², or auto)"
              onCommit={(text) =>
                act(() => {
                  if (!text || text === "auto") return [set("body.inertia_kgm2", "auto")];
                  const value = Number(text);
                  if (!(value > 0) || !Number.isFinite(value)) throw new Error(`The inertia is auto, or a number of kg·m² more than 0: "${text}" isn't`);
                  return [set("body.inertia_kgm2", value)];
                })
              }
            />
          </Row>
          <Row label="CG" unit="in" title="Center of gravity: x and y in the robot's frame, and its height above the floor (or drag it on the diagram)">
            {(["x", "y", "height"] as const).map((axis, k) => (
              <Num
                key={axis}
                label={`CG ${axis} (in)`}
                value={robot.body.cg_in[k]}
                positive={k === 2}
                act={act}
                onSet={(v) => [set("body.cg_in", robot.body.cg_in.map((c, j) => (j === k ? v : c)))]}
              />
            ))}
          </Row>
        </section>

        <ShapeSection robot={robot} act={act} run={run} part={props.shapePart} onPart={props.onShapePart} />

        <section data-testid="drive">
          <h3>Drive</h3>
          <Row label="Type">
            <select value={robot.drivetrain.type} onChange={(e) => run(() => [set("drivetrain.type", e.target.value)])} aria-label="Drive type" data-testid="drive-type">
              {DRIVE_TYPES.map(([type, label]) => (
                <option key={type} value={type}>
                  {label}
                </option>
              ))}
            </select>
          </Row>
          <Row label="Start over" title="New wheels and motor groups for the robot's shape, on free ports; its mechanisms and sensors stay (Undo takes it back)">
            <select
              value=""
              onChange={(e) => {
                const preset = e.target.value;
                if (preset) props.onPreset(preset);
              }}
              aria-label="Start the drive over with a preset"
              data-testid="drive-preset"
            >
              <option value="">with a preset drive…</option>
              {DRIVE_PRESETS.map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </Row>

          <h4>Wheels</h4>
          <table className="design-table" data-testid="wheels">
            <thead>
              <tr>
                <th>Name</th>
                <th title="inches forward of the robot's origin">x</th>
                <th title="inches to the left">y</th>
                <th title="the way it rolls, degrees counter-clockwise from forward">Heading</th>
                <th>Type</th>
                <th title="diameter, inches">⌀</th>
                {mecanum && <th title="the angle of its rollers on the floor, degrees">Rollers</th>}
                <th aria-label="Remove" />
              </tr>
            </thead>
            <tbody>
              {wheels.map((wheel, i) => {
                const path = `drivetrain.wheels[${i}]`;
                return (
                  <tr key={i} className={item(path, "")} data-path={path} onFocus={() => pick(path)}>
                    <td>
                      <Entry
                        value={wheel.name}
                        label={`Wheel ${i + 1} name`}
                        className="name"
                        onCommit={(text) =>
                          act(() => {
                            const problem = nameProblem(text, wheelNames.filter((n) => n !== wheel.name));
                            if (problem) throw new Error(`Wheel ${wheel.name}: ${problem}`);
                            return renameWheelEdits(robot, i, text);
                          })
                        }
                      />
                    </td>
                    <td>
                      <Num label={`${wheel.name} x (in)`} value={wheel.pos_in[0]} act={act} onSet={(v) => [set(`${path}.pos_in`, [v, wheel.pos_in[1]])]} />
                    </td>
                    <td>
                      <Num label={`${wheel.name} y (in)`} value={wheel.pos_in[1]} act={act} onSet={(v) => [set(`${path}.pos_in`, [wheel.pos_in[0], v])]} />
                    </td>
                    <td>
                      <Num label={`${wheel.name} heading (degrees)`} value={wheel.heading_deg ?? 0} act={act} onSet={(v) => [set(`${path}.heading_deg`, v)]} />
                    </td>
                    <td>
                      <select value={wheel.type} onChange={(e) => run(() => wheelTypeEdits(robot, i, e.target.value as WheelConfig["type"]))} aria-label={`${wheel.name} type`}>
                        {WHEEL_TYPES.map((type) => (
                          <option key={type}>{type}</option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <Num label={`${wheel.name} diameter (in)`} value={wheel.diameter_in} positive act={act} onSet={(v) => [set(`${path}.diameter_in`, v)]} />
                    </td>
                    {mecanum && (
                      <td>
                        {wheel.type === "mecanum" && (
                          <Num label={`${wheel.name} roller angle (degrees)`} value={wheel.roller_angle_deg ?? null} act={act} onSet={(v) => [set(`${path}.roller_angle_deg`, v)]} />
                        )}
                      </td>
                    )}
                    <td>
                      <button
                        type="button"
                        className="ghost small"
                        aria-label={`Remove wheel ${wheel.name}`}
                        title="Take this wheel away"
                        onClick={() =>
                          run(
                            () => {
                              if (wheels.length <= 1) throw new Error("A drive needs a wheel.");
                              const alone = groups.find(([, g]) => g.wheels.length === 1 && g.wheels[0] === wheel.name);
                              if (alone) throw new Error(`${wheel.name} is the only wheel motor group ${alone[0]} drives: give the group another wheel first, or take the group away.`);
                              return removeWheelEdits(robot, i);
                            },
                            () => props.onSelect(null),
                          )
                        }
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="design-add">
            <button type="button" className="small" onClick={() => run(() => [{ location: "drivetrain.wheels", op: "add", value: newWheel(robot) }])} data-testid="add-wheel">
              Add a wheel
            </button>
          </div>

          <h4>Motor groups</h4>
          {groups.map(([name, group]) => {
            const path = `drivetrain.gearing.${name}`;
            const rpm = CARTRIDGE_RPM[group.cartridge] * ratioValue(group.ratio);
            const side = sided && SIDES.includes(name); // named by the drive's type
            return (
              <div key={name} className={item(path)} data-path={path} data-testid={`group-${name}`}>
                <div className="design-item-head">
                  {side ? (
                    <strong className="group-name" title={`A ${robot.drivetrain.type === "hdrive" ? "H-drive" : "tank drive"}'s ${name} side: its name is the drive's`}>
                      {name}
                    </strong>
                  ) : (
                    <Entry
                      value={name}
                      label="Motor group name"
                      className="name"
                      onCommit={(text) =>
                        act(() => {
                          const problem = nameProblem(text, Object.keys(robot.drivetrain.gearing).filter((n) => n !== name));
                          if (problem) throw new Error(`Motor group ${name}: ${problem}`);
                          return [{ location: path, op: "rename", value: text }];
                        })
                      }
                    />
                  )}
                  <span className="muted small">
                    {group.motors.length} motor{group.motors.length === 1 ? "" : "s"}, wheels at {Math.round(rpm)} rpm
                  </span>
                  <button
                    type="button"
                    className="ghost small"
                    aria-label={`Remove motor group ${name}`}
                    title={side ? "A side of the drive stays: change its motors instead" : "Take this motor group away"}
                    disabled={side}
                    onClick={() =>
                      run(() => {
                        if (groups.length <= 1) throw new Error("A drive needs a motor group.");
                        return [remove(path)];
                      })
                    }
                  >
                    ×
                  </button>
                </div>
                <Motors path={path} motors={group.motors} cartridge={group.cartridge} ratio={group.ratio} act={act} run={run} name={name} />
                <Row label="Wheels" title="The wheels these motors turn">
                  <span className="checks">
                    {wheelNames.map((wheel) => (
                      <label key={wheel} className="check">
                        <input
                          type="checkbox"
                          checked={group.wheels.includes(wheel)}
                          onChange={(e) =>
                            run(() => {
                              const on = e.target.checked;
                              const next = wheelNames.filter((w) => (w === wheel ? on : group.wheels.includes(w)));
                              if (!next.length) throw new Error(`Motor group ${name} needs a wheel to drive.`);
                              return [set(`${path}.wheels`, next)];
                            })
                          }
                        />{" "}
                        {wheel}
                      </label>
                    ))}
                  </span>
                </Row>
              </div>
            );
          })}
          <div className="design-add">
            <button
              type="button"
              className="small"
              disabled={robot.drivetrain.type === "differential"}
              title={
                robot.drivetrain.type === "differential"
                  ? "A tank drive's motors are in two groups, left and right"
                  : robot.drivetrain.type === "hdrive"
                    ? "Another strafe group"
                    : "Motors geared to wheels of their own"
              }
              onClick={() =>
                run(() => {
                  const [name, group] = newGroup(robot);
                  return [set(`drivetrain.gearing.${name}`, group)];
                })
              }
              data-testid="add-group"
            >
              Add a motor group
            </button>
          </div>
        </section>

        <section data-testid="mechanisms">
          <h3>Mechanisms</h3>
          {mechanisms.length === 0 && <p className="muted small">Motors that aren't the drive's: an intake, a lift, an arm.</p>}
          {mechanisms.map(([name, mechanism]) => {
            const path = `mechanisms.${name}`;
            return (
              <div key={name} className={item(path)} data-path={path} data-testid={`mechanism-${name}`}>
                <div className="design-item-head">
                  <Entry
                    value={name}
                    label="Mechanism name"
                    className="name"
                    onCommit={(text) =>
                      act(() => {
                        const problem = nameProblem(text, Object.keys(robot.mechanisms ?? {}).filter((n) => n !== name));
                        if (problem) throw new Error(`Mechanism ${name}: ${problem}`);
                        return [{ location: path, op: "rename", value: text }];
                      })
                    }
                  />
                  <span className="muted small">
                    {mechanism.motors.length} motor{mechanism.motors.length === 1 ? "" : "s"}, output at {Math.round(CARTRIDGE_RPM[mechanism.cartridge] * ratioValue(mechanism.ratio))} rpm
                  </span>
                  <button type="button" className="ghost small" aria-label={`Remove mechanism ${name}`} title="Take this mechanism away" onClick={() => run(() => [remove(path)])}>
                    ×
                  </button>
                </div>
                <Motors path={path} motors={mechanism.motors} cartridge={mechanism.cartridge} ratio={mechanism.ratio} act={act} run={run} name={name} output="output" />
                <Row label="Load" unit="kg·m²" title="The inertia of what it moves, at its output">
                  <Num label={`${name} load inertia (kg·m²)`} value={mechanism.inertia_kgm2 ?? 0} min={0} act={act} onSet={(v) => [set(`${path}.inertia_kgm2`, v)]} />
                </Row>
                <Row label="Torque" unit="N·m" title="A constant torque at the output, toward negative angles: a lift's weight times its spool's radius">
                  <Num label={`${name} load torque (N·m)`} value={mechanism.load_torque_nm ?? 0} act={act} onSet={(v) => [set(`${path}.load_torque_nm`, v)]} />
                </Row>
                <Row label="Friction" unit="N·m" title="Friction at the output">
                  <Num label={`${name} friction (N·m)`} value={mechanism.friction_nm ?? 0} min={0} act={act} onSet={(v) => [set(`${path}.friction_nm`, v)]} />
                </Row>
                <Row label="Stops" unit="°" title="Hard stops: the lowest and highest output angles, from where it starts (blank: none)">
                  <Entry
                    value={mechanism.range_deg ? mechanism.range_deg.map(shown).join(", ") : ""}
                    label={`${name} hard stops (degrees, low, high)`}
                    placeholder="none"
                    onCommit={(text) =>
                      act(() => {
                        if (!text) return mechanism.range_deg ? [remove(`${path}.range_deg`)] : [];
                        const range = text.split(/[\s,]+/).filter(Boolean).map(Number);
                        if (range.length !== 2 || !range.every(Number.isFinite) || !(range[0] <= 0 && 0 <= range[1] && range[0] < range[1])) {
                          throw new Error(`${name}'s hard stops are two angles, low and high, with 0 (where it starts) between them: "${text}" aren't`);
                        }
                        return [set(`${path}.range_deg`, range)];
                      })
                    }
                  />
                </Row>
              </div>
            );
          })}
          <div className="design-add">
            <button
              type="button"
              className="small"
              onClick={() =>
                run(() => {
                  const [name, mechanism] = newMechanism(robot);
                  return [set(`mechanisms.${name}`, mechanism)];
                })
              }
              data-testid="add-mechanism"
            >
              Add a mechanism
            </button>
          </div>
        </section>

        <section data-testid="sensors">
          <h3>Sensors</h3>
          {sensors.length === 0 && <p className="muted small">None yet: a robot without them drives, but its program can't see where it is.</p>}
          {sensors.map((sensor, i) => (
            <SensorItem
              key={i}
              sensor={sensor}
              index={i}
              ports={ports}
              act={act}
              run={run}
              className={item(`sensors[${i}]`)}
              onFocus={() => pick(sensor.type === "rotation" && sensor.tracking_wheel ? `sensors[${i}].tracking_wheel` : `sensors[${i}]`)}
              onRemove={() => run(() => [remove(`sensors[${i}]`)], () => props.onSelect(null))}
            />
          ))}
          <div className="design-add" data-testid="add-sensor">
            <span className="muted small">Add</span>
            {SENSOR_TYPES.map(([type, label]) => (
              <button key={type} type="button" className="small" onClick={() => run(() => [{ location: "sensors", op: "add", value: newSensor(robot, type) }])} data-testid={`add-${type}`}>
                {label}
              </button>
            ))}
          </div>
        </section>

        <section>
          <h3>Ports</h3>
          <ol className="port-map" data-testid="port-map">
            {Array.from({ length: PORTS }, (_, i) => i + 1).map((port) => {
              const users = ports.get(port) ?? [];
              const state = users.length > 1 ? "clash" : users.length ? "used" : "free";
              return (
                <li key={port} className={`port ${state}`} title={users.length ? users.map(describeUser).join("\n") : "Free"} data-testid={`port-${port}`} data-state={state}>
                  <span className="port-number">{port}</span>
                  <span className="port-users">{users.length ? users.map(shortUser).join(" + ") : "free"}</span>
                </li>
              );
            })}
          </ol>
          {clashes > 0 && (
            <p className="bad small" role="alert">
              {clashes === 1 ? "A port has" : `${clashes} ports have`} two things on {clashes === 1 ? "it" : "them"}: give one of them another port.
            </p>
          )}
        </section>
      </fieldset>
    </div>
  );
}

function shortUser(user: PortUser): string {
  if (user.kind === "sensor") return user.name;
  return `${user.name}${user.kind === "drive" ? " drive" : ""}${user.reversed ? " (rev)" : ""}`;
}

// --- the shape ---------------------------------------------------------------------------------

function ShapeSection(props: { robot: RobotConfig; act: Act; run: (make: () => ConfigEdit[], then?: () => void) => void; part: number | null; onPart: (index: number | null) => void }) {
  const { robot, act, run } = props;
  const shape = shapeOf(robot.body);
  const index = props.part !== null && props.part < shape.length ? props.part : null;
  const part = index === null ? null : shape[index];
  const put = (next: ShapePart): ConfigEdit[] => {
    if (next.type === "outline") {
      const problem = outlineProblem(next.points_in);
      if (problem) throw new Error(`That outline can't be: ${problem}.`);
    }
    return partEdits(robot, index!, next);
  };
  const mirror = part ? mirroredPart(part) : null;

  return (
    <section data-testid="shape">
      <h3>Shape</h3>
      {isFootprint(robot.body) && (
        <p className="muted small">
          A rectangle (<code>body.footprint_in</code>). Draw on it, or change it here, and it becomes a shape of parts.
        </p>
      )}
      <ol className="design-parts">
        {shape.map((p, i) => (
          <li key={i}>
            <button type="button" className={`ghost small${i === index ? " on" : ""}`} aria-pressed={i === index} onClick={() => props.onPart(i === index ? null : i)} data-testid={`shape-part-${i}`}>
              {describePart(p)}
            </button>
          </li>
        ))}
      </ol>
      {part && (
        <div className="design-item on" data-testid="shape-part">
          {part.type !== "outline" && (
            <Row label="Center" unit="in">
              {[0, 1].map((k) => (
                <Num
                  key={k}
                  label={`Part ${index! + 1} center ${"xy"[k]} (in)`}
                  value={(part.pos_in ?? [0, 0])[k]}
                  act={act}
                  onSet={(v) => put({ ...part, pos_in: (part.pos_in ?? [0, 0]).map((c, j) => (j === k ? v : c)) as [number, number] })}
                />
              ))}
            </Row>
          )}
          {part.type === "rect" && (
            <>
              <Row label="Size" unit="in" title="Length (along x, forward) and width">
                {[0, 1].map((k) => (
                  <Num
                    key={k}
                    label={`Part ${index! + 1} ${k ? "width" : "length"} (in)`}
                    value={part.size_in[k]}
                    positive
                    act={act}
                    onSet={(v) => put({ ...part, size_in: part.size_in.map((c, j) => (j === k ? v : c)) as [number, number] })}
                  />
                ))}
              </Row>
              <Row label="Turned" unit="°" title="Degrees counter-clockwise">
                <Num label={`Part ${index! + 1} heading (degrees)`} value={part.heading_deg ?? 0} act={act} onSet={(v) => put({ ...part, heading_deg: v })} />
              </Row>
            </>
          )}
          {part.type === "circle" && (
            <Row label="Diameter" unit="in">
              <Num label={`Part ${index! + 1} diameter (in)`} value={part.diameter_in} positive act={act} onSet={(v) => put({ ...part, diameter_in: v })} />
            </Row>
          )}
          {part.type === "outline" && (
            <table className="design-table">
              <thead>
                <tr>
                  <th>Point</th>
                  <th>x</th>
                  <th>y</th>
                  <th aria-label="Remove" />
                </tr>
              </thead>
              <tbody>
                {part.points_in.map(([x, y], i) => (
                  <tr key={i}>
                    <td className="muted">{i + 1}</td>
                    {[x, y].map((value, k) => (
                      <td key={k}>
                        <Num
                          label={`Point ${i + 1} ${"xy"[k]} (in)`}
                          value={value}
                          act={act}
                          onSet={(v) => put({ ...part, points_in: part.points_in.map((p, j): [number, number] => (j === i ? (k ? [p[0], v] : [v, p[1]]) : p)) })}
                        />
                      </td>
                    ))}
                    <td>
                      <button
                        type="button"
                        className="ghost small"
                        aria-label={`Remove point ${i + 1}`}
                        disabled={part.points_in.length <= 3}
                        onClick={() => run(() => put({ ...part, points_in: part.points_in.filter((_, j) => j !== i) }))}
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="design-add">
            {part.type === "outline" && (
              <button
                type="button"
                className="small"
                title="A point halfway along the edge from the last point back to the first"
                onClick={() =>
                  run(() => {
                    const points = part.points_in;
                    const [a, b] = [points[points.length - 1], points[0]];
                    return put({ ...part, points_in: [...points, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]] });
                  })
                }
              >
                Add a point
              </button>
            )}
            <button
              type="button"
              className="small"
              disabled={!mirror}
              title={mirror ? "Add its mirror image across the robot's center line" : "It is its own mirror image"}
              onClick={() => mirror && run(() => partEdits(robot, null, mirror), () => props.onPart(shape.length))}
              data-testid="mirror-part"
            >
              Mirror copy
            </button>
            <button
              type="button"
              className="small"
              disabled={shape.length <= 1}
              title={shape.length <= 1 ? "A robot's shape needs a part" : "Take this part away (Delete, on the diagram)"}
              onClick={() => run(() => partEdits(robot, index!, null), () => props.onPart(null))}
              data-testid="delete-part"
            >
              Delete
            </button>
          </div>
        </div>
      )}
      <p className="muted small">Draw more with the tools on the diagram: where parts overlap they merge.</p>
    </section>
  );
}

// --- motors and sensors ------------------------------------------------------------------------

/** A motor group's or a mechanism's motors: their ports, cartridge and gearing. */
function Motors(props: {
  path: string;
  name: string;
  motors: number[];
  cartridge: (typeof CARTRIDGES)[number];
  ratio: string | number | undefined;
  act: Act;
  run: (make: () => ConfigEdit[]) => void;
  output?: string;
}) {
  const { path, name, act } = props;
  return (
    <>
      <Row label="Ports" title="Smart ports, separated by commas; a negative port runs its motor reversed">
        <Entry
          value={props.motors.join(", ")}
          label={`${name} motor ports`}
          wide
          onCommit={(text) =>
            act(() => {
              const ports = readPorts(text);
              if (!ports) throw new Error(`${name}'s motor ports are 1 to ${PORTS}, separated by commas (a negative one runs reversed): "${text}" aren't`);
              return [set(`${path}.motors`, ports)];
            })
          }
          testid={`${path}.motors`}
        />
      </Row>
      <Row label="Cartridge">
        <select value={props.cartridge} onChange={(e) => props.run(() => [set(`${path}.cartridge`, e.target.value)])} aria-label={`${name} cartridge`}>
          {CARTRIDGES.map((cartridge) => (
            <option key={cartridge} value={cartridge}>
              {cartridge} ({CARTRIDGE_RPM[cartridge]} rpm)
            </option>
          ))}
        </select>
      </Row>
      <Row label="Ratio" title={`Gear teeth, motor : ${props.output ?? "wheel"} (36:48 turns it at 3/4 of the motors' speed), or a number`}>
        <Entry
          value={props.ratio === undefined || props.ratio === null ? "1" : String(props.ratio)}
          label={`${name} gear ratio`}
          onCommit={(text) =>
            act(() => {
              const ratio = readRatio(text);
              if (ratio === null) throw new Error(`${name}'s gear ratio is teeth, motor : ${props.output ?? "wheel"} (like 36:48), or a number more than 0: "${text}" isn't`);
              return [set(`${path}.ratio`, ratio)];
            })
          }
        />
      </Row>
    </>
  );
}

function SensorItem(props: {
  sensor: Sensor;
  index: number;
  ports: Map<number, PortUser[]>;
  act: Act;
  run: (make: () => ConfigEdit[]) => void;
  className: string;
  onFocus: () => void;
  onRemove: () => void;
}) {
  const { sensor, act } = props;
  const path = `sensors[${props.index}]`;
  const name = sensorName(sensor.type);
  const title = sensor.type === "rotation" ? (sensor.tracking_wheel ? "Tracking wheel" : "Rotation sensor") : name[0].toUpperCase() + name.slice(1);
  const position = (at: string, pos: [number, number] | undefined, what: string) => (
    <Row label="Position" unit="in" title="x forward and y left of the robot's origin (or drag it on the diagram)">
      {[0, 1].map((k) => (
        <Num
          key={k}
          label={`${what} ${"xy"[k]} (in)`}
          value={(pos ?? [0, 0])[k]}
          act={act}
          onSet={(v) => [set(`${at}.pos_in`, (pos ?? [0, 0]).map((c, j) => (j === k ? v : c)))]}
        />
      ))}
    </Row>
  );
  const turned = (key: string, value: number | undefined, label: string, hint: string) => (
    <Row label={label} unit="°" title={hint}>
      <Num label={`${title} ${label.toLowerCase()} (degrees)`} value={value ?? 0} act={act} onSet={(v) => [set(`${path}.${key}`, v)]} />
    </Row>
  );
  return (
    <div className={props.className} data-path={path} onFocus={props.onFocus} data-testid={`sensor-${props.index}`}>
      <div className="design-item-head">
        <strong>{title}</strong>
        <label className="small">
          Port{" "}
          <select value={sensor.port} onChange={(e) => props.run(() => [set(`${path}.port`, Number(e.target.value))])} aria-label={`${title} port`}>
            {Array.from({ length: PORTS }, (_, i) => i + 1).map((port) => {
              const users = port === sensor.port ? [] : (props.ports.get(port) ?? []);
              return (
                <option key={port} value={port}>
                  {port}
                  {users.length ? ` (${users.map(describeUser).join(", ")})` : ""}
                </option>
              );
            })}
          </select>
        </label>
        <button type="button" className="ghost small" aria-label={`Remove ${title} on port ${sensor.port}`} title="Take this sensor away" onClick={props.onRemove}>
          ×
        </button>
      </div>
      {sensor.type === "imu" && (
        <>
          {position(path, sensor.pos_in, title)}
          {turned("mount_yaw_deg", sensor.mount_yaw_deg, "Mounted", "Which way it faces, degrees counter-clockwise from forward")}
          <Row label="Scale error" title="Its own error over a full turn, if measured: (reading - true) / true, e.g. 0.0025. Blank: each run draws one at random">
            <Num
              label="IMU scale error"
              value={sensor.scale_error ?? null}
              placeholder="random"
              act={act}
              onClear={() => (sensor.scale_error == null ? [] : [remove(`${path}.scale_error`)])}
              onSet={(v) => {
                if (Math.abs(v) >= 0.5) throw new Error("An IMU's scale error is between -0.5 and 0.5.");
                return [set(`${path}.scale_error`, v)];
              }}
            />
          </Row>
        </>
      )}
      {sensor.type === "rotation" && (
        <>
          <Row label="Reversed">
            <input type="checkbox" checked={!!sensor.reversed} onChange={(e) => props.run(() => [set(`${path}.reversed`, e.target.checked)])} aria-label="Rotation sensor reversed" />
          </Row>
          <Row label="Tracking" title="A free-spinning wheel this sensor measures, for odometry">
            <input
              type="checkbox"
              checked={!!sensor.tracking_wheel}
              onChange={(e) => props.run(() => [e.target.checked ? set(`${path}.tracking_wheel`, { pos_in: [0, -1.5], heading_deg: 0, diameter_in: 2 }) : remove(`${path}.tracking_wheel`)])}
              aria-label="A tracking wheel"
            />
          </Row>
          {sensor.tracking_wheel && (
            <>
              {position(`${path}.tracking_wheel`, sensor.tracking_wheel.pos_in, "Tracking wheel")}
              <Row label="Heading" unit="°" title="The way it rolls, degrees counter-clockwise from forward">
                <Num label="Tracking wheel heading (degrees)" value={sensor.tracking_wheel.heading_deg ?? 0} act={act} onSet={(v) => [set(`${path}.tracking_wheel.heading_deg`, v)]} />
              </Row>
              <Row label="Diameter" unit="in">
                <Num label="Tracking wheel diameter (in)" value={sensor.tracking_wheel.diameter_in} positive act={act} onSet={(v) => [set(`${path}.tracking_wheel.diameter_in`, v)]} />
              </Row>
            </>
          )}
        </>
      )}
      {sensor.type === "distance" && (
        <>
          {position(path, sensor.pos_in, title)}
          {turned("heading_deg", sensor.heading_deg, "Facing", "Which way its beam points, degrees counter-clockwise from forward")}
          <Row label="Height" unit="in" title="Its beam's height above the floor: field elements lower than it pass under (blank: it sees them all)">
            <Num
              label="Distance sensor height (in)"
              value={sensor.height_in ?? null}
              positive
              placeholder="sees all"
              act={act}
              onClear={() => (sensor.height_in == null ? [] : [remove(`${path}.height_in`)])}
              onSet={(v) => [set(`${path}.height_in`, v)]}
            />
          </Row>
        </>
      )}
      {sensor.type === "gps" && (
        <>
          {position(path, sensor.pos_in, title)}
          {turned("mount_yaw_deg", sensor.mount_yaw_deg, "Facing", "Which way its camera faces, degrees counter-clockwise from forward")}
        </>
      )}
      <Row label="Noise" title="ideal: exact readings; default: like a real one; harsh: worse">
        <select value={sensor.noise ?? "default"} onChange={(e) => props.run(() => [set(`${path}.noise`, e.target.value)])} aria-label={`${title} noise`}>
          {NOISE.map((noise) => (
            <option key={noise}>{noise}</option>
          ))}
        </select>
      </Row>
    </div>
  );
}

// --- fields ------------------------------------------------------------------------------------

function Row(props: { label: string; unit?: string; title?: string; children: ReactNode }) {
  return (
    <div className="design-row" title={props.title}>
      <span className="design-label">{props.label}</span>
      <span className="design-values">{props.children}</span>
      <span className="design-unit muted">{props.unit ?? ""}</span>
    </div>
  );
}

/** A value typed in a box: written when you leave it or press Enter, put back as it is with
 * Escape. Until it's written the box shows what you typed. */
function Entry(props: {
  value: string;
  onCommit: (text: string) => Promise<void>;
  label: string;
  className?: string;
  placeholder?: string;
  numeric?: boolean;
  wide?: boolean;
  testid?: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const writing = useRef(false);
  const commit = async () => {
    if (draft === null || writing.current) return;
    const text = draft.trim();
    if (text !== props.value.trim()) {
      writing.current = true;
      try {
        await props.onCommit(text);
      } catch {
        // the editor says why; the box shows the value as it is
      } finally {
        writing.current = false;
      }
    }
    setDraft(null);
  };
  return (
    <input
      className={[props.className, props.numeric && "num", props.wide && "wide"].filter(Boolean).join(" ") || undefined}
      value={draft ?? props.value}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commit();
        } else if (e.key === "Escape" && draft !== null) {
          e.preventDefault();
          setDraft(null);
        }
      }}
      aria-label={props.label}
      title={props.label}
      placeholder={props.placeholder}
      inputMode={props.numeric ? "decimal" : undefined}
      spellCheck={false}
      autoComplete="off"
      data-testid={props.testid}
    />
  );
}

/** A number in a box. Blank means none, where it can be (`onClear`). */
function Num(props: {
  label: string;
  value: number | null | undefined;
  onSet: (value: number) => ConfigEdit[];
  onClear?: () => ConfigEdit[];
  act: Act;
  positive?: boolean;
  min?: number;
  placeholder?: string;
  testid?: string;
}) {
  const what = props.label.replace(/ \(.*\)$/, "");
  return (
    <Entry
      numeric
      value={shown(props.value)}
      label={props.label}
      placeholder={props.placeholder}
      testid={props.testid}
      onCommit={(text) =>
        props.act(() => {
          if (!text) {
            if (props.onClear) return props.onClear();
            throw new Error(`${what} needs a number.`);
          }
          const value = Number(text);
          if (!Number.isFinite(value)) throw new Error(`${what}: "${text}" isn't a number.`);
          if (props.positive && value <= 0) throw new Error(`${what} is more than 0.`);
          if (props.min !== undefined && value < props.min) throw new Error(`${what} is ${props.min} or more.`);
          return props.onSet(value);
        })
      }
    />
  );
}
