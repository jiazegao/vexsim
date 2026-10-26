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
- PROS and LemLib use a different convention: heading clockwise from +y. Robot code never sees vexsim's frame. `vexsim::report_pose` takes the LemLib convention and converts it ([cpp.md](cpp.md#whats-simulated)).

## Robot config semantics
**Wheels**
- `heading_deg` is the direction the wheel rolls when driven forward. Differential drive wheels use 0.
- `drop_in` lowers a wheel relative to the others, as in a drop-center drivetrain.

**Gearing**
- `ratio: "36:48"` means a 36-tooth gear on the motor side drives a 48-tooth gear on the wheel side, so the wheel turns at 0.75x motor speed. A bare number is wheel speed divided by motor speed.
- Write ratios quoted or unquoted. Unquoted `36:48` stays text, where plain YAML would read it as the base-60 number 2208.

**Ports**
- Ports 1-21, one device per port across motors and sensors.
- A negative motor port means reversed, as in PROS 4.

**Tracking wheels:** `heading_deg` is the direction of travel the wheel measures. Use 0 for a forward-tracking wheel and 90 for a sideways-tracking wheel.

**`inertia_kgm2: auto`** treats the robot as a uniform box over its footprint, using `m(L^2 + W^2)/12`. Give a measured value if you have one.

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

- **Reversal follows PROS.** A negative motor port, or `reversed: true` on a rotation sensor, means the raw reading runs backwards, and the robot code is expected to reverse it, exactly like `pros::Motor(-4)`. The baseline localizers read these flags from the config.
- **Tracking wheel geometry.** A tracking wheel's `heading_deg` is the direction of travel it measures: 0 for vertical, 90 for horizontal. 180 and 270 count backwards.
- **Odometry offsets** are measured from the footprint center: a vertical wheel by its `y` (+left), a horizontal wheel by its `x` (+forward).

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
