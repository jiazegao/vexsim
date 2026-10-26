# Physics models

Every parameter below is labeled by where it comes from:
- **VEX**: published by VEX.
- **Fit**: derived from VEX's published curves by community curve-fitting.
- **Community**: reported on the VEX Forum, not official.
- **Estimate**: our assumption.

Estimates are calibration targets for Phase 10. All of them can be changed per robot through `overrides:` in the robot YAML, e.g. `motor.free_current_a: 0.2`. Run `vexsim validate-config` to see the accepted keys.

## V5 Smart Motor (11W): `vexsim/physics/motor.py`

![Simulated torque, current and power vs. speed, red cartridge](img/motor_curves_red.png)

`vexsim motor-curves --cartridge red --out docs/img/motor_curves_red.png` regenerates this chart. Use `--csv` for the numbers.

### Electrical and mechanical model
The model works at the motor core, before the cartridge. It ignores inductance, because the electrical time constant is far below the 1 ms step.
```
I           = (V - ke * w_core) / R        clamped to the effective current limit
torque_core = kt * I - (coulomb * tanh(w_core / w_s) + viscous * w_core)
torque_out  = G * torque_core,   w_core = G * w_out,   G = 36 / 18 / 6 (red / green / blue)
```
- `kt` and `ke` are fitted separately. `kt` / `ke` ≈ 0.88 absorbs gearbox efficiency.
- The motor reports its electrical draw (`V * I`) to the power system.
- I²R heat goes into the thermal model.

### Calibration targets (red cartridge, output side, 12.8 V)
| Quantity | Value | Source |
|---|---|---|
| Natural (uncapped) free speed | 121 rpm | Fit ([VEX Forum][fit]) |
| Natural stall torque | 3.99 N·m | Fit |
| Natural stall current | 4.69 A | Fit |
| No-load current | 0.15 A | Estimate |
| Coulomb share of no-load friction | 30% | Estimate |
| Current limit | 2.5 A (default and maximum) | VEX / PROS |
| Rotor inertia (core) | 2.0e-6 kg·m² | Estimate |

**Derived constants (core):**
- R = 2.729 Ω
- kt = 0.02386 N·m/A
- ke = 0.02716 V·s/rad
- Coulomb friction 1.07e-3 N·m
- viscous friction 5.5e-6 N·m·s

**Reflected rotor inertia at the output:**
| Cartridge | Inertia |
|---|---|
| red | 2.6e-3 kg·m² |
| green | 6.5e-4 kg·m² |
| blue | 7.2e-5 kg·m² |

### What the fit reproduces (checked in `tests/test_motor.py`)
| VEX statement ([KB][kb]) | Model |
|---|---|
| Stall torque 2.1 N·m (red); 1.05 green, 0.35 blue | 2.15 / 1.07 / 0.36 N·m (within 2.3%) |
| Holds full speed up to ~35% of stall torque | holds 100 rpm up to 0.71 N·m (34%) |
| Peak power ~12.75 W; 11 W+ across ~30% of the speed range | 12.6 W peak; above 11 W across about 30% of the range |
| Free speed is software-limited for motor-to-motor consistency | `move_velocity` capped at 100/200/600 rpm; speed holds on a low battery |

### Firmware behavior modeled
- **Velocity mode (`move_velocity`).** The target is clamped to rated speed. A feedforward plus PI loop runs every step, using a velocity estimate filtered at 2 ms. It can drive up to the full battery voltage, which is what lets it hold rated speed under load.
  - The integral term only accumulates near steady state, while acceleration is below 0.25 rated speeds per second. It only exists to reject load torque, and integrating during the approach would wind up.
  - Result: overshoot ≤ 1.5% and settling in 0.05–0.5 s for drivetrain-like loads (4–40× rotor inertia).
  - A load step of 30% of stall torque recovers fully in about 0.4 s.
  - Gains are an **estimate**; VEX does not publish the internal controller.
- **Voltage mode (`move_voltage`).** Applies the commanded voltage, ±12 V, limited by the battery. It is **not speed-capped**, so 12 V spins about 13% past rated speed (113 rpm on the red cartridge).
  - **Unverified**, and the first thing to measure on a real robot (see below).
- **Position mode and hold.** A position P loop (15 /s) produces a velocity target, which feeds the velocity loop above. `HOLD` captures the position at the moment the motor stops, holds it within 1° under half of stall torque, and springs back after overshooting.
- **Zero commands.** `move_voltage(0)` and `move_velocity(0)` stop the motor using its brake mode.
  - The PROS docs state this for `brake()` and velocity 0. For voltage 0 it's an **assumption**, to be verified in Phase 7.
