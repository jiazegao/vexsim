# vexsim

A VEX V5 robot simulator for testing localization and motion-control code before it runs on the robot. It models:
- **drive physics**: wheel slip and drift on omni, traction and mecanum wheels; tank drives, X-drives, mecanum drives and H-drives; weight transfer; collisions with the field walls;
- **the V5 motor**: its torque-speed curve, firmware velocity, position and hold loops, current limiting, heating and thermal derating, and battery sag;
- **mechanisms**: lifts, intakes and arms, with loads, friction and hard stops;
- **sensors**: motor encoders, IMU, rotation sensors (tracking wheels), distance sensors and the GPS, with realistic latency, noise and per-device errors;
- **game elements**: fixed obstacles (some low enough to drive over) and pieces the robot pushes around.

You can write robot programs in Python against a PROS 4-style API, or **run your PROS 4 C++ project, LemLib included, without changing it**. You can benchmark algorithms over hundreds of randomized trials, and calibrate the physics to your own robot from a log of a short drive.

This README is the complete guide: how to use every feature, and what every module does. The [`docs/`](docs/) folder goes deeper on a few topics (where each physics parameter comes from, worked examples, a real team's port), and each section links to it.

![The viewer after the example tour](docs/img/viewer_tour.png)

## Contents
1. [Install](#1-install)
2. [Quick start](#2-quick-start)
3. [Concepts: units, frames, time, randomness](#3-concepts-units-frames-time-randomness)
4. [Describing a robot](#4-describing-a-robot)
5. [Describing a field](#5-describing-a-field)
6. [Running a simulation: `vexsim run`](#6-running-a-simulation-vexsim-run)
7. [Writing robot programs in Python](#7-writing-robot-programs-in-python)
8. [Running PROS 4 and LemLib C++ code](#8-running-pros-4-and-lemlib-c-code)
9. [Analysis commands: motor curves, drift, odometry](#9-analysis-commands-motor-curves-drift-odometry)
10. [Benchmarking algorithms: `vexsim bench`](#10-benchmarking-algorithms-vexsim-bench)
11. [Calibrating to your robot](#11-calibrating-to-your-robot)
12. [Porting a team's code](#12-porting-a-teams-code)
13. [Using vexsim as a Python library](#13-using-vexsim-as-a-python-library)
14. [Module reference: what each part does](#14-module-reference-what-each-part-does)
15. [The physics models](#15-the-physics-models)
16. [Limits: what isn't modeled](#16-limits-what-isnt-modeled)
17. [Developing vexsim](#17-developing-vexsim)

---

## 1. Install
vexsim needs **Python 3.11 or newer**.

**Windows (PowerShell)**
```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,viz]"
```

**Linux / macOS**
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,viz]"
```

| Extra | Adds | Needed for |
|---|---|---|
| (none) | numpy, pydantic, PyYAML | everything headless: configs, simulation, benchmarks, calibration fits |
| `viz` | matplotlib, pygame | the live viewer, screenshots, every plot and chart |
| `dev` | pytest, ruff | running the tests and the linter |

The `vexsim` command is installed with the package (`python -m vexsim` works too).

### C++ toolchain (only for running PROS C++ code)
vexsim compiles PROS projects for your PC with g++ 11 or newer.
- **Windows:** install MSYS2 from https://www.msys2.org (default folder `C:\msys64`). In the "MSYS2 UCRT64" terminal, run `pacman -S --needed mingw-w64-ucrt-x86_64-gcc`. vexsim finds it in `msys64` or `msys2` at the top of any drive. Otherwise add `...\ucrt64\bin` to your PATH, or set `VEXSIM_CXX` to the full path of `g++.exe`.
- **Linux:** `sudo apt install g++` (or your distribution's equivalent).
- **macOS:** `brew install gcc`, then set `VEXSIM_CXX=g++-14` (or the version you installed).

Then check it:
```
vexsim doctor
```
```
[ ok ] compiler   /usr/bin/g++
                  g++ 13.3.0, target x86_64-linux-gnu, thread model posix
[ ok ] build      test program compiled and linked in 2.0 s
[ ok ] run        tasks, delays and mutexes run in lockstep with simulated time
```

| Environment variable | Effect |
|---|---|
| `VEXSIM_CXX` | the g++ to use |
| `VEXSIM_CACHE_DIR` | where builds go (default `%LOCALAPPDATA%\vexsim\build` on Windows, `~/.cache/vexsim/build` elsewhere) |
| `VEXSIM_LEMLIB_SOURCE` | a LemLib source checkout to build from, instead of downloading the release (for working offline) |

---

## 2. Quick start
Every command below runs from the repository root, with the example files.

**Check a robot config and see what the simulator builds from it:**
```
vexsim validate-config examples/robots/full_omni_6m.yaml --field examples/fields/v5rc_empty.yaml
```
```
Robot  examples/robots/full_omni_6m.yaml
  name        Example 6-motor full omni
  body        6.50 kg (14.3 lb), footprint 15.0 x 15.0 in, CG (0.0, 0.0, 3.5) in
              yaw inertia 0.157 kg*m^2 (auto: uniform box)
  drivetrain  differential, 6 wheels (6 omni)
    left      motors 1, 2, 3 | blue 600 rpm | ratio 36:48 -> 450 rpm | 3.25 in -> 76.6 in/s free speed
    right     motors -4, -5, -6 | blue 600 rpm | ratio 36:48 -> 450 rpm | 3.25 in -> 76.6 in/s free speed
    top speed forward 76.6 in/s, turning 731 deg/s (kinematic, rated motor speed)
  sensors     port 10  imu       at (0.0, 0.0) in, mount yaw 0 deg, noise default
              ...
Result: OK (0 error(s), 0 warning(s))
```

**Drive the robot yourself** in the viewer (W/S throttle, A/D turn; press H for every key):
```
vexsim run examples/robots/full_omni_6m.yaml
```

**Run the example Python program**, a tour of every chassis motion:
```
vexsim run examples/robots/full_omni_6m.yaml --program examples/programs/tour.py
```

**Run a PROS 4 C++ project** (needs the toolchain above):
```
vexsim run examples/robots/full_omni_6m.yaml --program examples/pros_projects/minimal_pros4 --start 0,0,90
vexsim run examples/robots/lemlib_example.yaml --program examples/pros_projects/lemlib_template --start 0,0,90
```

**Run without a window**, log telemetry, save the last frame, and plot the log:
```
vexsim run examples/robots/full_omni_6m.yaml --program examples/programs/tour.py --headless --record tour.csv --screenshot tour.png
vexsim plot tour.csv --out telemetry.png
```

**Try the other drivetrains, and a field with game elements:**
```
vexsim run examples/robots/mecanum_4m.yaml --input examples/inputs/strafe_square.csv --start=-12,12,0
vexsim run examples/robots/full_omni_6m.yaml --field examples/fields/practice_elements.yaml
```

**Benchmark two path followers over 20 randomized trials each:**
```
vexsim bench examples/scenarios/s_curve.yaml --seeds 20
```

### The example files
| Folder | Contents |
|---|---|
| `examples/robots/` | `full_omni_6m` (6-motor full-omni tank with tracking wheels, IMU and a distance sensor: the main example), `traction_6m` (traction wheels in the middle), `xdrive_4m`, `mecanum_4m`, `hdrive_5m`, `lemlib_example` (the robot LemLib's example program configures), `1239e_2026-27` (a real team's robot, with mechanisms) |
| `examples/fields/` | `v5rc_empty` (walls only), `practice_elements` (a barrier, two goals, six balls), `1239e_2026-27` (the 2026-27 field as team 1239E models it) |
| `examples/programs/` | `tour.py`: a Python program that runs every chassis motion |
| `examples/inputs/` | `strafe_square.csv`: scripted controller input |
| `examples/pros_projects/` | `minimal_pros4` (its own tracking-wheel odometry, driving a square), `lemlib_template` (LemLib's own example program), `lemlib_bench` (LemLib motions as benchmark controllers), `calibration` (the calibration routine for `full_omni_6m`), `1239e_2026-27` (a real team's code) |
| `examples/scenarios/` | benchmark scenarios: `s_curve`, `pose_approach`, `lemlib_vs_python` |
| `examples/scripts/` | `evaluate_1239e.py`: runs every 1239E routine and measures its localization |

---

## 3. Concepts: units, frames, time, randomness
### Units
| Where | Units |
|---|---|
| Physics, sensors, internal math | SI: m, kg, s, rad, N, N·m, V, A |
| Config files, CLI output, logs, robot-code API | VEX: inches, degrees, rpm, mV; kg for mass |

Conversions happen only at those boundaries (`vexsim/units.py`).

### Frames and angles
- **Robot frame:** origin at the center of the footprint, **+x forward, +y left**, +z up. Angles are counter-clockwise from +x, seen from above. Everything you place on the robot (`pos_in`, `cg_in`) uses this frame.
- **Field frame:** origin at the field center, axes parallel to the walls, angles counter-clockwise from +x. The walls' inside faces are at `x = ±size_in[0]/2` and `y = ±size_in[1]/2` (144 × 144 in by default).
- **Poses** in vexsim (`--start`, Python programs, scenarios, telemetry) are `x, y` in inches and a heading in degrees **counter-clockwise from +x**.
- **PROS and LemLib** use heading **clockwise from +y**. Robot code never sees vexsim's frame: the IMU reads clockwise-positive as on the V5, and a pose reported by C++ code (LemLib's, or `vexsim::report_pose`) is converted. To start the simulated robot where LemLib's `chassis.setPose(x, y, theta)` says it is, use `--start x,y,(90 - theta)`. LemLib's (0, 0, 0) faces +y, so it is `--start 0,0,90`.

### Time and determinism
- Simulated time is an integer number of **microseconds**, so long runs never drift. The physics steps every **1 ms**.
- Each tick at time `t`: every due event fires in priority order (sensors at -100, controllers at 0, recorders at 100; ties in registration order), so a controller sees that tick's readings; then every physics system steps from `t` to `t + 1 ms`.
- Robot code takes no simulated time: Python programs run between `yield`s, and C++ tasks run until they block (`pros::delay`, mutexes, notifications). So a run is **identical every time** for the same seed, at any speed, console output included.

### Randomness
- Every random number comes from a named stream derived from the run's seed (`--seed`, default 0): `sensor.imu.10`, `sensor.rotation.11.static`, and so on. Adding or removing a sensor never changes the noise another sensor sees, which keeps comparisons between robot configs fair.
- The same seed with the same versions of numpy and vexsim gives bit-identical runs. Results can differ across platforms or library versions.

### Truth and belief
The simulator always knows where the robot really is (the **true pose**, drawn solid in the viewer). Robot code and localizers only see sensor readings and produce an **estimated pose** (the blue outline). Every comparison vexsim makes (in the viewer, telemetry, benchmarks and `vexsim run`'s headless summary) is the estimate against the truth.

---

## 4. Describing a robot
A robot is a YAML file. Copy `examples/robots/full_omni_6m.yaml`; its comments explain every field. Here is every section:

```yaml
version: 1
name: Example 6-motor full omni

body:
  mass_kg: 6.5
  inertia_kgm2: auto            # auto = uniform box over the footprint, m(L^2 + W^2)/12; or a number in kg*m^2
  footprint_in: [15, 15]        # length (x) by width (y)
  cg_in: [0, 0, 3.5]            # x, y, height above the floor
  battery: v5_default

drivetrain:
  type: differential            # differential | xdrive | mecanum | hdrive
  wheels:                       # every wheel, listed explicitly
    - {name: lf, pos_in: [ 5.5,  6.0], heading_deg: 0, type: omni, diameter_in: 3.25}
    - {name: lm, pos_in: [ 0.0,  6.0], heading_deg: 0, type: omni, diameter_in: 3.25}
    - {name: lb, pos_in: [-5.5,  6.0], heading_deg: 0, type: omni, diameter_in: 3.25}
    - {name: rf, pos_in: [ 5.5, -6.0], heading_deg: 0, type: omni, diameter_in: 3.25}
    - {name: rm, pos_in: [ 0.0, -6.0], heading_deg: 0, type: omni, diameter_in: 3.25}
    - {name: rb, pos_in: [-5.5, -6.0], heading_deg: 0, type: omni, diameter_in: 3.25}
  gearing:                      # gear groups: motors geared to wheels
    left:  {motors: [1, 2, 3],    cartridge: blue, ratio: "36:48", wheels: [lf, lm, lb]}
    right: {motors: [-4, -5, -6], cartridge: blue, ratio: "36:48", wheels: [rf, rm, rb]}

mechanisms:                     # optional: lifts, intakes, arms
  lift: {motors: [7, -8], cartridge: red, ratio: "12:60", load_torque_nm: 2.0, range_deg: [0, 120]}
  intake: {motors: [9], cartridge: blue}

sensors:
  - {type: imu, port: 10, pos_in: [0, 0], mount_yaw_deg: 0, noise: default}
  - type: rotation              # vertical (forward-tracking) wheel
    port: 11
    reversed: false
    tracking_wheel: {pos_in: [0, -1.5], heading_deg: 0, diameter_in: 2.0}
  - type: rotation              # horizontal (sideways-tracking) wheel
    port: 12
    tracking_wheel: {pos_in: [-3, 0], heading_deg: 90, diameter_in: 2.0}
  - {type: distance, port: 13, pos_in: [7, 0], heading_deg: 0}
  - {type: gps, port: 15, pos_in: [0, -4], mount_yaw_deg: 180}

overrides:                      # optional: any model parameter
  wheel.omni.lateral_mu: 0.25
```
(The `mechanisms:`, the GPS and the override are added for illustration; the example file has none of them.)

### Body
| Key | Meaning |
|---|---|
| `mass_kg` | the whole robot, mechanisms included |
| `inertia_kgm2` | yaw inertia; `auto` treats the robot as a uniform box over its footprint |
| `footprint_in` | length × width, centered on the robot origin. It collides with walls and obstacles, and every wheel and sensor must be inside it. |
| `cg_in` | center of gravity (x, y, height); the height sets the weight transfer |
| `battery` | `v5_default` (the only preset) |

### Drivetrain
**Wheels.** Each wheel has a `name`, a position `pos_in`, a `type` (`omni`, `traction` or `mecanum`) and a `diameter_in`.
- `heading_deg` is the direction the wheel rolls when its gear group turns forward. Differential wheels use 0. H-drive strafe wheels use 90, so positive strafe pushes the robot left. X-drive wheels use ±45 (front-left -45, front-right 45, back-left 45, back-right -45 in the examples, so driving ahead turns every group forward).
- `drop_in` (0–0.5) lowers a wheel, as in a drop-center drivetrain; a lowered wheel carries more weight.
- `roller_angle_deg` (mecanum only, required) is the axis of the rollers touching the ground, counter-clockwise from the rolling direction: usually -45 at front-left and back-right, and 45 at front-right and back-left. Check it in the viewer: the left stick's sideways axis should strafe the robot that way.

**Gearing groups** tie motors to wheels; all wheels in a group turn together.
- `motors`: smart ports. A **negative port means reversed**, as in PROS 4, and a group's positive direction always rolls its wheels forward.
- `cartridge`: `red` (100 rpm), `green` (200) or `blue` (600).
- `ratio`: wheel speed / motor speed. `"36:48"` means 36 teeth on the motor side driving 48 on the wheel side (0.75×). A bare number works too. Write it quoted or not: vexsim reads `36:48` as text, where plain YAML would read the number 2208.

| `type` | Gearing groups | Checks |
|---|---|---|
| `differential` | exactly `left` and `right` | wheels parallel to x, each side on its own side |
| `hdrive` | `left`, `right`, plus one or more strafe groups (any names) | as differential; strafe wheels perpendicular |
| `xdrive` | any, usually one per wheel | must be able to strafe; warns about non-omni wheels |
| `mecanum` | any, usually one per wheel | must be able to strafe; warns about non-mecanum wheels |

Any wheel type works in any drivetrain: a tank drive with traction wheels in the middle is `differential`.

### Mechanisms
Motors that drive something other than the wheels. Each mechanism is one output (a lift's spool, a roller, an arm's pivot) with its own motors:

| Key | Meaning (all at the output) |
|---|---|
| `motors`, `cartridge` | as for gearing groups; positive is the motors' positive direction |
| `ratio` | output speed / motor speed: `"12:48"` is a 4:1 reduction (default 1) |
| `inertia_kgm2` | the load's inertia (the motors' own is added) |
| `load_torque_nm` | a constant torque pulling toward negative angles: a lift's weight times its spool radius |
| `friction_nm` | Coulomb friction; a lighter load stays put |
| `range_deg` | hard stops `[low, high]`, in output degrees from the start, so `low <= 0 <= high`. A lift that starts at the bottom has `low: 0`. |

Mechanism motors are full V5 motors on their ports: robot code drives them like any motor, they draw from the battery, and telemetry records each output's angle (`lift_deg`). A mechanism doesn't push the chassis or pick anything up.

### Sensors
Every sensor has a `type`, a `port` and a `noise` preset (`ideal`, `default` or `harsh`; see [Sensors](#sensors-1)).

| `type` | Keys |
|---|---|
| `imu` | `pos_in`, `mount_yaw_deg`; optional `scale_error`: this IMU's measured error, (reading − true) / true over a full turn, e.g. `0.002528` for one that reads 360.91° per real turn. Without it each simulated IMU draws a random one. |
| `rotation` | `reversed`; optional `tracking_wheel: {pos_in, heading_deg, diameter_in}`. A tracking wheel's `heading_deg` is the direction of travel it measures: 0 for vertical (forward), 90 for horizontal (sideways). |
| `distance` | `pos_in`, `heading_deg` (where the beam points); optional `height_in`: the beam's height above the floor, so field elements no taller than that pass under it |
| `gps` | `pos_in` (where the sensor sits), `mount_yaw_deg` (where its camera faces; 180 = backward) |

Odometry offsets are measured from the footprint center: a vertical wheel by its `y` (+left), a horizontal wheel by its `x` (+forward).

### Overrides
`overrides:` changes any model parameter by its dotted name. Calibration writes its results here.

| Group | Parameters (defaults) |
|---|---|
| `motor` | `reference_voltage_v` 12.8, `natural_free_rpm` 121, `natural_stall_torque_nm` 3.99, `natural_stall_current_a` 4.69, `free_current_a` 0.15, `coulomb_fraction` 0.3, `current_limit_a` 2.5, `max_command_v` 12, `rotor_inertia_kgm2` 2e-6, `friction_smoothing_rad_s` 2, `velocity_kp` 2, `velocity_ki` 20, `velocity_filter_s` 0.002, `integral_gate` 0.25, `position_kp` 15 (output values are the red cartridge's) |
| `thermal` | `ambient_c` 25, `winding_heat_capacity_j_per_k` 12, `housing_heat_capacity_j_per_k` 50, `winding_to_housing_k_per_w` 1.5, `housing_to_ambient_k_per_w` 4, `derate_start_c` 55, `derate_step_c` 5 |
| `battery` | `capacity_mah` 1100, `internal_resistance_ohm` 0.1 |
| `chassis` | `wheel_stiffness_n_per_m` 20000, `gravity_m_s2` 9.81 |
| `wheel.omni` | `longitudinal_mu` 0.9, `slip_velocity_m_s` 0.03, `lateral_mu` 0.2 (**controls drift**), `lateral_velocity_m_s` 0.02, `rolling_resistance` 0.1, `rolling_velocity_m_s` 0.02, `mass_kg` 0.06 |
| `wheel.traction` | `mu` 1.1, `slip_velocity_m_s` 0.03, `rolling_resistance` 0.12, `rolling_velocity_m_s` 0.02, `mass_kg` 0.07 |
| `wheel.mecanum` | `grip_mu` 0.8, `slip_velocity_m_s` 0.03, `roller_mu` 0.15, `roller_velocity_m_s` 0.02, `rolling_resistance` 0.12, `rolling_velocity_m_s` 0.02, `mass_kg` 0.15 |
| `field` | `wall_restitution` 0.2, `wall_friction` 0.3 |
| `sensor.motor` | `period_ms` 10, `latency_ms` 5, `counts_per_core_rev` 50, `velocity_noise` 0.005 |
| `sensor.rotation` | `period_ms` 10, `latency_ms` 5, `resolution_deg` 0.088, `noise_deg` 0.02, `diameter_error` 0.005, `offset_error_in` 0.05, `scrub` 0.01, `liftoff_rate_hz` 0, `liftoff_duration_s` 0.05 |
| `sensor.imu` | `period_ms` 10, `latency_ms` 5, `calibration_s` 2, `raw_bias_deg_s` 0.3, `rate_noise_deg_s` 0.05, `bias_walk_deg_s` 0.0005, `scale_error` 0.005, `heading_noise_deg` 0.01 |
| `sensor.distance` | `period_ms` 33, `latency_ms` 10, `min_range_mm` 20, `max_range_mm` 2000, `short_noise_mm` 7.5, `long_noise_fraction` 0.025 |
| `sensor.gps` | `period_ms` 20, `latency_ms` 20, `position_noise_m` 0.005, `range_noise` 0.004, `heading_noise_deg` 0.3, `min_range_m` 0.3, `max_range_m` 4, `gyro_noise_deg_s` 0.1, `error_growth_m_s` 0.05 |

The `sensor.*` values shown are the `default` preset's; an override applies on top of each sensor's own preset. [docs/models.md](docs/models.md) gives the source of every value, and simple experiments to measure them.

### Validation
`vexsim validate-config ROBOT.yaml [--field FIELD.yaml] [--strict] [-q]` prints what the simulator will build, and every problem. Exit code 0 means valid and 1 means errors; `--strict` fails on warnings too, and `-q` prints only problems.
- **Structure:** a misspelled key is an error that suggests the closest valid key, and duplicate keys are errors (plain YAML silently keeps the last one).
- **Errors:** a port used twice (motors, mechanisms and sensors share ports 1–21); the CG, a wheel or a sensor outside the footprint; wheels all in a line, or the CG outside the polygon they form (the robot would tip over); a wheel in no gear group, or in two; unknown wheel names; a mecanum wheel without `roller_angle_deg`, or roller angles on other wheels; a differential drive without exactly `left` and `right`; an X-drive, mecanum or H-drive that can't strafe independently; mechanism stops that don't contain the start; unknown or inconsistent overrides.
- **Warnings:** a footprint over the 18 in starting size; more than 88 W of drive motors; wheels geared together with different diameters (they scrub); unusual wheel types for the drivetrain.

---

## 5. Describing a field
A field YAML gives the inside-wall size and the game elements:

```yaml
version: 1
name: Practice field with game elements
size_in: [144, 144]               # inside the walls; real fields measure a little less, so measure yours
elements:
  - {type: obstacle, name: barrier, shape: rect, pos_in: [0, 0], size_in: [48, 3], heading_deg: 0}
  - {type: obstacle, name: goal, shape: circle, pos_in: [-48, 48], diameter_in: 10, color: "#d33f49"}
  - {type: obstacle, name: low base, shape: rect, pos_in: [47, -23.5], size_in: [5, 5], height_in: 6, solid: false}
  - {type: piece, name: ball, pos_in: [-24, 24], diameter_in: 7, mass_kg: 0.25, friction: 0.4, restitution: 0.3}
```

| Element key | Meaning |
|---|---|
| `type` | `obstacle` (fixed) or `piece` (a movable disc: a ball, ring or cylinder by its outer diameter) |
| `pos_in` | center, in the field frame |
| `shape`, `size_in`, `diameter_in`, `heading_deg` | obstacles: a `rect` (length along `heading_deg` × width) or a `circle` |
| `height_in` | obstacles: their top above the floor. Distance sensors whose beam is higher see over it. Omitted: taller than any sensor. |
| `solid` | obstacles: `false` for an element low enough to drive over (a base the robot straddles). Robots and pieces pass over it; sensors still see it. The viewer draws it as an outline. |
| `mass_kg`, `friction`, `restitution` | pieces: mass; ground friction coefficient (default 0.4); share of speed kept in a bounce (default 0.3) |
| `color` | `"#rrggbb"`, for the viewer only |

Validation: elements must be inside the walls; a piece that starts overlapping a wall, a solid obstacle or another piece gets a warning. Without `--field`, the robot drives on an empty 144 × 144 in field.

---

## 6. Running a simulation: `vexsim run`
```
vexsim run ROBOT.yaml [--program FILE.py | --program PROS_PROJECT] [options]
```
Without `--program`, you drive the robot from the keyboard or a gamepad.

| Option | Meaning |
|---|---|
| `--program` | a Python program file, or a PROS 4 project folder (built automatically) |
| `--mode` | `autonomous`, `driver`, `match` or `skills` (default: `autonomous` for PROS projects and for Python programs with an `autonomous` function, else `driver`) |
| `--field FILE` | field YAML (default: an empty field) |
| `--start x,y,heading` | the robot's true starting pose (in, deg CCW; default `0,0,0`). Write `--start=-12,12,0`, with `=`, when x is negative. |
| `--seed N` | random seed (default 0) |
| `--noise ideal\|default\|harsh` | one noise preset for every sensor |
| `--speed X` | viewer speed, 0.1 to 8 (0 = as fast as possible) |
| `--input FILE.csv` | scripted controller input |
| `--record FILE.csv` | telemetry log |
| `--robot-log FILE.csv` | a robot log: what the robot's own sensors read, as on a real robot (for calibration) |
| `--headless` | no window: run, print a summary, save files |
| `--seconds S` / `--max-seconds S` | headless: run exactly S seconds / give up after S (default 180) |
| `--screenshot FILE.png` | headless: save the final frame |
| `--env KEY=VALUE` | an environment variable for the robot program (repeatable). `VEXSIM_SEED` is always set to the seed. |
| `--busy-timeout S` | PROS projects: stop if a task runs S seconds of real time without blocking (default 5; 0 = never) |

**Competition modes** behave as under field control:

| `--mode` | Sequence | PROS `competition::get_status()` |
|---|---|---|
| `autonomous` | `initialize` (disabled), then `autonomous`: like a competition switch | connected |
| `driver` | `initialize`, then `opcontrol`: a robot with no field connection | not connected |
| `match` | `initialize` (disabled), 15 s `autonomous`, 105 s `opcontrol`, then `disabled` | field control |
| `skills` | `initialize` (disabled), 60 s `autonomous`, then `disabled` | field control |

When a period's time runs out, every motor stops.

**The headless summary** compares the estimate with the truth:
```
autonomous finished at t = 17.37 s
  true pose      x   42.50  y   19.66  heading  207.6
  estimated pose x   42.37  y   21.51  heading  207.7
  the robot code's pose vs. the true one during autonomous: mean 1.66 in, max 7.00 in (at 7.3 s), final 1.78 in; heading mean 0.53, max 4.3 deg
```

### The viewer
It shows the field with 24 in tiles; the robot (true pose) and a blue outline where its odometry thinks it is; path trails; the active motion's target or path (orange); each wheel shaded from dark (gripping) to red (sliding), with sideways roller forces as orange ticks; wall and obstacle contacts (orange dots); obstacles and pieces. The side panel shows the poses and the odometry error, speed, battery, each motor's current and temperature, the controller sticks, the brain screen (`pros::lcd` lines from C++ code) and the console.

| Key | Action | Key | Action |
|---|---|---|---|
| Space | pause / resume | W / S | left stick Y (arcade throttle) |
| `.` | one step while paused | A / D | right stick X (arcade turn) |
| + / - | speed 0.1× … 8×, max | Up / Down | right stick Y (tank) |
| R | restart | Left / Right | left stick X (strafe) |
| G / T / F | ghost / trails / wheel forces | Shift | half stick |
| H | help | Q / Z, E / C | L1 / L2, R1 / R2 |
| Esc | quit | I / L / K / J | X / A / B / Y |
| | | Ctrl + T/G/F/H | d-pad |

A connected gamepad works too, through SDL's mapping. The sticks match. The Xbox face buttons map to the V5's by position (Y→X, B→A, A→B, X→Y), the bumpers to L1/R1 and the triggers to L2/R2.

### Scripted input
`--input inputs.csv` replays controller input. Its columns are `time_s, LEFT_X, LEFT_Y, RIGHT_X, RIGHT_Y, buttons` (sticks -127..127, buttons space-separated, like `R1 A`). Each row holds until the next. See `examples/inputs/strafe_square.csv`.

### Telemetry, plots and replays
- `--record run.csv` logs a row every 10 ms: `time_s, phase`; the true pose (`x_in, y_in, heading_deg`); the estimated pose (`est_x_in, est_y_in, est_heading_deg`); `speed_in_s, yaw_rate_deg_s, battery_v, battery_soc`; each motor's `motor<p>_current_a, motor<p>_temp_c, motor<p>_volts`; and each mechanism's `<name>_deg`.
- `vexsim plot run.csv --out run.png [--title T]` plots the path, speed, motor currents and temperatures, and the battery. Motors geared together are drawn as one line.
- `vexsim replay ROBOT.yaml run.csv [--speed X]` plays a log back in the viewer; `--headless --at 5.0 --screenshot frame.png` saves one frame.

![A recorded tour: telemetry](docs/img/telemetry_tour.png)

---

## 7. Writing robot programs in Python
A program is a Python file with up to three **generator functions**. Each receives the `bot`, as PROS hands you the robot:

```python
from vexsim.api import delay


def initialize(bot):  # optional; this is what the default does
    imu = bot.Imu(10)
    while imu.is_calibrating():  # keep still until the IMU has calibrated
        yield delay(10)


def autonomous(bot):
    chassis = bot.chassis
    yield from chassis.move_to_point(24, 0)  # LemLib-style motions
    yield from chassis.turn_to_heading(90)
    bot.print("done at", chassis.pose)


def opcontrol(bot):  # optional; the default is arcade drive (plus strafing, if the robot can)
    while True:
        bot.chassis.arcade(
            bot.controller.get_analog("LEFT_Y"), bot.controller.get_analog("RIGHT_X")
        )
        yield delay(10)  # like pros::delay(10)
```
- `yield delay(ms)` waits like `pros::delay(ms)`; a bare `yield` waits 10 ms. Code between yields takes no simulated time.
- The IMU calibrates for about 2 s when the simulation starts. The default `initialize` waits for it; if you write your own, wait too, or the robot drives with no heading.
- A plain (non-generator) function runs once and returns.
- `bot.millis()`, `bot.battery_voltage_mv()`, `bot.print(...)` (to the console panel and the terminal) and `bot.pose` (the estimated pose) are always available.

### Devices (PROS 4 style)
The constructors live on `bot`. Names and units follow PROS 4, so a Python prototype maps line for line onto C++. A negative port reverses the device.
```python
left = bot.MotorGroup([1, 2, 3])
right = bot.MotorGroup([-4, -5, -6])
left.move_voltage(6000)  # mV
right.move_velocity(300)  # rpm
lift = bot.Motor(7)
lift.move_absolute(720, 100)  # degrees, rpm
lift.set_brake_mode("hold")  # coast | brake | hold
imu = bot.Imu(10)
imu.get_rotation()  # degrees, CLOCKWISE positive (VEX convention)
bot.Rotation(11).get_position()  # centidegrees
bot.Distance(13).get()  # mm, 9999 if nothing is in range
gps = bot.Gps(15, 0.0, 0.15)  # like pros::Gps(port, x_offset, y_offset), meters
gps.get_position()  # (x, y) meters from the field center
bot.controller.get_analog("LEFT_Y")  # -127..127
bot.controller.get_digital_new_press("R1")
```
| Class | Methods |
|---|---|
| `Motor` | `move` (-127..127), `move_voltage`, `move_velocity`, `move_absolute`, `move_relative`, `brake`, `set_brake_mode`, `set_current_limit`, `tare_position`, `set_zero_position`, `get_position`, `get_actual_velocity`, `get_current_draw`, `get_voltage`, `get_temperature`, `get_torque`, `get_power`, `is_over_temp` |
| `MotorGroup` | every `Motor` command, applied to all its motors; getters read the first motor; `get_position_all` |
| `Imu` | `reset` (starts a ~2 s calibration), `is_calibrating`, `get_rotation`, `get_heading`, `get_gyro_rate_z`, `set_rotation`, `set_heading`, `tare_rotation` |
| `Rotation` | `get_position`, `get_angle`, `get_velocity`, `reset_position`, `set_reversed` |
| `Distance` | `get` |
| `Gps` | `initialize_full`, `set_offset`, `get_offset`, `set_position`, `set_data_rate`, `get_position`, `get_position_x`, `get_position_y`, `get_heading`, `get_heading_raw`, `get_yaw`, `get_pitch`, `get_roll`, `get_position_and_orientation`, `get_error`, `get_gyro_rate` |
| `Controller` | `get_analog`, `get_digital`, `get_digital_new_press` |

Readings come from the simulated sensors, so they lag, quantize and carry noise. Before a device's first sample, a reading returns `PROS_ERR_F` (infinity), as PROS does. `set_zero_position(p)` makes the motor's current position read `p`; the zero belongs to the motor on that port, so every object using the port sees it. The GPS follows PROS: meters, a heading clockwise from +y, and `set_offset(x, y)` with +y along the camera's direction.

### Driving any drivetrain: `bot.drive`
`bot.drive.move(forward, strafe, turn)` takes stick-style inputs (-127..127, as from `LEFT_Y`, `LEFT_X` and `RIGHT_X`): positive strafe is to the right and positive turn clockwise. Each input at 127 is the top speed in that direction alone; a combination that asks a gear group for more than its rated speed slows every group together, so the robot keeps the commanded direction. It uses voltage control, and a drivetrain that can't strafe ignores `strafe` (`bot.drive.holonomic` says whether it can). It works on every drivetrain, because the group speeds come from the robot's kinematics.

### Chassis motions: `bot.chassis`
The chassis drives the `left` and `right` gear groups, so it exists on differential drives and H-drives (X-drive and mecanum robots use `bot.drive`). It localizes with the best baseline the robot's sensors allow. Poses are inches and degrees counter-clockwise; `chassis.set_pose(x, y, heading)` re-zeros odometry, and `chassis.pose` reads it.

Each motion runs as `yield from chassis.<motion>(...)`. It returns when the motion settles or after `timeout_ms`, then stops the drive:

| Motion | What it does | Key options |
|---|---|---|
| `turn_to_heading(h)` | PID turn in place, with a small static-friction term | `max_volts`, `static_volts`, `pid`, `exit` |
| `turn_to_point(x, y)` | turn to face a point | as above |
| `move_to_point(x, y)` | LemLib `moveToPoint`: turning has priority over forward output; it stops turning near the target and may back up to settle | `forwards`, `max_volts`, `slew_volts_per_s`, `lateral`, `angular` |
| `move_to_pose(x, y, h)` | boomerang (LemLib `moveToPose`): chase a carrot point `lead` × distance behind the target, then square up | `lead` (0.6), `max_volts` (9 V), `settle_radius_in` |
| `drive(d)` | a straight line on a trapezoid or S-curve (jerk-limited) profile, with heading hold | `profile`, `max_speed_fraction`, `max_accel_in_s2`, `max_jerk_in_s3` |
| `follow(waypoints, method="pure_pursuit")` | pure pursuit along a Catmull-Rom spline through the waypoints | `lookahead_in`, `max_speed_fraction` |
| `follow(waypoints, method="ramsete")` | RAMSETE on a speed-, acceleration- and curvature-limited trajectory | `b`, `zeta`, `max_lateral_accel_in_s2` |

There are also `chassis.tank(l, r)` and `chassis.arcade(throttle, turn)` (-127..127, positive turn = clockwise, like LemLib), `chassis.apply(DriveCommand(...))` for raw volts or wheel speeds, and `chassis.stop()`.

**Your own controller:** any object with `step(pose, frame, dt) -> DriveCommand` and `done()` runs with `yield from chassis.run(my_controller, timeout_ms)`. `frame` holds every sensor reading (see [Sensors](#sensors-1)).

**Why the defaults are what they are** (measured on the full-omni example; `tests/test_control.py`): turning gets priority over forward speed, because a full-omni robot driving hard while turning slides out of the curve. Boomerang defaults to 9 V, because at 12 V it reaches the heading but ends 5–9 in to the side. RAMSETE trajectories are planned at 40 in/s² of sideways acceleration (about half the rollers' grip), since RAMSETE assumes wheels never slide. Turns add 1.5 V of static-friction feedforward, without which a P-only turn stalls about 7° short.

---

## 8. Running PROS 4 and LemLib C++ code
```
vexsim build path/to/project                                     # compile only (incremental)
vexsim run ROBOT.yaml --program path/to/project                  # build if needed, then the viewer
vexsim run ROBOT.yaml --program path/to/project --mode driver    # drive it: keyboard or gamepad
vexsim run ROBOT.yaml --program path/to/project --headless --record run.csv --screenshot end.png
```
`vexsim build` options: `--debug` (compile with `-O0 -g`, for a debugger), `--jobs N` (parallel compiles), `--cxx PATH`.

![The example PROS project driving a square](docs/img/cpp_square.png)

### How your project is built
- **It isn't modified.** Build output goes to the cache folder ([Install](#1-install)). Only sources whose code, included headers or flags changed are recompiled.
- **The PROS SDK in your project is skipped.** `include/api.h`, `include/pros/`, `include/liblvgl/`, `include/display/`, `firmware/` and every header a template lists as its own in `project.pros` are replaced by vexsim's PROS 4 shim. Your own headers and sources are used as they are. Includes resolve as with PROS's makefile: a source in `src/<folder>/` finds `include/<folder>/` headers by bare name.
- **The robot config must match your ports.** A call to a device the config doesn't have on that port fails with `errno = ENODEV`, as on a robot with a missing device, and the console says so:
  ```
  vexsim: port 7: the code uses a motor here, but the robot config has nothing on this port (calls fail with errno ENODEV)
  ```
- `VEXSIM` is defined (`-DVEXSIM=1`), so `#ifdef VEXSIM` marks simulator-only code.

### What's simulated
| PROS 4 API | In the simulator |
|---|---|
| `pros::Motor`, `pros::MotorGroup` | everything: `move*`, getters (and `_all`), brake modes, current and voltage limits, encoder units, gearing, zero position. Drive motors turn the wheels; `mechanisms:` motors turn lifts, intakes and arms. |
| `pros::Imu` | rotation, heading, yaw, z gyro rate, tare/set offsets, `reset`, `is_calibrating`. Pitch and roll read 0 (flat field), acceleration 0. Clockwise-positive. |
| `pros::Rotation` | position, angle, velocity, reversal, `reset`, `set_position` |
| `pros::Distance` | distance to walls and game elements; confidence 63 and object size 400 when something is in range; object velocity 0 |
| `pros::Gps` | position (m) and heading (deg clockwise from +y) with the offset and initial position the code sets; error, raw heading, yaw, z gyro rate; it keeps its last position without a view of the code strip |
| `pros::Controller` | the master's sticks and buttons (keyboard, gamepad or `--input`), `get_digital_new_press` / `_new_release`; screen text is kept. The partner controller is not connected. |
| Tasks, `delay`, `delay_until`, mutexes, notifications, `millis`, `micros` | everything, in lockstep (below) |
| `pros::battery`, `pros::competition` | from the battery model; status per mode |
| `pros::lcd` (LLEMU), `pros::screen::print` | text lines appear in the viewer's brain-screen panel; drawing is ignored; screen buttons are never pressed |
| LVGL 9 (`liblvgl`) | a stand-in: screens, objects, labels, buttons, images (including LVGL image-converter files), event callbacks, timers and the common style setters compile and run. Nothing is drawn and no event fires. A missing function fails to compile: add it to `vexsim/bridge/cpp/include/liblvgl/lvgl.h` and `runtime/lvgl.cpp`. |
| `printf`, `std::cout`, `std::cerr` | console panel and terminal, stamped with simulated time |
| `pros::adi::*` | not simulated yet: outputs remember what was written (a `Pneumatics` reads back as extended); inputs read 0 |
| `pros::Optical`, `Vision`, `Link`, `Serial` | not simulated yet: calls fail with `ENODEV`, and the first one logs a note |
| SD card | not inserted: `pros::usd::is_installed()` reads 0 and files under `/usd/` don't open |

**PROS 4 behaviors reproduced, so they bite in the simulator too:** plain `MotorGroup` setters (`set_brake_mode`, `tare_position`) act on the first motor only, and the `_all` versions on every motor; `set_zero_position(p)` makes the current position read `p` and belongs to the port; declaring `green` on a `blue` cartridge makes `move_velocity(100)` spin 3× faster than meant (the console warns once); reversal is per object, while brake mode, limits, units, gearing and zero belong to the port.

### How simulated time works for C++
- **Lockstep.** Every PROS task is a thread, but only one runs at a time, and simulated time stands still while it runs. Time moves on only when every task is blocked in `pros::delay`, `delay_until`, a mutex or a notification wait. Runs are identical every time, at any speed.
- **FreeRTOS scheduling:** the highest-priority ready task runs first; among equal priorities, the one that became ready first. Waking a higher-priority task switches to it at once.
- **Busy loops** are charged 1 ms of simulated time per 1000 PROS calls, so `while (pros::millis() < t) {}` works. A loop that calls nothing (`while (true) {}`) can't advance time; it is stopped after `--busy-timeout` seconds of real time, with the task's name.
- **Crashes** (a bad memory access, an uncaught exception, `abort`) end the run with the task's name and its last console lines, instead of taking the simulator down.
- **Competition functions** run in the PROS competition task. When a period ends, that task is deleted (no destructors run, and held mutexes stay held), while tasks your code created keep running. While the robot is disabled, motor commands are ignored.
- **The brain has booted at time 0:** the IMU's power-on calibration is done, so it reads 0. `imu.reset(true)` recalibrates for about 2 s; keep the robot still.

### vexsim extras for C++: `vexsim/sim.hpp`
Guard its use, since the header doesn't exist on the robot:
```cpp
#if __has_include("vexsim/sim.hpp")
#include "vexsim/sim.hpp"
#endif
...
#ifdef VEXSIM
vexsim::report_pose(pose.x, pose.y, pose.theta);   // inches, theta clockwise from +y (LemLib's)
#endif
```
- `vexsim::report_pose(x, y, theta)` shows your own odometry as the estimated pose (in the viewer, telemetry and the headless summary). LemLib's pose is read automatically.
- `vexsim::benchmark_task()` returns the task of a benchmark trial (see [C++ controllers](#c-controllers-your-pros-project)).

**Environment variables** reach your code through `getenv()`: `vexsim run --env KEY=VALUE`, or `CppProgram(..., env={...})` from Python. Nobody taps the simulated brain screen, so this is how to choose an autonomous routine:
```cpp
#ifdef VEXSIM
if (const char* name = std::getenv("AUTON")) selected = find_routine(name);
#endif
```
`VEXSIM_SEED` is always set to the simulation's seed: seed your own random numbers with it to repeat a run exactly.

### LemLib
- **Built from source.** The LemLib template installs LemLib precompiled for the V5's ARM CPU, which can't run on a PC. vexsim reads LemLib's version from `project.pros`, fetches that release's source from GitHub (with git, or as a zip), and compiles it once per version and compiler. Offline, set `VEXSIM_LEMLIB_SOURCE` to a checkout. LemLib 0.5.x (for PROS 4) is tested.
- **`ASSET()` works:** every file in `static/` is embedded under the name `ASSET()` expects (`static/example.txt` is `ASSET(example_txt)`).
- **LemLib's pose shows up on its own** once `chassis.calibrate()` starts its odometry.
- **Start pose:** `chassis.setPose(x, y, theta)` is `--start x,y,(90 - theta)`.
- **Edited LemLib headers work as on the robot.** If the project has a complete copy of `include/lemlib/` (or `include/fmt/`) that differs from the release's, its code compiles against its own copy while LemLib itself is built from source, and the build notes which headers differ. Edits must keep class layouts the same (access and `const` changes are fine; new data members are not).

![LemLib's example program in the simulator](docs/img/lemlib_template.png)

### Differences from the robot
- **Compute time is free.** A long calculation takes no simulated time; on the robot it delays every task at its priority and below.
- **Wall-clock time isn't the robot's time.** `std::chrono` and `time()` read your PC's clock. Use `pros::millis()` or `micros()`, which work the same on the robot.
- **Integer sizes.** `long` and pointers are 4 bytes on the V5, and 8 on 64-bit Linux and macOS (pointers are 8 on 64-bit Windows too). Code that stores pointers in `int` needs fixing.
- **Precompiled ARM libraries won't link.** Only LemLib is rebuilt from source; OkapiLib isn't supported.
- **newlib extras** the V5 has and PC libraries lack are provided: `infinity()`, `infinityf()`, MinGW's `isnanf`/`isinff`/`finitef`, and `std::sqrtf`-style float functions on g++ before 14.
- Not modeled: time slicing among equal-priority busy tasks, and mutex priority inheritance.

### Troubleshooting
| Message | What to do |
|---|---|
| `no C++ compiler (g++) found` | install it ([C++ toolchain](#c-toolchain-only-for-running-pros-c-code)) and run `vexsim doctor` |
| `couldn't get LemLib 0.5.6's source` | connect to the internet once per LemLib version, or set `VEXSIM_LEMLIB_SOURCE` |
| `ASSET(name) needs a file static/...` | put the file in `static/`, named so its `.` becomes `_` |
| `... defines autonomous() with C++ linkage, so it is never called` | include `main.h` in that file; it declares the competition functions `extern "C"` |
| `robot code hung: task '...' ran for 5.0 s of real time without calling pros::delay()` | add a delay to that loop; on the robot it would starve every other task |
| `port N: the code uses ... but the robot config has ...` | make the robot YAML's ports match your code |
| `pros::Optical is not simulated yet` | expected; the call returned `PROS_ERR` |
| `'lv_...' was not declared in this scope` | the LVGL stand-in lacks that function: add it, or keep that code out of simulator builds with `#ifndef VEXSIM` |

---

## 9. Analysis commands: motor curves, drift, odometry
**`vexsim motor-curves`** measures the simulated V5 motor on a dynamometer, under `move_velocity(max)` and `move_voltage(12000)`:
```
vexsim motor-curves --cartridge red --out red.png      # torque, current, power vs. speed
vexsim motor-curves --cartridge blue --csv             # the data as CSV
```
Options: `--cartridge red|green|blue`, `--supply-voltage` (default 12.8), `--points` (default 61).

![Simulated V5 motor curves, red cartridge](docs/img/motor_curves_red.png)

**`vexsim drift`** drives a differential robot on an arc with fixed side speeds (fractions of rated speed) for several roller friction values, and compares the true path with what drive-encoder odometry believes. Compare it with a video of your robot to calibrate `wheel.omni.lateral_mu`:
```
vexsim drift examples/robots/full_omni_6m.yaml --left 1.0 --right 0.4 --lateral-mu 0.1,0.2,0.3 --out drift.png
```
Options: `--left`, `--right`, `--seconds`, `--lateral-mu` (up to 3 values), `--out`, `--csv`.

![True path vs. drive-encoder odometry in a fast arc](docs/img/drift_arc.png)

**`vexsim odometry`** calibrates the IMU, drives a scripted path, and runs every baseline localizer the robot's sensors allow:
```
vexsim odometry examples/robots/full_omni_6m.yaml --script aggressive --noise default --out odom.png
```
```
aggressive drive, default sensor noise, seed 0:
  drive encoders         final error  76.92 in   3.37 deg   worst  76.92 in
  drive encoders + IMU   final error  77.12 in   0.34 deg   worst  77.12 in
  tracking wheels + IMU  final error   1.65 in   0.34 deg   worst   1.65 in
```
Options: `--script gentle|aggressive`, `--noise`, `--seed`, `--out`, `--csv`.

![Odometry baselines on the aggressive drive](docs/img/odometry_aggressive.png)

---

## 10. Benchmarking algorithms: `vexsim bench`
A benchmark runs one task many times (seeds) for every combination of the localizers and controllers a scenario lists, in parallel processes, and writes CSVs and a self-contained HTML report.
```
vexsim bench examples/scenarios/s_curve.yaml --seeds 100
```
```
S-curve under a mid-path shove: 400 trials in 97 s
  localizer / controller                success  final error mean/p95  loc error mean/p95
  tracking wheels + IMU / pure pursuit      47%     2.13 /  3.70 in      1.40 /  2.87 in
  tracking wheels + IMU / RAMSETE           17%     3.39 /  5.87 in      1.40 /  2.85 in
  drive encoders + IMU / pure pursuit       18%     3.58 /  6.52 in      4.56 /  7.76 in
  drive encoders + IMU / RAMSETE            18%     3.07 /  5.12 in      2.08 /  4.54 in
```
Options: `--seeds N` and `--first-seed S`; `--workers` (default CPU cores − 1); `--localizers` and `--controllers` (comma-separated subsets of the scenario's); `--out DIR` (default `bench_<scenario>`); `--no-worst` (don't re-run the worst cases).

| Output | Contents |
|---|---|
| `report.html` | settings, summary table, distribution charts, worst cases; opens offline in any browser |
| `trials.csv` | one row per trial: every metric, and what was randomized |
| `summary.csv` | per combination: success rate, timeouts, and the mean / median / p95 / max of every metric |
| `charts/*.png` | the report's charts |
| `worst_<localizer>__<controller>.csv` | the telemetry of each combination's worst seed; watch it with `vexsim replay` |

Trials are deterministic: any row of `trials.csv` reproduces exactly from its seed, in one process or many. [docs/benchmarking.md](docs/benchmarking.md) discusses an example 100-seed result, and its full report is [docs/benchmarks/s_curve_100/report.html](docs/benchmarks/s_curve_100/report.html).

![Final position error, all 400 trials](docs/benchmarks/s_curve_100/charts/final_position_error.png)

### Writing a scenario
```yaml
version: 1
name: Boomerang to a pose, 9 V vs 12 V         # shown in the report
description: ...
robot: ../robots/full_omni_6m.yaml             # paths are relative to this file
field: ../fields/v5rc_empty.yaml               # optional; game elements work
start: {x: 0, y: 0, heading: 0}                # inches, degrees CCW
noise: default                                 # one preset for every sensor (optional)
battery_soc: 1.0
time_limit_s: 6                                # per trial
settle_window_s: 0.5                           # keep recording after the controller finishes
task: {type: move_to_pose, x: 30, y: 30, heading: 90}
disturbances:
  - {type: imu_bias_step, at_s: 1.0, deg_per_s: 0.5}
randomize:
  start_xy_in: 0.5                             # std. dev. of the true start vs. the believed one
  start_heading_deg: 1.0
  battery_soc: [0.6, 1.0]                      # uniform range per seed
  params:                                      # any override key, uniform range per seed
    wheel.omni.lateral_mu: [0.15, 0.25]
localizers: [tracking wheels + IMU]            # baseline names, "all", or file.py:factory
controllers:
  - {name: boomerang 9V, kind: boomerang}
  - {name: boomerang 12V, kind: boomerang, options: {max_volts: 12}}
```

| `task.type` | Fields | Built-in controller `kind`s (first = default) |
|---|---|---|
| `move_to_point` | `x, y, forwards, tolerance_in` (1.5) | `move_to_point` |
| `move_to_pose` | `x, y, heading, tolerance_in` (2), `heading_tolerance_deg` (3) | `boomerang` |
| `turn_to_heading` | `heading, heading_tolerance_deg` (2) | `turn_pid` |
| `drive` | `distance_in, tolerance_in` (1) | `profiled_trapezoid`, `profiled_scurve` |
| `follow` | `waypoints, tolerance_in` (2, at the end) | `pure_pursuit`, `ramsete` |

| Disturbance `type` | Fields | Effect |
|---|---|---|
| `push` | `at_s, duration_s, force_n: [fx, fy]` | a force at the CG in the field frame (another robot shoving) |
| `imu_bias_step` | `at_s, deg_per_s, port` (optional) | the gyro bias jumps, as after a hard hit |
| `tracking_wheel_liftoff` | `at_s, duration_s, port` | a tracking wheel stops counting |

**Localizer names** are the baselines a robot supports: `drive encoders`, `drive encoders + IMU`, `tracking wheels + IMU`, `tracking wheels (no IMU)` and `tracking wheels + IMU + GPS` (see [Localization baselines](#localization-baselines)).

### Your own algorithms
Point the scenario at a Python file and a factory function, relative to the scenario:
```yaml
localizers: [tracking wheels + IMU, my_algos.py:make_ekf]
controllers:
  - {name: my follower, kind: my_algos.py:make_follower, options: {lookahead_in: 10}}
```
```python
# my_algos.py
# A localizer: .name, .reset(pose, frame), .update(frame) -> Pose
def make_ekf(config):
    return MyEkf(config)


# A controller: .step(pose, frame, dt) -> DriveCommand, .done()
def make_follower(task, geometry, lookahead_in=12.0):
    return MyFollower(task.waypoints, geometry, lookahead_in)
```
A localizer gets the same `SensorFrame` PROS code would read; a controller gets the localizer's estimate and returns a `DriveCommand`. Neither ever sees the true pose, which is what makes the comparison honest.

### C++ controllers: your PROS project
```yaml
controllers:
  - {name: Python boomerang, kind: boomerang}
  - {name: LemLib moveToPose, kind: pros, project: ../pros_projects/lemlib_bench}
```
The project is built once, and each trial runs its `initialize()` and `autonomous()`. `vexsim::benchmark_task()` gives the task: its `type`, the start pose odometry should assume, the target, `forwards`, `distance`, `timeout_ms`, for `follow` the path as a LemLib path file, and the controller's options through `task.option(name, fallback)`. Poses use LemLib's convention. Completion is when `autonomous()` returns, and the code's own localization shows as the localizer `robot code`. `examples/pros_projects/lemlib_bench` maps every task type to a LemLib motion.

### Metrics
| Column | Meaning |
|---|---|
| `success` | finished within tolerance (and heading tolerance) before the time limit |
| `timed_out` | the controller never reported done |
| `final_error_in`, `final_heading_error_deg` | the true end pose against the target |
| `completion_time_s`, `settle_time_s` | when the controller reported done; how long the true pose had been within tolerance |
| `overshoot_in` | point tasks: the furthest past the target along the approach |
| `path_rms_in`, `path_max_in` | follow tasks: the true path's distance to the reference |
| `loc_error_final_in`, `loc_error_max_in`, `loc_error_per_100in` | the estimate against the truth |
| `energy_j`, `peak_motor_temp_c`, `wall_contacts` | battery energy used, the hottest motor, wall hits |

The built-in Python controllers drive the `left` and `right` sides (differential drives and H-drives). Benchmark X-drive and mecanum robots with a PROS project controller, or your own Python one.

---

## 11. Calibrating to your robot
Most physics parameters are estimates: how well your wheels grip your tiles, how freely the rollers turn, how much a coasting robot slows. Calibration measures them on your robot, with no extra equipment:

1. **Generate** a drive routine for your robot and add it to your PROS project:
   ```
   vexsim calibration-routine ROBOT.yaml MY_PROS_PROJECT
   ```
   This writes `include/vexsim_calibration.hpp` and `src/vexsim_calibration.cpp`. They use only the PROS 4 C API, so they build with PROS and run unchanged in vexsim. Call the routine from `autonomous()`:
   ```cpp
   #include "vexsim_calibration.hpp"
   void autonomous() { vexsim_calibration::run(); }
   ```
2. **Run it on the robot**, in the middle of a field, on the tiles you compete on, with a charged battery. It calibrates the IMU (keep the robot still), then drives for about 7 s (9 s for drivetrains that strafe) with fixed voltages and no feedback, staying within about 4 ft of the start:

   | Step | Measures |
   |---|---|
   | launch from rest | traction limit and motor torque |
   | coast | rolling resistance |
   | reverse, then brake | back-EMF braking |
   | strafe out and back (X-drive, mecanum, H-drive) | roller resistance |
   | spin in place | roller friction and scrub |
   | fast arc, then coast | sideways sliding (drift) |

   The log goes to the SD card (`/usd/vexsim_log.csv`). Without a card it goes to the terminal, between `#vexsim-log begin` and `#vexsim-log end`; capture it with `pros terminal > run.txt` over USB. Either file works.
3. **Fit:**
   ```
   vexsim calibrate ROBOT.yaml vexsim_log.csv --out calibration
   ```
   ```
   parameter                           before      after  uncertainty
   wheel.omni.longitudinal_mu             0.9     0.7527  +/-0.066%
   wheel.omni.lateral_mu                  0.2      0.278  +/-0.027%
   wheel.omni.rolling_resistance          0.1     0.1397  +/-0.03%
   battery.internal_resistance_ohm                  0.15  from battery voltage vs. current
   RMS difference, simulated vs. logged (28 replays):
     motor velocity (rpm): 40.9 -> 3.01
     ...
   ```
   Paste the printed `overrides:` block into the robot YAML. `--out` also saves it as `overrides.yaml`, with the plot and the fitted replay. Options: `--fit` (a comma-separated list of any parameters; `none` only replays and compares), `--max-iterations`, `--workers`.

![A logged calibration run vs. the simulation, before and after the fit](docs/img/calibration.png)

- **What it fits** by default: the parameters of each wheel type on the robot (omni: `longitudinal_mu`, `lateral_mu`, `rolling_resistance`; traction: `mu`, `rolling_resistance`; mecanum: `grip_mu`, `roller_mu`, `rolling_resistance`). The battery's internal resistance is read off the log, as the slope of its voltage against its current.
- **How:** the log's motor commands are replayed in the simulator at the log's times, with ideal sensors, the logged battery voltage, and the readings' age found from the motor currents. Levenberg-Marquardt adjusts the parameters (in log space, so they stay positive) until the simulated motor velocities and currents, tracking-wheel speeds and heading rates match the log, each group weighted equally.
- **Check it on another run:** `vexsim calibrate ROBOT.yaml another_run.csv --fit none`. Any program can log: call `vexsim_calibration::start_logging()` and `save()`. To compare a simulated run with a real one, record the simulated run with `vexsim run ... --headless --robot-log sim_run.csv`.
- **Try it without a robot:** `examples/pros_projects/calibration` is the routine for `full_omni_6m`:
  ```
  vexsim run examples/robots/full_omni_6m.yaml --program examples/pros_projects/calibration --headless > run.txt
  vexsim calibrate examples/robots/full_omni_6m.yaml run.txt
  ```

[docs/calibration.md](docs/calibration.md) has the log format and more detail.

---

## 12. Porting a team's code
[docs/porting_1239e.md](docs/porting_1239e.md) ports team 1239E's 2026-27 code step by step: LemLib with distance-sensor wall resets (RCL), a 2048-particle Monte Carlo localizer (MCL), a lift and end effector, an LVGL auton selector, and nine autonomous routines. It runs with three small marked edits:
```
vexsim run examples/robots/1239e_2026-27.yaml --program examples/pros_projects/1239e_2026-27 --field examples/fields/1239e_2026-27.yaml --start=60,0,0 --env "VEXSIM_AUTON=Left 40"
python examples/scripts/evaluate_1239e.py --seeds 6 --plot errors.png
```
The evaluation script runs every routine with and without the distance sensors, and measures LemLib's pose against the truth.

![1239E routines: LemLib's pose vs. the true pose](docs/img/1239e_localization.png)

**The steps for any team's code:**
1. **Take stock** of every device, library and system call, against [what's simulated](#whats-simulated).
2. **Copy** `src/`, your own headers and `project.pros`, leaving out what PROS installs. Run `vexsim build`, and fix what doesn't compile.
3. **Make small, inert edits:** replace wall-clock timing with `pros::millis()` or `micros()`; read the routine's name from an environment variable under `#ifdef VEXSIM`; seed random numbers from `VEXSIM_SEED`.
4. **Write the robot config** from your code's ports, gearing and sensor offsets (convert `chassis.setPose` and offsets as in [Frames](#frames-and-angles)). Measure the rest, then [calibrate](#11-calibrating-to-your-robot).
5. **Write the field config**, with element heights if your sensors care about them.
6. **Run each routine** headless, and compare the pose your code believes with the truth.

---

## 13. Using vexsim as a Python library
Everything the commands do is available from Python.

**A full simulation with a program** (a Python module or a C++ project):
```python
from vexsim.algorithms.localization import Pose
from vexsim.bridge.program import CppProgram
from vexsim.config import load_field, load_robot
from vexsim.runtime.program import load_program
from vexsim.runtime.simulation import Simulation

config = load_robot("examples/robots/full_omni_6m.yaml")
program = load_program("examples/programs/tour.py")
sim = Simulation(config, program=program, seed=1, start=Pose(0, 0, 0), echo=None)
sim.start("autonomous")
sim.run_until_finished(60)
print(Pose.from_si(sim.robot.pose), sim.estimated_pose)
print(sim.recorder.pose_error("autonomous"))  # mean, max and final position and heading errors
sim.recorder.write_csv("tour.csv")

# A PROS project instead (built incrementally); env reaches getenv() in the code
program = CppProgram.from_project("examples/pros_projects/minimal_pros4", env={"MY_FLAG": "1"})
field = load_field("examples/fields/v5rc_empty.yaml")
sim = Simulation(config, program=program, field=field, start=Pose(0, 0, 90), echo=None)
sim.start("autonomous")
sim.run_until_finished(30)
sim.close()  # ends the robot code's process
print(sim.console[-3:])
```
`Simulation(config, program=None, field=None, seed=0, noise=None, start=Pose(0, 0, 0), believed_start=None, battery_soc=1.0, localizer=None, input_source=None, record=True, echo=print, walls=True)` has `start(mode)`, `run_for(seconds)`, `run_until_finished(max_seconds)` and `close()`, and exposes `robot`, `sensors`, `arena`, `world`, `recorder`, `console`, `lcd`, `reported_pose` and `estimated_pose`.

**The world loop and a robot:**
```python
from vexsim.config import load_robot
from vexsim.physics import PRIORITY_SENSOR, World
from vexsim.physics.robot import Robot

world = World(seed=1)  # 1 ms physics step
robot = world.add_system(Robot(load_robot("examples/robots/full_omni_6m.yaml")))
left, right = robot.group("left"), robot.group("right")
left.set_velocity(left.rated_speed)  # motor shaft rad/s; positive = wheels forward
right.set_velocity(0.5 * right.rated_speed)
world.every(100, lambda w: print(round(w.time, 1), robot.pose), priority=PRIORITY_SENSOR)
world.run_for(1.0)
print(robot.body_velocity, robot.contacts.normal)
```

**Sensors and your own localizer** (readings in PROS units):
```python
from vexsim.algorithms.localization import Pose, baseline_localizers
from vexsim.config import load_robot
from vexsim.devices.suite import SensorSuite
from vexsim.physics import World
from vexsim.physics.robot import Robot

config = load_robot("examples/robots/full_omni_6m.yaml")
world = World(seed=1)
robot = world.add_system(Robot(config))
sensors = SensorSuite(robot, world.rng).attach(world)  # attach after the robot
world.run_for(2.1)  # the IMU calibrates; keep still
odom = baseline_localizers(config)[-1]  # tracking wheels + IMU
odom.reset(Pose(0, 0, 0), sensors.frame(world.time))
world.every(10, lambda w: odom.update(sensors.frame(w.time)), priority=1)
robot.group("left").set_velocity(40)
robot.group("right").set_velocity(30)
world.run_for(2.0)
print(odom.pose, Pose.from_si(robot.pose))
```

**A single motor on a test rig:**
```python
from vexsim.physics import BrakeMode, PowerSystem, V5Motor, World
from vexsim.physics.rig import ShaftRig

world = World()
power = PowerSystem()  # V5 battery + brain power distribution
motor = V5Motor("blue")
power.attach(motor)
rig = world.add_system(ShaftRig(motor, load_inertia_kgm2=1e-3))
motor.brake_mode = BrakeMode.HOLD
world.every(10, lambda w: motor.set_velocity(50.0 if w.time < 1 else 0.0))
world.run_for(2.0)
print(rig.omega, motor.current, motor.temperature_c, power.bus_voltage)
```

**Benchmarks and calibration:**
```python
from vexsim.bench.runner import run_bench

result = run_bench("examples/scenarios/pose_approach.yaml", seeds=[0, 1, 2], workers=1)
print(result.combos(), result.rows[0]["final_error_in"])
```
`vexsim.calibration.log.RobotLog.read(path)`, `vexsim.calibration.fit.fit(config, log, parameters)` and `compare(config, log, overrides)` do what `vexsim calibrate` does.

---

## 14. Module reference: what each part does
```
vexsim/
  cli.py, __main__.py   the `vexsim` command
  units.py, v5.py       unit conversions; V5 hardware constants
  config/               robot and field schemas, YAML loading, validation, summaries
  core/                 clock, event scheduler, random streams
  physics/              the world loop and every physical model
  devices/              simulated sensors and motor encoders
  algorithms/           localization (odometry, GPS) and control (PID, motions, paths)
  api/                  the Python robot-program API
  runtime/              simulations, competition phases, programs, telemetry
  bridge/               PROS 4 C++ code in the loop: build, host process, shim
  bench/                Monte-Carlo benchmarks and reports
  calibration/          robot logs, the calibration routine, replays, fitting
  viz/                  the live viewer and every plot
```

### Top level
| Module | What it does |
|---|---|
| `cli.py` | Every `vexsim` command: parses arguments, loads configs, wires the pieces below together, and prints results. `main(argv)` returns the exit code. |
| `__main__.py` | Makes `python -m vexsim` work. |
| `units.py` | Conversions between VEX units and SI (`in_to_m`, `rpm_to_rad_s`, `mv_to_v`, ...). The simulator computes in SI and converts only at its boundaries. |
| `v5.py` | V5 constants: 21 smart ports, cartridge speeds (100/200/600 rpm), ±12000 mV, 11 W per motor, the 88 W motor budget, the 18 in starting size. |

### `config/`: robot and field configs
| Module | What it does |
|---|---|
| `robot.py` | The robot YAML schema (pydantic): `RobotConfig`, with `BodyConfig`, `DrivetrainConfig` (`WheelConfig`, `GearGroupConfig`), `MechanismConfig`, and the sensor configs (`ImuConfig`, `RotationConfig` with `TrackingWheelConfig`, `DistanceConfig`, `GpsConfig`). Per-field rules (port ranges, positive sizes) and `ratio_value("36:48")`. |
| `field.py` | The field YAML schema: `FieldConfig`, `ObstacleConfig`, `PieceConfig`, and `check_field` (elements inside the walls, overlapping pieces). |
| `checks.py` | Cross-field robot checks (`check_robot`): ports, footprint containment, tipping, gearing, drivetrain layout, strafing ability, motor budget, overrides. |
| `loader.py` | `load_robot` and `load_field` (raise on errors), and `validate_robot` and `validate_field` (return a report), from a file or a mapping. |
| `yaml_io.py` | A strict YAML loader: `36:48` stays text instead of becoming the base-60 number 2208, and duplicate keys are errors. |
| `issues.py` | `ConfigIssue`, `ValidationReport` and `ConfigError`: problems with a location, a severity and a message, with "did you mean" suggestions. |
| `summary.py` | The human-readable summary `validate-config` prints (ASCII only, for Windows consoles). |

### `core/`: simulation infrastructure
| Module | What it does |
|---|---|
| `clock.py` | `SimClock`: time as integer microseconds, so long runs never drift. |
| `events.py` | `EventScheduler`: timed and periodic callbacks, fired in order of time, priority, then registration. |
| `rng.py` | `RngStreams`: independent named random streams from one seed (`world.rng.stream("sensor.imu.10")`), hashed with BLAKE2 so they match in every process. |

### `physics/`: the models
| Module | What it does |
|---|---|
| `world.py` | `World`: the fixed-step loop. Each tick fires the due events (`every`, `after`), steps every physics system (`add_system`), and advances the clock; `run_for`, `run_until`. Priorities `PRIORITY_SENSOR`, `PRIORITY_CONTROL`, `PRIORITY_RECORD`. |
| `motor.py` | `V5Motor`: the 11 W motor. The electrical model, the firmware's velocity, position and hold loops, voltage mode, brake modes, the current limit, thermal derating and power draw. `MotorSpec`, `BrakeMode`, `ControlMode`. |
| `thermal.py` | `MotorThermal`: the two-node (winding, housing) heat model and the firmware's current derating steps. |
| `battery.py` | `Battery`: open-circuit voltage against charge, internal resistance, charge counting. |
| `power.py` | `PowerSystem`: sums every motor's draw into battery current, sags the bus voltage, and shares a 20 A budget beyond 8 motors. `IdealSupply` for tests and rigs. |
| `wheel.py` | Wheel-ground contact: `OmniWheelSpec`, `TractionWheelSpec`, `MecanumWheelSpec`; smoothed Coulomb friction on three channels; the traction friction circle. |
| `chassis.py` | `NormalLoads`: each wheel's share of the weight, with weight transfer under acceleration and turning, drop-center rocking and lift-off. |
| `robot.py` | `Robot`: the drivetrain built from a config. Gear groups (`DriveGroup`), wheels, chassis, mechanisms and power; the implicit integrator; the pose, velocities and contacts; wall and obstacle contacts. |
| `kinematics.py` | `DriveKinematics`: which gear-group speeds produce a body motion (forward, sideways, turn), for any drivetrain; whether it can strafe; top speeds. |
| `mechanism.py` | `Mechanism`: a lift, intake or arm: its motors through a ratio, inertia, load, friction and hard stops. |
| `field.py` | `Walls` and `FieldSpec`: the perimeter. Footprint corners past a wall are resolved with impulses (bounce, wall friction), then pushed back inside. `robot_impulses` is shared with obstacles. |
| `arena.py` | `Arena`: game elements. Robot contacts with solid obstacles; pieces (`Pieces`) sliding, bouncing and being pushed; ray casts for sensors (`ray`, with a beam height). `Shape` is a rectangle or a circle. |
| `params.py` | `PhysicsParams` and `resolve_params`: every parameter group with the config's `overrides` applied; `check_overrides` validates the keys. |
| `rig.py` | `ShaftRig` (a motor driving an inertia), and the dynamometer behind `motor-curves` (`torque_speed_curve`, `free_speed`, `hold_speed`). |

### `devices/`: simulated sensors
| Module | What it does |
|---|---|
| `devices.py` | One class per device: `MotorDevice` (encoder counts, velocity, current, ...), `RotationDevice` (a tracking wheel's true travel, with diameter, mounting and scrub errors), `ImuDevice` (gyro bias, noise, scale error, calibration), `DistanceDevice` (a ray to walls and elements), `GpsDevice` (fixes from the code strip, its gyro between fixes). Each samples the physics on its period and publishes after its latency. `ray_to_walls`. |
| `specs.py` | Timing and error parameters per sensor type, and the `ideal`, `default`, `harsh` and `replay` presets; `sensor_spec(kind, preset, overrides)`. |
| `suite.py` | `SensorSuite`: one device per port from the config (motors included), wired into the world; `frame(time)` collects every reading. |
| `frame.py` | `SensorFrame` and the reading types: what robot code sees, in PROS units and sign conventions. |

### `algorithms/`: localization and control
| Module | What it does |
|---|---|
| `localization/base.py` | `Pose` (in, deg CCW; `from_si`, `distance_to`, `heading_error`) and the `Localizer` interface (`reset`, `update`). |
| `localization/odometry.py` | `ArcOdometry`, the arc method LemLib uses, over `RotationTracker`s (tracking wheels) or `MotorTracker`s (drive encoders), with heading from an IMU or two parallel wheels. |
| `localization/gps.py` | `GpsCorrected`: odometry pulled toward GPS fixes by a complementary filter, with latency compensation. |
| `localization/baselines.py` | `baseline_localizers(config)`: every baseline the robot's sensors support, best last. |
| `localization/runner.py` | `run_odometry`: the scripted drives (`gentle`, `aggressive`) behind `vexsim odometry`. |
| `control/base.py` | `DriveCommand` (volts or wheel speeds), `ChassisGeometry`, and the `Controller` interface. |
| `control/pid.py` | `PID` (with an integral zone, and an integral reset when the error changes sign) and LemLib-style `ExitCondition`s. |
| `control/profiles.py` | `TrapezoidProfile` and `SCurveProfile`: 1-D motion profiles. |
| `control/motions.py` | `TurnToHeading`, `MoveToPoint`, `Boomerang` (moveToPose) and `ProfiledDrive`, with LemLib-like gains. |
| `control/paths.py` | `PurePursuit`, `Ramsete`, and path tools: `spline` (Catmull-Rom), `densify`, `smooth`, `generate_trajectory`. |

### `api/`: Python robot programs
| Module | What it does |
|---|---|
| `__init__.py` | `delay(ms)`, what programs yield to wait. |
| `devices.py` | PROS-style `Motor`, `MotorGroup`, `Imu`, `Rotation`, `Distance`, `Gps` and `Controller`, backed by the simulated devices. |
| `drive.py` | `Drive`: forward, strafe and turn for any drivetrain, from its kinematics. |
| `chassis.py` | `Chassis`: LemLib-style motions as generators, tank and arcade drive, and its own odometry. |

### `runtime/`: running programs
| Module | What it does |
|---|---|
| `simulation.py` | `Simulation`: the world, robot, arena, sensors, a localizer, a program, inputs and telemetry, with the competition phases (`MODES`). `Bot` (what programs receive), `ScriptedInput` (`--input`), and the default `initialize` and `opcontrol`. |
| `program.py` | `load_program`, and the coroutine runner that turns generator functions into competition phases. |
| `recorder.py` | `Recorder`: the 10 ms telemetry log, and `pose_error` (the estimate against the truth). `Log` reads a CSV back for plots and replays. |

### `bridge/`: PROS 4 C++ code in the loop
| Module | What it does |
|---|---|
| `build.py` | `vexsim build`: finds g++ (`find_toolchain`), stages the project without the PROS SDK, compiles incrementally with dependency tracking, embeds `static/` for `ASSET()`, builds the shared runtime, and links `robot_host`. Reads the templates in `project.pros`. |
| `lemlib.py` | Finds the project's LemLib version, fetches and caches its source, and compiles it once per version; detects edited LemLib headers. |
| `host.py` | `RobotHost`: starts `robot_host` and speaks its line protocol over pipes. Readings and `RUN <time>` go in; motor commands, console text, LCD lines, the reported pose and the next wake-up time come out. |
| `program.py` | `CppProgram`: a built project as a simulation program. It sends readings, applies commands, maps competition modes to status bits, and sets `VEXSIM_SEED` and `--env` variables. |
| `doctor.py` | `vexsim doctor`: toolchain checks, and a test build and run. |
| `cpp/include/` | The PROS 4 shim headers robot code compiles against: `api.h`; `pros/*.h(pp)` (motors, IMU, rotation, distance, GPS, rtos, misc, llemu, screen, adi, and stubs for unsimulated devices); `liblvgl/` (LLEMU and the LVGL stand-in); `vexsim/sim.hpp` (`report_pose`, `benchmark_task`); `vexsim/newlib_compat.h` (newlib extras). |
| `cpp/runtime/` | The C++ side, linked into every build: `host.cpp` (process setup, the protocol loop, console capture, crash reports), `scheduler.cpp` (the lockstep FreeRTOS-style scheduler: tasks, delays, mutexes, notifications), `devices.cpp` (the PROS device C API over a device table), `lvgl.cpp` (the LVGL stand-in), `defaults/` (empty competition functions, used only when the code has none, like PROS's weak defaults). |

### `bench/`: benchmarks
| Module | What it does |
|---|---|
| `scenario.py` | The scenario YAML schema: tasks, disturbances, randomization and controllers; `load_scenario`. |
| `trial.py` | One trial: builds the robot with the seed's randomization, runs the localizer and controller (or the PROS project), applies disturbances, and records. |
| `metrics.py` | `score`: the metrics, from a trial's true and estimated poses. |
| `runner.py` | `run_bench`: every seed × localizer × controller in parallel processes, then the worst-case re-runs. |
| `report.py` | `trials.csv`, `summary.csv`, the charts, and the self-contained `report.html`. |

### `calibration/`: fitting the model to a robot
| Module | What it does |
|---|---|
| `routine.py` | The calibration maneuvers (launch, coast, reverse, strafe, spin, arc) as fixed-voltage steps, scaled to the robot. |
| `cpp.py` | Generates the routine and a 10 ms logger as PROS 4 C++ for one robot config. |
| `log.py` | `RobotLog`: the robot-log CSV format, read from a file or cut out of terminal output. |
| `record.py` | `RobotLogger`: writes the same log from a simulation (`--robot-log`). |
| `replay.py` | Replays a log's commands in the simulator, with ideal sensors and the logged battery voltage, at the log's reading age. |
| `fit.py` | A Levenberg-Marquardt fit of any parameters to a log; the battery's resistance from voltage against current; `compare`. |

### `viz/`: viewer and plots
| Module | What it does |
|---|---|
| `viewer.py` | The pygame viewer: live simulations (`LiveSource`) and log replays (`ReplaySource`), keyboard and gamepad input, the side panel. |
| `motor_curves.py`, `drift.py`, `odometry.py`, `telemetry.py`, `calibration.py` | The plots behind `motor-curves`, `drift`, `odometry`, `plot` and `calibrate`. |

### Outside the package
| Folder | What it holds |
|---|---|
| `examples/` | robot and field configs, Python and C++ programs, inputs, scenarios, scripts ([the table above](#the-example-files)) |
| `docs/` | deep dives: [models.md](docs/models.md) (every parameter's source, measurement experiments), [conventions.md](docs/conventions.md), [programming.md](docs/programming.md), [cpp.md](docs/cpp.md), [benchmarking.md](docs/benchmarking.md) (a worked 100-seed example), [calibration.md](docs/calibration.md), [porting_1239e.md](docs/porting_1239e.md); images and an example report |
| `tests/` | the test suite, including a C++ test project for the bridge (`tests/cpp/bridge_test`) |
| `PLAN.md` | the design plan and the phase history |

---

## 15. The physics models
This is a summary; [docs/models.md](docs/models.md) gives every parameter's source (VEX, a curve fit, a community report, or an estimate) and how to measure it.

### Motor
- Modeled at the motor core: `I = (V − ke·ω)/R`, clamped to the current limit; torque `kt·I` minus Coulomb and viscous friction; the cartridge multiplies torque by 36, 18 or 6 (red, green, blue). Fitted to VEX's published curve: about 2.1 N·m stall at the 2.5 A limit (red), rated speed held up to about a third of stall torque, about 12.7 W peak.
- **Firmware:** `move_velocity` is capped at rated speed and runs a feedforward plus PI loop that can use the full battery voltage, so it holds speed under load. `move_voltage` isn't speed-capped (12 V spins about 13% past rated). Position mode and `HOLD` add a position loop. A zero command stops with the brake mode: `COAST` (windings open), `BRAKE` (shorted: back-EMF braking) or `HOLD`.
- **Heat:** I²R heats a winding node that leaks to the housing, where the temperature sensor is. Above about 55 °C the firmware cuts current to 1/2, 1/4, 1/8, then 0. A stalled motor reaches the first step after about 160 s.

### Battery and power
1100 mAh, 13.5 V full to 11.2 V empty, 0.1 Ω internal resistance. Motors see the bus voltage under the total draw (plus the brain's 0.3 A) from the previous 1 ms step. Beyond 8 motors, each motor's current limit becomes 20 A ÷ N. Regeneration feeds other motors but never charges the battery.

### Wheels
Each wheel has three friction forces, each `coeff · N · tanh(velocity / smoothing)`:
- **grip**, along the wheel's grip direction: it drives the robot (`longitudinal_mu`, `mu` or `grip_mu`);
- **free**, across it: the rollers' resistance (`lateral_mu`, `roller_mu`), or a traction wheel's sideways grip;
- **rolling**: rolling resistance, so a coasting robot slows down.

Omni wheels grip along their rolling direction and roll freely across it, which is why X-drives work. Mecanum wheels grip along their ground rollers' axis (`roller_angle_deg`), so driving one pushes the robot diagonally. Traction wheels share one friction circle between grip and sideways slip, so a scrubbing wheel loses drive traction.

**Why omni robots drift:** a turn needs a sideways force of mass × speed × yaw rate, and only roller friction supplies it, up to `lateral_mu · g` (about 2 m/s²). Past that the robot slides outward, and a fast arc becomes a spiral, while drive-encoder odometry believes it traced the tight circle.

### Chassis and robot dynamics
- Each wheel sits on a stiff spring under a rigid chassis. The loads carry the weight and balance the pitch and roll moments of the ground forces below the CG: weight transfer, drop-center rocking, wheel lift-off.
- The degrees of freedom are the body's forward, sideways and yaw velocities, plus one shaft speed per gear group. Contact velocities are linear in them, and each 1 ms step solves a linearly implicit Euler update, stable even though tire friction is far stiffer than the step. Motor torques are explicit. The example robot runs about 6× faster than real time on one core.

### Walls, obstacles, pieces, mechanisms
- **Walls and solid obstacles:** footprint corners inside them are contacts, resolved with impulses: a bounce (`wall_restitution`, none below 5 cm/s) and friction (`wall_friction`); then the robot is moved out. A robot driving into a wall stalls with its wheels slipping, and an angled approach squares it up (a wall reset).
- **Pieces** slide with Coulomb ground friction, bounce off walls, obstacles, each other and the robot, and get pushed; a piece pinned against something stops the robot. They don't spin, and robots can't pick them up.
- **Mechanisms:** see [Mechanisms](#mechanisms). Friction is implicit (exact stiction), and hard stops are inelastic.

### Sensors
Every device samples on its period and publishes after its latency, in PROS units. The noise presets are `ideal` (no noise, latency or quantization, for debugging algorithms), `default` and `harsh`; `replay` is for calibration. Static errors are drawn once per device.

| Sensor | Default model |
|---|---|
| Motor encoder | 10 ms, 5 ms latency; 1800/900/300 counts per output rev (red/green/blue); velocity noise 0.5% of rated |
| Rotation (tracking wheel) | 10 ms; 0.088° resolution; 0.02° noise; per-wheel diameter error 0.5% and mounting error 0.05 in; scrub 1% of sideways travel; `harsh` adds lift-offs |
| IMU | 10 ms; a 2 s calibration that removes the gyro bias (0.3°/s); 0.05°/s rate noise; per-device scale error 0.5%, not removed by calibration; clockwise-positive |
| Distance | ~30 Hz, 10 ms latency; 20–2000 mm; σ 7.5 mm below 200 mm, 2.5% above; a ray to walls, obstacles (respecting heights) and pieces |
| GPS | 20 ms, 20 ms latency; a fix while the camera sees the code strip 0.3–4 m away, unblocked; σ 5 mm + 4 mm per meter; heading σ 0.3° |

A tracking wheel integrates the true contact velocity at its true mounting point with its true diameter. Localizers only know the configured geometry, so per-device errors show up as odometry error, as on a real robot.

### Localization baselines
| Name | Needs |
|---|---|
| drive encoders | a differential drive |
| drive encoders + IMU | + an IMU |
| tracking wheels + IMU | ≥1 vertical tracking wheel + an IMU |
| tracking wheels (no IMU) | ≥2 vertical tracking wheels |
| tracking wheels + IMU + GPS | tracking wheels + an IMU, and a GPS: odometry pulled toward GPS fixes (time constant 0.5 s), heading from the IMU |

All use the arc method, which is exact for constant-curvature motion. X-drive, mecanum and H-drive robots slide sideways on purpose, so they need tracking wheels.

---

## 16. Limits: what isn't modeled
- Robots don't pick up, carry or score pieces; mechanisms move but touch nothing.
- There are no other robots (a benchmark `push` disturbance stands in for a shove).
- The field is flat: no ramps, nothing to climb, no pitch or roll.
- The distance sensor is a ray (the real one has a cone of view), and its confidence is constant.
- Not simulated: ADI devices (outputs only remember what was written), the optical, vision and AI vision sensors, serial and radio links, the SD card, and touch input on the brain screen (LVGL runs headless).
- Compute time on the brain isn't charged, and precompiled ARM libraries other than LemLib can't run.
- Many physics parameters are estimates until you [calibrate](#11-calibrating-to-your-robot). Voltage-mode speed and thermal timing are the least certain; [docs/models.md](docs/models.md#calibrating-against-a-real-robot) lists experiments to measure them.

---

## 17. Developing vexsim
```
pytest          # every test (the C++ bridge tests skip without g++, unless VEXSIM_REQUIRE_CXX is set)
ruff check .    # lint
ruff format .   # format
```
CI (`.github/workflows/ci.yml`) runs on Windows (with MSYS2 g++) and Linux, with Python 3.11 and 3.13: lint, every test with the C++ bridge required, validation of every example config, and every example command, uploading the plots and telemetry as artifacts.

**Adding to vexsim:**
- *A model parameter:* add a field to the spec dataclass (`MotorSpec`, `OmniWheelSpec`, ...). It becomes an override key automatically. Document its source in `docs/models.md`.
- *A sensor type:* a config class in `config/robot.py`, a spec in `devices/specs.py` (in every preset), a device in `devices/devices.py`, the suite in `devices/suite.py`; for C++, the shim header, `runtime/devices.cpp`, and a reading line in `bridge/program.py`.
- *A PROS function:* declare it in the shim header under `vexsim/bridge/cpp/include/pros/`, implement it in `runtime/devices.cpp` or `scheduler.cpp`, and exercise it in `tests/cpp/bridge_test`.
- *A benchmark task or controller:* `bench/scenario.py` (the schema and `CONTROLLER_KINDS`) and `bench/trial.py`.
