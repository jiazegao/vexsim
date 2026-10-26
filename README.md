# vexsim

A VEX V5 robot mechanics simulator. It models:
- drive physics, including wheel slip and drift on omni wheels
- the V5 motor, including current limiting, heat and battery sag
- sensors and odometry, with realistic noise

It's built to test localization and motion-control algorithms, and to run unmodified PROS 4 and LemLib robot code.

**Status: Phases 1-8 of 10 are done**:
- configs and world loop
- V5 motor, thermal, battery and power models
- full-omni drivetrain and chassis, with drift, weight transfer and traction limits
- V5 sensors with realistic noise, and odometry baselines
- a PROS-style Python API, LemLib-style motions (PID, boomerang, pure pursuit, RAMSETE, motion profiles) and a live viewer you can drive with keyboard or gamepad
- Monte-Carlo benchmarks of localizers and controllers, with HTML reports
- unmodified PROS 4 C++ projects, compiled for your PC and run in lockstep with the physics
- LemLib projects, with LemLib built from source, `ASSET()` path files, and LemLib motions as benchmark controllers

Field wall collisions and more drivetrains come next in Phase 9. See [PLAN.md](PLAN.md) for the full roadmap and [docs/models.md](docs/models.md) for the physics, including the source of every parameter.

## Install

Requires Python 3.11 or newer.

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
The `viz` extra (matplotlib, pygame) is only needed for plots and the viewer.

Running C++ robot code also needs g++: MSYS2's MinGW-w64 (UCRT64) on Windows. `vexsim doctor` checks it and prints install steps; see [docs/cpp.md](docs/cpp.md#setup-once).

## Use

**Run a robot program in the live viewer** (or drive it yourself: leave out `--program`):
```
vexsim run examples/robots/full_omni_6m.yaml --program examples/programs/tour.py
```
![The viewer after the example tour](docs/img/viewer_tour.png)

Programs are Python generators against a PROS 4-style API, with LemLib-style chassis motions:
```python
from vexsim.api import delay


def autonomous(bot):
    yield from bot.chassis.move_to_point(30, 0)
    yield from bot.chassis.turn_to_heading(90)
    yield from bot.chassis.follow([(30, 0), (30, 30), (0, 40)], method="pure_pursuit")


def opcontrol(bot):
    while True:
        bot.chassis.arcade(
            bot.controller.get_analog("LEFT_Y"), bot.controller.get_analog("RIGHT_X")
        )
        yield delay(10)
```
See [docs/programming.md](docs/programming.md) for the API, every motion, viewer keys, and telemetry (`--record`, `vexsim plot`, `vexsim replay`).

**Run your PROS 4 project** unchanged: vexsim compiles it with g++ against its own PROS 4 headers and runs it in step with the physics:
```
vexsim doctor                                   # once: check the C++ toolchain
vexsim run examples/robots/full_omni_6m.yaml --program examples/pros_projects/minimal_pros4 --start 0,0,90
```
![The example PROS project driving a square](docs/img/cpp_square.png)
- **What runs:** your `initialize`, `autonomous` and `opcontrol`, plus every task the code starts, on motors, IMU, rotation and distance sensors and the controller, with `printf` and `pros::lcd` in the viewer.
- **Determinism:** simulated time only moves when every task is blocked, so runs repeat exactly.
- **Isolation:** a crash or an infinite loop ends the run with the task's name instead of taking the simulator down.