- **Brake modes:**
  - `COAST`: windings open, so zero current.
  - `BRAKE`: windings shorted, so back-EMF brakes the motor, with a time constant of about 0.13 s at typical loads.
  - `HOLD`: closed-loop hold of the stopped position.

## Thermal model and derating: `vexsim/physics/thermal.py`
The model has two nodes:
- **Winding:** I²R heat enters here (heat capacity 12 J/K).
- **Housing/PCB:** where the temperature sensor sits (50 J/K).

Thermal resistances are 1.5 K/W from winding to housing and 4 K/W from housing to ambient, with ambient at 25 °C.

| Behavior | Value | Source |
|---|---|---|
| Derating steps | current × 1/2, 1/4, 1/8, then 0 | Community ([VEX Forum][derate]) |
| First step | 55 °C sensor temperature | Community (observed, not exact) |
| Spacing between steps | 5 °C | Estimate |
| Thermal capacities and resistances | see above | Estimate |
| Sensor reads the PCB / average, with lag | housing node, lagging the winding | Community |

With these values, a fully stalled motor (17 W of heat) reaches the first derating step after about 160 s, then cycles at the 50% step around 55 °C. Cruising unloaded stays near ambient.

## Battery: `vexsim/physics/battery.py`
| Quantity | Value | Source |
|---|---|---|
| Capacity | 1100 mAh | VEX |
| Nominal voltage | 12.8 V (4 LiFePO4 cells in series) | VEX |
| Open-circuit curve | 13.5 V full, 13.1 V at 50%, 12.6 V at 10%, 11.2 V empty | Estimate (generic LiFePO4 shape) |
| Internal resistance (cells + BMS + wiring) | 0.10 Ω | Estimate |

State of charge is tracked by counting charge, and the sim never charges the battery.

## Power distribution: `vexsim/physics/power.py`
- **Bus voltage:** the battery's terminal voltage under the total draw, plus the brain's 0.3 A (**estimate**). Motors see the previous step's bus voltage. That 1 ms lag stands in for bus capacitance and avoids an algebraic loop.
- **Current sharing:** with more than 8 motors plugged in, each motor's current limit becomes 20 A ÷ N. Community-reported ([VEX Forum][share]), not official.
- **Regeneration:** a motor generating power can feed other motors on the bus, but never charges the battery.

## Wheel contact: `vexsim/physics/wheel.py`
Each wheel produces three forces. Each is smoothed Coulomb friction, `coeff * N * tanh(x / x_s)`, of one contact velocity:

| Channel | Velocity | Force |
|---|---|---|
| traction | slip `s = w_wheel * r - v_long` | along the rolling direction (drives the robot) |
| roller | sideways velocity `v_lat` | across the wheel (resists sliding) |
| rolling | `w_wheel * r` | resists wheel rotation (coast-down losses) |

On an **omni** wheel the main wheel and the rollers are mechanically separate, so the channels are independent. An omni wheel rolling sideways on its rollers keeps full drive traction, which is how X-drives work. Traction and mecanum wheels need a coupled friction ellipse and arrive in Phase 9.

| Omni parameter (`wheel.omni.*`) | Default | Source |
|---|---|---|
| `longitudinal_mu`: main wheel traction on tiles | 0.9 | Estimate |
| `slip_velocity_m_s`: traction smoothing | 0.03 | Estimate |
| `lateral_mu`: roller friction when sliding sideways | 0.2 | Estimate; **controls drift** |
| `lateral_velocity_m_s`: roller smoothing | 0.02 | Estimate |
| `rolling_resistance`: lumped coast-down loss (foam, bearings, chain) | 0.10 | Estimate, sized so coast mode glides about 5 ft from full speed |
| `mass_kg`: per wheel, for spin inertia | 0.06 | Estimate |

![True path vs. drive-encoder odometry in a fast arc](img/drift_arc.png)

`vexsim drift examples/robots/full_omni_6m.yaml --out drift.png` regenerates this chart.

**Why omni robots drift.** In a turn the robot needs a sideways force of mass × speed × yaw rate. Only roller friction can supply it, up to `lateral_mu * g` of acceleration (about 2 m/s² by default). Past that the robot slides outward. Each instant the wheels push the robot along its new, rotated heading, and the sideways momentum it already had is only weakly resisted. So a sustained fast arc grows into a wide spiral, and the motors keep feeding it energy. Energy accounting is checked in `tests/test_drive.py`. Drive-encoder odometry sees only wheel rotation, so it believes the robot traced the tight kinematic circle.

