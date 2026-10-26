# Conventions

## Units
| Where | Units |
|---|---|
| Physics, sensors, internal math | SI: m, kg, s, rad, N, N*m, V, A |
| Config files, CLI output, logs, robot-code API | VEX: inches, degrees, rpm, mV, kg for mass |

Conversions happen only at those boundaries, using `vexsim.units`.

## Frames
**Robot frame**
- Origin at the center of the footprint.
- **+x forward, +y left, +z up**, right-handed.
- Angles are counter-clockwise from +x when seen from above.
- Positions in the robot YAML (`pos_in`, `cg_in`) are in this frame.

**Field frame**
- Origin at the field center, axes parallel to the walls. Right-handed, with angles counter-clockwise from +x.
- The walls' inside faces are at `x = ±size_in[0]/2` and `y = ±size_in[1]/2` (default 144 x 144 in, from the field config).
- PROS and LemLib use a different convention: heading clockwise from +y. Robot code never sees vexsim's frame. `vexsim::report_pose` takes the LemLib convention and converts it ([cpp.md](cpp.md#whats-simulated)).

## Robot config semantics
**Wheels**
- `heading_deg` is the direction the wheel rolls when its gear group turns forward (positive).
  - Differential drive wheels use 0.
  - H-drive strafe wheels use 90, so a positive strafe group pushes the robot to its left.
  - X-drive wheels use ±45. In the examples every wheel rolls forward-ish (front-left -45, front-right 45, back-left 45, back-right -45), so driving straight ahead turns every group forward.
- `drop_in` lowers a wheel relative to the others, as in a drop-center drivetrain. A lowered wheel carries more of the robot's weight.
- `roller_angle_deg` (mecanum wheels only, required) is the axis of the rollers touching the ground, counter-clockwise from the rolling direction, seen from above.
  - The usual layout is -45 at front-left and back-right, and 45 at front-right and back-left.
  - Looking down on such a robot, the rollers on top of the wheels form an "X". The ground rollers are their mirror image.
  - Check it with `vexsim run`: the left stick's sideways axis should strafe the robot that way.

**Drivetrain types**
| `type` | Gearing groups | Validation |
|---|---|---|
| `differential` | exactly `left` and `right` | wheels parallel to x, sides on the right sides |
| `hdrive` | `left`, `right`, plus one or more strafe groups (any names) | as differential; strafe wheels perpendicular |
| `xdrive` | any, usually one per wheel | must be able to strafe; warns about non-omni wheels |
| `mecanum` | any, usually one per wheel | must be able to strafe; warns about non-mecanum wheels |

Any wheel type works in any drivetrain: a tank drive with traction wheels in the middle is a `differential` drive.

**Gearing**
- `ratio: "36:48"` means a 36-tooth gear on the motor side drives a 48-tooth gear on the wheel side, so the wheel turns at 0.75x motor speed. A bare number is wheel speed divided by motor speed.
- Write ratios quoted or unquoted. Unquoted `36:48` stays text, where plain YAML would read it as the base-60 number 2208.

**Ports**
- Ports 1-21, one device per port across motors and sensors.
- A negative motor port means reversed, as in PROS 4.

**Tracking wheels:** `heading_deg` is the direction of travel the wheel measures. Use 0 for a forward-tracking wheel and 90 for a sideways-tracking wheel.

**`inertia_kgm2: auto`** treats the robot as a uniform box over its footprint, using `m(L^2 + W^2)/12`. Give a measured value if you have one.

**GPS:** `pos_in` is where the sensor sits, and `mount_yaw_deg` the direction its camera faces, counter-clockwise from the robot's +x. A GPS facing backward has `mount_yaw_deg: 180`.

**Distance sensors:** `height_in` is the beam's height above the floor. Field elements with a `height_in` at or below it pass under the beam. Without it, the sensor sees every element.

**IMU `scale_error`** (optional) is that IMU's measured scale error: (reading - true) / true over a full turn. An IMU that reads 360.91° for a real 360° has `scale_error: 0.002528`. Without it, each simulated IMU draws its own at random.

