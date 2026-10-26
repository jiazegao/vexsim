# Writing robot programs

This page covers Python programs. To run your PROS 4 C++ project unchanged, see [cpp.md](cpp.md).

A program is a Python file with any of three **generator functions**. Each one receives the `bot` object, as PROS hands you the robot:

```python
from vexsim.api import delay


def initialize(bot):  # optional; the default waits for the IMU to calibrate
    yield


def autonomous(bot):
    chassis = bot.chassis
    yield from chassis.move_to_point(24, 0)  # LemLib-style motions
    yield from chassis.turn_to_heading(90)
    bot.print("done at", chassis.pose)


def opcontrol(bot):  # optional; the default is arcade drive (plus strafing, if it can)
    while True:
        bot.chassis.arcade(
            bot.controller.get_analog("LEFT_Y"), bot.controller.get_analog("RIGHT_X")
        )
        yield delay(10)  # like pros::delay(10)
```

**Timing**
- `yield delay(ms)` waits like `pros::delay(ms)`. A bare `yield` waits 10 ms.
- Code between yields runs instantly in simulated time, which keeps runs deterministic.
- A plain (non-generator) function runs once and returns.

**Competition modes** (`vexsim run --mode ...`)
| Mode | Sequence |
|---|---|
| `autonomous` | `initialize` → `autonomous` |
| `driver` | `initialize` → `opcontrol` |
| `match` | `initialize` → 15 s `autonomous` → 105 s `opcontrol` |
| `skills` | `initialize` → 60 s `autonomous` |

When a period's time runs out, every motor stops, as under field control.

**Run it**
```
vexsim run examples/robots/full_omni_6m.yaml --program examples/programs/tour.py
vexsim run examples/robots/full_omni_6m.yaml                 # no program: drive it yourself
vexsim run ROBOT.yaml --program auton.py --headless --record run.csv --screenshot end.png
```

## Devices (PROS 4 style)
Constructors live on `bot`, and a negative port reverses the device, as in PROS 4:

```python
left = bot.MotorGroup([1, 2, 3])
right = bot.MotorGroup([-4, -5, -6])
left.move_voltage(6000)  # mV
right.move_velocity(300)  # rpm
lift = bot.Motor(7)
lift.move_absolute(720, 100)
lift.set_brake_mode("hold")
imu = bot.Imu(10)
imu.get_rotation()  # degrees, CLOCKWISE positive (VEX convention)
tracker = bot.Rotation(11)
tracker.get_position()  # centidegrees
bot.Distance(13).get()  # mm, 9999 if nothing in range
bot.controller.get_analog("LEFT_Y")
bot.controller.get_digital_new_press("R1")
bot.millis()
bot.print("text")  # console panel + terminal
```

**Behavior to expect**
- Readings come from the simulated sensors, so they lag, quantize and carry noise.
- Before a device's first sample, a reading returns `PROS_ERR_F` (infinity), as PROS does.
- `Imu.reset()` starts a ~2 s calibration; poll `is_calibrating()` until it finishes.
- `set_zero_position(p)` makes the motor's current position read `p` and `tare_position()` reads 0, as in PROS 4. The zero belongs to the motor on that port, so every object using the port sees it.
- Every class and method is in `vexsim/api/devices.py`.

## Driving any drivetrain (`bot.drive`)
`bot.drive.move(forward, strafe, turn)` drives any drivetrain from stick-style inputs, -127..127, as from `LEFT_Y`, `LEFT_X` and `RIGHT_X`:
- positive `strafe` is to the right, and positive `turn` is clockwise, like `chassis.arcade`;
- each input at 127 is the top speed in that direction alone; when a combination asks a gear group for more than its rated speed, every group slows together, so the robot keeps the commanded direction;
- it uses voltage control, and a drivetrain that can't strafe ignores `strafe`.

```python
def opcontrol(bot):  # robot-centric strafing, the default when the robot can strafe
    c = bot.controller
    while True:
        bot.drive.move(c.get_analog("LEFT_Y"), c.get_analog("LEFT_X"), c.get_analog("RIGHT_X"))
        yield delay(10)
```

That is also the default `opcontrol` on X-drive, mecanum and H-drive robots. `bot.drive.holonomic` tells whether the robot can strafe. The group speeds come from the drivetrain's kinematics (`vexsim/physics/kinematics.py`), built from the wheel positions, headings, roller angles and gearing in the config.

## Chassis motions (`bot.chassis`)
The chassis is built from the robot's `left` and `right` gear groups, so it exists on differential drives and H-drives (where the strafe groups stay idle). It localizes with the best baseline the robot's sensors allow (tracking wheels + IMU on the example robot). X-drive and mecanum robots have no `bot.chassis`; drive them with `bot.drive`, your own controller, or your C++ code.

- **Poses and pose control:** poses are inches and degrees **counter-clockwise** in the field frame. `chassis.set_pose(x, y, heading)` re-zeros odometry.
- **Running motions:** each motion is used as `yield from chassis.<motion>(...)`. It returns when the motion settles or after `timeout_ms`, then stops the drive.
- **Driver-style control:** `chassis.tank(l, r)` and `chassis.arcade(throttle, turn)` take -127..127, with positive turn = clockwise, like LemLib. `chassis.apply(DriveCommand(...))` gives raw control.