## Chassis and normal loads: `vexsim/physics/chassis.py`
- Each wheel sits on a vertical spring under a rigid chassis plane: `chassis.wheel_stiffness_n_per_m`, default 2e4 N/m (an estimate covering the tire and foam).
- Every step the plane is solved so the loads carry the weight and balance the pitch and roll moments of the previous step's ground forces acting below the CG.
- This gives weight transfer, with rear wheels gaining load under acceleration (`sum(N*x) = -h*Fx`), drop-center rocking, and wheel lift-off.
- While all wheels touch the ground the loads are linear in the horizontal force, so that map is precomputed. Lift-off falls back to an active-set solve.

## Robot dynamics: `vexsim/physics/robot.py`
**Degrees of freedom**
- The CG's body-frame velocity and yaw rate: `u, v, w`.
- One shaft speed per gear group. All wheels in a group turn together.

**Contact forces**
- Every contact velocity is a fixed linear function of the velocity vector, `c = C @ qdot`.
- The generalized contact forces are `-C.T @ F(c)`, with Jacobian `-C.T @ diag(F') @ C`. That Jacobian is symmetric and dissipative.

**Integration**
- Each 1 ms step solves the linearly implicit Euler update `(M - dt*J) dq = dt*Q`. Tire friction has time constants near 0.15 ms, so a plain explicit step would blow up; this one stays stable with no substeps.
- Motor torques, rotating-frame terms and external forces are explicit.

**Motor direction:** a negative port means the motor's raw positive direction drives its group backward. Group commands apply that sign, as a PROS 4 `MotorGroup` does.

**Speed:** about 170 µs per simulated millisecond for the 6-motor example, so about 6× faster than real time on one core.

**What the tests check** (`tests/test_drive.py`):
- top speed matches the gearing within 1%
- launch acceleration is limited by traction (μg), with the wheels spinning
- turning in place matches kinematics within 1%, with the center fixed
- slow arcs follow kinematics, fast arcs drift outward, and drift grows monotonically as roller friction drops
- sideways pushes break away at the roller friction limit
- no energy is created under random commands
- runs are deterministic