**LemLib projects** run unchanged too. vexsim fetches the LemLib version your `project.pros` lists and builds it from source; `ASSET()` path files work, and LemLib's pose shows in the viewer:
```
vexsim run examples/robots/lemlib_example.yaml --program examples/pros_projects/lemlib_template --start 0,0,90
```
![LemLib's example program in the simulator](docs/img/lemlib_template.png)

See [docs/cpp.md](docs/cpp.md) for setup, what's simulated, and the PROS 4 behaviors it reproduces.

**Benchmark algorithms**: run a scenario across many seeds for every localizer x controller, in parallel:
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
It writes `report.html` (self-contained), CSVs, charts and replayable worst cases. Plug in your own localizers and controllers by file, or a PROS project, such as LemLib's motions against the Python ones (`examples/scenarios/lemlib_vs_python.yaml`). See [docs/benchmarking.md](docs/benchmarking.md).

**Check a robot config** and see what the simulator will build from it:
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
  sensors     port 10  imu       at (0.0, 0.0) in, mount yaw 0 deg, noise default
              ...
Result: OK (0 error(s), 0 warning(s))
```
Exit codes: `0` means valid, `1` means there are errors. Add `--strict` to treat warnings as failures, and `-q` to print problems only.

**Motor curves**: measure the simulated V5 motor on a dynamometer:
```
vexsim motor-curves --cartridge blue --out blue.png     # torque / current / power vs. speed
vexsim motor-curves --cartridge red --csv               # the same data as CSV
```
![Simulated V5 motor curves, red cartridge](docs/img/motor_curves_red.png)

**Drift**: drive a fast arc and compare the true path with drive-encoder odometry:
```
vexsim drift examples/robots/full_omni_6m.yaml --left 1.0 --right 0.4 --out drift.png
```
![True path vs. drive-encoder odometry in a fast arc](docs/img/drift_arc.png)

**Odometry**: calibrate, drive a scripted path, and compare every localizer the robot's sensors allow:
```
vexsim odometry examples/robots/full_omni_6m.yaml --script aggressive --noise default --out odom.png
```
```
aggressive drive, default sensor noise, seed 0:
  drive encoders         final error  76.92 in   3.37 deg   worst  76.92 in
  drive encoders + IMU   final error  77.12 in   0.34 deg   worst  77.12 in
  tracking wheels + IMU  final error   1.65 in   0.34 deg   worst   1.65 in
```
![Odometry baselines on the aggressive drive](docs/img/odometry_aggressive.png)

**Writing a robot config**
- Copy `examples/robots/full_omni_6m.yaml`. Its comments explain every field.
- [docs/conventions.md](docs/conventions.md) covers frames, units, gear ratios and port rules.
- `overrides:` in the YAML tunes any model parameter, e.g. `motor.free_current_a: 0.2` or `battery.internal_resistance_ohm: 0.15`. [docs/models.md](docs/models.md) lists them.

**Using it from Python**
```python
from vexsim.config import load_robot
from vexsim.physics import World, PRIORITY_SENSOR

robot = load_robot("examples/robots/full_omni_6m.yaml")
world = World(seed=1)  # 1 ms physics step
world.every(10, lambda w: print(w.time), priority=PRIORITY_SENSOR)
world.run_for(0.05)
```

Drive a robot built from its config:
```python
from vexsim.config import load_robot
from vexsim.physics.robot import Robot

robot = Robot(load_robot("examples/robots/full_omni_6m.yaml"))
left, right = robot.group("left"), robot.group("right")
left.set_velocity(left.rated_speed)  # motor shaft rad/s; positive = forward
right.set_velocity(0.5 * right.rated_speed)
robot.run(2.0)  # or world.add_system(robot)
print(robot.pose, robot.body_velocity, robot.contacts.normal)
```

Read sensors and run your own localizer (readings use PROS units; see docs/conventions.md):
```python
from vexsim.algorithms.localization import Pose, baseline_localizers
from vexsim.config import load_robot
from vexsim.devices.suite import SensorSuite
from vexsim.physics import World
from vexsim.physics.robot import Robot

config = load_robot("examples/robots/full_omni_6m.yaml")
world = World(seed=1)
robot = world.add_system(Robot(config))
sensors = SensorSuite(robot, world.rng).attach(world)  # after the robot
world.run_for(2.1)  # IMU calibrates, robot still
odom = baseline_localizers(config)[-1]  # tracking wheels + IMU
odom.reset(Pose(0, 0, 0), sensors.frame(world.time))
world.every(10, lambda w: odom.update(sensors.frame(w.time)), priority=1)
robot.group("left").set_velocity(40)
robot.group("right").set_velocity(30)
world.run_for(2.0)
print(odom.pose, Pose.from_si(robot.pose))
```

Drive a single motor on a test rig:
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

## Develop
```
pytest          # tests (the C++ bridge tests are skipped if g++ is missing)
ruff check .    # lint
ruff format .   # format
```
CI runs on Windows (with MSYS2 g++) and Linux with Python 3.11 and 3.13 (`.github/workflows/ci.yml`).

## Layout
```
vexsim/
  config/    robot + field schemas, strict YAML loading, cross-field checks, summaries
  core/      integer-microsecond clock, deterministic event scheduler, named RNG streams
  physics/   world loop; V5 motor, thermal, battery, power; wheel contact, chassis, robot; overrides
  devices/   V5 sensors and motor encoders: sampling, latency, noise presets, PROS-unit frames
  algorithms/localization/  Localizer interface, arc odometry baselines, scripted runner
  algorithms/control/       PID, motion profiles, LemLib-style motions, pure pursuit, RAMSETE
  api/       PROS 4-style devices and a LemLib-style chassis for Python programs
  runtime/   simulation, competition phases, program coroutines, inputs, telemetry log
  bench/     scenarios, Monte-Carlo trials, metrics, parallel runner, HTML reports
  bridge/    PROS 4 shim headers and robot host runtime (C++), `vexsim build`, the host process
  viz/       live viewer (pygame); plots (motor curves, drift, odometry, telemetry)
  cli.py     `vexsim` command
examples/    robot and field configs, example Python program, PROS 4 and LemLib projects, scenarios
docs/        conventions, physics models and parameter sources, guides for Python programs, C++
             (PROS) code and benchmarking, and an example 100-seed benchmark report
tests/       including a C++ test project for the bridge (tests/cpp/)
```
