# VEX V5 Mechanics Simulator — Plan

**Status:** Final v1.1 (2026-10-26). Phases 1-7 complete. Next: Phase 8.

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
  devices/         port-addressed devices (motor, rotation, IMU, distance; GPS and controller later)
                   with their noise / quantization / latency models and presets (specs.py)
  algorithms/
    localization/  Localizer interface + baselines
    control/       Controller interface + baselines
  bridge/
    cpp/include/   PROS 4 shim headers (api.h, pros/*.h/.hpp) + vexsim/sim.hpp hooks
    cpp/runtime/   PROS C API over a device table, lockstep task scheduler, competition task,
                   robot host protocol loop, crash and hang reports
    build.py       project staging, incremental g++ build (LemLib from source and ASSET in Phase 8)
    host.py        robot host process and protocol
    program.py     CppProgram: a built project as a Simulation program
    doctor.py      toolchain check
  bench/           scenarios, metrics, Monte-Carlo runner (multiprocessing), HTML/CSV reports
  viz/             live top-down view, telemetry plots, replay, log export
  calibration/     fit model params from real robot logs (later phase)
  cli.py           vexsim run | build | doctor | bench | replay | validate-config
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
  type: differential            # differential | xdrive | mecanum | hdrive (later)
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
  - **Traction:** high lateral μ (later phase).
  - **Mecanum:** rollers at 45° (later phase).
- Drift appears on its own when lateral demand exceeds the friction limit. A fast turn on full omni slides outward and corrupts heading and odometry the way it does on a real robot.

### 5.3 Chassis
- A 2D rigid body with states (x, y, θ, vx, vy, ω).
- Each wheel has a stiff vertical spring to set its normal load. This handles weight transfer from acceleration (using CG height) and drop-center layouts without special cases.
- Drivetrain friction losses and rolling resistance.

### 5.4 Integration and field
- Semi-implicit Euler at 1 kHz, with adaptive substeps when friction gets stiff. A seeded RNG drives all noise.
- Field: the 12'×12' perimeter. The robot footprint collides with walls (impulse-based, with restitution and friction). Game elements come in a later phase.

## 6. Sensors
| Sensor | Model |
|---|---|
| Motor encoder | Quantized, 10 ms update. Follows wheel rotation, not robot travel, so slip corrupts it |
| Rotation (tracking wheel) | 0.01° resolution, configurable data rate. Diameter and mount offset errors, small scrub, optional lift-off events |
| IMU | Calibration period, heading bias drift, white noise, scale-factor error, mount yaw offset |
| Distance | Ray-cast against the walls, range-dependent noise, maximum range, invalid readings out of range |
| GPS | Later phase |
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
   + (Phase 8) LemLib built from source, static/ → ASSET symbols
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
3. **LemLib from source.** PROS templates ship LemLib as a precompiled **ARM** `.a`, which can't run on a PC. `vexsim build` reads the LemLib version from `project.pros`, fetches the matching LemLib source tag (cached), and compiles it with the shim. The first target is the LemLib 0.5.x line for PROS 4. Newer releases are validated as they come out.
4. **`ASSET()` paths.** LemLib path files in `static/` are embedded through linker symbols (`_binary_static_<name>_start/_end`). The build generates a C++ file that defines those symbols from the files' bytes, so `ASSET(path_txt)` and `chassis.follow(...)` work without changes.
5. **Lockstep scheduler** (deterministic simulated time):
   - Each PROS task is a host `std::thread` (MinGW UCRT64 uses the posix thread model), but only one runs at a time under baton passing. This matches FreeRTOS on the V5 user core.
   - `delay` and `delay_until` park the task until its wake time. Mutex waits park it until the mutex is free.
   - `RUN <t>` returns once all tasks are parked. Python then advances physics to the next wake time, sends the sensor values that changed, and runs it again.
   - Ready tasks resume in a fixed order (priority first, then the order they became ready), and a task that readies a higher-priority one is switched out at once, so identical inputs give identical runs at any speed.
   - Busy waits: a task making PROS calls without parking is charged 1 ms per 1000 calls, so polling loops advance time. A task that runs for a configurable wall-clock budget without any PROS call is reported, with its task name.
6. **Competition harness.** The sim calls `initialize()`, `autonomous()`, `opcontrol()` and `disabled()` as a field controller would, in the PROS competition task: a mode change deletes that task and starts the next, while user tasks keep running. Competition status bits match the mode (switch, field control, or none), and a disabled robot ignores motor commands. It supports a skills or match timeline and autonomous-only runs.
7. **Console and screen.** `printf` / `std::cout` and `pros::lcd` lines appear in a panel in the viewer and in the run log.
8. **Pose telemetry.** Ground truth always comes from the sim.
   - The robot's own estimate is read automatically from LemLib's odometry pose accessor, which works because LemLib is compiled from source.
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
  - LVGL / brain-screen UIs (they run headless)
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
| 8 | LemLib: build from source, `ASSET` embedding, pose readback | `lemlib_template` autonomous (moveToPoint, turnToHeading, follow) runs unchanged; C++ algorithms run in the bench |
| 9 | Field wall collisions; traction, mecanum, X-drive and H-drive models and layouts | Collision and new drivetrain tests pass |
| 10 | Calibration from real robot logs; game elements; GPS sensor | Fitted parameters reproduce a recorded run within tolerance |

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