## Sensors: `vexsim/devices/`
**Timing and units**
- Every device is sampled on its own period, at sensor priority, so controllers in the same tick see fresh data.
- Each reading becomes visible `latency_ms` later.
- Readings use **PROS units and sign conventions**; see [conventions.md](conventions.md#sensor-readings). Python algorithms therefore see exactly what PROS code sees.

**Presets and randomness**
- Each sensor picks a preset with `noise: ideal | default | harsh`. `ideal` means no noise, latency or quantization, for debugging algorithms.
- `sensor.<type>.<field>` overrides apply on top of the preset.
- Per-device static errors are drawn once from the stream `sensor.<type>.<port>.static`. Per-sample noise uses `sensor.<type>.<port>`. Adding or removing a sensor never changes another sensor's noise.

**Default values**
| Sensor | Default model | Source |
|---|---|---|
| Motor encoder | 10 ms; 50 counts per motor-core rev (1800/900/300 per output rev); velocity noise 0.5% of rated | counts: PROS; rest estimates |
| Rotation sensor | 10 ms; 0.088° resolution; 0.02° noise; per-wheel diameter error 0.5% and mounting error 0.05 in; scrub 1% of sideways travel | 10 ms: [PROS][rot]; 0.088°: retailer spec sheet ([RS][rot-rs]); rest estimates |
| IMU | 10 ms; 2 s calibration; gyro bias 0.3°/s, removed by calibration; 0.05°/s rate noise; per-device scale error 0.5%, **not** removed by calibration | calibration and scale behavior: [VEX API][imu]; drift level: [VEX Forum][imu-drift]; rest estimates |
| Distance | ~30 Hz; 20–2000 mm; σ 7.5 mm below 200 mm, 2.5% above | range and accuracy (±15 mm / ±5%, taken as ~2σ): [VEX][dist]; rate: VEX Forum |

**Rotation sensor (tracking wheel).** The wheel's rotation is integrated every physics step from the true contact velocity at its *true* mounting point with its *true* diameter. The localizer only knows the configured geometry, so per-device errors show up as odometry error, as on a real robot. The harsh preset adds random lift-off moments, when the wheel stops counting.

**IMU.**
- Calibration averages the raw gyro over 2 s and subtracts that from then on.
- A still robot is left with a few tenths of a degree per minute of drift. That's checked over 20 seeds, matching the VEX Forum's "normal".
- A robot that *moves* during calibration gets a large phantom turn rate, as in VEX's warning.
- Heading is clockwise-positive, as in VEX.

## Localization baselines: `vexsim/algorithms/localization/`
**Interface:** `Localizer.reset(pose, frame)` and `Localizer.update(frame) -> Pose`. Poses are in inches and degrees, counter-clockwise, in the field frame.

**`ArcOdometry`** is the standard arc method used by LemLib-style odometry. Between updates the robot moves along a circular arc:
- a vertical tracker at lateral offset `y` that rolled `dV` means the center moved `dV + y*dθ` forward;
- a horizontal tracker at longitudinal offset `x` that rolled `dH` means it moved `dH - x*dθ` sideways;
- each becomes an arc chord rotated by the mid-step heading.

Heading comes from the IMU, or from two parallel vertical wheels. It's exact for constant-curvature motion (tested to 0.01 in).

**Baselines built from a config** (`baseline_localizers`):
| Name | Needs |
|---|---|
| drive encoders | differential drive |
| drive encoders + IMU | + IMU |
| tracking wheels + IMU | ≥1 vertical tracking wheel + IMU |
| tracking wheels (no IMU) | ≥2 vertical tracking wheels |

![Odometry baselines on the aggressive drive](img/odometry_aggressive.png)

`vexsim odometry examples/robots/full_omni_6m.yaml --out odom.png` regenerates this chart. It calibrates, drives a scripted path (`--script gentle|aggressive`) and compares every baseline the robot supports. Use `--noise ideal|default|harsh` to apply one preset to every sensor.

**Typical results on the example robot:**
- On the aggressive drive, drive encoders end 70–80 in off, because they can't see the sideways slide. Adding an IMU doesn't help, since the slide is the problem, not the heading.
- Tracking wheels + IMU end 1–3 in off with default noise and 0.01 in with ideal sensors.
- While the robot moves, the estimate trails it by the sensor latency (about an inch at 60 in/s).

## Calibrating against a real robot (Phase 10, or sooner)
Each of these quick experiments replaces one of the biggest estimates.

1. **Voltage-mode free speed.** Run `move_voltage(12000)` on a motor with nothing attached and log `get_actual_velocity()` for 3 s.
   - About 113% of rated speed confirms the model.
   - About 100% means voltage mode is also capped, so set the cap in the model.
2. **Thermal timing.** Stall a motor against a hard stop with `move_velocity(max)` and log `get_temperature()` and `is_over_temp()` every second until it derates. Fit the thermal capacities and the derating onset.
3. **Battery sag.** Log `pros::battery::get_voltage()` and `get_current()` while all drive motors push against a wall. Fit the internal resistance.
4. **Velocity loop.** Step `move_velocity` from 0 to max on the robot's drivetrain and log the velocity. Fit `velocity_kp` and `velocity_ki`.
5. **Roller friction (`wheel.omni.lateral_mu`).** Hook a luggage scale to the side of the robot at about CG height and pull it sideways across the tiles at a slow, steady speed. Divide the force by the robot's weight. Cross-check with `vexsim drift` against a video of the same arc on the real robot.
6. **Coast-down (`wheel.omni.rolling_resistance`).** Drive at full speed, release in coast mode, and measure how far the robot glides. Adjust until the sim's coast distance matches.
7. **Launch traction (`wheel.omni.longitudinal_mu`).** Log `get_actual_velocity()` during a full-power launch. If the wheels spin, the acceleration is about `longitudinal_mu * g`.
8. **IMU scale error (`sensor.imu.scale_error`).** Spin the robot 10 full turns in place and compare `get_rotation()` with 3600°. Most teams then correct it in code; to simulate your sensor as-is, set the override to the measured fraction.
9. **Tracking wheel diameter.** Push the robot exactly 10 ft in a straight line and compare the distance the tracking wheel reports. That gives the effective diameter to put in the robot config.

[fit]: https://www.vexforum.com/t/v5-smart-motor-estimating-performance-parameters/135200
[kb]: https://kb.vex.com/hc/en-us/articles/360044325872-Understanding-V5-Smart-Motor-Performance
[derate]: https://www.vexforum.com/t/v5-overheating-threshold/64984
[share]: https://www.vexforum.com/t/10-motor-current-limiting-question/113733
[rot]: https://pros.cs.purdue.edu/v5/pros-4/group__c-rotation.html
[rot-rs]: https://uk.rs-online.com/web/p/stem-electronic-components/2097751
[imu]: https://api.vex.com/v5/home/blocks/inertial_gyro.html
[imu-drift]: https://www.vexforum.com/t/what-is-the-normal-drift-of-an-inertial-sensor/139591
[dist]: https://www.vexrobotics.com/276-4852.html