| Motion | What it does | Key options |
|---|---|---|
| `turn_to_heading(h)` | PID turn in place, with a small static-friction term | `max_volts`, `static_volts`, `pid`, `exit` |
| `turn_to_point(x, y)` | turn to face a point | as above |
| `move_to_point(x, y)` | LemLib `moveToPoint`: turning has priority over forward output; it stops turning near the target and may back up to settle | `forwards`, `max_volts`, `slew_volts_per_s`, `lateral`, `angular` |
| `move_to_pose(x, y, h)` | boomerang (LemLib `moveToPose`): chase a carrot point `lead` x distance behind the target, then square up | `lead` (0.6), `max_volts` (9 V), `settle_radius_in` |
| `drive(d)` | straight line on a trapezoid or S-curve (jerk-limited) motion profile, with heading hold (velocity mode) | `profile`, `max_speed_fraction`, `max_accel_in_s2`, `max_jerk_in_s3` |
| `follow(waypoints, method="pure_pursuit")` | pure pursuit along a Catmull-Rom spline through the waypoints | `lookahead_in`, `max_speed_fraction` |
| `follow(waypoints, method="ramsete")` | RAMSETE tracking of a speed-, acceleration- and curvature-limited trajectory | `b`, `zeta`, `max_lateral_accel_in_s2` |

Every motion is also a plain controller (`vexsim/algorithms/control/`) with `step(pose, frame, dt) -> DriveCommand` and `done()`. You can write your own and run it with `yield from chassis.run(my_controller, timeout_ms)`.

### Why the defaults are what they are (full-omni lessons)
These were measured on the example 6-motor full-omni robot, with the tests in `tests/test_control.py`.

- **Turning gets priority over forward speed.** A controller that drives at full speed while still turning makes a full-omni robot slide out of the curve, because it has little sideways grip. Turning first fixed `move_to_point` on targets 90° away; before, the robot spiraled away.
- **Boomerang runs at 9 V by default.** At 12 V it reached the right heading but finished 5–9 in to the side. With a 9 V limit, a 0.6 lead and a 4 in settle radius, all test poses finish within 1.4 in and 2°.
- **RAMSETE is capped by sideways grip.** RAMSETE assumes wheels never slide sideways. When it falls behind, it speeds up to catch up, and through a turn that exceeds the rollers' grip: the robot slides, falls further behind, and spirals off. Planning trajectories at 40 in/s² of sideways acceleration (about half the roller limit), capping RAMSETE's speed × yaw rate, and splining the waypoints brings final errors from 8–44 in down to 1–4 in. Expect a few inches of cross-track error at sharp waypoints at 70% speed. Slow down, or add waypoints, for tighter tracking.
- **Turns get a static-friction term.** Turning in place must first overcome roller and rolling friction. That takes about 1.7 V, so a P-only turn stalls about 7° short. With `static_volts` = 1.5, a 90° turn settles in about 0.5 s.

## The viewer
`vexsim run` opens a window showing:
- the field with 24 in tiles;
- the robot (true pose), and a blue outline for where its odometry *thinks* it is;
- path trails;
- the active motion's target or path (orange);
- wheels shaded from dark (gripping) to red (sliding), and sideways roller forces (orange ticks); mecanum wheels show their ground rollers' axis as a light stroke;
- wall contacts (orange dots);
- a side panel with poses, odometry error, speed, battery, per-motor current and temperature, controller sticks, the brain screen (C++ programs' `pros::lcd` lines) and the program console.

| Key | Action |
|---|---|
| Space | pause / resume |
| . | step one millisecond (while paused) |
| + / - | speed 0.1x ... 8x, max |
| R | restart |
| G / T / F | toggle ghost / trails / forces |
| H | help |
| Esc | quit |
| W / S | left stick Y (arcade throttle) |
| A / D | right stick X (arcade turn) |
| Up / Down | right stick Y (tank) |
| Left / Right | left stick X (strafe) |
| Shift | half stick |
| Q / Z, E / C | L1 / L2, R1 / R2 |
| I / L / K / J | X / A / B / Y |
| Ctrl + T/G/F/H | d-pad |

**Gamepad:** a connected gamepad works too, through SDL's game-controller mapping. Sticks match. The Xbox face buttons are mapped to the V5 buttons by position (Xbox Y→X, B→A, A→B, X→Y), with bumpers as L1/R1 and triggers as L2/R2. Gamepad support has not been tested on real hardware yet.

**Scripted input:** `--input inputs.csv` replays controller input from a file with columns `time_s, LEFT_X, LEFT_Y, RIGHT_X, RIGHT_Y, buttons` (buttons space-separated). Each row holds until the next, for reproducible driver tests.

## Telemetry
- `--record run.csv` logs every 10 ms: true and estimated pose, speed, yaw rate, battery voltage and charge, and each motor's current, temperature and voltage.
- `vexsim plot run.csv --out run.png` plots the path, speed, currents, temperatures and battery. Motors geared together are drawn as one line.
- `vexsim replay ROBOT.yaml run.csv` plays a log back in the viewer.

![A recorded tour: telemetry](img/telemetry_tour.png)
