# VEX V5 Mechanics Simulator — Plan

**Status:** v1.2 (2026-10-27). Phases 1-10 complete; phase 11, a browser UI, in progress ([section 13](#13-browser-ui-phase-11)): 11.1 and 11.2 are done.

**v1.1:** Phase 7 runs robot code in a separate host process over pipes instead of a DLL loaded with `ctypes`, and compiles with g++ directly instead of CMake and Ninja. Sections 0, 2, 3 and 7 are updated.

## 0. Decisions
| Topic | Decision |
|---|---|
| Core language | Python ≥ 3.11 (physics, sensors, viz, benchmark harness) |
| Robot definition | Fully configurable YAML: every wheel (position, type, diameter, drop), gearing, ports, mass/CG, sensor placement |
| First drivetrain | Full-omni differential (tank). Other wheel types and layouts are config and parameter sets, not new code paths |
| Platform scope | VEX V5 only, 2D top-down |
| Robot code target | **PROS 4 + LemLib**, run with minimal or no source changes |
| User OS | **Windows** (primary), with Linux and macOS also supported |
| C++ toolchain on Windows | **MinGW-w64 GCC (MSYS2 UCRT64)**, chosen to match PROS's GCC family and `gnu++20` dialect. Clang is a secondary option |
| Python ⇄ C++ boundary | **A separate robot host process** (the compiled project plus vexsim's runtime) driven over pipes with a line protocol. Nothing has to match Python's compiler or ABI, and a crash in robot code can't take the simulator down |
| Algorithm testing | First-class: pluggable localization and control in Python or C++, seeded Monte-Carlo benchmarks |
| User interface | **A local browser app** (`vexsim ui`) with its own field renderer, replacing the terminal for everyday use. The CLI stays for scripts and CI; the pygame viewer stays too, for now. It listens on this computer only (no network viewing) |

## 1. Goals
1. Realistic drive physics: wheel slip, drift, turning scrub, weight transfer, omni vs. traction behavior.
2. Faithful V5 motor model: torque–speed curve, current limit, thermal fade, battery sag, cartridges, brake modes.
3. Realistic sensing, so odometry error behaves the way it does on a real robot.
4. Unchanged PROS 4 / LemLib projects build and run in the sim.
5. Localization and control algorithms compared under identical, seeded conditions.
6. Deterministic runs: the same seed gives the same result on the same machine. Usable for CI and parameter sweeps.

## 2. Tech stack
- **Python:**
  - `numpy` for math
  - `pydantic` + `PyYAML` for config schema and validation
  - `pygame` for the live viewer and gamepad input
  - `matplotlib` for plots
  - `pytest` for tests
- **C++:** C++20 / `gnu++20`, compiled directly with g++ by `vexsim build` (incremental, with `-MMD` dependency files; no CMake or Ninja needed).
- **Packaging:** `pyproject.toml`, installed with `pip install -e .`, with a `vexsim` console entry point.
- **CI:** GitHub Actions on `windows-latest` (MSYS2 UCRT64) and `ubuntu-latest`.

## 3. Architecture
```
vexsim/
  config/          YAML schemas (robot, field, scenario), loader, validation, unit conversion
  physics/
    motor.py       V5 11W motor: DC model, current limit, thermal, internal velocity/position PID, brake modes
    battery.py     voltage sag vs. total current
    wheel.py       contact model per wheel type (omni first; traction/mecanum later)
    chassis.py     2D rigid body + per-wheel normal loads (spring model)
    field.py       12'x12' perimeter, collisions
    world.py       fixed-step loop: 1 kHz physics, sensor/command scheduling, sim clock
  devices/         port-addressed devices (motor, rotation, IMU, distance, GPS)
                   with their noise / quantization / latency models and presets (specs.py)
  algorithms/
    localization/  Localizer interface + baselines
    control/       Controller interface + baselines
  bridge/
    cpp/include/   PROS 4 shim headers (api.h, pros/*.h/.hpp) + vexsim/sim.hpp hooks
    cpp/runtime/   PROS C API over a device table, lockstep task scheduler, competition task,
                   robot host protocol loop, crash and hang reports
    build.py       project staging, incremental g++ build, ASSET embedding
    lemlib.py      LemLib fetched and built from source
    host.py        robot host process and protocol
    program.py     CppProgram: a built project as a Simulation program
    doctor.py      toolchain check
  bench/           scenarios, metrics, Monte-Carlo runner (multiprocessing), HTML/CSV reports
  viz/             live top-down view, telemetry plots, replay, log export
  calibration/     fit model params from real robot logs (Phase 10)
  app/             services shared by the CLI and the UI: run specs, sessions, jobs, workspace
  ui/              the UI's server (FastAPI) and its built browser app (static/)
  cli/             vexsim run | build | doctor | bench | replay | validate-config | ui
frontend/          the browser app's source (React + TypeScript, built with Vite)
examples/
  robots/          full_omni_6m.yaml, ...
  scenarios/       straight_48in.yaml, s_curve.yaml, fast_turn_drift.yaml, ...
  pros_projects/   minimal_pros4/, lemlib_template/
tests/
```
Units: SI internally. The API, config and logs use VEX conventions (inches, degrees, rpm, mV), converted at the boundary.

## 4. Robot configuration (example: 6-motor full omni)
```yaml
version: 1
name: Example 6-motor full omni
body:
  mass_kg: 6.5
  inertia_kgm2: auto            # auto = uniform box from footprint; or explicit value
  footprint_in: [15, 15]
  cg_in: [0, 0, 3.5]            # x, y, height (height drives weight transfer)
  battery: v5_default

drivetrain:
  type: differential            # differential | xdrive | mecanum | hdrive
  wheels:                       # explicit per wheel → any omni/traction mix
    - {name: lf, pos_in: [ 5.5,  6.0], heading_deg: 0, type: omni, diameter_in: 3.25, drop_in: 0}
    - {name: lm, pos_in: [ 0.0,  6.0], heading_deg: 0, type: omni, diameter_in: 3.25, drop_in: 0}
    - {name: lb, pos_in: [-5.5,  6.0], heading_deg: 0, type: omni, diameter_in: 3.25, drop_in: 0}
    - {name: rf, pos_in: [ 5.5, -6.0], heading_deg: 0, type: omni, diameter_in: 3.25, drop_in: 0}
    - {name: rm, pos_in: [ 0.0, -6.0], heading_deg: 0, type: omni, diameter_in: 3.25, drop_in: 0}
    - {name: rb, pos_in: [-5.5, -6.0], heading_deg: 0, type: omni, diameter_in: 3.25, drop_in: 0}
  gearing:
    left:  {motors: [1, 2, 3],    cartridge: blue, ratio: "36:48", wheels: [lf, lm, lb]}
    right: {motors: [-4, -5, -6], cartridge: blue, ratio: "36:48", wheels: [rf, rm, rb]}

sensors:
  - {type: imu,      port: 10, pos_in: [0, 0], mount_yaw_deg: 0, noise: default}
  - {type: rotation, port: 11, reversed: false,
     tracking_wheel: {pos_in: [0, -1.5], heading_deg: 0,  diameter_in: 2.0}}
  - {type: rotation, port: 12, reversed: false,
     tracking_wheel: {pos_in: [-3, 0],  heading_deg: 90, diameter_in: 2.0}}
  - {type: distance, port: 13, pos_in: [7, 0], heading_deg: 0}

overrides:                      # optional per-run tweaks for sensitivity studies
  wheel.omni.lateral_mu: 0.08
```
Negative port numbers mean "reversed", matching PROS 4. These ports are what bind C++ code (`pros::MotorGroup left({1,2,3})`) to simulated hardware.

Configs are validated on load. Errors include duplicate ports, wheels assigned to no motor group, and sensors outside the footprint.

## 5. Physics models
### 5.1 V5 motor
- Electrical model: `V = I·R + kₑ·ω_motor`. Torque: `τ = kₜ·I − τ_friction(ω)`.
- The cartridge sets the output ratio. Constants are fit to VEX specs:
  - output free speed of 100, 200 or 600 rpm, depending on the cartridge
  - about 2.1 N·m stall torque on the red cartridge, scaled for the others
  - 2.5 A current limit
- The electrical time constant is neglected, which is valid at 1 kHz.
- Command modes, matching PROS 4:
  - `move` / `move_voltage`: ±127 / ±12000 mV
  - `move_velocity`: modeled internal velocity PID, with its own update rate
  - `move_absolute` / `move_relative`: modeled internal position controller
- Brake modes: coast, brake and hold.
- Thermal: a lumped two-node model (winding → case → ambient). The current limit derates in steps as temperature rises, and the PROS temperature and over-temp flags are reported.
- Battery: 12.8 V nominal with internal resistance. Total current makes the voltage sag, and every motor's available voltage drops with it.

### 5.2 Wheel and ground contact (the source of drift)
- For each wheel, compute the contact-patch velocity in the wheel frame, split into longitudinal slip (`ω·r − v_long`) and lateral velocity.
- Friction uses a smoothed Coulomb/brush model inside a friction ellipse: `|F| ≤ μ·N`.
- Wheel types are parameter sets:
  - **Omni:** high longitudinal μ. Lateral motion is resisted only by roller rolling friction plus a small saturating side force.
  - **Traction:** one isotropic friction circle for slip and sideways sliding (Phase 9).
  - **Mecanum:** grip along the ground rollers' axis, free across it, with the rollers at a configured angle, usually ±45° (Phase 9).
- Drift appears on its own when lateral demand exceeds the friction limit. A fast turn on full omni slides outward and corrupts heading and odometry the way it does on a real robot.

### 5.3 Chassis
- A 2D rigid body with states (x, y, θ, vx, vy, ω).
- Each wheel has a stiff vertical spring to set its normal load. This handles weight transfer from acceleration (using CG height) and drop-center layouts without special cases.
- Drivetrain friction losses and rolling resistance.

### 5.4 Integration and field
- Semi-implicit Euler at 1 kHz, with adaptive substeps when friction gets stiff. A seeded RNG drives all noise.
- Field: the 12'×12' perimeter. The robot footprint collides with walls (impulse-based, with restitution and friction). Game elements (Phase 10): fixed obstacles and movable pieces from the field config.

## 6. Sensors
| Sensor | Model |
|---|---|
| Motor encoder | Quantized, 10 ms update. Follows wheel rotation, not robot travel, so slip corrupts it |
| Rotation (tracking wheel) | 0.01° resolution, configurable data rate. Diameter and mount offset errors, small scrub, optional lift-off events |
| IMU | Calibration period, heading bias drift, white noise, scale-factor error, mount yaw offset |
| Distance | Ray-cast against the walls, range-dependent noise, maximum range, invalid readings out of range |
| GPS | Phase 10: position and heading from the perimeter code strip when the camera sees it, range-dependent noise, latency, dead-reckoned heading without a fix |
| Controller | Gamepad (Xbox mapped to V5 layout), keyboard fallback, or scripted input file |

Every sensor has an update period and a latency. Noise profiles are named presets (`ideal`, `default`, `harsh`) and can be overridden per parameter.

## 7. Running PROS 4 + LemLib code
### 7.1 Approach
The robot code is compiled, not interpreted.
- The user's project is compiled with host GCC (MinGW-w64 on Windows) against **vexsim shim headers** that replace the PROS 4 SDK.
- The result is linked with vexsim's runtime into a small executable, `robot_host`. The simulator runs it as a child process and steps it over pipes.

```
 PROS 4 project (src/, include/main.h, static/, project.pros) — unchanged
        │
        ▼  vexsim build <project>
 staging dir: src/ + include/ minus the SDK (include/api.h, include/pros/, include/liblvgl/)
   + vexsim shim headers (api.h, pros/*.h, pros/*.hpp)
   + LemLib built from source, static/ → ASSET data
        │  g++ -std=gnu++20, incremental → robot_host[.exe] (static on Windows)
        ▼
 robot host process: PROS C API + lockstep scheduler + protocol loop
        │  pipes: readings + RUN <t>  →  ←  motor commands, console, W <next wake>
        ▼
 Python world (physics, sensors, viz, bench)
```

### 7.2 Key components
1. **PROS 4 API shim.** Header-compatible reimplementations of the classes and functions PROS 4 and LemLib use:
   - Devices: `pros::Motor`, `MotorGroup`, `Imu`, `Rotation`, `Distance`, `Controller`
   - Tasks and timing: `Task`, `Mutex`, `delay`, `Task::delay_until`, `millis`, `micros`
   - Screen: `pros::lcd` (llemu)
   - Matching C-API functions where LemLib calls them

   Each call reads or writes a port-indexed device table. Unsupported pieces (LVGL, SD card, VEXlink, serial) become stubs. Calling one logs a one-time warning.
2. **Project staging.** On Windows (and elsewhere), a quoted `#include "api.h"` finds the project's own copy first, because the including file's directory is searched before `-I` paths. So `vexsim build` copies the project into a staging directory without `include/pros/`, `include/api.h` or `firmware/`, then compiles there. Your source tree is never modified.
3. **LemLib from source.** PROS templates ship LemLib as a precompiled **ARM** `.a`, which can't run on a PC. `vexsim build` reads the LemLib version from `project.pros`, fetches the matching LemLib source tag (git, else a zip; cached; `VEXSIM_LEMLIB_SOURCE` for offline use), and compiles it with the shim once per version. The template's own files (each template's `system_files` in `project.pros`) are left out of staging. The first target is the LemLib 0.5.x line for PROS 4. Newer releases are validated as they come out.
4. **`ASSET()` paths.** On the V5, objcopy embeds `static/` files as linker symbols, including a `_size` symbol whose *address* is the size, which a PC's relocatable executables can't express. vexsim ships its own `lemlib/asset.hpp` and generates a C++ file with each file's bytes and size, so `ASSET(path_txt)` and `chassis.follow(...)` work without changes.
5. **Lockstep scheduler** (deterministic simulated time):
   - Each PROS task is a host `std::thread` (MinGW UCRT64 uses the posix thread model), but only one runs at a time under baton passing. This matches FreeRTOS on the V5 user core.
   - `delay` and `delay_until` park the task until its wake time. Mutex waits park it until the mutex is free.
   - `RUN <t>` returns once all tasks are parked. Python then advances physics to the next wake time, sends the sensor values that changed, and runs it again.
   - Ready tasks resume in a fixed order (priority first, then the order they became ready), and a task that readies a higher-priority one is switched out at once, so identical inputs give identical runs at any speed.
   - Busy waits: a task making PROS calls without parking is charged 1 ms per 1000 calls, so polling loops advance time. A task that runs for a configurable wall-clock budget without any PROS call is reported, with its task name.
6. **Competition harness.** The sim calls `initialize()`, `autonomous()`, `opcontrol()` and `disabled()` as a field controller would, in the PROS competition task: a mode change deletes that task and starts the next, while user tasks keep running. Competition status bits match the mode (switch, field control, or none), and a disabled robot ignores motor commands. It supports a skills or match timeline and autonomous-only runs.
7. **Console and screen.** `printf` / `std::cout` and `pros::lcd` lines appear in a panel in the viewer and in the run log.
8. **Pose telemetry.** Ground truth always comes from the sim.
   - The robot's own estimate is read automatically from LemLib's odometry pose accessor (`lemlib::getPose()`, once its odometry task runs), through a hook the build generates.
   - Custom odometry can call `vexsim::report_pose(x, y, θ)` from `vexsim/sim.hpp`. On the real robot, `__has_include` guards make that call compile to nothing.
9. **Windows specifics:**
   - `robot_host.exe` is linked statically, so it needs no MinGW DLLs. Windows locks a running executable; a rebuild while the viewer is open links to a new name.
   - `vexsim doctor` checks for MSYS2 UCRT64 g++ (version, target, thread model), builds and runs a test program, and prints exact install steps if anything is missing.
   - Build outputs go to `%LOCALAPPDATA%\vexsim\build\<project>-<hash>`.
10. **Crash isolation.** A crash in user code (for example a null-pointer access) must not take the GUI down silently.
    - The robot code runs in a separate **robot host process**, which talks to the physics over pipes, only at the times a task needs to run.
    - A crash or uncaught exception ends the run with the task's name, the cause and the last console lines.
    - Monte-Carlo trials already run in worker processes.

### 7.3 Expected adjustments
- **No changes:** typical PROS 4 / LemLib code, meaning motors, motor groups, sensors, tasks, controller input, LemLib chassis/odometry/PID/motion and path following with `ASSET`.
- **Stubs or small edits:**
  - LVGL / brain-screen UIs (they run headless against a stand-in; nobody taps the screen, so pick routines by environment variable)
  - wall-clock timing (`std::chrono`): use `pros::millis()`/`micros()`
  - other precompiled ARM libraries (they must be rebuilt from source)
  - inline ARM assembly
  - code that assumes `sizeof(long) == 4` (it's 8 on 64-bit Linux) or that pointers fit in an `int` (they're 8 bytes on a PC)
  - logic that depends on how long its own computation takes (the sim doesn't charge for compute time, only for PROS calls in busy loops)
- **Not supported:** the PROS 3 API (v1 targets PROS 4 only).

## 8. Algorithm testing
### 8.1 Interfaces (Python)
```python
class Localizer(Protocol):
    def reset(self, pose: Pose, frame: SensorFrame) -> None: ...  # frame = zero point
    def update(self, frame: SensorFrame) -> Pose: ...  # called at sensor rate


class Controller(Protocol):  # one-shot: the target is given to the constructor
    def step(self, est: Pose, frame: SensorFrame, dt: float) -> DriveCommand: ...
    def done(self) -> bool: ...
```
Python algorithms use the same device and port model as C++. A C++ algorithm runs through the bridge, and the bench scores both the same way.

### 8.2 Scenarios (YAML)
- start pose
- target, waypoint list or path file
- disturbances (a timed bump impulse, wheel lift-off, IMU bias step, battery level)
- noise preset
- time limit
- the algorithm(s) under test

### 8.3 Metrics
- final position and heading error
- RMS and max path-tracking error
- completion and settle time
- overshoot
- localization error over time (estimate vs. truth) and how fast it grows per meter
- energy used, peak motor temperature, wall contacts

### 8.4 Runner and reports
- `vexsim bench scenario.yaml --algos a,b --seeds 100` runs trials in parallel worker processes.
- Outputs:
  - a summary table (mean, p95)
  - error-distribution plots
  - worst-case replays
  - a self-contained HTML report and CSV

### 8.5 Built-in baselines
- **Localization:**
  - drive-encoder odometry
  - 2- and 3-tracking-wheel arc odometry
  - tracking wheels with IMU heading
  - wall resets with the distance sensor (later: MCL)
- **Control:**
  - PID drive and turn
  - motion-profiled PID (trapezoid and S-curve)
  - pure pursuit, boomerang, RAMSETE

## 9. Visualization
- **Live pygame view:**
  - the field, true pose, and the estimated-pose "ghost"
  - path trail, wheel force vectors and slip indicators
  - motor current and temperature bars
  - console panel
  - pause, step and speed controls (0.1× to max)
- matplotlib telemetry plots, replay from logs, and CSV/Parquet export.
- Headless mode for CI and benchmarks.

## 10. Validation and acceptance tests
| Area | Test |
|---|---|
| Motor | Free speed and stall torque within 3% of the fitted spec. Linear torque–speed curve. Current clamps at the limit |
| Thermal | A sustained stall heats the motor, current derates, and output drops over time |
| Battery | A load step gives the expected sag. Free speed drops at low charge |
| Drive | Top speed ≈ wheel rpm × circumference, minus losses. Acceleration is limited by current and traction |
| Drift | A full-omni high-speed turn shows measurable lateral slide. Lowering omni lateral μ increases drift monotonically |
| Odometry | Drive-encoder odometry collects slip error in drift scenarios. 3-wheel tracking odometry stays within tolerance |
| Determinism | Same seed → identical logs on the same machine (Python-only and bridge runs) |
| Bridge | `minimal_pros4` and `lemlib_template` build on Windows (MSYS2) and Linux CI and run an autonomous route **with no source changes**. LemLib's pose matches sim truth within the expected odometry error |
| Scheduler | Multi-task programs with mutexes are deterministic. A busy-wait is detected and reported |

## 11. Phases and deliverables
| # | Phase | Done when |
|---|---|---|
| 1 | **[done]** Scaffolding: package layout, config schema and loader, world loop, sim clock, RNG, CLI skeleton, CI (Windows + Linux) | `vexsim validate-config` works on the example robot; CI is green |
| 2 | **[done]** Motor and battery models | Motor, thermal and battery tests pass; torque–speed plot generated |
| 3 | **[done]** Chassis and omni wheel contact (full-omni tank) | Drive and drift tests pass |
| 4 | **[done]** Device registry and sensors; Python odometry baselines | Odometry tests pass; noise presets in place |
| 5 | **[done]** Python control API and baseline controllers; live viewer and plots | Drive a scenario from the keyboard/gamepad and run a Python autonomous route visually |
| 6 | **[done]** Benchmark harness | 100-seed comparison of two localizers and two controllers produces an HTML report |
| 7 | **[done]** C++ bridge: PROS 4 shim, lockstep scheduler, robot host process over pipes, `vexsim build` and `vexsim doctor` | `minimal_pros4` runs unchanged on Windows and Linux; scheduler tests pass |
| 8 | **[done]** LemLib: build from source, `ASSET` embedding, pose readback | `lemlib_template` autonomous (moveToPoint, turnToHeading, follow) runs unchanged; C++ algorithms run in the bench |
| 9 | **[done]** Field wall collisions; traction, mecanum, X-drive and H-drive models and layouts | Collision and new drivetrain tests pass |
| 10 | **[done]** Calibration from real robot logs; game elements; GPS sensor | Fitted parameters reproduce a recorded run within tolerance |
| port | **[done]** First real team port (1239E 2026-27): mechanisms, element and beam heights, an LVGL stand-in, edited LemLib headers, `--env` | All nine routines run; RCL and MCL evaluated against the truth ([docs/porting_1239e.md](docs/porting_1239e.md)) |
| 11.1 | **[done]** UI foundations: service layer (run specs, sessions, jobs, workspace) with the CLI on it; server and protocol; app shell with its own field renderer; `vexsim ui`; frontend build in CI | `vexsim ui` lists a workspace and runs a simulation; all existing tests pass |
| 11.2 | **[done]** Simulate view: parity with `vexsim run` and the pygame viewer | 1239E Left 40 runs, and `full_omni_6m` drives by keyboard and gamepad, from the UI; drag-to-start works; build errors are clickable |
| 11.3 | **[done]** Timeline, plots, run history, replay, compare, export | Scrub a finished run, reopen an old one, overlay two |
| 11.4 | **[done]** Robot and field editors | Drag a sensor in `1239e_2026-27.yaml`: the number changes and its comments survive |
| 11.5 | **[done]** Bench, Calibrate, Analyze, Sweeps pages | Every remaining command has a page; the 1239E evaluation runs as a sweep |
| 11.6 | **[done]** Real-robot logs and debug drawing | An MCL log plays beside its replay; robot code can draw on the field (`vexsim::draw_*`) |
| 11.7 | **[done]** Desktop window and shortcut, a VS Code panel | `vexsim ui --window` opens the app in a window of its own, which stops the server when closed; `vexsim shortcut` puts it in the Start menu (Windows) or the applications menu (Linux); `vexsim vscode` installs a VS Code panel that runs it beside the code, its file links opening in VS Code |
| 12.1 | **[done]** Pick a PROS project's autonomous routine in the app | 1239E's nine routines are listed; picking `right30` runs it inside `autonomous()` from its `setPose`, with the project unchanged (Linux and Windows CI) |
| 12.2 | **[done]** Robot outlines: rectangles, circles and outlines as the robot's shape | A robot made of a rectangle, a circle and an outline hits walls, a goal and pieces by its shape; all existing tests pass unchanged |
| 12.3 | **[done]** Design view: draw a robot, fill in its motors and sensors (**New robot…**) | From **New robot…**: draw a robot, give it a 6-motor drive, an IMU and a distance sensor, save it and drive it without opening the YAML; its comments survive edits |
| 13.1 | **[done]** Routes and their runner: route files, the team's functions read from its headers, a route run in the simulator straight from its file, each step's endpoint reported | A route for 1239E's project (LemLib motions, a pause, the team's `moveForward` and `startFrontIntake`) runs with the project unchanged and reports where each step ended; a changed step reruns without a rebuild |
| 13.2 | **[done]** The autonomous maker: a route's steps beside the field, planned endpoints drawn as you edit, simulated ones a moment later | Build a route from scratch in the app (motions, turns, a pause, the team's functions); dragging an endpoint moves its planned pose at once and its simulated one within seconds; the route's comments survive the edits |
| 13.3 | **[done]** Export into the PROS project | Export a route: the project builds, the routine list shows it, and run from there it ends each step where the maker's run did (within 0.25 in); exporting again changes nothing |
| 13.4 | **[done]** vexsim's own motions, beyond LemLib's: RAMSETE and `moveArc` | A route with a RAMSETE trajectory and an arc runs in the simulator and exported, its planned trajectory drawn whole |
| 14.1 | **[done]** vexsim's logger: every device it finds, the code's own poses, numbered files on the SD card | In a project, it logs every device and the code's poses and marks, to the card on the robot or to `--sd` in the simulator; a simulated run's log matches vexsim's own `--robot-log` of it; old and new logs both read |
| 14.2 | **[done]** 1239E's project on vexsim's logger, its MCL log removed | No MCL logging is left; each routine's log has LemLib's and MCL's poses; all nine routines still run; `--follow` takes a robot log |
| 14.3 | **[done]** The calibration program, in a slot of its own, its driving tests planned around the field's elements | For 1239E's robot and field, every test runs in the simulator from the program's menu by scripted button presses, each driving test clear of every element by its margin; a press stops the motors at once; the device check catches a reversed motor and two swapped distance sensors |
| 14.4 | **[done]** Collect a session and fit it | From simulated "real" robots with hidden changes (1239E's, and `full_omni_6m` with two tracking wheels), the tools recover each value within its tolerance, a held-out run matches within the sensors' noise, and `--apply` writes the robot config with its comments kept |
| 14.5 | **[done]** The autonomous check: the real routine against the simulated one | 1239E's Left 40 on a simulated "real" robot passes with the calibrated config and fails with the default one, at pass marks the team sets |
| 14.6 | **[done]** The calibration guide, for students | `docs/calibration_guide.md` takes a student from an uncalibrated robot to a checked autonomous, every command written out, its pictures made from 1239E's robot and field |
| 14.7 | **[done]** The Calibrate page | A whole session runs in the app, and a robot log plays on the field beside its simulated run |
| 15.1 | **[done]** The simulator's quick wins: no drawings where nobody watches, no collision checks while nothing is in reach, smooth pacing at speeds the computer can't reach | A headless 1239E Left 40 runs at least 15% faster, its results the same to the last digit; asked for 8×, the app still shows 50 frames a second or more |
| 15.2 | **[done]** The field gets the screen: one header row, a run bar that folds to a line, panels that fold away, the key as a pop-up, layouts for short and narrow windows; the field drawn only when it changes | At 1366 × 768 the field is at least 500 px square during a run and 450 after it (330 and 250 before); at 1024 × 700 nothing overlaps or is cut off; an idle page draws nothing |
| 15.3 | **[done]** Nothing stale: Restart runs the code as it is now, the workspace list follows the disk, run-on-save, and the address keeps your place | After an edit, Restart runs the new code; a new file is listed without *Refresh*; with run-on-save, a save reruns within about 5 s; reload, Back and Forward return to the same page, session and run |
| 15.4 | **[done]** A way in: a first-run panel in an empty folder, a starter program, the guides in the app, the Calibrate session's steps with their state | From an empty folder a student makes a robot, drives it and runs a first program without leaving the app; each Calibrate step says done, next or to do, and links to its section of the guide |
| 15.5 | **[done]** Accessibility: readable grey text, a keyboard path, the right roles, an audit in the browser tests | No serious or critical axe finding on any page, light or dark; *Run* is two key presses from the top with the skip link, and at most 12 Tab presses without it (83 before) |
| 15.6 | **[done]** What the server sends, checked; drawings packed; a reload mid-run keeps the code's drawings | Every endpoint's response is checked against its protocol model in the tests; a run whose code draws MCL's particles records at least 40% fewer bytes a second; a page reloaded mid-run shows the drawings |
| 15.7 | **[done]** The big files split by feature: `App.tsx`, `server.py`, `protocol.py`, `cli.py` | None of the four is over about 600 lines; every test passes unchanged; the generated `protocol.ts` is the same, byte for byte |
| 16.1 | **[done]** The physics step, compiled ([section 18](#18-the-physics-step-compiled-phase-16)): the wheels' loads, the motors, the mechanisms, the contact, the solve and the battery in C, built with the toolchain vexsim finds, the robot's state shared with it; the Python step stays the model | With the compiled step every existing test passes unchanged; from the same state the two steps agree on every number to 1 part in 10⁹, and whole runs to a nanometre; a Python program's run is at least 2.5× faster and 1239E's Left 40 at least 1.5×; without a compiler everything runs as before |
| 16.2 | **[done]** The rest of a millisecond: what Python still does every step (sensors, events, the loop), trimmed without changing a number | A Python program's run at least 3× faster than before the phase and Left 40 at least 1.7×, with results the same as 16.1's to the last bit |
| 16.3 | **[done]** Where it shows: run records and the app say which step ran; the step built in the background when `vexsim ui` starts | A recorded run says which step made it; the first run after installing doesn't wait for the build |
| port 2 | **[done]** 1239E's six-bar robot, from the team's `six-bar` branch: its code as a project of its own with the first port's edits merged in, a robot and a field for it, saved runs and a sweep | Its three routines run to the end; the robot has every device the code uses, where the code says; RCL and MCL evaluated against the truth ([its README](examples/pros_projects/1239e_six_bar/README.md)) |
| 17.1 | **[done]** The 5.5 W motor in the model and the configs ([section 19](#19-the-55-w-motor-phase-17)): its own numbers, an 8 V drive, mixed groups, the compiled step, `cartridge: 5.5w` | On vexsim's dynamometer the 5.5 W motor gives the numbers it was fitted to; a mixed drive's 5.5 W motors turn at the speed their gearing says and share the load; the two physics steps agree on it; no number of a robot without one changes |
| 17.2 | **[done]** Robot code and the app see it: the motor's type, its fixed gearing, the Design view, the editor, the Analyze page, the motor budget | A PROS program reads `E_MOTOR_TYPE_EXP` for a 5.5 W motor and can't change its gearing; a robot with 5.5 W motors is made and driven from the Design view |
| 17.3 | 1239E's six-bar robot with its 5.5 W motors; a calibration session's free spin with them | Its routines run with them; its README's numbers are its sweep's again; the free spin fits the 11 W motors without the 5.5 W ones |

## 12. Risks and mitigations
| Risk | Mitigation |
|---|---|
| Physics parameters (μ, roller friction, motor constants) differ from real hardware | Conservative presets from specs; sensitivity overrides; Phase 10 fits them to real logs |
| Stiff friction makes the integration unstable | Smoothed friction curves, adaptive substeps, energy and stability tests |
| LemLib internals change between versions | Pin and test against specific tags; build version detected from `project.pros` |
| Shim API gaps | Coverage driven by LemLib plus the example projects; missing calls fail at compile time with a clear "not yet supported" message |
| Windows toolchain setup friction | `vexsim doctor` with exact MSYS2 install commands; CI on `windows-latest` |
| Python is too slow for large Monte-Carlo sweeps | Vectorize per-wheel math with numpy; parallel workers; numba as an optional speedup |
| Development and validation happen on Linux, but you're on Windows | Windows CI job on every change, plus a hands-on check on your machine at the end of Phases 7 and 8 |

## 13. Browser UI (phase 11)
`vexsim ui [folder]` starts a small server on this computer and opens the browser on the app. Everything the commands and the pygame viewer do becomes clicks: run configurations instead of command lines, the robot dragged to its start, a timeline to scrub, editors that mark errors at the line, and pages for building, benchmarking and calibrating.

**Decisions** (2026-10-27): browser-based; the browser draws the field itself (canvas), separately from the pygame viewer, which stays for now; the server listens on 127.0.0.1 only, with no network viewing; after the simulate view, the pages come in the order of the phases below.

```
browser (React + TypeScript)      <-- HTTP -->   vexsim ui server (FastAPI)
  field canvas, plots, editors    <-- WS ---->   workspace, configs, runs, jobs
                                                    |
                 sim worker process (one per live run)    job processes
                 Simulation + program (+ C++ robot host)  build, bench, calibrate, sweeps
```
- **Service layer (`vexsim/app/`), shared by the CLI and the UI.** `RunSpec` holds everything `vexsim run` takes and converts to and from its arguments, so the UI can copy a run as a command. `Session` runs one simulation; `Jobs` runs long tasks (builds first) with progress and cancel; `Workspace` finds the robots, fields, programs, PROS projects, scenarios, inputs and logs in a folder.
- **Each live simulation runs in its own process.** A hung program or a crashed C++ host can't freeze the UI, and environment variables don't leak between runs. The worker paces simulated time (real time x speed) and sends about 60 frames a second.
- **Protocol:** JSON over a WebSocket per session, plus REST for the rest. Message types are pydantic models in `vexsim/ui/protocol/` (one file until phase 15.7); `frontend/src/protocol.ts` is generated from them, and a test fails if it is stale.
- **Builds** of a PROS project run as jobs, one at a time per project, and a session waits for its project's build. Compiler errors and Python tracebacks become `file:line` links that open in VS Code (`vscode://file/...`).
- **Saved runs** are named run specs in the workspace's `.vexsim/launch.yaml` (start pose and environment included), so a team commits them with its code; this repository's cover its examples and every 1239E routine.
- **Driving:** the page sends the virtual controller (keyboard as in the pygame viewer, the browser's Gamepad API, an on-screen controller) to the run's worker whenever it changes; frames carry what the robot's controller reads.
- **Run history:** every run is recorded when it ends (finished, stopped, restarted or failed) in the workspace's `.vexsim/runs/<id>/`: its spec and how it ended, a tape (a frame every 50 ms of simulated time) to scrub, its 10 ms telemetry, console and SD card. The newest 50 stay, plus any marked kept. A finished run's recording replaces it on the field, with a timeline; older runs, and telemetry logs from the workspace, open from lists. Compared runs are drawn over it in grey, each in its own dashes and labelled with its name, since the field's hues are all taken; the plots (uPlot) draw one unit per chart and share a crosshair. Exports: telemetry as CSV, the field as PNG, or a WebM video recorded from the canvas.
- **Config editors:** a robot or field config opens in a tab: YAML (CodeMirror, loaded only when an editor first opens) beside a diagram drawn from it. The text stays the source of truth. The server checks it as it's typed and maps each issue's dotted path to its line through PyYAML's node positions (`yaml.compose`). A drag on the diagram sends the new numbers, and the server rewrites just those scalars in place, so comments, layout and untouched values survive; values reached through anchors, aliases or merge keys are refused. Saves keep the file's line endings and are refused if the file changed on disk since it was opened.
- **Jobs and their pages:** benchmarks, sweeps, calibration fits, analyses and builds are jobs of their kind (`JOB_KINDS`), each in its own process with its own worker pool, whose workers exit when their parent does, so *Cancel* stops all of it. A job reports log lines, progress and the parts of its result that come early (a sweep's finished trials), which its page polls for. What lasts is written to the workspace's `.vexsim/bench/`, `sweeps/` and `calibrations/` (a folder per result, the newest 20 of each), and listed on each page. A benchmark's worst cases play back on the field; a calibration's fitted values go into the robot's config through its editor, written in place.
- **Sweeps:** saved runs × variations (values of environment variables) × seeds, with a hand's placement error, measured by the robot code's pose error while its program runs; kept in `.vexsim/sweeps.yaml`. The 1239E evaluation is two of them, and gives `evaluate_1239e.py`'s numbers exactly. A trial reopens by running again: runs are deterministic.
- **Debug drawing:** robot code draws on the field in named layers: `vexsim::draw_*` in C++ (`sim.hpp`; a `D` line per shape to the host, LemLib's angles), `bot.draw` in Python. A layer keeps its shapes until it's cleared, so code clears and redraws it. Shapes are lists (point, line, circle, ellipse, pose, text) colored from the field's palette by name, so they follow the themes. The worker sends the layers when they change, tapes keep them as events (at most every 50 ms, thinned past 2 million shapes), and the key shows and hides each layer.
- **Real robots' logs:** `vexsim/mcllog.py` reads MCL logs in 1239E's format (blocks told apart by how many numbers a line has, so any number of sensors and particles), and the server sends one as a tape of drawings (rays, particles, 2-sigma spread) and its estimate, without truth. A run can follow a log (`RunSpec.follow`, `vexsim run --follow`): a virtual driver (`runtime/follow.py`, from `replay_1239e_mcl_log.py`) drives the logged path through the program's sticks and inverted drive curve, starting where the log does (`VEXSIM_START` for C++ code), and the run ends with the log. A saved run with `follow` and no log replays whichever log the app is given. The log plays beside the run on one timeline, its first update at the moment the replay began following it (recorded as `follow_start`), or where another run's program began, adjustable. The repository's logs are simulated ones (`examples/logs/left40_simulated.1239e`); the team's real logs stay out of it.
- **On the desktop and in VS Code:** `vexsim ui --window` opens the app in a browser's app mode (Edge, which every Windows has, else Chrome, Chromium or Brave; `$VEXSIM_BROWSER`) on a profile of its own: a window with no tabs or address bar. Each page holds a presence WebSocket, and a server started for a window stops once its last page has been closed for 10 s (a reload is no close), or if none opens within 2 minutes. `vexsim shortcut` makes shortcuts that run `vexsim ui FOLDER --window` with this Python: `.lnk` files in the Start menu and on the desktop on Windows (through the Windows shell, run with pythonw, whose output goes to a log file; console programs it starts get no window of their own), a desktop entry on Linux, an app in `~/Applications` on macOS. `vexsim vscode` packs the extension in `vexsim/ui/vscode` (plain JavaScript, type-checked against VS Code's API) into a `.vsix` and installs it with VS Code's command line. The extension runs `vexsim ui FOLDER` and shows the app in a panel's frame; the page knows it's framed (`?embed=vscode`) and sends what it can't do there to VS Code through `postMessage`: file links open in the editor, files are saved through VS Code's save dialog, reports open in the browser, and the colors follow VS Code's theme.
- **Safety:** the server can build and run code, so it binds to 127.0.0.1, requires a random token (from the URL `vexsim ui` opens, then kept in a cookie, and sent with each request as a bearer token: a framed page gets no cookie), checks the Host and Origin headers, and serves and writes only files inside the workspace. Only the app's own scripts, styles and icons are served without the token.
- **Packaging:** `pip install -e ".[ui]"`. The built app is committed under `vexsim/ui/static/`, so users need no Node.js; CI rebuilds it and fails if the committed copy is stale. Every asset is local, so the UI works offline.
- **Tests:** pytest for the services and the server (including WebSockets), Vitest for the frontend's logic, Playwright end to end (Ubuntu CI), including the app framed by another site's page and the VS Code panel's page, and the extension installed in a real VS Code (Ubuntu and Windows CI).

## 14. Routines and robot design (phase 12)
**Decisions** (2026-10-27): a picked routine runs *inside* the project's `autonomous()`, which keeps its setup; a drawn shape is what the robot collides with; new and existing robots share one editor, its Design view and its YAML kept in step; the outline tool draws closed outlines.

- **Routines (12.1):** the routines are the functions in a PROS project's `include/custom/auton.hpp` that take no arguments (in any namespace); the run bar lists them, and picking one fills the start pose from its `setPose(x, y, θ)` (LemLib's convention). The project is never changed: in vexsim's build cache, the files that define the routines are compiled with each routine under an internal name (an `asm` label in a force-included header), so calls among them stay as they are, and a generated file takes the routines' own names: each runs the routine it names, except that the first call made while `VEXSIM_ROUTINE` names a routine runs that one instead, and says so on the console. So `autonomous()` runs as written, setup included, and whatever routine it picks becomes the one picked in the app; if it never calls one, the run says the pick didn't run. `RunSpec.routine` (`vexsim run --routine`, `routine:` in saved runs) carries the pick, and `vexsim routines PROJECT` lists them.
- **Robot outlines (12.2):** `body.shape`, instead of `footprint_in`: rectangles, circles and closed outlines (inches, robot frame, placed around the origin). `vexsim/geometry.py` finds the union's outside edge exactly, as segments and arcs; only that edge touches walls, goals and pieces, and a circle in a notch touches both of its sides. Inertia `auto` comes from its area; wheels, sensors and the CG must lie inside it and it must fit the 18 in limit. The field view (an arrow marks the front), the editor's diagram, the pygame viewer and the start check use the shape. A robot with `footprint_in` keeps today's rectangle code exactly, and a shape of one rectangle moves as it does (to 1e-12 m). Example: `examples/robots/shaped_6m.yaml`.
- **Design view (12.3):** **New robot…** in the robot list creates a config (blank, a template, or a copy of a robot) and opens it in the robot editor's Design view: rectangle, circle and outline tools with snapping, mirroring and exact numbers; wheels, sensors and the CG dragged into place; forms for the body, drive and motor groups, mechanisms and sensors; a port map. Its edits are in-place edits of the YAML, as the diagram's are, which learn to write words and to add and remove list items in their neighbours' style, so comments survive.
  - *As built:* `vexsim/app/yamledit.py` makes the changes (`set` any value, adding a missing key; `add` a list item; `remove` an item or a key with its lines; `rename` a key): new text copies its neighbours' style (flow items among flow items, block among block, the indentation), an empty `[]` or `{}` opens into a block with its comment where it was (and closes again), a word is quoted only if it wouldn't read back as itself (`"36:48"`), and values reached through anchors, aliases or merges are refused, as for drags. `vexsim/app/newrobot.py` writes the template (a 15 × 15 in rectangle on one of five drives: 4- and 6-motor tank, X-drive, mecanum, H-drive; with comments that say what each section is) and the presets: wheels placed on the robot's biggest part and drawn in until each is 0.5 in inside its edge, motors on ports nothing else uses. The server adds `POST /api/config/new` (never over a file) and `/api/config/drive`, and `/api/config/patch` takes the changes. In the app, a change that would leave the YAML unreadable isn't made (the editor says why), changes are made one after another, and the YAML editor stays open behind the Design view, so one undo history covers both. A tank drive's `left` and `right` motor groups keep their names (the checks require them).
  - *Since:* Ctrl+C and Ctrl+V on a robot's diagram copy the selected wheel, sensor or part of the shape and paste copies a step along (a wheel's under the next free name, in its motor groups; a sensor's on a free port), into that robot or another open in the app; each paste is worked out in its turn in the editor's queue, from the robot the ones before it left. The workspace list's items have a menu (a right-click, or their ⋯ button) in place of the *Edit* button: *Edit* (configs in the app, other files in your editor), *Duplicate* (`vexsim/app/files.py`: a copy beside it, a config's named as a copy) and *Delete* (confirmed); a project's folder is neither copied nor deleted there.

## 15. Autonomous maker (phase 13)
**Decisions** (2026-10-28): a route is a file in its PROS project, which the simulator runs as it is and which is exported as C++ when asked; the team's own movements are the functions its headers declare; each step's endpoint is drawn as planned at once and as simulated a moment later; an export writes `src/vexsim_autons.cpp` and declares its routines in `include/custom/auton.hpp` between markers.

- **Routes (13.1):** a route is a YAML file in a PROS project's `routes/` folder: its name, the robot and field it's drawn and simulated with, its start pose (the routine's `chassis.setPose`), the headers its functions come from, and its steps. Numbers are in LemLib's convention (inches, θ clockwise from +y), as the robot's code has them. A step is one of:
  - a LemLib 0.5 motion: `move_to_point`, `move_to_pose`, `turn_to_heading`, `turn_to_point`, `swing_to_heading`, `swing_to_point`, with its timeout and options (`forwards`, `max_speed`, `min_speed`, `early_exit`, `lead`, `direction`, `locked_side`) and `async` (start it and go on, as LemLib's last argument does);
  - a pause: `wait` (ms: `pros::delay`), `wait_until` (inches along the async motion before it: `chassis.waitUntil`) or `wait_until_done`;
  - `call`: one of the team's own functions, its arguments by parameter name (one left out takes its default).

  ```yaml
  version: 1
  name: Left 40
  robot: ../../../robots/1239e_2026-27.yaml   # relative to this file
  field: ../../../fields/1239e_2026-27.yaml
  start: [60, 0, 90]                          # chassis.setPose(60, 0, 90)
  functions: [include/custom/util_funcs.hpp, include/custom/lift_control.hpp]
  steps:
    - {call: moveForward, args: {inches: -10, timeout: 800}}
    - {turn_to_heading: 270, timeout: 800, max_speed: 100, async: true}
    - {move_to_point: [14, 0], timeout: 1000, max_speed: 60, async: true}
    - {call: startFrontIntake}
    - {wait: 100}
  ```
  `vexsim/app/routes.py` reads and checks a route as configs are checked, each issue at its line: a function the headers don't declare, an argument of the wrong type, a target off the field, a start on top of a field element, `wait_until` after a motion that isn't `async`. The workspace lists routes under *Autonomous routes*.
- **The team's functions (13.1):** `vexsim/bridge/functions.py` reads the route's headers with 12.1's tokenizer. Each function that returns `void` (in any namespace) and takes numbers, `bool`s or values of an enum the project declares becomes a step type, its parameters' names, types and defaults kept for the step's form. Any other function (references, pointers, classes, templates, overloads) is listed with the reason it can't be a step.
- **Running a route (13.1):** vexsim's build of the project adds a generated runner, in the build cache, so the project doesn't change. The runner is a routine that reads the route's steps when it runs (from the file `VEXSIM_ROUTE` names) and makes the same calls an export would: the project's own LemLib chassis (found by its declaration), `pros::delay`, and the team's functions through a table generated from their declarations. So only a change to those functions rebuilds; a changed step only reruns. The runner runs as 12.1's routines do, inside `autonomous()`. It reports each step as it starts and each motion as it ends, so the run records where the robot really was, and where LemLib thought it was, at the end of every step, and how long each step took; a motion that used up its timeout is flagged. `RunSpec.route` (`vexsim run --route FILE`) runs one; a `route` job runs it headless and returns those endpoints.
- **As built (13.1):** `vexsim/app/routes.py` (the route model and checks, `runner_input`, `run_route`), `vexsim/bridge/functions.py`, `vexsim/bridge/runner.py` and `vexsim/bridge/cpp/route/runner.cpp`; `vexsim route check|run FILE`, `vexsim run --route FILE`, the `route` job, and the run bar's **Routine** list, which lists a project's routes too (clicking one in the workspace list sets up its run). Where it differs from the plan above, or adds to it:
  - *Motion ends, exactly.* The runner can't see LemLib's motion queue, which is private; vexsim's scheduler can. LemLib starts each async motion's task while it holds its chassis' motion mutex, so the scheduler follows the tasks created then (`vexsim_follow_tasks`) and calls the runner as each starts and ends, in the same simulated millisecond. A step ends when its call has returned and every motion it started (itself, or inside one of the team's functions) has ended. A motion "used up its timeout" when it ran that long, counted from when the motions queued before it ended.
  - *Builds.* A route build is the project's build plus one generated file, with an executable of its own beside the usual one, so switching between routes and other runs relinks nothing. Its function table holds the functions a compiled file defines (`nm`), so one a header declares but nothing defines (1239E's `partnercontrollervibrate()`) is left out, and a route that calls it can't run, with why.
  - *Arguments.* A call's arguments go by parameter name; one left out before a given one is filled in with its default when that's a plain value (a number, `true`, an enum's value), and must be given otherwise. Enum values are passed by name, through a table of each enum's values generated with the runner.
  - *Options.* `move_to_pose` also takes LemLib's `horizontal_drift`. Speeds are 0 to 127, whole numbers for turns (LemLib's `int` fields there).
  - *Where it runs.* In a project without routines the robot host runs the route in place of `autonomous()`; with routines, the switch runs it in place of the first routine called (`vexsim: autonomous() called left40(); running the route instead`).
- **The maker (13.2):** a route opens in an editor tab, as a config does: its steps on the left, the field on the right.
  - *Steps:* a line for each (*Move to (14, 0) · max 60 · async*), opened into a form with all its options. *Add* offers the motions, the pauses and the team's functions, by header. Steps reorder by dragging, and duplicate, delete, copy and paste (Ctrl+C, Ctrl+V), between routes too.
  - *The field:* the robot at its start (drag it, and its heading handle, to move the start), and every step's endpoint as planned, drawn as soon as it changes: a numbered marker with the robot's outline and heading there, joined to the one before by the way it gets there (a line, a swing's arc). The selected step's endpoint drags (snapped to tiles, half or quarter tiles, or inches), its heading handle turns, and a click on the field with a motion tool adds a step there. An endpoint whose outline would hit a field element or leave the field is marked.
  - *Planned endpoints* follow LemLib's targets: `move_to_point` ends at its point facing the way it went (or away, going backwards), `move_to_pose` at its pose, a turn where it started, a swing about its locked side (the robot's track width). The team's functions can't be planned unless they say what they do: a comment just above a function's declaration maps its parameters to a motion the planner knows (`// vexsim: drive(inches)`, `turn_by(degrees)`, `arc(radius, degrees)`, `point(x, y)`, `pose(x, y, theta)`, `none` for a function that doesn't move the robot), and then its endpoint, and the way to it, is drawn as soon as it changes too. One that doesn't say is carried on unmoved, and marked, until a run says where it ended; after a run, the plan goes on from where the robot really was.
  - *Simulated endpoints*, a moment after an edit (the route run headless with its own seed; a newer edit cancels the run): the path the robot drove, and each step's real endpoint beside its planned one, with the distance between them, its time, and the total against the 15 s autonomous period. *Watch* plays the route on the Simulate page, with its timeline and plots.
  - Edits are in-place changes to the route's YAML (12.3's `yamledit`), so its comments stay, it has a YAML view, and undo covers everything. *Mirror* makes the route for the other side of the field (across the field's middle line, in x or y). *New route…* (beside the routes in the list) asks for a name and a project, and starts from the run bar's start pose, with no steps.
- **As built (13.2):** `frontend/src/components/RouteEditor.tsx` (the tab: its steps and forms), `RouteField.tsx` (the field), `NewRouteDialog.tsx`, and `frontend/src/route.ts` (the planner, and the values the editor writes); on the server, `GET /api/route`, `POST /api/route/check`, `/api/route/patch`, `/api/routes/new` and `/api/routes/mirror`, `yamledit`'s new `insert` (a list item before another, and the comments above it) and `move` (an item with its comments), `routes.mirror_text` and `new_route_text`, and the hints in `functions.py`. Where it differs from the plan above, or adds to it:
  - *New motions wait.* A motion the maker adds is written with `async: false` (LemLib's default is `true`), and a timeout for its distance and turn (600 ms, plus 40 ms an inch and 4 ms a degree, to the next 100 ms). So a route made in the maker runs as it's drawn, one step after another: after an async motion, a pause or a function starts while the motion is still going, which the plan can't follow (the first try ended a `moveForward` 17 in from its plan, as it read the pose mid-turn).
  - *One marker for one place.* Steps one after another that end where the step before them did (a turn, a pause) share a numbered marker (`1–3`), drawn with the selected step's outline; clicking it selects them in turn.
  - *Numbers one at a time.* A box sets just its own number (`start[1]`, `steps[3].move_to_point[0]`), so two typed one after the other don't undo each other; a header is added to `functions` and taken out by its place.
  - *Hints.* 1239E's `moveForward` has `// vexsim: drive(inches)` above its declaration, so the plan follows it. A hint that doesn't read says why in the step's form.
  - *Runs.* The simulated run is a `route` job on the editor's text, saved or not; a job for the same text (by its hash) is joined rather than started again.
  - *Since:* *Add a step* is a box to type in (`StepPicker.tsx`). What's typed finds a motion, a pause or a function by any part of its name, whatever its case, spaces and underscores (`stepsearch.ts`: from its start, from one of its words on, inside it, then its letters in order), best first. It finds the functions of the project's headers that the route doesn't list too (the route check's `more_functions`, read again only when a header changes), and picking one lists its header in the same edit. Points drag, and the field's tools add steps, where the pointer is (to 0.1 in), so the snap menu is gone; headings still turn in 15° steps (Shift: 1°).
- **Export (13.3):** *Export to project* writes each of the project's routes as a C++ routine (`void left_40()`, named after the route) into `src/vexsim_autons.cpp`, which says it's generated and is rewritten whole on each export, and declares them in `include/custom/auton.hpp` between `// vexsim routes: begin` and `// vexsim routes: end` (added the first time), so 12.1's routine list and the team's selector can call them. Each call is written as the runner makes it: a motion with its options as LemLib's designated initializers (`{.forwards = false, .maxSpeed = 60}`) and its `async`, `pros::delay`, and the team's functions with the arguments given. The app shows which files it will change before it writes them, and exporting the same routes again changes nothing.
- **As built (13.3):** `vexsim/app/autons.py` (`plan_export`, `export`), `vexsim route export PROJECT [--dry-run] [--diff]`, `GET` and `POST /api/routes/export`, and *Export…* in the maker (`ExportDialog.tsx`), which saves the route first and shows the routines, each file's state (new, changed, as it is) with its diff, and what's left out, before anything is written. Where it differs from the plan above, or adds to it:
  - *Names.* A routine is named after its route, as a C++ name (*Left 40* is `left_40()`; one that starts with a digit gets `route_` before it, a keyword or one of PROS's own names `_route` after). A route whose routine's name another route already has, or that the project's own headers declare (outside vexsim's block), is left out, with why, as is a route with errors; the rest are exported. If none can be, nothing is written.
  - *The routine.* It starts with the route's `chassis.setPose(x, y, theta)`, as the runner does, then a line per step. Options and `async` are written only where they aren't LemLib's defaults (`chassis.moveToPoint(24, 0, 1000);`), the options in the order LemLib's params structs declare them. A call fills in a default left out before a given argument with its value, and writes an enum's value with its enum's name (`lemlib::DriveSide::RIGHT`). The file includes `main.h`, `lemlib/api.hpp`, the routes' headers, the header that declares the chassis (or declares it `extern` itself) and `auton.hpp`.
  - *auton.hpp.* Its block is put at its end (inside a closing `#endif`'s include guard), replaced in place on later exports, and keeps the file's line endings; a file with only one of the two comments is refused. A project with no `auton.hpp` gets one, and a note that `autonomous()` (or the selector) must call the routines for the robot to run them.
  - *The check.* 1239E's `left_start` route, exported into a copy of the project, builds, is listed as a routine (starting at its `setPose`), and run from the routine list ends each step within 0.25 in of where the route's run ended it (here, to within 0.001 in); exporting again changes neither file.
- **vexsim's own motions (13.4):** a small C++ library on LemLib's chassis (its odometry and drive motors), with steps of their own in the maker. *RAMSETE*: a trajectory through waypoints within speed and acceleration limits, followed with the RAMSETE law and a feedforward drive model (kS, kV, kA) that vexsim works out from the robot's config and the Calibrate page can fit to a real robot's log; the maker draws the whole planned trajectory, colored by speed. *moveArc*: a constant-curvature arc of a given radius through a given angle, on a speed profile. Ported from vexsim's Python RAMSETE and profiled drive, and tested against them. An export copies the library's source into the project (`include/vexsim/motions.hpp`, `src/vexsim/motions.cpp`), so the real robot runs what was simulated.
- **As built (13.4):** `vexsim/bridge/cpp/motions/` (`include/vexsim/trajectory.hpp`: `planArc`, `planPath` and `sample`, plain C++17; `include/vexsim/motions.hpp` and `src/vexsim/motions.cpp`: `vexsim::Motions` with `moveArc(radius, degrees, timeout, ArcParams, async)` and `ramsete(points, timeout, PathParams, async)`, and `vexsim::Drive`), its plans in Python (`algorithms/control/trajectory.py`) and TypeScript (`frontend/src/trajectory.ts`), the drive model (`calibration/feedforward.py`), route steps `move_arc: [radius, degrees]` and `ramsete: [[x, y], ...]` with a route's `drive:` section, the runner's `drive` line and two step kinds, and in the maker, the trajectories, forms and points to drag. Where it differs from the plan above, or adds to it:
  - *The plans.* An arc is closed-form. A path is a cubic Hermite curve through the robot's position and the points: it sets off along the robot's heading, bends through each point with a Catmull-Rom tangent, and ends along its last stretch or at `end_heading`. Both are sampled every 0.25 in, each sample's speed capped by the step's speed, the outside wheel's top speed and the turning limit, then by the acceleration forwards and backwards, and timed into states every 10 ms. The C++, Python and TypeScript do it step for step: the C++ is tested against the Python (to 1e-9, in pytest, through `tests/cpp/trajectory/main.cpp`), the TypeScript too (Vitest). The follower is the RAMSETE law of the Python `Ramsete` (the textbook b = 2, ζ = 0.7), but it drives voltage from the model instead of wheel speeds. Motions queue with LemLib's own through the chassis' protected motion queue (a derived class's pointers to its members), async as LemLib's are (a task of their own, started while the queue is held), and `waitUntil()`, `waitUntilDone()` and `cancelMotion()` work on them.
  - *More to the model than kS, kV, kA.* With those alone, the first RAMSETE path ended 10 in from its plan: the robot turned far less than planned, because a turn takes about 0.9 V more per side against the scrub of the wheels sliding sideways, which straight-line driving doesn't show. So the model has `kT` (volts against the scrub, by a smooth sign of the turn: `tanh(w / 0.15 rad/s)`), fitted from turns in place, and `kP` (volts per in/s a side's wheels are behind, from their motors' speeds: 4 × kV by default), the feedback WPILib's RAMSETE uses too. vexsim works the model out by driving the robot's config open-loop for about 9 s (straight at a few voltages, then turns in place) and fitting that (about 1 s, then cached).
  - *The turning limit comes from the middle wheels.* With the plan's turning limit at half the wheels' mean sideways grip, an all-omni robot slid outward through every arc: in a turn the wheels ahead of and behind its middle are already sliding sideways, so only the middle ones hold it on its curve. The limit is half the sideways grip of the wheels within 1.5 in of the robot's middle, by their share of its weight (12.9 in/s² for 1239E's six omnis; 70.8 with traction wheels in the middle). With both, each motion of the test routes ends within 1.3 in and 2° of its plan, on 1239E's robot and the LemLib example's.
  - *Fitting a real robot's log.* `vexsim calibrate` and the Calibrate page fit the model to the log as it is (`fit`, by least squares, the log's own voltages and wheel speeds), and print the route's `drive:` line to copy (`drive.yaml` in its files). Stretches that turn harder than the wheels can hold (the routine's fast arc, on an all-omni robot) are left out, as the robot slides; a log that doesn't turn the robot fits no `kT`. On the calibration routine's simulated log, 1239E's fit is within 0.1 V of its characterization.
  - *A route's drive: section* gives any of `kS`, `kV`, `kA`, `kT`, `kP`, `max_velocity`, `max_accel` and `max_lateral_accel`, the rest being vexsim's: the limits follow the constants given (80% of the top speed, no faster than the motors' rated speed turns the wheels, which a log of slower driving can't tell; a third of 12 V's acceleration; the turning grip), unless they're given too. The server's check sends the model for any robot with two drive sides, so a route's first arc is planned right away.
  - *Builds.* Every LemLib build has the library's headers on its include path, after the project's own, so a project's copy wins; a route build compiles vexsim's `motions.cpp` (generated into its cache) unless the project has `src/vexsim/motions.cpp`.
  - *Export.* A routine with these motions starts with `static vexsim::Motions motions(chassis, {.kS = …, …, .maxLateralAccel = …});`, the whole model the route was simulated with. The library's three files are copied into the project when it doesn't have them; one it has that differs is left as it is, and noted.
  - *In the maker.* Trajectories are drawn whole, shaded in one hue from slow to fast, with a key; a selected path's points are diamonds to drag, and the *RAMSETE path* tool adds a path to a clicked point. A new arc or path gets a timeout half a second longer than its plan, and the form says when a timeout is shorter than the plan. *Drive model* under the route's name shows each number it drives with, to change. Mirroring negates an arc's degrees, and mirrors a path's points and its `end_heading`.
  - *The check.* On a copy of LemLib's template, a route with a RAMSETE path and an arc ends each within 2.5 in of its plan; exported (with the library) and called from `autonomous()`, the routine ends each step within 0.25 in of where the route's run did (here, within 0.001 in). By hand, the same on a copy of 1239E's project, with a backwards path: within 0.001 in.
- **Risks:** the runner and the export could disagree, so both are generated from one description of each step, and a test runs a route both ways and compares where each step ends. LemLib queues a motion started while another runs; the runner calls LemLib exactly as the export does, so the queueing is LemLib's own. Functions vexsim can't call from a route (templates, macros, references) are listed with the reason. A route's first run builds the project, as any run does; after that, a rerun is a headless run of about 15 s of simulated time, a few seconds.

## 16. Calibrating with a physical robot (phase 14)
A team calibrates vexsim to its own robot without help. A program on the robot runs each test and logs it; vexsim collects the logs, fits the model and writes the results into the robot's config; then the calibrated simulator is checked against the team's real autonomous. A step-by-step guide for students walks through all of it.

**Decisions** (2026-10-31):
- Logs go to the brain's microSD card, with USB as the fallback; a laptop with USB is at the field.
- The wheels come off the ground by laying the robot on its side; no stand.
- Tests run on a full field with the season's elements in place, so there's no 3 × 3 m of open floor: each driving test is planned, from the robot's shape and the field config, to fit between the elements.
- The first robot is 1239E 2026-27: 6 omni wheels, an IMU, 5 distance sensors, no tracking wheels, and a trapezoid at the back for aligning at goals. The team's next robot has two tracking wheels and about the same outline, its drivetrain and distance sensors not known yet; so everything comes from the robot config, and nothing is specific to one robot.
- The calibration program is a program of its own, in a spare slot. Calibrating doesn't touch the competition code; only the autonomous check adds the logger to it.
- Tests cover the drive, its motors and the sensors; no mechanisms.
- The real autonomous is checked against the simulator. For that, 1239E's project drops its MCL log entirely, and vexsim's logger records everything instead.
- The command line comes first, then the Calibrate page.
- The guide is for students working on their own: plain language, every command written out.
- The autonomous check passes when the simulated run ends within a distance and a heading of the real one, both set by the team.

**A session**, in the guide's order (about an hour):

| # | Test | Where | What it measures | What it sets |
|---|---|---|---|---|
| 1 | Device check | on its side, then flat | each device answers on its port, as its type; each side's motors turn together and forward; tracking wheels and the IMU count the right way; each distance sensor is the one the config says (a hand over each in turn) | nothing: a failed check says what to fix, and the fit won't start until it passes |
| 2 | Free spin | on its side | top speed and current at 3, 6, 9 and 12 V; steps in velocity mode | `motor.natural_free_rpm`, `motor.free_current_a`, `motor.coulomb_fraction`, `motor.velocity_kp` and `velocity_ki` |
| 3 | IMU, still for 60 s | flat | drift and noise | the IMU's `bias_walk_deg_s` and `rate_noise_deg_s` |
| 4 | IMU, 10 turns by hand each way | lined up on a tape line | the scale error, each way | the IMU's `scale_error` |
| 5 | Push, each way | between two tape marks 6–8 ft apart, on a lane the plan picks; motors coasting | how far the wheels really roll | the drive and tracking wheels' `diameter_in` |
| 6 | Drive tests, 3 runs each | spots the plan picks | launch, coast, reverse, brake; spin; arc | wheel friction and rolling resistance, the battery's resistance, the drive model (kS, kV, kA, kT) |
| 7 | Slow spin, 5 turns (tracking wheels only) | a spot the plan picks | where each tracking wheel is | the tracking wheels' `pos_in` |
| 8 | Distance sweep (distance sensors only) | 2–3 spots the plan picks, measured from the walls | readings of the walls at many distances and angles | distance sensor noise, range, misses at glancing angles, confidence |
| 9 | The team's autonomous | the competition program, from its own start | where the robot ends, measured | pass or fail against the team's marks |

- **vexsim's logger (14.1):** `vexsim_log.hpp` and `vexsim_log.cpp`, the same two files in every project (not generated per robot), PROS 4 C API only.
  - `start(name)` finds what is plugged into each port (`get_plugged_type`) and logs every device every 10 ms, in a task of its own: motors (command, position, velocity, current, voltage, temperature, brake mode), rotation sensors, IMUs (rotation, heading, rates), distance sensors (distance, confidence, object size), GPS, the battery (voltage, current, charge) and the competition mode.
  - The code adds what only it knows: poses by name (`pose("lemlib", fn)`, a function the logger calls every 10 ms), numbers (`value(name, fn)`) and marks (`mark("intake on")`).
  - Rows stay in memory, so nothing is written to the card while the robot drives. `stop()` saves them, and so does the logger itself when autonomous ends (the field or the switch ends the autonomous task, not the logger's). They go to the next numbered file on the card, by a counter file as 1239E's MCL log does, or without a card over USB between `#vexsim-log begin` and `#vexsim-log end`. A log stops at 3 minutes.
  - The format, version 2: `# key: value` lines first (format, robot, program, the log's name, battery, the ports found), then the CSV as now with the new columns; marks are `#mark` lines among the rows. `RobotLog` reads both versions, and every framed log in a terminal capture (today only the last).
  - `vexsim logger add PROJECT` copies the files in and says what to add to `main.cpp`. The calibration routine's `start_logging()` and `save()` move onto it.
  - In the simulator, `vexsim run --sd FOLDER` stands in for the card (`usd_is_installed()` says yes, and `/usd/` paths open in the folder), so the logger writes the same files there. 1239E's own `VEXSIM_SD_DIR` hook goes.
- **As built (14.1):** `vexsim/bridge/cpp/logger/` (`include/vexsim_log.hpp`, `src/vexsim_log.cpp`), `vexsim/bridge/logger.py` and `vexsim logger add`, `bridge/cpp/runtime/usd.cpp` and `vexsim run --sd` (`RunSpec.sd`), format 2 in `calibration/log.py` (`info`, `marks`, `parse_all`, `read_all`, `pose`) and `record.py`. Where it differs from the plan:
  - *A row holds only what changes.* An IMU's heading is its rotation (mod 360, by the code's own offsets) and its rate follows from the rotation, so a row has the rotation alone, as in format 1; the battery's charge is a header line (`battery_pct`), and the competition mode's changes are marks (`mode: disabled`). Distance sensors gained their confidence and object size (`d<p>_conf`, `d<p>_size`). Every motor is logged, the mechanisms' too, and `columns_for` lists them; a rotation sensor the code reversed is read as if it weren't.
  - *Commands.* The logger can't see what the code told a motor, so `vexsim_log::command(port, mV)` and `command_velocity(port, rpm)` say it; the calibration routine does, and samples by hand (`Sampling::manual`) right after each step's command, so its log is the one it wrote before, row for row.
  - *Saving.* Rows are kept as floats in blocks of 500 and written at the end, to the next free `/usd/vexsim_NNNN_<name>.csv` past the number in `/usd/vexsim_count.txt` (no folders: PROS may not make them). A log started in autonomous saves itself when the mode changes (the simulated field disables the robot after autonomous, as a real one does), and any log at its limit (`set_limit_s`, 180 s). Without a card the log is printed, framed, 20 lines at a time.
  - *The card in the simulator.* `VEXSIM_SD_DIR` (which `--sd` sets, to an absolute path) names the folder, made if missing; `usd_is_installed()` then reads 1. On Linux the robot host defines `fopen` and `fopen64` and maps `/usd/` paths before calling the C library's own (`dlsym(RTLD_NEXT)`), which reaches libstdc++'s file streams too; on Windows the link wraps both (`--wrap=fopen,--wrap=fopen64`), MinGW's static libstdc++ opening streams with `fopen64`. 1239E's own `VEXSIM_SD_DIR` hook is in `initLog()`, which 14.2 removes; until then it reads the same variable.
  - *The check.* A project that logs a second of driving, with a pose and a number of its own, runs in the simulator: its log has every device, the code's columns and marks, numbered files and the counter; it matches the simulator's own record of the run (`RobotLogger`, every millisecond) at the log's times, to within the logger's decimals, from its second row (at its first, 2 ms in, before the motors' first readings, the code reads 0 where the simulator has none yet). A log started in autonomous saves itself when autonomous ends, one at its limit when it reaches it, and without a card the log is printed and reads back. The calibration routine on the logger logs what the Python routine logs, as before.
- **1239E on vexsim's logger (14.2):**
  - Out of the project: `initLog()` and its call, the `mcl_log<N>.1239e` files and their `DATA.1239e` counter, `MclTracking::logMcl()`, the async logger task and its queue, the `LogData` records written in `update_weights()` and `get_estimate()`, and `MCL_Log_Format` (`DISABLED`, `SDCARD`, `SCREEN`) with `mclLog` and `mclLogTimer`. The PID tuner's `PIDValues.1239e` stays.
  - In: `vexsim_log`, with two poses (LemLib's `chassis.getPose()` and MCL's estimate), MCL's spread as values, and the routine's name as the log's name. `autonomous()` starts it; it saves itself when autonomous ends.
  - The guide lists the same edits for the team's own copy of the code, which is newer than the port's.
  - In vexsim: `--follow` takes a robot log's pose as well as an MCL log. vexsim still reads the team's existing MCL logs. `examples/scripts/replay_1239e_mcl_log.py` needs the project to write MCL logs, so it retires with its tests; [docs/1239e_real_vs_sim.md](docs/1239e_real_vs_sim.md) stays as the record of what it found, at the commit that found it.
- **As built (14.2):** the port's `main.cpp` (`initRoutineLog()`), `auton_selector.cpp` (`startRoutineLog()` in `runAuton()`) and `MclTracking.cpp` (`updateSpread()`, `getSpread()`); `logged_path` in `app/runspec.py` and `robot_log_path` in `runtime/follow.py`. Where it differs from the plan:
  - *The logger saves in a task of its own.* A routine that ends near the end of the period would have its save cut off when the field ends the autonomous task, so `stop()` hands the log to a saving task (below the code's own tasks' priority, so a long save doesn't hold up driver control) and polls every millisecond until it's saved; if the waiting task is ended meanwhile, the save goes on.
  - *Only with a card.* The routine is logged only when a card is in (`usd_is_installed()`), as the MCL log was: so a simulated run without `--sd` doesn't print a log of every routine, and runs as it did. Without a card, `initialize()` rumbles the controller, as `initLog()` did.
  - *The log's name is the selector's pick.* `runAuton()` names the log for the routine it runs, so a run that picks the routine with `VEXSIM_AUTON` names it right; `--routine` runs its routine in place of the selector's, under the selector's name.
  - *Hooks.* The seven-number `startMcl` hook went with the replay script it served; plain `VEXSIM_AUTON=startMcl` and `VEXSIM_BRAKE` stay, for following logs.
  - *Following a robot log.* A robot log is followed along its first logged pose (LemLib's, for 1239E). Before the code's first `setPose`, its pose stands still and then jumps further than a robot moves in 10 ms (2 in, or 20°); those rows are left out, so the path, and the run's start, begin where the routine put the robot.
  - *The check.* The nine routines end where they did before the change, to the hundredth of an inch. With a card, Right 30 logs itself as `vexsim_0001_right_30.csv`: the nine motors, five distance sensors and IMU, LemLib's and MCL's poses (LemLib's last within 0.5 in of the pose the simulator read from LemLib) and MCL's spread, and following it starts at the routine's `setPose(-60, 0, -90)`. Following Left 40's log in the simulator drives the whole path, ending about 5 in from its logged end. The replay script's three tests went with it; the throttle curve it inverted is tested on its own.
- **The calibration program and its field plan (14.3):** `vexsim calibration program ROBOT.yaml FIELD.yaml FOLDER` writes the program into a PROS project made with `pros c n FOLDER`, for `pros upload --slot 8`. It's generated from the robot config (drive sides, ports and directions, sensors, shape) and the plan (where each test starts), and uses only the PROS 4 C API and the logger, so it also runs unchanged in vexsim.
  - *The plan* (`vexsim calibration plan ROBOT.yaml FIELD.yaml`, which `program` runs too): each driving test is simulated from rest over a spread of the parameters it measures (friction, mass, motor speed), since the uncalibrated robot can be anywhere in that spread. The robot's shape swept along every one of those paths, plus a margin (6 in by default), must stay clear of the walls and of every element, those robots can drive over included (a log needs flat tiles). The start is searched over the field: positions on a grid, headings by 15°, square to the walls preferred. A test with no room is slowed and shortened, down to a floor; below that, the plan names the elements in the way. The push lane and the spots for the slow spin and the distance sweep are planned the same way. For each test it draws a map (start, swept area, margin) and says where to put the robot as distances from two walls, so a tape measure is enough.
  - *The menu*, on the brain screen and the controller: the battery, the hottest motor, card or not, and how many runs are saved; then the tests in the session's order, each with what to do. A *Drive* mode (tank, half speed) moves the robot between spots without changing programs.
  - *Safety:* a driving test starts only once the robot is still, after a 3 s countdown with a rumble. Any button, or a stick past 20%, stops every motor at once. So does leaving the plan's envelope: turning or travelling further than any of the plan's paths did, by the IMU and the motor encoders. A stopped run is kept and marked as stopped.
  - *Before each run:* every device in the config answers, as its type; the battery is at 80% or more (below, it asks first); no motor is over 45 °C.
  - *After each run:* its length, top speed and total turn, and warnings: a sudden stop (did it hit something?), a hot motor, a sagging battery, the robot moving while the IMU calibrated.
- **As built (14.3):** `vexsim/calibration/plan.py` (`vexsim calibration plan`), `calibration/program.py` and `bridge/cpp/calibration/main.cpp` (`vexsim calibration program`), `calibration/student.py`, `routine.drive_tests`; in the simulator `Robot.lifted`, `Robot.place` and `DistanceDevice.blocked_mm`. Where it differs from the plan, or says more:
  - *The driving tests* are the routine's maneuvers, each from rest on a spot of its own and ending braked: straight (launch, coast, reverse, brake), spin, arc, and strafe for drives that can; three runs each. A test with no room runs at 85%, 70% or 55% of its speeds and drive times, the first that fits.
  - *The spread* is five variants: as configured; rolling further (rolling resistance x0.6, roller friction x0.7, grip x1.2, motors 10% faster, 15% lighter); stopping sooner; sliding more; gripping more. On 1239E's field the straight test goes 19 to 48 in out, and the arc turns 79 to 281 degrees.
  - *The search* correlates the swept area (sampled every 0.25 in, the robot's edge along each path and its shape at the ends) with the cells too near a wall or element, by FFT, for each heading: square headings win if any fits at that speed, then the most room, then the middle of it. Every element counts, game pieces don't (the plan says to clear them). The push lane keeps 3 in clear (it's pushed by hand); the spins in place need an IMU (they turn by it), and the sweeps' spots are picked one at a time for the most readings in 100 mm steps the others don't have.
  - *Placing the robot:* square to the walls, how far two of its sides are from the walls they face, to the half inch (the plan's pose is the one those numbers give), each from the nearer wall unless only the farther one's tape line misses the elements; otherwise two of its corners from two walls each. Three short lines of it fit the brain's screen. The maps are numbered as the program's menu numbers the tests.
  - *The program* is one fixed file and a header generated for the robot and plan; it refuses a project with code of its own. It also prints a `#vexsim-cal` line at each step (what it does, or waits for), which the simulated student reads; the laptop can too.
  - *The device check* spins each group of drive motors at 3 V on its side and asks which way the wheels went (A forward, B backward, X didn't); a group whose motors fight is spun motor by motor, which names the reversed one. The distance sensors are told apart by a hand over each in turn, as planned, so it needs no spot on the field; a swapped pair is named as one.
  - *The envelope stops early enough to brake.* A run stops when a drive motor's distance from its start, plus how far it would turn braking from its speed (at 4000 deg/s², on the safe side) if moving away, passes the plan's travel. Without the braking term, a robot rolling far past the spread (rolling resistance 0.015, motors at 140 rpm) stopped too late and rolled onto a base; with it, it stops with 6.7 in to spare.
  - *Warnings:* "slowed suddenly" is the wheels losing 20 in/s within 100 ms while coasting or driven the way they turn (a coast loses about 4); a relative drop fired on every coast and every reverse.
  - *The free spin* runs all the drive motors together (3, 6, 9 and 12 V, then 50% and 100% in velocity mode); on 1239E they reach 165, 336, 509 and 680 rpm, then 300 and 600.
  - *The simulated student* answers the program's prompts as a person would: presses buttons, lays the robot on its side (`Robot.lifted`: no ground force, so the wheels spin free and nothing moves it), puts it on each spot (`Robot.place`, the heading turned the short way as the IMU sees carrying), pushes and turns it by hand (a stiff spring and damper on its pose, at 1 kHz), watches the wheels to say which way they went, and covers a distance sensor (`blocked_mm`) where the program's config says it is, on whichever robot is simulated. After two stopped runs in a row it goes back to the menu.
  - *The check.* On 1239E's robot and field, the student runs every test from the menu in order (18 logs, 4.6 minutes simulated in about a minute): every log finished, with its test, run and spot; each driving test's true path stays more than the margin from every element (straight 11.4 in, spin 16.6, arc 11.9, the sweeps 10.7 and 10.8; the push lane 3.7 of its 3); the free spin leaves the robot where it lay; the IMU turns read its 0.25% scale. A press 0.8 s into a run has every motor told to stop within 20 ms, and the run is logged as stopped. With motor 9 wired the other way and the sensors on ports 1 and 8 swapped, the device check says "motor 9 runs backward: make it -9" and "ports 1 and 8 are swapped". The same program runs `full_omni_6m`'s tracking-wheel checks and slow spin, and the X-drive's strafe. Not done: building it with the real PROS toolchain in CI.
- **Collect and fit a session (14.4):**
  - `vexsim calibration collect SESSION` copies new runs into `SESSION/runs/`: `--from-card` finds the card (a drive letter on Windows, `/Volumes` on macOS, `/media` on Linux), `--from FOLDER` takes a folder, and `--usb` wraps `pros terminal` and saves each log as it arrives. It checks each run (the robot's name and ports, finished or stopped, its warnings) and lists them in `SESSION/session.yaml`: the robot, the field, and each run's test, quality and whether the fit uses it.
  - `vexsim calibrate ROBOT.yaml SESSION` fits each test into what it measures, in an order where each fit uses the ones before: the wheels' diameters, the motors, the IMU, the drive (all its runs at once, one held out to check the result), the tracking wheels, then the distance sensors. A failed device check stops it, saying what to fix. A single log still fits as it does today.
  - Replays learn two things: a *lifted* robot (wheels off the ground) for free spin, and the per-device errors already measured (the IMU's scale) in place of ideal sensors.
  - The distance sensor model gains what the real sensors showed in [docs/1239e_real_vs_sim.md](docs/1239e_real_vs_sim.md): misses at glancing angles, more of them with distance, and a confidence that drops with both. Their defaults keep today's behavior (no misses, confidence 63), so nothing changes until a fit fills them in.
  - The report (`SESSION/report/`: `report.md` with its plots, and `changes.yaml`) gives each test's result, before and after, which values the logs pin down and which they don't, its warnings, and whether the held-out run matches within the sensors' noise. `--apply` writes the changes into the robot YAML (overrides, wheel diameters, sensor fields), keeping its comments, with a comment naming the session; it also prints the routes' `drive:` line.
- **As built (14.4):** `vexsim/calibration/session.py` (`vexsim calibration collect`), `calibration/session_fit.py` (`calibrate`), `calibration/report.py` (the report, `--apply`), `vexsim calibrate ROBOT.yaml SESSION`; in the models `motor.voltage_cap` and the distance sensor's `glancing_miss`, `glancing_deg`, `glancing_mm`, `confidence_per_m` and `confidence_per_deg`; `fit.fit_logs`, `feedforward.fit_logs`. Where it differs from the plan, or says more:
  - *The order.* The motors come first (the free spin), then the IMU, then the wheels' diameters: the push is replayed with the motors coasting, and how far coasting wheels creep depends on the motors' drag and on the wheels' friction. So the push, the tracking wheels and the drive go twice, the second time with the friction the first found. On 1239E a plain ratio of the lane to the wheels' travel is 2% off; the replayed push with vexsim's default friction 0.7%, with the fitted friction 0.16%.
  - *The free spin* first tells whether voltage commands are capped at rated speed: a free motor runs about 1.34 times as fast at 12 V as at 9 V, a capped one 1.18 (cut at 1.25). Fitting the motors without knowing that leaves the velocity 19 rpm off and the values skewed; with it, at the noise (3 rpm). `velocity_ki` isn't fitted (a free spin can't tell it: its uncertainty came out over 1000%). The motors' speed noise comes from the steady stretches.
  - *Replays* read ideal sensors whatever `sensor.*` overrides the config has (they made the replay noisy, and a fitted config has them), start with the IMU calibrated (instead of 2 s of simulated calibration), and leave the distance sensors out when fitting; a motor that was never driven needs no logged commands. A replay is about twice as fast.
  - *The tracking wheels* are placed from the slow spin by its replay: the spin rolls a wheel, per radian of the IMU's turn, as far as it is from the center of the turn, and the replay with the configured position says where that center is. They go before the drive, which compares their readings too.
  - *The distance sweeps* need the field: `--field`, or the field config named as the logs name it, next to the robot's folder. The readings' age relative to the IMU is found from the readings (0 to 2 ms in vexsim, not the 25 ms its latencies suggested: the IMU's readings are as old). The glancing misses' edges come from the likelihood over a grid and their rate from the beams well inside, since a small pose error moves beams near the edges across them (at 80 degrees off square, a degree of heading is 145 mm of reading).
  - *Pinned down* means the uncertainty is within the value's tolerance (0.5% for diameters, 0.0005 for the IMU's scale, 5% for friction, ...); `--apply` writes only those, and only where they differ from the config by more than half that. A new `overrides:` section is appended as a block (yamledit makes a new mapping in flow style).
  - *The simulated student* now holds the robot firmly at the end of each move by hand, as a person lines it up on the tape: before, friction left a 10-turn twist 2.2 degrees short, which read as an IMU scale error of 0.06%. The game pieces are cleared off the field for the session, as the plan says.
  - *The held-out run* matches if each group of its readings, simulated against logged, is within 1.5 times what the sensors' noise alone leaves: the run simulated with each sensor's noise (the config's, read every millisecond, without per-device errors) against its replay without. Worked out by hand from the specs, the tracking wheels' floor left out the wheels' scrub while they roll (1.5 deg/s, where the truth leaves 2.3).
  - *The check* (`tests/test_calibration_sessions.py`, marked `session`: `pytest -m session`, and a CI job of its own; plain `pytest` leaves them out). 1239E and `full_omni_6m`, each with the hidden changes, run the program in vexsim with the student, `collect` takes the card, `calibrate` fits it (under 3 minutes each on 4 CPUs): 1239E's wheels come back 3.2001 in (3.20), its IMU 0.00502 (0.0050), friction 0.746, 0.250 and 0.130 (0.75, 0.25, 0.13), the cap 1, the distance sensors 0.32% and 2290 mm (0.3%, 2300), misses 85% past 45 degrees and 1500 mm (90%, 45, 1500), confidence 8.01 per m and 0.242 per degree (8, 0.25); the motors and the battery as vexsim's own. `full_omni_6m`: wheels 3.2082 (3.21), IMU 0.00398 (0.004), friction 0.750, 0.250, 0.130, the forward tracking wheel 2.0444 in across −1.759 in and the sideways one at −3.322 in (as built, with their own small errors: 2.0444, −1.759, −3.321). Each held-out arc matches within the noise (motor speed 2.97 and 3.00 rpm against 2.85 and 3.05). `--apply` writes 1239E's config with every comment kept and a valid result; the miswired 1239E (motor 9 backward, distance sensors 1 and 8 swapped) stops at the device check, naming both.
- **The autonomous check (14.5):** the competition program, with the logger in it, runs a routine on the real robot. Before moving the robot, put tape at two of its corners and measure each from two walls; vexsim works the end pose out from the robot's shape. `vexsim calibration check-auton ROBOT.yaml LOG --program PROJECT --end MEASUREMENTS` then runs the same routine in vexsim from the log's start (the code's first pose), with a few seeds, and compares:
  - where the robot ended, simulated against measured, as a distance and a heading, against the pass marks;
  - the code's own pose, real against simulated, through the run, and the first moment they part by more than the marks;
  - heading, wheel travel and distance readings over time, to show where they part.

  The pass marks (2 in and 2° by default) are set in `.vexsim/calibration.yaml` (`max_distance_in`, `max_heading_deg`) or by `--max-distance` and `--max-heading`; marks finer than a tape measure can tell (0.5 in, 1°) get a warning. Several real runs of one routine are compared as a spread, against the seeds' spread.
- **As built (14.5):** `vexsim/calibration/auton.py` (`check_auton`, the report), `vexsim calibration check-auton ROBOT.yaml LOG... --program PROJECT --field FIELD.yaml --end MEASUREMENTS...`; `plan.draw_field`, `follow.set_pose_time`. Where it differs from the plan, or says more:
  - *The verdict takes in the run.* It passes when the end is within both marks and, through the run, the code's pose (real against simulated, time from the routine's `setPose`, RMS, the mean over the seeds) within the distance mark. The end alone couldn't tell: on the simulated "real" 1239E, Left 40 ends within 1.3 in and 2.4 degrees of the real one whether the config is calibrated or vexsim's default (LemLib's motions and MCL correct a robot that's slower and turns differently), while the uncalibrated simulation gets there at other times, up to 5 in from the real one mid-routine.
  - *Where it ended* is where the robot came to rest: each simulated run goes on after the period until the robot has been still for 0.3 s (at most 3 s), as the real one was when it was measured. Left 40 is still moving at 30 to 35 in/s at the buzzer and stops 8 in further on.
  - *The end, from tape:* the two corners are named as the plan names them (front-left, ...: the outline's furthest point each way), each measured from an x wall and a y wall; the measurements read as sentences (`front-left: 23.5 from -x, 40 from +y; back-right: ...`) or short (`FL -x 23.5 +y 40, BR ...`, fractions as 23 1/2). The pose is the rigid fit of the two corners to the two marks; marks whose spacing is more than an inch off the corners' get a warning, and two corners under 6 in apart are refused. To the quarter inch, the heading comes back within about 0.6 degrees.
  - *The start* is the routine's `setPose` as the project's source says it (`routine_start`), when it's within 2 in and 5 degrees of the log's first pose (which is already a row into the motion); otherwise the log's. The routine is the project's whose name, without spaces and case, is the log's (`Left 40`: `left40()`), or `--routine`.
  - *The parting moment* is when the code's poses first come more than the distance mark apart and stay that far on average for half a second: a turn a few milliseconds early sets them inches apart for a moment (on Left 40 every pair of runs, real or simulated, is more than 2 in apart for a moment near 2.5 s). The report also gives where they're furthest apart and how much of the run they spend over the mark; heading through the run is plotted, not judged (turns at 300 degrees/s make it tens of degrees for a moment).
  - *Spreads:* with several real runs, their ends' mean and their RMS's mean are judged; a warning says when the simulated runs alone spread wider than the marks (a run vexsim can't tell from its own could fail them), and when the real runs spread more than twice the simulated ones (something varies on the real robot that the simulation doesn't have).
  - *The pass marks* come from `--max-distance` and `--max-heading`, else the nearest `.vexsim/calibration.yaml` from the folder vexsim runs in upward, else 2 in and 2 degrees. Left 40's end heading varies 3 to 4 degrees run to run, real or simulated, so 2 degrees would fail a perfect simulator about half the time: the team's mark in the check is 4.
  - *The logger logs motor positions in degrees*, whatever encoder units the code set: 1239E's code reads its drive in rotations, which the log had as degrees.
  - *The check.* The simulated "real" 1239E (14.4's) runs Left 40 twice from 1239E's code with a card, each end measured to the quarter inch; against 3 seeds, at the team's 2 in and 4 degrees, the config 14.4's session wrote (`--apply`) passes (the ends 0.66 and 0.80 in off, the runs 1.08 and 1.45 in RMS) and vexsim's default fails on the run (2.23 and 2.49 in RMS; its ends 1.27 and 0.84 in off would pass). A check takes about 10 s once built.
- **The guide (14.6):** `docs/calibration_guide.md`, for students on their own. It covers:
  - what to bring;
  - describing the robot: weighing it, measuring its outline (the trapezoid too) in the Design view, the wheel positions and the CG, and checking the field config against the real field;
  - putting the program on the robot;
  - the session test by test: what to do, what the screen should say, and what to do when it doesn't;
  - collecting, fitting, reading the report and applying it;
  - the autonomous check, and switching a project to vexsim's logger;
  - when to calibrate again (new tiles or a new venue, new wheels, more than about 0.5 kg added);
  - a new robot: a copy of the old one's outline, and tracking wheels;
  - troubleshooting, and a one-page checklist to print.

  Every command is written out, for Windows and macOS. Its pictures come from the tools: the plan's maps on 1239E's field, the program's screens in the simulator, a report. README section 12 becomes a short overview pointing to it, and [docs/calibration.md](docs/calibration.md) stays as the reference (formats, how the fits work).
- **As built (14.6):** `docs/calibration_guide.md`; its pictures in `docs/img/guide/`, made by `examples/scripts/calibration_guide_pictures.py` (about 5 minutes: a whole session by the simulated student on 14.4's "real" 1239E, the device check of a miswired one, the session's fit and report, and the autonomous check of Left 40, run twice); `tests/test_calibration_guide.py`. README section 12 is an overview pointing to the guide, and [docs/calibration.md](docs/calibration.md) says it's the reference. Where it differs from the plan, or says more:
  - *Commands* differ between Windows and macOS only in setting up (Python, the environment, the compiler) and in finding the card, so the guide gives one command where they agree, with paths written with `/` (PowerShell takes them), and one for each where they don't. They use 1239E's files, with a table of what to put in their place; the program goes in `calibration/vexsim_calibration` and a session in `calibration/DATE`, inside the vexsim folder.
  - *Its pictures:* three of the plan's maps (the push lane, the straight test's spot, a sweep's); 18 screens of the brain and the controller side by side, each as the student met it (both a quarter second after the program asks, before the student answers, so the controller has shown its lines and the two status lines agree), and the device check's result on a robot with motor 9 reversed and two distance sensors swapped; the report's free spin, held-out run and distance plots, and the whole report (`report_example.md`); the autonomous check's paths and how far apart they were. The session is dated 2026-11-07, so they come out the same any day: 1.4 MB in all. The outputs it quotes (the plan's text, `collect`, `calibrate`, `check-auton`) are the commands' own, run on the script's session (`--keep FOLDER`).
  - *Describing the robot* follows the Design view's own labels. The center of gravity is found by tipping the robot onto its back wheels, then its front ones, and reading each angle with a phone: its height is r + L / (tan A + tan B), with L the wheels' spacing and r their radius.
  - *What the screens can say,* and what to do about each, is in tables: before a test (a device missing, the battery, a hot motor), the device check's problems, and how a run ended.
  - *The device check's result now shows each problem whole,* wrapped onto as many of the page's four lines as it takes: the guide's table showed that "the sensor at the front left, facing forward is on port 8, not 1" (63 characters) was cut at the brain's 48. Problems that don't fit are counted ("...and 2 more (see the log)"). With motor 9 reversed and two sensors swapped, the page is as before.
  - *The check* (`tests/test_calibration_guide.py`, fast): every picture and link in the guide and its example report is there, headings' anchors included, and every picture the script makes is in the guide; every `vexsim` command in its code blocks parses with vexsim's own parser, and the example files they name exist; every screen text it quotes (its "The screen says" tables, and "the screen says `...`") is one of the program's strings with its printf fields filled in; the README links to it. In `test_calibration_program.py`, three distance sensors wired round in a ring show the first problem over two lines and "...and 2 more". Not done: students using the guide on the real robot; the first session will show what's unclear.
- **The Calibrate page (14.7):** the whole session in the app: the robot and field, the plan's maps, writing the program, collecting from the card or USB, each test's result, the fit and its report, *Apply*, and the autonomous check with its pass marks. Robot logs play on the field as MCL logs do now (the logged poses' paths, the distance readings as rays, a timeline), beside the simulated run.
- **As built (14.7):** The Calibrate page has three tabs:
  - *Session*: the plan's whole session.
  - *Autonomous check*.
  - *Quick fit*: the page as it was, the routine's fit from one run.

  The services are in `vexsim/app/calsession.py`: the session's state, and its jobs `calibration_program`, `calibration_practice`, `calibration_usb`, `calibration_fit` and `calibration_check`. Robot logs become tapes in `vexsim/app/logtape.py`. The endpoints are under `/api/calibration/`, with `/api/robotlog` and `/api/image`. Where it differs from the plan, or says more:
  - *The session's steps,* down the page:
    1. The robot and the field.
    2. The program, planned and written. The plan's table shows each test, its runs, its place (from two walls) and its map. `/api/image` serves the maps, and only PNGs inside the workspace.
    3. Collecting: from the card, from a folder, or over USB. USB is a job that runs `pros terminal` until *Stop listening*. That stop is graceful: the job is told to stop, and has 5 s to end the terminal and save the log it's receiving before it's ended.
    4. Each test's runs, with what each measured (`run_result`):
       - the free spin's speed;
       - the IMU's drift, and its error over the turns;
       - the push's wheel travel against the lane's length;
       - a driving run's length, top wheel speed and turn.

       Each run has a *Use* box.
    5. The fit and its report, read from `report/report.json` (written beside `report.md` by the fit), and *Apply*.

    The sessions are listed beside the page, and in the workspace list as items of their own (`calsession`). A session's runs and report aren't listed on their own.
  - *Practice in vexsim first,* not in the plan. The simulated student runs the program from step 2, test by test, on the robot made unlike its config (`student.unlike`):
    - the wheels at 3.20/3.25 of their size;
    - the IMU 0.25% further off;
    - the wheels' grip and rolling as on real tiles;
    - voltage commands held to rated speed;
    - the real distance sensors.

    Its logs go into a practice session (`practice: true` in `session.yaml`). A practice session refuses real logs, and a session with real runs refuses practice. The student needs the plan the program was written with, so `write_plan` now writes `plan.json` too: the tests in the menu's order, with their numbers, kinds, spots and maps. The page reads the same file.
  - *Apply* writes what the fit found into the robot's config in its editor, in place with the comments kept, for the student to look over and save. The quick fit's *Add the fitted values* works the same way. The report keeps a digest of the config it was fitted to, and Apply refuses a config that has changed since ("fit the session again").
  - *The autonomous check:*
    - The page reads each end as it's typed (`/api/calibration/end`): where the robot ended, and a warning when the two corners don't fit the robot's outline.
    - The team's pass marks are saved to `.vexsim/calibration.yaml` from the page.
    - Checks are kept as results in `.vexsim/checks/`, with their report's plots.
  - *Robot logs on the field:*
    - The workspace finds format-2 logs by their `# vexsim-log:` line.
    - A log plays from its code's first pose, from its first `setPose` on (as `--follow` takes it). Each distance sensor's reading is a ray from where the config mounts it. The other poses are drawn beside it, each with its path (`LogPath`, a point a frame).
    - A calibration log has no pose of its code's, so it plays from its spot by odometry. Its heading comes from the IMU, with its configured scale error. Its travel comes from the drive motors, by least squares through the drive's kinematics. It plays with the robot and field the log names.
    - A routine's log gets *Run left40* (its routine, by the log's name). It runs the routine from the run bar's program, in autonomous, from the routine's `setPose`, on one timeline with the log.
    - A log with nothing to play, such as the quick fit's routine log, opens on the quick fit, as robot logs did before. `/api/robotlog` answers it with `NothingToPlay`, a 200, not a 422: it's a log for a fit, not an error.
  - *A fix to the session's fit.* With only some driving tests (straight and spin runs, no arcs), the drive step can't pin the longitudinal μ: it came out 79 ± 29. The second round used it anyway, and put the wheels at 3.25 in against the truth's 3.20. The second round now carries forward only the drive values the logs pin down.
  - *The checks:*
    - `tests/test_calibration_app.py`, fast: the tapes and odometry; the workspace's sessions and logs; each run's result line and *Use*; practice and real runs kept apart; Apply and its refusal; the pass marks and ends; the USB job's graceful stop; the endpoints.
    - Its session-marked test runs a whole session through the services (program; practice of five tests; fit; apply) and finds the wheels within 0.02 in.
    - `frontend/e2e/calibrate.spec.ts` runs a whole session in the app: written, practiced, fitted with the held-out run matching, applied, and a run played on the field. It also plays a routine's log beside its routine and checks the routine against it. That log is written by the simulated 1239E running Left 40 with `--sd`.

    CI's browser job installs the `viz` extra as the guide does, since the maps and plots need matplotlib; without it, the page says so where they'd be.

    Not done: a real robot's session in the app.
- **Testing without the robot:** "real" robots in the simulator, each a config with hidden changes: wheels 3.20 in, an IMU 0.25% off, omni friction 0.75, voltage mode capped at rated speed, the real distance sensors' noise, a motor reversed in the config, two distance sensors swapped. Each runs the generated program in vexsim, by scripted controller presses, with `--sd`; the session tools have to recover each value and catch each mistake. The same for `full_omni_6m`, with its two tracking wheels. The first session on the real robot is the real test; its logs tune the warnings and thresholds.
- **Risks:** an open-loop test can hit an element, so the plan covers the parameter spread with a margin, leaving the plan's envelope stops the robot, and any button does. The shim's headers can differ from PROS's, so the program uses only PROS 4 C API calls, each checked against PROS 4's own headers, and a CI job builds it with the real PROS kernel and ARM toolchain if the network allows. PROS may not make folders on the card, so logs go to its root, numbered by a counter file, as 1239E's MCL logs were. A fit can trade one parameter for another (a lighter robot, or more grip), so each test measures only a few, in an order where each fit builds on measured values, and the report says which values the logs pin down.

## 17. Faster, roomier, harder to trip over (phase 15)
A review of the whole project (2026-11-17), by measuring it: the simulator's speed and where its time goes, the server's endpoints and its live stream, the page in Chromium (load, CPU, memory), every page at a laptop's size, an accessibility audit, and the code's shape. The server, the page's weight and the build loop are fine. The gains are in the simulator's own speed, the Simulate page's layout on a laptop, and a handful of traps in the everyday flow.

**What was measured** (this repository, a 4-core Linux container, headless Chromium):

| What | Result |
|---|---|
| Simulator, a robot sitting still, no field | 12 to 14× real time (73 to 93 µs for each 1 ms step) |
| Simulator, 1239E Left 40 (C++, LemLib, MCL) | 4× real time: 15 s of autonomous in 3.7 s. 74% of it is vexsim's own Python, 26% waiting on the robot code (182 exchanges a simulated second, 360 µs each) |
| Parsing the robot code's drawings, headless | 10% of that run (2.76 s of Python CPU with, 2.48 s without) |
| Collision checks with nothing within 29 in | 19% of a step (123 µs against 104 µs with them off) |
| The app asked for 8× | delivers 4×, at 17 frames a second (each frame simulates up to 0.25 s) |
| Page load | usable in 0.9 s; 151 KB over the wire |
| Page, nothing running | 4.5% of a core; 9.5% with a finished run on show (the field redrawn 60 times a second) |
| Page, a live 1239E run | 18% of a core, 60 frames a second; heap 5 to 20 MB, flat over a minute |
| Server during a live run | 4 to 6% of a core; every endpoint under 230 ms (the workspace scan 190 ms) |
| The live stream | 200 KB/s, 74% of it the code's drawings; a recording is 107 KB per simulated second, 92% of its drawings the 128 MCL particles, written one by one |
| Rebuild after editing one file of 1239E's project | 2.4 to 2.9 s (first build 11.6 s, nothing changed 0.05 s) |
| Field at 1366 × 768 | about 330 px square (10% of the screen): 254 px of controls above it; 250 px after a run. At 1024 px wide the run bar wraps to four rows and the key covers half the field |
| Grey text | 3.5:1 against its background on 42 to 48 elements a page (4.5:1 is the mark) |
| Keyboard | 83 Tab presses from the top of the page to *Run* |
| Code | `App.tsx` 1,294 lines with 46 state variables, re-rendered 10 times a second in a run; `server.py` 1,755, `protocol.py` 1,950, `cli.py` 1,686; 12 of 59 endpoints declare what they return |
| CI | 6.5 to 16 min a Python job, 14.5 min the sessions, 10 min the browser tests |

**Decisions** (2026-11-17):
- The compiled physics step is a phase of its own, later (phase 16): it means keeping a second copy of the physics in step with the Python one. Measured again, it's worth about 1.7× on a C++ project and 3× on a Python program, not the 3 to 4× first estimated.
- The built page stays committed: the team installs from a clone, with no Node.js, and the app works offline. The repository grows about 330 KB for each change to the page.
- Nothing in this phase changes the simulation's numbers: the speed-ups only skip work that can't matter. Every existing test passes unchanged, but for the browser tests that open the key, which now starts closed.
- Running the Python tests in parallel wasn't tried (the session's permissions refused it), so it isn't in this phase.

**15.1 The simulator's quick wins**
- *No drawings where nobody watches.* `Simulation(drawings=False)` drops what the robot code draws: a Python program's `bot.draw` does nothing, and a C++ program is told so (`VEXSIM_DRAWINGS=0` to the robot host), so `vexsim::draw_*` returns before it formats a line. Off where nothing shows them: sweep trials, benchmark trials, the calibration's replays and the autonomous check's runs, practice sessions, route runs, and `vexsim run --headless` without `--screenshot`. On for the app's live runs (they're recorded) and the viewer.
- *No collision checks while nothing is in reach.* The arena already skips each element that's too far to touch, one by one, every millisecond. Instead it remembers how much room the robot had at its last full check, and skips the fixed elements altogether until the robot has moved that far. The skip is exact: within that distance the full check would have found nothing.
- *Smooth pacing.* The app's worker simulates what real time owes, but only for most of a frame's time (as "as fast as possible" already does), so a speed the computer can't reach gives the fastest it can at 60 frames a second, not a quarter second of simulation a frame. The run bar says the speed reached beside the one asked for.

- **As built (15.1):** `Simulation(drawings=False)` (`Drawings(enabled=False)`, `VEXSIM_DRAWINGS=0`, `vexsim_drawing()` in the runtime, checked in `sim.hpp` before a line is formatted); `Arena._room` and `_remember_room`; `Worker.advance`. Measured on 1239E's Left 40, headless, the variants interleaved in one process (the machine's speed wanders by a quarter from minute to minute):

  | | Wall time for 15 s | Python CPU | |
  |---|---|---|---|
  | before | 4.41 s | 3.27 s | 3.4× real time |
  | drawings off | 3.98 s (10% less) | 2.85 s | |
  | obstacle checks skipped while there's room | 3.95 s (10% less) | 2.85 s | |
  | both | 3.70 s (16% less) | 2.60 s (20% less) | 4.1× real time |

  The end state (pose, velocities, the code's own estimate) is the same in all four, to the last bit. Where it differs from the plan, or says more:
  - *The arena already passed by each far obstacle,* one at a time, every millisecond; the cost was the passing by (a footprint made and fourteen distances taken, each step). Now it keeps the robot's room at its last check that found nothing in reach: where its CG was, and the least distance any obstacle's circle was from the circle around its body, less a nanometer for rounding. Until the CG has moved that far it checks nothing. The walls had their own test already, and the pieces are left as they were (1239E's field has none in play, and a piece can be moved from outside).
  - *Drawings are off* for sweep trials, benchmark trials, the autonomous check's runs, practice sessions, route runs and `vexsim run --headless` without `--screenshot`. The calibration's replays never had a program. `vexsim::drawing()` and `bot.draw.shown` say which, for code that would rather not work out what to draw. A program's mistakes (a color that isn't one) are still mistakes when nobody watches.
  - *Pacing:* asked for 8×, the app showed 4× at 17 frames a second; now 3.5× at 60, the same as *Max* (a fifth of each frame's time is left for sending it). While a run is behind the speed asked, the worker doesn't wait for the next frame's time. The page says *3.5× real time (of 8× asked)*. At speeds the computer reaches, every millisecond owed is simulated as before.
  - *The checks:* the skip's run against the plain one, state for state, across open floor, into a barrier, along it and away (`test_elements.py`); a robot's room against the geometry; nothing kept or sent with drawings off, for a Python program and a C++ one, the rest of the run the same (`test_drawing.py`, `test_bridge.py`); the worker's pacing at a speed it can't reach and one it can (`test_ui.py`).
  - Not done: anything that changes the numbers. What's left is the step itself (56% of a profiled run) and the wait on the robot code (19%): phase 16.

**15.2 The field gets the screen**
- *One header row:* the name, the pages' tabs, then *Keys* and the theme, in one row.
- *The run bar folds to a line* in a short window (under 800 px high) once a run is on show: the saved run's name (or the robot and program), the routine, the mode, the start, with *Edit* to unfold it and *Run* still there. It's unfolded when nothing is running. A switch pins it either way.
- *The bottom panel* (console, build, problems, plots) folds to its row of tabs in a short window; a tab opens it, and its height drags.
- *The key is a pop-up* that starts closed (a *Key* button on the field), so it never covers the field or the hint in an empty folder. It stays open once opened, until closed.
- *The sidebar and the readout fold away* (a button each, remembered). Under 1100 px wide they start folded and open over the page.
- *The timeline* is one row.
- *Drawn only when it changes:* the field view keeps its animation loop but skips drawing when nothing it draws from has changed (the frame, the time shown, the view, the layers, the theme, the size), and while its page is hidden. `data-draws` on the canvas counts the draws, for the tests.
- *The README's pictures of the app* are made by a script (`frontend/scripts/pictures.mjs`), as the guide's are, so a layout change doesn't leave them stale.

- **As built (15.2):** `frontend/src/layout.ts` (the two window kinds, and each panel's kept choice), the shell in `App.tsx`, `RunBar.tsx`, `ConsolePanel.tsx`, `FieldView.tsx`, and the end of `styles.css`. Measured in Chromium, the field's canvas:

  | Window | Before | During a run | After it (its timeline below) |
  |---|---|---|---|
  | 1366 × 768 | 792 × 378 (the field 330 px, the key over its edge) | 800 × 562 | 800 × 507 |
  | 1024 × 700 | 450 × 298 (the key over half of it, the timeline cut off) | 998 × 494 | 998 × 446 |

  Where it differs from the plan, or says more:
  - *One header row,* at every size: ☰ (the workspace list), the name, the pages' tabs and the open files' (they scroll sideways when there are many), the version, *Keys* and the theme. The page on show is underlined on the bar's own edge.
  - *A short window* is 800 px high or less, *a narrow one* 1100 px wide or less (`SHORT`, `NARROW`). The browser tests' window, 1280 × 860, is neither, so they see the page as it was but for the header and the key.
  - *The run bar* folds once anything is on show (a run, a recording, a log), to the saved run's name, or the robot's, then the program, the routine, the mode and the start. *Edit* unfolds it, *Fold* folds it, and *Run* folds it again. A run that can't start (a start that isn't a number) leaves it unfolded: what's wrong is in it.
  - *The bottom panel* folds to its tabs with *Hide*; a tab opens it. A run that fails opens it by itself for as long as that run shows, and *Can't run* shows whether it's folded or not. Its heights already dragged (the console's and the plots' own corners), so nothing was added for that.
  - *The key* opens over the field from its button and scrolls if the field is shorter than it. The runs compared with are named beside the button all the while, open or not: their dashes need telling apart.
  - *The readings* fold from a button among the field's own (*Readings*). In a narrow window they open over the field's side, under those buttons: a browser test found them covering the button that closes them.
  - *The workspace list* in a narrow window opens over the page with the rest dimmed; a pick, Esc or a click beside it puts it away. Its tabs and *Refresh* stay at its top while the list scrolls under them (the pictures showed a long list scrolled with nothing to say what it was).
  - *Each choice is kept* per panel and per kind of window (`vexsim.panel.sidebar.small`, say), so folding the list away beside an editor doesn't fold it on a big screen.
  - *Drawn only on change:* each animation frame the field view gathers what its picture is made from (the run and its latest frame, the time shown, the start being dragged, the layers, the runs compared, the view, the colors) and draws only if any of it differs from the last draw. With a finished run on show it now draws nothing (60 a second before: 9.5% of a core); its page hidden, nothing.
  - *The README's pictures:* `frontend/scripts/pictures.mjs` makes six of the eight (the run, the comparison, the editor, the Design view, the maker, the sweep) on its own `vexsim ui`. Two stay as they were: the real robot's MCL log, which isn't in the repository, and the maker's motions, of a route made by hand. The Design view's is now of the example shaped robot, and the maker's of the example route as it is (its third step a move to a point).
  - *The checks:* `frontend/e2e/layout.spec.ts` (the field's size on a laptop during a run and after, the bar folding and unfolding, a failed run's output showing, the key closed and kept, no draws while idle or hidden; in a narrow window the list and the readings over the page, nothing past the window's edge, each row under the one before; in a roomy one each panel folding by hand and kept), `frontend/tests/layout.test.ts`. Two existing browser tests changed, by a line each: one opens the key before using its switches; the other (copy and paste between two robots' editors) now waits for the second editor's file before it presses Ctrl+V, a race it had always had and lost one run in four on a slower day. The other 34 pass as they were.

**15.3 Nothing stale**
- *Restart runs the code as it is now:* for a PROS project the build runs first (0.05 s when nothing changed; errors are shown and the old run stays), and a Python program is loaded again.
- *The list follows the disk:* the page asks for the workspace again when its window gets the focus back, and the server answers from a cheap stamp of the folder (names, sizes, times) when nothing changed. *Refresh* stays.
- *Run on save:* a switch in the run bar. While it's on, the server watches the run's own files (the program or the project's `src/` and `include/`, the robot, the field, the route) once a second, and a change starts the run again. Off, a changed file shows as "code changed" beside *Run*.
- *The address keeps your place:* the page, the Calibrate tab and session, the open config and the run on show are in the address (`#/calibrate/session?session=calibration/2026-11-07`), so reload returns there, and Back and Forward move between pages.

- **As built (15.3):** `vexsim/app/runfiles.py` (a run's files and their stamp), `Session.watching`, `fresh` and `look`, `UIServer.restart_session` and its watcher, `Workspace.stamp` and the scan it keeps, `frontend/src/address.ts`, and the shell in `App.tsx`. Measured here:

  | | |
  |---|---|
  | *Restart*, nothing changed | the new run in 10 to 14 ms, in the same session (a Python program, and 1239E's project) |
  | *Restart*, a Python program edited | the new run's first frame in 0.33 s |
  | A save of a Python program, *Run on save* on | told in 0.6 s, running again 1.0 s after the save |
  | A save of one file of 1239E's project | told in 0.9 s, built and running again 4.2 s after the save |
  | A run's stamp (1239E: 41 files) | 0.16 ms, twice a second while a page shows the run |
  | The workspace's stamp (this repository) | 1.9 ms, against 200 ms to scan it; a scan of a folder that's as it was, 2.8 ms |

  Where it differs from the plan, or says more:
  - *A run's files* are the robot, the field, the route, the input and the log it follows; a Python program and every module it imported from the workspace (the worker says which, once it has loaded them: `sources`); and for a PROS project, `project.pros` and whatever is in `src/`, `include/` (but for the SDK's headers, which the build replaces), `static/` and `static.lib/` at the time, so a new file counts. Their stamp is each one's size and time: nothing is read.
  - *Restart* is the server's now (`POST /api/sessions/{id}/restart`), not the worker's alone. If the stamp is what it was when the run started and its worker can start again (running, paused or finished), the worker restarts it in place, as before. Otherwise the run is checked and started as *Run* starts one: a new session in the old one's place, the project built first, a failed check answered with why (and the old run left as it is), a failed build shown as any failed build is. So *Restart* also restarts a run that stopped, failed, or never built; its button and R are live whenever there's a run.
  - *The plan had the old run stay on the field when a rebuild fails.* It doesn't: the rebuild is a new run, and the field is its from the start (the old one is in the run history). Keeping two runs alive to show the old one behind a failed build wasn't worth the second process.
  - *Code changed:* while a page shows a run, the server looks at its files every half second and tells the page (`changed`, with the files as the workspace names them) once they've stopped changing for one look: an editor saves in steps, and a half-written file isn't one to build. The page says so over the field's foot (*Code changed since this run started · Restart runs it*), where it costs the field no room; the plan had it beside *Run*, where it pushed the run's status onto a second row. A click on it restarts.
  - *Run on save* is a switch in the run bar (on its folded line too), kept in the browser. A change told while it's on restarts the run; so does switching it on with a change waiting. A run that failed to load or build is watched like any other, so the save that mends it runs it. A run that can't be checked at all (a robot config that doesn't read) has no session to watch: *Run* it again.
  - *The list follows the disk:* the page asks again when its window gets the focus back (once a second at most), with the stamp of the answer it has (`GET /api/workspace?unless=`); the server answers "unchanged" from the folder's stamp without reading a file. The stamp covers every file a scan looks at, a project's routes and the headers they're checked against, and the saved runs' file. A file written in the last 2 s makes no stamp (it could be written again with the same size and time: file systems' clocks are coarse, FAT's to 2 s), so the next look reads the folder. The server keeps its last scan by its stamp, so the other places that list the folder (duplicating a file, deleting one) don't read it again either. *Refresh* reads everything whatever the stamps say.
  - *The address* is the part after `#`, so the server never sees it: `#/sweeps`, `#/calibrate/check?session=...`, `#/edit?file=...`, `#/simulate?run=...`; the Simulate page with nothing on show has none. A new page, editor or Calibrate tab is a step for Back; a different run or session on the same page changes the address where it is. On arrival the page and Calibrate's tab are set at once, the editor when the folder is listed, the run when it's fetched (beside its session, if that's still there, so *Restart* works; not over a run in progress). An address that names what's gone (a deleted file, a pruned run, a typo) is put right in place.
  - *The run form was being lost at every reload:* the page saved its form as soon as it knew its folder, before the saved one had been read back, so the empty form replaced it. Older than this phase; found by the reload test. It's saved only once it's been restored.
  - *The checks:* `tests/test_stale.py` (a run's files and a project's; Restart in place, afresh after an edit to the program and to a module it imports, after a stop, and with why it can't; a program that doesn't load, watched and mended; a project rebuilt; "changed" told once, for the right files, and to a page that opens later; a folder not read again until it changes, its racy window, the project's routes and headers in its stamp; the server's stamped answers), `frontend/e2e/stale.spec.ts` (Restart with an edited program, the notice and its click; Run on save through a broken save and a mended one, kept over a reload; a file made elsewhere listed on focus, and "unchanged" answered; the address over reloads, Back and Forward, an editor, typed addresses and ones that name nothing; a reload back to the run on show with its form), `frontend/tests/address.test.ts`. One browser test of 15.2 changed by a line: it waits for its second run to start before waiting for it to finish (it had been reading the first run's *Finished*).

**15.4 A way in**
- *First run:* in a folder with no robot, the Simulate page shows where to start instead of an empty field: make a robot (*New robot…*), drive it (no program needed), add a starter program, use your PROS project, read the guide.
- *A starter program:* `programs/first_program.py`, written into the folder: a short autonomous and a tank drive, commented.
- *The guides in the app:* a *Guide* page shows the README and the documents in `docs/` (their text, tables, code and pictures), each heading with its own address, from the files beside the package; where they aren't installed, the links go to the repository's pages.
- *Calibrate's steps with their state:* the Session tab opens with its five steps in a row, each done, next or to do (from the program's folder, the session's runs and its report), a click going to the step; each step links to its section of the guide.

- **As built (15.4):** `vexsim/app/starter.py` and `guide.py` with their endpoints (`POST /api/programs/starter`, `GET /api/guide`, `/api/guide/doc`, `/api/guide/file`); in the page, `components/Steps.tsx` (a row of steps, each done, next or to do), `components/FirstRun.tsx`, `pages/GuidePage.tsx`, `markdown.ts` and `components/Markdown.tsx` (the documents read and drawn), `guide.ts` (where their links go), `pages/calibrate/steps.ts`. Where it differs from the plan, or says more:
  - *Start here* is four steps above the field: make a robot, drive it, add a program, run your program. Each is done by what's there (a robot that loads; any run; a program or a PROS project; a run of a program), the first that isn't is next and has the button that does it, and a step that's done has no button. It shows whenever a step is left and no run is going, so after driving a student sees what's next without closing anything; a run on the page counts at once, so the panel doesn't flash back between a run's end and its recording. It's gone when all four are done, and *Hide* puts it away for the folder (kept in the browser). So a team's folder that has robots, programs and runs never sees it.
  - *The plan had it instead of the empty field.* It's above the field: the field is where the robot shows as soon as there is one, and where its start is dragged.
  - *The starter program* (`programs/first_program.py`, or `first_program_2.py`: never over a file) is a short autonomous and driver control. The plan said tank drive; it's arcade through `bot.drive`, which drives every drivetrain and suits a keyboard (W and S, A and D), with tank drive as a commented line. Its autonomous is a square by `bot.chassis` on a tank drive and a second forward and back by power on a robot that can strafe: an X-drive or a mecanum drive has no `bot.chassis`, and an H-drive's has no way to tell where it is until the robot has sensors. It's run, in the tests, on every robot *New robot…* makes.
  - *The Guide page* shows the README and the nine documents in `docs/` from the files beside the package (a clone, which is how teams install it); installed without them, it lists them as links to the repository's pages. The Markdown reader is vexsim's own, about 400 lines and no dependency: headings with GitHub's ids (so the documents' own `#links` work), paragraphs, fenced code, nested and numbered lists and boxes to tick, tables, quotes, rules, and within a line code, bold, italics, links (inline, by reference, bare addresses) and pictures. Nothing in a document is treated as HTML. No syntax coloring.
  - *Links:* a heading's `#link` and a link to another document go there in the app (each has an address, `#/guide/cpp?at=the-build`, a step for Back); a link to anything else opens in a tab of its own. Inside VS Code's panel those depend on the panel: its bridge only opens the server's own pages, and wasn't widened for this.
  - *The session's steps* are the Session tab's five cards, in a row at its top: robot and field, plan and program, run and collect, check the runs, fit and apply. Done is the robot and field picked, the program in its folder, runs collected, a good run in use for every planned test, and a report. A click goes to the step's card; *In the guide* opens its section of the calibration guide. The Calibrate page's first lines link to the guide too.
  - *The checks:* `tests/test_start.py` (the starter on all five drive presets, in autonomous and from the sticks; never over a file; the documents listed, read, and only their pictures served; a copy without them; the endpoints), `frontend/tests/markdown.test.ts` (each mark, and what isn't one), `frontend/tests/documents.test.ts` (all ten real documents read with nothing of their marks left over, and every link and picture in them going somewhere: it found a wrong link in the README while this was written), `frontend/tests/steps.test.ts`, and `frontend/e2e/start.spec.ts`, which has a second `vexsim ui` on an empty folder: the steps, put away and kept; a robot made, driven with the keys, the starter added and run to its end; the guide's documents, sections, pictures and links, over Back and a reload; the session's steps and their links.

**15.5 Accessibility**
- *Grey text* at 4.5:1 or better against every surface it sits on, in both themes; a test computes it from the stylesheet's tokens.
- *A keyboard path:* a skip link to *Run*; the workspace list is one tab stop, with the arrow keys moving within it, Enter picking and the menu key opening an item's menu; the page tabs likewise.
- *Roles:* *Refresh* out of the tab list; a heading on the Simulate page.
- *An audit in the browser tests* (axe-core): every page, light and dark, with no serious or critical finding.

- **As built (15.5):** in the page, `roving.ts` (a group that's one stop for Tab), `scrollfocus.ts` and `components/ScrollPre.tsx` (a box that scrolls, scrolled from the keyboard), the text and fill tokens in `styles.css`; `tests/contrast.test.ts`, `tests/roving.test.ts` and `e2e/a11y.spec.ts`. Where it differs from the plan, or says more:
  - *The audit came first, and found more than grey text:* 81 serious or critical findings over the pages in both themes, of three kinds. Text too faint to read: the grey, but also every place a series or status color was used for words (links and switched-on buttons in the series blue, errors in the status red, *done* in its green, a warning in its yellow at 1.5 to 1 on the light theme), and white on the main button in the dark theme. Tab lists holding things that aren't tabs (*Refresh*; the console's *Open files in* and *Hide*; the open files' close buttons). Boxes that scroll but can't be reached to scroll them.
  - *Text has tokens of its own* (`--link`, `--bad-text`, `--good-text`, `--warning-text`, beside `--text-*`), and so do the fills that white text sits on (`--primary`, `--good-fill`, `--chip-fill`); the series and status colors are left for marks, where they were validated. Worst case against the four surfaces, before and after: grey text 2.9 to 4.8 (light) and 3.8 to 4.8 (dark); links 3.6 to 5.4 and 3.7 to 6.5; error text 3.9 to 5.2 and 2.8 to 5.2; *done* 2.7 to 4.8 and 4.1 to 5.8; warning text 1.5 to 5.6 (light); white on the main button 4.4 to 5.6 and 3.6 to 5.0. The unit test reads the three token blocks from the stylesheet, checks each text token against each surface and against the accent's wash over them, each fill under its text, that the two dark blocks agree, and that no rule colors text with a series or status color.
  - *One stop for Tab* is a hook, `useRoving`, on the pages' tabs, the open files, *Keys* and the theme, the list's tabs and *Refresh*, the workspace list, the run history, the bottom panel's tabs, and *Calibrate*'s and *Analyze*'s. Tab comes to the selected tab, else to where the keyboard last was in the group, else to what's picked, else to the first; a `MutationObserver` keeps that right as controls come, go and are picked, so a child component's own renders can't leave a second stop. Across a row, Left and Right move; down a list, Up and Down, with Left and Right for what's beside a row's own control (an item's ⋯ button, a run's four actions), which Tab passes by. So the plan's *menu key* is one of three ways to an item's menu: the Menu key or Shift+F10 (the browser's own event, at the item), or Right to its ⋯ button and Enter, which is the one a Mac has. The menu puts the keyboard back on what opened it when it closes, and Tab closes it.
  - *The arrow keys are a group's only when Tab brought the keyboard to it.* They are also the robot's (Up and Down, Left and Right are its sticks) and a recorded run's (Left and Right move through it, Home and End go to its ends). A student who clicks the *Console* tab and then drives with the arrows must still be driving: so a click leaves them as they were, and only after Tab does a group take its keys, and then takes all of them, whether or not there's anywhere to go (the driving and the timeline skip a key that's been taken). Tested both ways, with a recorded run and a live one.
  - *Run from the top:* Tab, Enter with the skip link (from any page: it comes to the Simulate page's *Run*, or with no robot yet to the first thing to set). Without it, 12 presses, each a group or a field: the skip link, ☰, the pages, *Keys*, the list's tabs, the list, *Saved run*, *Robot*, *Field*, *Program*, *Mode*, *Run* (13 with a PROS project picked, which adds *Routine*). It was 83.
  - *Roles:* the open files are no longer tabs, since a tab can't hold its close button: each is a button (`aria-current` when it's the one on show) with its close button beside it, in a toolbar next to the pages' tab list. *Refresh* sits in a toolbar with the list's tab list, and the console's select and *Hide* beside its tab list. The Simulate page has a heading, read out and not shown (its tab says it).
  - *Boxes that scroll:* the console, a job's log and a guide's code take a stop for Tab only while what's in them doesn't fit and nothing in them takes the keyboard (`useScrollFocus`); the readings and the plots always have one. The YAML editor's text says outright that it takes the keyboard (`tabindex`), which it did anyway: the audit can't tell from `contenteditable`.
  - *The audit* (`e2e/a11y.spec.ts`, axe-core 4.14, a dev dependency) runs each scene in the light theme and the dark: the Simulate page set up, with a run paused, with a finished run and the key open, its plots, the run history, the *Keys* dialog, an item's menu, *New robot* and *New route*; Sweeps, Bench, Analyze and its three tools, Build, Calibrate's three tabs, the Guide; a robot's YAML and Design view, a field's editor, the autonomous maker; an empty folder's *Start here*; and a narrow window with the list over the page. 25 scenes and so 50 audits, none with a serious or critical finding; it takes about a minute. It doesn't cover what axe can't judge: whether the order things are read in makes sense, or the field's canvas, which has no text alternative beyond the readings beside it.

**15.6 What the server sends, checked**
- *One table* (`protocol.RESPONSES`) says what each endpoint returns: a model, or nothing checked for files and pages. The tests' client checks every response against it, and a test fails for an endpoint the table doesn't have. The server doesn't check at run time: a recording is megabytes.
- *Drawings packed.* Measured, every layer changes on every MCL update, so sending only what changed would save nothing; the bytes are the particles. Runs of points of one color and size travel as one shape (`["points", color, size, [x, y, x, y, ...]]`) in the live stream and in recordings; `sim.drawings` and the drawing API are as they were, and old recordings still play.
- *A reload mid-run* gets what the code has drawn and the mark where a replay began: the session's catch-up left them out.

- **As built (15.6):** `protocol.RESPONSES` and `response_model`; the tests' client in `tests/conftest.py` (`check_answer`); `drawing.packed` and `count`; `Session.drawings` and `following`; `tests/test_answers.py`, and more in `tests/test_drawing.py`, `frontend/tests/draw.test.ts` and `frontend/e2e/logs.spec.ts`. Where it differs from the plan, or says more:
  - *The table* has the server's 66 endpoints, each with the model it answers with when it succeeds: 55 models (two unions, four lists), one that goes by its `kind` (a saved result is a benchmark's, a sweep's, a calibration's or a check's), a live run's WebSocket (each message a `ServerMessage`), and 9 with nothing to check (four that answer with nothing, the WebSocket a page holds open, four files). The page itself isn't in it: the table is the API. The generated pages of documentation (`/openapi.json`, `/redoc`) are turned off, which nothing used, so every route the server has is in the table.
  - *The tests' client checks every answer.* An autouse fixture wraps Starlette's test client and its WebSocket session, so whatever a test asks the server, the answer is matched to its route and validated against the table's model, with unknown fields refused, whether or not the test looks at it: 12 test files and their 21 clients, unchanged. An answer that says no (4xx) has to say why (a `detail`, or a `RunProblem`). A test fails for an endpoint the table lacks, and for an entry whose endpoint is gone, and the checker is tested on itself (a wrong model, a missing entry, a wrong message). Nothing it checked was wrong: the endpoints that send what they keep without validating it (the tape, the telemetry, replays, logs, job and result reads) all sent what their models say.
  - *No endpoint goes unasked.* With `VEXSIM_REQUIRE_ANSWERS=1`, as CI's run of every test has it, the run fails if an endpoint answered no test. Seven didn't: five of a calibration session's (state, collect, use, apply, saving the pass marks), which only the minutes-long `session` test asked, and in CI that test was skipped, since its job installs no server; the list of going runs; and cancelling a job. One quick test now asks all seven, the session's on a card of made-up logs.
  - *Packed drawings:* `packed` turns each run of two or more points of one color and size into `["points", color, size, [x, y, ...]]`, keeping everything in the order it was drawn; a point alone, and every other shape, goes as it is. It's applied where layers leave: the worker's `drawings` message, the tape's drawings, and an MCL log's tape (its particles). `sim.drawings`, `Drawings.layers` and `MclLog.drawings` hold what they held. The page fills a run in one path, and counts its points one by one, so the shape counts the tests read are what they were. Recordings made before hold single points and play as they did: `point` is still a shape.
  - *Measured,* a 1239E autonomous with MCL drawing (17.4 s, 128 particles an update), at real-time speed: the drawings in the live stream go from 152 to 66 kB a second (57% fewer), and the whole stream from 205 to 119 (42% fewer). Its recording as the page is sent it and reads it goes from 1.86 to 0.96 MB (107 to 55 kB a second of the run, 48% fewer). **On disk it's 8% smaller, not 40:** the tape is kept gzipped (0.30 to 0.28 MB), and gzip had already squeezed out what packing removes, the repeated `["point",` and `,"violet",4]`; what's left is the coordinates. So the plan's 40% holds for what travels and what the page parses, and not for the file.
  - *A reload mid-run:* the session keeps the last `drawings` and `following` messages, forgets them when a run begins, and its catch-up sends them after the overlay. In the browser test, a run is paused once its code has drawn, the page is reloaded, and the ten shapes are there; before, they came only when the code next drew.

**15.7 The big files split by feature,** one at a time, nothing else changed:
- `App.tsx`: the shell, with the Simulate page, the log bar, and the state each feature keeps (workspace, runs, the real robot's log, the config editors, the address) in files of their own.
- `server.py`: the server, the guard and the hub, with a router a feature (workspace and files, configs, routes, runs, sessions, jobs and results, calibration).
- `protocol.py`: a package, a module a feature, the generated TypeScript unchanged.
- `cli.py`: a package, a module a command group; `vexsim.cli:main` and `build_parser` where they were.

- **As built (15.7):** four commits, one a file, each with every test passing as it was (848 of pytest, 213 of the page's unit tests, 60 in the browser; none of the tests changed). The three Python files were cut by a script that moves each top-level statement, with the comments above it, into the module it's given, and works out each module's imports from the names it uses; so nothing was retyped. Where it differs from the plan, or says more:
  - *`protocol.py`* (2,098 lines) is `vexsim/ui/protocol/`: `base` and `scene`, then `workspace`, `sessions`, `runs`, `configs`, `routes`, `jobs`, `results`, `calibration`; `registry` (every model in the order the page's types are written, and `RESPONSES`); `typescript` (the generator), with `__main__` so `python -m vexsim.ui.protocol` still writes the file. Every model's schema is what it was, and `frontend/src/protocol.ts` is byte for byte the same, its first line included, which still says `vexsim/ui/protocol.py`. The largest file is `registry.py`, 513 lines of lists.
  - *`cli.py`* (1,687 lines) is `vexsim/cli/`: `analysis`, `running`, `projects`, `bench`, `calibration`, `calibrate`, `app`, on `common`. `build_parser` was one function of 535 lines: each group's commands are now added by a function in the group's module, called in the order the commands were, and `parser.py` has what's left of it and `main`. Every command's help text, and the function it runs, is what it was (compared for all 28 parsers), and so is every function's source. The largest file is 371 lines.
  - *`server.py`* (1,885 lines) is `vexsim/ui/server/`: `state` (`UIServer`), `hub`, `guard`, `checks`, `serving` (`serve`), and the endpoints, which were one function of 1,000 lines of closures: `workspace`, `configs`, `routes`, `runs`, `sessions`, `jobs`, `calibration`, `guide`, each a function that adds its endpoints to the app, their code as it was. The plan said routers; plain functions that take the app keep the endpoints' order exactly, which a router each wouldn't without care (two features' endpoints were interleaved), and FastAPI matches in that order. `app.py`'s `create_app` calls them in the order they were. Every route is where it was, with its handler's source as it was but for three helpers the closures shared, now functions of `common` (`run_problem`, `config_file`, `robot_config`). The package's `__init__` imports FastAPI itself, so `vexsim ui` still says what to install where it's missing. The largest file is 329 lines.
  - *`App.tsx`* (1,662 lines, 54 pieces of state) is 590, the shell: the header, the workspace list, the page on show, the dialogs, and what the features share (the page, the run form, a run's problem). What each feature keeps is a hook in `frontend/src/app/`: `useWorkspace` (the folder and its saved runs), `useRunForm` (what the form names, read from the server; its saved runs), `useRuns` (the run that's going and the recorded ones, and which the field shows: 376 lines, the largest), `useRealLog`, `useEditors`, `useAddress`, `useKeys`; `SimulatePage` and `LogBar` are the Simulate page's markup, and `shared.ts` what they all use. The plan's list had no run form, keys or shared file: without them the shell was still over 600. Of the old file's 1,604 lines that aren't blank, 1,488 are in the new files as they were; the rest are imports, and names now reached through a hook's result. The page's script is 5 kB larger (461 kB) for the plumbing.
  - *What it doesn't do:* the hooks hand each other what they need as arguments, in one order (the folder, the form, the runs, the log, the editors, the address), and `App` still re-renders as a whole on every frame of a run, as it did. Splitting the state so that only the field's part re-renders is a change of behaviour, and wasn't this sub-phase's.
  - *Afterwards, with phase 15 done:* the README's six pictures of the app that are made by `frontend/scripts/pictures.mjs` were made again (they were 15.2's: no *Guide* page, no *Run on save*, the old text colors). Making them showed vexsim's own tests and its starter program's template in the workspace list as Python programs, in the repository's own folder: the list went by a file's text holding `def autonomous`, and those hold programs in strings. It goes by what the file defines now (`Workspace`, with a test); a file that doesn't parse still goes by its text, so a program being typed stays listed.

## 18. The physics step, compiled (phase 16)
The simulator steps every millisecond in Python and NumPy. Phase 15.1 took what could be had without touching the step; this phase compiles the step itself, with the C++ toolchain vexsim already finds. It's the only phase that changes the simulation's numbers, so how much it may change them was decided first.

**What was measured** (2026-11-24, this repository, a 4-core Linux container; its speed wanders by a fifth from hour to hour):

| What | Result |
|---|---|
| A Python program (`tour.py` on `full_omni_6m`, 6 motors) | 116 µs for each 1 ms step. The step itself (`Robot.advance`) is 83 µs of it (72%); the sensors' work every millisecond 13, their sampling 6, the events and the loop 12 |
| 1239E Left 40 (C++, LemLib, MCL; 9 motors, 4 mechanisms) | 305 µs a step. The step is 144 µs (47%), the wait on the robot code 106 (35%), the sensors' sampling 20, the rest 35 |
| So, with a step that costs next to nothing | a Python program about 3× faster, 1239E's project about 1.8× |
| The step's arithmetic done in another order (the solve on the system reversed, `tanh` from the C library one at a time) | the solve differs by up to 1.5 × 10⁻¹² of its size in a step; six scenarios' paths end within 6 × 10⁻¹² mm of the plain step's over 10 to 15 s |
| Every step's velocities nudged by 1 part in 10¹³ | paths within 7 × 10⁻⁹ mm: the dynamics damp an error, they don't grow it |
| The same, by 1 part in 10¹¹ | the same, but 1239E's Left 40 once ended 30 mm away: a reading had sat on a rounding edge, and from there it was another run |
| A wheel off the floor | 0 to 1% of the examples' steps (more for a robot with a dropped center wheel) |
| Touching a wall or an element | 0.6% of Left 40's steps, 5 to 17% when driven among elements; 90 to 150 µs each. Walls and elements together cost 1.3 to 5.6 µs a step in autonomous runs |
| Copying nine motors' state to a compiled step and back, each step | 13 µs. Reading a number through a property over shared memory: 40 ns more than a plain attribute |

**Decisions** (2026-11-24):
- *The tolerance, first.* From the same state, one step of the compiled step gives every number within one part in 10⁹ of the Python step's (10⁻⁹ outright for a number under 1). A whole run from the same start stays within a nanometre and 10⁻⁷ degrees of the Python step's. Both are a hundred thousand times what rounding was measured to leave, and far under anything a model change would. Not promised: the same digits. A run where a sensor's reading falls within that distance of a rounding edge can part from its twin, as it could from a nudge of 1 part in 10¹¹; nothing in the measured scenarios came near.
- *The Python step stays the model.* `Robot`, `V5Motor`, `Mechanism` and the rest are what the documents describe and what a change is made to first. The C is a copy of their arithmetic, expression for expression, and nothing is in it that isn't in them.
- *Checked three ways:* the library's own check when it's first built on a computer (a made-up robot stepped by both, a few hundred steps); tests that step every example robot both ways from the same states, and run whole scenarios both ways; and a mode that runs both steps on every step of anything (`VEXSIM_STEP=check`), which CI runs the whole test suite under. A model change made in one copy only fails all three.
- *Optional.* Used when a compiler is found, the library builds and its check passes; else the Python step, without a word (`vexsim doctor` says which, and why). `VEXSIM_STEP=python` or `compiled` picks one; `compiled` is an error where it can't be had.
- *What's compiled:* the wheels' loads (with wheels lifting off), the motors with their firmware loops, current limit and heat, the mechanisms, the wheels' contact and its Jacobian, the solve, the pose, the battery. *What stays in Python:* walls and elements (already skipped while there's room, and rare), the pieces, the sensors, the events, and any supply that isn't the stock battery (a replay's logged voltage): the step takes its voltage and gives back the load.
- *The state is shared, not copied.* A robot's numbers live in one block of doubles the C reads and writes in place. The Python objects that held them (`V5Motor`, `MotorThermal`, `PowerSystem`, `Battery`, `Mechanism`, the contact state) become views of the block when the robot first steps: the same classes' methods, their numbers properties over it. So everything that reads or sets a motor, from a program to a test, works as it did, and the Python step runs on the same objects, which is how the check mode compares the two.
- *C, not C++,* built by the `gcc` beside the `g++` vexsim finds (one file, no library but the C one), into vexsim's build cache, loaded with `ctypes`: nothing to match Python's own compiler.
- *Not done, weighed:* stepping mechanisms and the thermal model less often, and resting a robot that isn't moving, were other ways to the same end. Compiled, a mechanism and a motor's heat are a few tens of nanoseconds a step and a resting robot's step the same few microseconds as a moving one's: nothing left to gain, and both would have changed the numbers.

**16.1 The step in C**
- `vexsim/physics/step.c`, a copy of the Python step's arithmetic, and `vexsim/physics/compiled.py`: where each number lives (one table, from which the C header is written and checked by a test, as the page's protocol types are), the build, the load, the library's own check, and the shared views.
- `Robot.advance` uses it from a robot's first step when it can: stock classes, one supply for every motor, a drivetrain within its sizes. Anything else steps in Python as before.
- `VEXSIM_STEP=python|compiled|check`; `vexsim doctor` reports the step.
- Tests: one step both ways from the same state, over every example robot and the states that take each branch (each control and brake mode, the current limit, derating, a lifted robot, wheels lifting off, mechanisms at their stops, pushes, traction wheels' friction circles); whole runs both ways (a Python program, driver input, walls and elements, a C++ project); the wheels' loads against NumPy's; no compiler, a build that fails, a robot it can't take. CI: the compiled step on Python 3.13's jobs, the Python step on 3.11's, and a job that runs every test in the check mode.

- **As built (16.1):** `vexsim/physics/compiled/`: `step.c` (the step, 440 lines of C) and `step_layout.h`; `layout.py` (the tables), `lib.py` (the library found, built, loaded, checked), `views.py` (the robot's objects over the block), `step.py` (`Compiled`, `engage`), `check.py`, `modes.py`; `Robot.advance`, `_step_python` and `step_name`; `vexsim doctor`'s line; `tests/test_step.py`. Measured here, the two steps interleaved in one process:

  | | Python step | Compiled | |
  |---|---|---|---|
  | A Python program: `tour.py`, 15 s | 115 µs a step | 26 µs | 4.5× faster: 38× real time |
  | 1239E Left 40 (C++, MCL), 15 s | 244 µs a step | 119 µs | 2.1× faster: 8.4× real time |
  | The step alone, 1239E's robot (9 motors, 4 mechanisms) | 144 µs | 3.1 µs, 1.9 of it the C | |
  | One step from the same state, every example robot, 3,000 steps of random commands each | | | the two differ by at most 1.5 × 10⁻¹³ of a number's size |
  | Whole runs, both ways: the tour; five robots driven for 9 s, two of them among walls, a goal and pieces; a C++ project; Left 40 | | | paths within 7 × 10⁻¹² mm |
  | The library, the first time on a computer | | | built in 0.4 s, checked in 0.1 s; found again in a millisecond |

  Every test that was there passes unchanged with either step (849), and with both compared at every step. Where it differs from the plan, or says more:
  - *A tracking wheel's noise is drawn every step now, and that changes the Python step's own runs.* The first whole run compared, the tour, ended 0.38 mm from its twin though every step of it agreed to 10⁻¹³. A tracking wheel drew its scrub noise only in steps where its sideways speed wasn't exactly zero, and on a straight drive that speed is zero or a rounding error, as the arithmetic falls: 4,022 of the run's 30,000 wheel-steps for one step, 4,023 for the other. One draw apart, the two runs had different noise from there on. It's drawn every step now (none comes of it at rest), and the two runs end 7 × 10⁻¹² mm apart. The price: a robot with tracking wheels and the default noise no longer gives the digits it gave before this phase, with either step (the tour's path moves by up to 1.5 mm). It's the same model with another sequence of noise, and it no longer hangs on rounding, here or between two computers. This is the one change to the numbers that is more than the tolerance.
  - *The state is shared as planned.* A robot's block holds its record (sizes, the body's numbers, the supply's), a record a motor (its state, its thermal model's, its constants), one a mechanism, and a column a wheel quantity. `V5Motor`, `MotorThermal`, `PowerSystem`, `Battery`, `Mechanism` and the contact state each have a view class, made from a table: the same class with properties over the block for its numbers. A robot's objects are given those classes at its first step (their numbers moved into the block), so nothing that holds one of them sees a different object. What a step reads that isn't a number (a spec, which supply, which thermal model) is a watched attribute: setting one marks the step to read its constants again. The robot's own few numbers (heading, time, the push on it) stay plain attributes, copied in and out each step (0.3 µs), and its arrays (`qdot`, the CG, the contact and mass matrices) are read where they are, by pointer, followed when one is replaced.
  - *Anything it can't take steps in Python,* on the same objects: a subclass of `Robot`, `V5Motor` or `Mechanism`, a motor whose supply isn't the robot's, more than 13 gear groups or 32 wheels. A supply that isn't the stock battery (a replay's logged voltage) is asked its voltage before the step and given the load after it, so calibration replays are compiled too.
  - *Wheels off the floor.* The Python finds the chassis plane with NumPy's least squares, whose answer for too few wheels is the one of least norm. The C gets the same from the 3 × 3 system's eigenvectors (Jacobi rotations), leaving out those NumPy's cutoff would. Ground forces from a nudge to far past tipping, on every example robot, load the wheels the same (0, 1, 2 and more wheels off).
  - *The walls stayed in Python,* against the plan's list: measured, they cost 1 to 6 µs a step in autonomous runs, and touching one is 0.6% of Left 40's steps.
  - *Found without running anything.* A built library is named by a digest of the source, the tables, the flags, and the compiler's path, size and time, so a process finds its library by reading two small files and looking at one. The compiler runs only to build. A build that fails, or a library that fails its check, leaves a note beside it and isn't tried again until the source or the compiler changes; `vexsim doctor` says why. Four processes building at once (a sweep's workers on a new computer) each build their own and put it in place; a test does it.
  - *`VEXSIM_STEP=check`* takes the compiled step from a copy of the state, then the Python step from the same state, which stands; a number further apart than the tolerance stops the run with its name (`motor 7 integral_v: … in Python, … compiled`). CI: the compiled step is required on Python 3.13's two jobs, the Python step taken on 3.11's two, and a fifth job runs every test in the check mode. `tests/test_step.py` compares the two on all of them.
  - *One existing browser test changed, by a number:* the Build page's check counts the doctor's passed lines, now four.
  - *One other existing test changed, and not for this phase.* CI's Windows jobs had begun to fail on their own, on the commit that only added this plan: `test_the_cpp_plans_as_the_python_does` ran g++ by itself, and g++ exited with status 1 where it had compiled a week before. Everything vexsim builds, it builds with the compiler's folder first on `PATH` (MinGW's helper programs find their DLLs there), and all of those still built. The test compiles that way now, links its harness statically on Windows, and shows the compiler's output if it fails. With that, every job passed.
  - Not done here: the rest of a millisecond (16.2), and saying in the app which step ran (16.3).

**16.2 The rest of a millisecond**
- With the step compiled, what a millisecond costs is the Python around it: every device asked to integrate and publish, every-millisecond events through the heap, the loop's own bookkeeping. Trimmed where that changes no number (a device with nothing to integrate or publish isn't asked; an event due every tick doesn't go through the heap), each measured, the results the same as 16.1's to the last bit.
- Walls in C only if contact turns out to matter in a run that's waited for.

- **As built (16.2):** `Device.integrates`, `SensorSuite.step`, `RotationDevice.integrate`, and the first test of `Walls.resolve` and of `Arena._robot_obstacles`. Measured on another computer than 16.1's table (the session's was replaced, by a faster one), all four interleaved in one sitting, in µs for each 1 ms step:

  | | Before the phase | 16.1 | Now, the Python step | Now, the compiled step |
  |---|---|---|---|---|
  | A Python program: `tour.py`, 15 s | 81 | 18.8 | 80 | 14.5: 5.6× faster than before the phase, 69× real time |
  | 1239E Left 40 (C++, MCL), 15 s | 149 | 64 | 153 | 62: 2.4× faster, 16× real time |

  Where it differs from the plan, or says more:
  - *What was left of a millisecond,* for the Python program after 16.1: the sensors' work each millisecond 10 µs of 27 (two tracking wheels at 3.3 µs each, and every device asked to add up motion it doesn't have and to publish a reading it hasn't got); events 14 (the sensors' sampling 4.5, the program's tick 3.8, the recorder 1.8); the compiled step with its Python 3.5; the walls 1.1.
  - *Three trims.* The suite asks a device to add up motion only if it does (`integrates`: a tracking wheel), and to publish only while a reading is waiting out its latency. A tracking wheel works out its travel on plain floats (NumPy's scalars are slow one at a time) and draws its noise as `sigma * rng.standard_normal()`, which is what `rng.normal(0.0, sigma)` computes. The walls' and the elements' first test (is anything in reach?) is on plain floats too.
  - *Not a bit different.* Twelve whole runs (six scenarios, each with both steps): every state every 10 ms, the tracking wheels' own angles, the console and the telemetry are what 16.1 gave, bit for bit. In the tests: a tracking wheel against the formula it replaced, every millisecond for 4 s; the noise against NumPy's, from the same place in the stream; no device asked that has nothing to do, and each reading still arriving when its latency is up.
  - *The walls stay in Python.* What they cost when nothing is in reach is now a third of a microsecond a step, elements included; touching one is rare in a run that's waited for (0.6% of Left 40's steps).
  - *Not done:* events due every tick still go through the heap (a microsecond a step; taking them out means keeping their order with every other event's by hand), and a sample still makes its reading object (4.5 µs a step, spread over ten devices). For a C++ project what's left is the robot code: of Left 40's 62 µs a step, 54 is waiting for it (182 exchanges a simulated second, about 300 µs each, its own work and the pipe's), and Python's part of an exchange is 10 (the readings formatted 5, sent 3, the reply applied 2). That's the bridge's shape, not the step's.

**16.3 Where it shows**
- A run's record says which step made it, and the app shows it; the Build page says whether the compiled step is in use, and why not.
- `vexsim ui` builds the step in the background when it starts, so the first run doesn't wait for it.
- The numbers, before and after, in the README.

- **As built (16.3):** `RunRecord.physics` and `Robot.step_name`; `prepare_step` in `vexsim/ui/server/serving.py`; in the page, `madeBy` and `runTitle` (`recording.ts`), the run list's hover and the Build page's words. Where it differs from the plan, or says more:
  - *A run's record says which step made it:* `physics` in its `run.json`, `compiled` or `python`, taken from its robot when the run ends (a run that ended before its first step has none, and neither have the records written before: they read as they did).
  - *The app shows it where a run's command already was:* hovering over a run in *Runs* gives its command, *Simulated with the compiled physics step* (or *the Python*), and what a click does. Not a column: it's a thing to be able to find out, not to read on every row.
  - *The Build page's check* is `vexsim doctor`, which has said which step runs, and why, since 16.1; the page's own words now say that it does.
  - *`vexsim ui` builds the step as it starts,* on a thread of its own (0.6 s, once on a computer), so a run's worker finds it made. Told to keep to the Python step (`VEXSIM_STEP=python`), it builds nothing.
  - *The numbers* are in the README where the step is described ([its section on the two steps](README.md#the-physics-step-python-or-compiled), and the models' section on speed), and above, in 16.2's table.
  - *The checks:* a run recorded with each step says so, in its message and its file; an old record without the field reads; the server's thread builds and checks the library into an empty cache, and builds nothing in Python mode; `serve` starts it. In the browser: a run's hover names the compiled step (`e2e/app.spec.ts`); `tests/recording.test.ts`.
  - *In CI,* against the run before the phase: the Linux job on the compiled step takes 6.7 min (10.4 before), the Windows one 12.2 (14.7), the calibration sessions 7.0 (8.4); the two jobs on the Python step take what they took (8.6 and 13.9 min); and the new job that runs every test with both steps, compared at every step, 9.2.

## 19. The 5.5 W motor (phase 17)
VEX makes two V5 Smart Motors: the 11 W one vexsim has simulated from the start, and the 5.5 W one (276-4842), smaller, with half the power and a fixed 200 rpm output, which teams mix into drives and use for light mechanisms. 1239E's six-bar robot has two on its drive, simulated as 11 W ones until now. This phase adds it: its model, what robot code sees of it, and where the configs and the app name it.

**What the research found** (2026-11-25). VEX's own pages, the forum and the PROS documentation are outside this environment's network, so they were read through web search; VEX's two graphs through the Purdue SIGBots wiki's copy of them (its source is on GitHub), and the software from the PROS kernel's and vexide's source:

| | 11 W | 5.5 W |
|---|---|---|
| Output | 100, 200 or 600 rpm, by cartridge | 200 rpm, fixed: it takes no cartridges |
| Encoder | 1800, 900 or 300 ticks a turn | 900, as the green cartridge |
| Power | 11 W continuous; VEX's curve peaks at 11.4 W | 5.5 W continuous; VEX's curve peaks at 6 W near 130 rpm; measured, 5.0 W |
| Torque | 2.1 N·m at stall (red), at the current limit | 0.5 N·m. VEX's curve: 0.52, flat to 106 rpm, then straight down to 0.2 at 200 rpm (the forum's measurer calls it idealized); measured, 0.47 at most |
| Current | limited to 2.5 A | the same 2.5 A: "the brain sees no difference" (James Pearman, VEX, 2021) |
| Voltage | the battery's | limited to about 8 V: it was made for VEX EXP's 7.2 V battery, and any command from 8 to 12 V gives the same free speed (VEX staff on the forum; vexide's `EXP_MAX_VOLTAGE = 8.0`) |
| Free speed | the motor holds velocity commands to rated speed; voltage commands run over it | the same; voltage commands reach about 150% of rated (measured, 2025), and the measured power peaks near 190 rpm, not VEX's 125 |
| The brain | shares the battery's current among more than 8 motors | VEXos 1.1.3 counts a 5.5 W motor as half an 11 W one in that |
| Software | `motor_get_type()` gives `E_MOTOR_TYPE_V5` (0) | `E_MOTOR_TYPE_EXP` (1), from VEXos 1.1.3; green only (code declares it green; vexide refuses another gearing and reports green) |
| Size | 155 g | 114 g |
| Rules | V5RC 2026-27 R10: all the motors' power together at most 88 W, unplugged ones included | |

Sources: VEX's knowledge base ("Understanding V5 Smart Motor (5.5W) Performance", "Understanding V5 Smart Motors") and product page (276-4842); the SIGBots wiki's motors page; the VEX Forum ("First look at VEX 5.5W V5 Smart Motors", "11w/5.5w V5 Motor Torque-Speed Curves - Based on Real World Data!", "Testing v5 motor performance", "Defining PROS small motor", "VEXos Version 1.1.3 for V5 issues"); PROS's `motors.h` and `vdml_motors.c`; vexide's `motor.rs`; the 2026-27 game manual's R10.

**The model** (decided 2026-11-25):
- The 11 W motor's model (a DC motor's line, the motor's own control loops, the current limit, its heat) with the 5.5 W motor's numbers, fitted to the measurements where there are any and to VEX's curve where not. Its line at full drive (8 V): 300 rpm free (150% of rated, measured) and 0.637 N·m at stall, so that it peaks at 5.0 W (measured), at 150 rpm; and a torque per amp that gives 0.47 N·m at the 2.5 A limit (measured). At 200 rpm that leaves 0.21 N·m, against VEX's 0.2.
- Not matched: the measured peak near 190 rpm. A DC motor's line peaks at half its free speed, and vexsim's model doesn't bend it; between 150 and 200 rpm the line is within a tenth of the measured power.
- Its drive is limited to 8 V, whatever the battery, in every mode. Commands still run to ±12 V (PROS's range), so from 8 to 12 V they give the same.
- Free current, the friction's split and the control loops' tuning as the 11 W motor's (nothing measured); its rotor's inertia half the 11 W motor's (a smaller motor; an estimate). Its heat: nothing published, so the 11 W motor's heat capacities scaled by weight (114/155), and its heat paths by its smaller surface (×1.23): estimates.
- `motor_5_5w.*` and `thermal_5_5w.*` override them, as `motor.*` and `thermal.*` do the 11 W motor's.

**Configs** (decided 2026-11-25):
- `cartridge: 5.5w` makes every motor of a drive group or a mechanism a 5.5 W motor, geared by `ratio` from its 200 rpm.
- A group or mechanism of 11 W motors names the 5.5 W ones among its `motors` in `motors_5_5w`. They're geared to turn it as fast at their 200 rpm as its cartridge's motors turn it at theirs: in a blue 36:48 drive, 2.25:1 up, to the same 450 rpm. That's how a team gears them so they don't fight; a config can't say any other gearing.
- The motor budget check (now the drive's motors, at 11 W each, against 88 W) counts each motor by its power.

**What robot code sees** (decided 2026-11-25):
- `motor_get_type()` and `get_type()` give `E_MOTOR_TYPE_EXP` (`MotorType::exp`) for a 5.5 W motor and `V5` for an 11 W one; the Python API's `get_type()` gives `"exp"` or `"v5"`.
- A 5.5 W motor is green, and stays green: `set_gearing()` to another succeeds and changes nothing, and vexsim says so once; it reports green, in green's units.
- In the brain's sharing of current among more than 8 motors, a 5.5 W motor counts as half.

**17.1 The model and the configs**
- `MotorSpec` for the 5.5 W motor, the 8 V drive limit, each motor's gearing within its group or mechanism (a third for a 5.5 W motor in a blue group), the configs' `5.5w` and `motors_5_5w`, the overrides, the brain's sharing, the compiled step with all of it, `vexsim motor-curves --cartridge 5.5w`, docs/models.md.
- Done when: on vexsim's dynamometer the 5.5 W motor gives 0.47 N·m at stall and 2.5 A, 5.0 W at its peak, 200 rpm under a velocity command with 0.21 N·m there, and 300 rpm free from a 12 V command as from an 8 V one; a mixed drive's 5.5 W motors turn at the speed their gearing says and share the load by their lines; the two physics steps agree on robots with 5.5 W motors to phase 16's tolerance; and every existing test passes unchanged, no number of a robot without a 5.5 W motor changing.

- **As built (17.1):** `Motor55Spec` and `Thermal55Spec` (subclasses of the 11 W motor's, with their own defaults, `reference_ratio` 18 and the overrides' group names), `MotorSpec.max_drive_v`, `V5Motor.gear` and `rated_power_w`; `GearGroupConfig` and `MechanismConfig`'s `motors_5_5w`, `motor_cartridge()`, `motor_gear()` and `power_w`; `PhysicsParams.motor_5_5w` and `thermal_5_5w`; `gear` and `max_drive_v` in the compiled step's motor record. Where it differs from the plan, or says more:
  - *The numbers it was fitted to come out* (to 0.001 N·m and 0.01 W): 0.470 N·m at stall and 2.5 A, 5.00 W at 150 rpm, 0.212 N·m at 200 rpm, free at 300.0 rpm under 8 or 12 V and 224 under 6.
  - *No number of a robot without one changed.* An 11 W motor's gear is 1 (a multiplication by 1 is exact) and its drive limit is the battery's (`min` with infinity is the battery's voltage), so the step's arithmetic is the same: phase 16's twelve reference runs (six scenarios, each with both steps, 1239E's Left 40 among them) are the same to the last bit, states, console and telemetry.
  - *A mixed drive* (a blue 36:48 group with one 5.5 W motor a side) has 0.81 of an all-11 W drive's torque at a standstill. Under velocity commands both kinds hold their rated speeds. Under voltage commands it runs a little over: lifted, its blue motors turn at 705 rpm against 680 without the 5.5 W motor, which, free at 150% of its rated speed against the blue motors' 113%, carries the load while they hold it back a little. That's the fighting teams report heating their 5.5 W motors; now the simulator shows it.
  - *A drive on the ground doesn't show the fifth less torque in its acceleration* when its wheels slip at the start: the test measures the torque at a standstill instead.
  - *The library's own check* takes 5.5 W motors too (a mixed drive, a mixed red lift, a 5.5 W intake held to 8 V): it agreed to 2 × 10⁻¹⁴ when rebuilt. The tests step a mixed robot both ways from the same states, 3000 steps of random commands.
  - *The configs' `cartridge` field and the page's types* take `5.5w`, so the Design view's list offers it already; the rest of the app is 17.2's.
  - *Docs:* models.md's new section (the research's table, the targets, what it gives, what's not matched, its heat, among 11 W motors), the README's config reference and overrides table, conventions.md, and the motor-curves chart of the 5.5 W motor (`docs/img/motor_curves_5_5w.png`).

**17.2 Robot code and the app**
- The C++ shim (the type, the fixed gearing and its warning), the Python API's `get_type()`, the Design view (5.5 W as a cartridge choice, and a mixed group's 5.5 W ports), the editor, the Analyze page's curves, the config summary, the motor budget; the built page.
- Done when: a PROS program reads `E_MOTOR_TYPE_EXP` for a 5.5 W port and `E_MOTOR_TYPE_V5` for the others; `set_gearing(blue)` on it changes nothing and says so; `move_voltage(12000)` and `(8000)` turn it at the same speed; a robot with 5.5 W motors is made and driven from the Design view; the Analyze page draws the 5.5 W motor's curves.

- **As built (17.2):** in the runtime (`devices.cpp`), `MotorPort.exp`, set from the device list's `5.5w`; `declared_ratio()` green for it whatever the code declares, `warn_gearing()` (one message for each kind), and `motor_get_type()`. The simulator sends each motor's cartridge by name. The Python API's `Motor.get_type()`. In the app, the cartridge lists end with *5.5 W motor (200 rpm)* (`cartridgeLabel`), a group or mechanism of more than one 11 W motor has a *5.5 W* box for its 5.5 W ports (`readSmallMotors`: some of its ports, written as they are there), and the motor-curves job takes `5.5w`. Where it differs from the plan, or says more:
  - *The checks,* in the bridge's test program (`small_motor`): an 11 W and a 5.5 W motor give types 0 and 1; declared blue, the 5.5 W motor still says green (PROS's 1, where port 1's blue motor says 2) and the console says once that the code's blue gearing changes nothing; 12 V and 8 V commands turn it at the same 300 rpm, 6 V at 224, and its windings get 8 V. In the browser: a new robot gets a 5.5 W motor a side among its six blue ones and a claw of a 5.5 W motor alone, from the Design view, saved (`motors_5_5w: [3]`, `[-6]`, `cartridge: 5.5w`) and driven.
  - *The Design view keeps the config valid as it changes:* new ports keep the 5.5 W ones still among them (dropping the key when none is); choosing the 5.5 W motor as the cartridge drops the box's ports; a box that would name every motor says to choose the 5.5 W motor as the cartridge instead. A single motor has no box: its cartridge says.
  - *Not done:* the robot's diagram doesn't tell a 5.5 W motor from an 11 W one (motors aren't drawn); the port list names a motor's group or mechanism, as before.
  - *A flaky test, fixed on the way:* the plan's own commit failed CI on Windows with Python 3.11 in `test_every_run_is_recorded`, which waited 20 s for a run's record as its session stopped; it waits 60 now, as its first wait already did.

**17.3 The six-bar robot, and calibrating with 5.5 W motors**
- 1239E's six-bar robot gets its 5.5 W drive motors (13 and 10); its sweep runs again and its README's numbers are the new ones.
- A calibration session's free spin fits the 11 W motors without the 5.5 W ones, whose own numbers stay the model's; a drive of 5.5 W motors only fits theirs (`motor_5_5w.*`).
- Done when: its routines run with them; its README's table is the new sweep's; the free spin of a simulated robot with both kinds recovers the 11 W motors' hidden changes as before.
