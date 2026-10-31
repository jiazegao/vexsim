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
  cli.py           vexsim run | build | doctor | bench | replay | validate-config | ui
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
| 14.3 | The calibration program, in a slot of its own, its driving tests planned around the field's elements | For 1239E's robot and field, every test runs in the simulator from the program's menu by scripted button presses, each driving test clear of every element by its margin; a press stops the motors at once; the device check catches a reversed motor and two swapped distance sensors |
| 14.4 | Collect a session and fit it | From simulated "real" robots with hidden changes (1239E's, and `full_omni_6m` with two tracking wheels), the tools recover each value within its tolerance, a held-out run matches within the sensors' noise, and `--apply` writes the robot config with its comments kept |
| 14.5 | The autonomous check: the real routine against the simulated one | 1239E's Left 40 on a simulated "real" robot passes with the calibrated config and fails with the default one, at pass marks the team sets |
| 14.6 | The calibration guide, for students | `docs/calibration_guide.md` takes a student from an uncalibrated robot to a checked autonomous, every command written out, its pictures made from 1239E's robot and field |
| 14.7 | The Calibrate page | A whole session runs in the app, and a robot log plays on the field beside its simulated run |

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
- **Protocol:** JSON over a WebSocket per session, plus REST for the rest. Message types are pydantic models in `vexsim/ui/protocol.py`; `frontend/src/protocol.ts` is generated from them, and a test fails if it is stale.
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
- **Collect and fit a session (14.4):**
  - `vexsim calibration collect SESSION` copies new runs into `SESSION/runs/`: `--from-card` finds the card (a drive letter on Windows, `/Volumes` on macOS, `/media` on Linux), `--from FOLDER` takes a folder, and `--usb` wraps `pros terminal` and saves each log as it arrives. It checks each run (the robot's name and ports, finished or stopped, its warnings) and lists them in `SESSION/session.yaml`: the robot, the field, and each run's test, quality and whether the fit uses it.
  - `vexsim calibrate ROBOT.yaml SESSION` fits each test into what it measures, in an order where each fit uses the ones before: the wheels' diameters, the motors, the IMU, the drive (all its runs at once, one held out to check the result), the tracking wheels, then the distance sensors. A failed device check stops it, saying what to fix. A single log still fits as it does today.
  - Replays learn two things: a *lifted* robot (wheels off the ground) for free spin, and the per-device errors already measured (the IMU's scale) in place of ideal sensors.
  - The distance sensor model gains what the real sensors showed in [docs/1239e_real_vs_sim.md](docs/1239e_real_vs_sim.md): misses at glancing angles, more of them with distance, and a confidence that drops with both. Their defaults keep today's behavior (no misses, confidence 63), so nothing changes until a fit fills them in.
  - The report (`SESSION/report/`: `report.md` with its plots, and `changes.yaml`) gives each test's result, before and after, which values the logs pin down and which they don't, its warnings, and whether the held-out run matches within the sensors' noise. `--apply` writes the changes into the robot YAML (overrides, wheel diameters, sensor fields), keeping its comments, with a comment naming the session; it also prints the routes' `drive:` line.
- **The autonomous check (14.5):** the competition program, with the logger in it, runs a routine on the real robot. Before moving the robot, put tape at two of its corners and measure each from two walls; vexsim works the end pose out from the robot's shape. `vexsim calibration check-auton ROBOT.yaml LOG --program PROJECT --end MEASUREMENTS` then runs the same routine in vexsim from the log's start (the code's first pose), with a few seeds, and compares:
  - where the robot ended, simulated against measured, as a distance and a heading, against the pass marks;
  - the code's own pose, real against simulated, through the run, and the first moment they part by more than the marks;
  - heading, wheel travel and distance readings over time, to show where they part.

  The pass marks (2 in and 2° by default) are set in `.vexsim/calibration.yaml` (`max_distance_in`, `max_heading_deg`) or by `--max-distance` and `--max-heading`; marks finer than a tape measure can tell (0.5 in, 1°) get a warning. Several real runs of one routine are compared as a spread, against the seeds' spread.
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
- **The Calibrate page (14.7):** the whole session in the app: the robot and field, the plan's maps, writing the program, collecting from the card or USB, each test's result, the fit and its report, *Apply*, and the autonomous check with its pass marks. Robot logs play on the field as MCL logs do now (the logged poses' paths, the distance readings as rays, a timeline), beside the simulated run.
- **Testing without the robot:** "real" robots in the simulator, each a config with hidden changes: wheels 3.20 in, an IMU 0.25% off, omni friction 0.75, voltage mode capped at rated speed, the real distance sensors' noise, a motor reversed in the config, two distance sensors swapped. Each runs the generated program in vexsim, by scripted controller presses, with `--sd`; the session tools have to recover each value and catch each mistake. The same for `full_omni_6m`, with its two tracking wheels. The first session on the real robot is the real test; its logs tune the warnings and thresholds.
- **Risks:** an open-loop test can hit an element, so the plan covers the parameter spread with a margin, leaving the plan's envelope stops the robot, and any button does. The shim's headers can differ from PROS's, so the program uses only PROS 4 C API calls, each checked against PROS 4's own headers, and a CI job builds it with the real PROS kernel and ARM toolchain if the network allows. PROS may not make folders on the card, so logs go to its root, numbered by a counter file, as 1239E's MCL logs were. A fit can trade one parameter for another (a lighter robot, or more grip), so each test measures only a few, in an order where each fit builds on measured values, and the report says which values the logs pin down.