**Mechanisms** (lifts, intakes, arms; see [models.md](models.md#mechanisms-vexsimphysicsmechanismpy)):
```yaml
mechanisms:
  lift: {motors: [-7, 21], cartridge: blue, ratio: 1, inertia_kgm2: 0.0004,
         load_torque_nm: 0.3, friction_nm: 0.03, range_deg: [0, 6300]}
  intake: {motors: [20], cartridge: blue}
```
- A mechanism is one output (a spool, a roller, a pivot). `ratio` is output speed / motor speed, written like the drive's gearing: `"12:48"` is a 4:1 reduction.
- Positive is the motors' positive direction; a negative port is mounted reversed, as in a `MotorGroup`.
- Angles are output degrees from where the mechanism starts. `range_deg: [low, high]` are its hard stops, so `low <= 0 <= high`. A lift that starts at the bottom has `low: 0`.
- `inertia_kgm2`, `load_torque_nm` (pulls toward negative angles) and `friction_nm` are at the output. All default to 0.

**Validation**
- Typos in keys are errors, and the message suggests the closest valid key.
- Duplicate keys are errors. Plain YAML silently keeps the last one.

## Sensor readings
Sensor frames (`vexsim.devices.frame.SensorFrame`) carry what PROS code would read, so algorithms move between Python and C++ unchanged.

| Device | Reading | Units |
|---|---|---|
| Motor | position, velocity, current, voltage, temperature | degrees, rpm, mA, mV, °C |
| Rotation | position (cumulative), velocity | centidegrees (int), centidegrees/s |
| IMU | rotation (cumulative), heading 0–360, gyro z | degrees, **clockwise positive**; `None` while calibrating |
| Distance | distance | mm (int); `None` when nothing is in range |
| GPS | position, heading, error | meters from the field center; degrees **clockwise from +y**; meters. `None` before the first fix |

- **Reversal follows PROS.** A negative motor port, or `reversed: true` on a rotation sensor, means the raw reading runs backwards, and the robot code is expected to reverse it, exactly like `pros::Motor(-4)`. The baseline localizers read these flags from the config.
- **Tracking wheel geometry.** A tracking wheel's `heading_deg` is the direction of travel it measures: 0 for vertical, 90 for horizontal. 180 and 270 count backwards.
- **Odometry offsets** are measured from the footprint center: a vertical wheel by its `y` (+left), a horizontal wheel by its `x` (+forward).
- **GPS frame.** vexsim's field frame is the GPS's: +y is the GPS's "north" (heading 0), so a robot facing +x reads heading 90. On a real field, point vexsim's +y the way your GPS reads 0. The reading is the sensor's own position and camera direction. The robot code's offset (`set_offset(x, y)`, in meters) is where the sensor sits relative to the robot's center, with +y along the camera's direction and +x to its right, as PROS defines it. With it, the GPS reports the robot's center.

## Field elements
A field config lists game elements under `elements:`. See `examples/fields/practice_elements.yaml`; it is generic, not any season's layout.

```yaml
elements:
  - {type: obstacle, name: barrier, shape: rect, pos_in: [0, 0], size_in: [48, 3], heading_deg: 0}
  - {type: obstacle, name: goal, shape: circle, pos_in: [-48, 48], diameter_in: 10, color: "#d33f49"}
  - {type: piece, name: ball, pos_in: [-24, 24], diameter_in: 7, mass_kg: 0.25, friction: 0.4, restitution: 0.3}
```

- `pos_in` is the center, in the field frame. A rect's `size_in` is its length (along `heading_deg`) by its width.
- Pieces are discs: give a ring or cylinder its outer diameter. `friction` is the ground friction coefficient (default 0.4); `restitution` is how much of its speed it keeps bouncing off something (default 0.3).
- An obstacle's `height_in` is its top above the floor. Distance sensors whose beam is higher see over it; without it, the obstacle is taller than any sensor.
- `solid: false` marks an obstacle low enough to drive over (a goal base the robot straddles, say): robots and pieces pass over it, and only sensors see it.
- `color` (`"#rrggbb"`) is only for the viewer. The viewer draws elements that aren't solid as outlines.
- Validation: elements must be inside the walls; a piece that starts overlapping a wall, a solid obstacle or another piece gets a warning.

## Time
- Simulation time is an integer number of **microseconds**, so runs never drift.
- The physics step defaults to 1 ms.
- Every event period and offset must be a whole number of physics steps.

One tick at time `t`:
1. Fire every event due at `t`, ordered by priority (lower first), then by registration order.
   - Sensors use `PRIORITY_SENSOR` (-100).
   - Controllers use `PRIORITY_CONTROL` (0).
   - Recorders use `PRIORITY_RECORD` (100).

   This way a controller sees that tick's sensor readings.
2. Step the physics systems from `t` to `t + dt`, in the order they were added.
3. Advance the clock.

## Randomness
- All noise comes from `world.rng.stream(name)`. Each name gets an independent generator derived from the run's seed.
- Name streams by source, for example `sensor.imu.10` or `sensor.rotation.11`. Adding a sensor then never changes the noise another sensor sees.
- The same seed with the same versions of numpy and vexsim gives bit-identical runs. Results are not guaranteed to match across platforms or library versions.
