# Running PROS 4 C++ code

vexsim compiles your PROS 4 project for your PC and runs it against the simulated robot. You don't edit the project, and the source is the same code you upload to the V5:

```
vexsim run examples/robots/full_omni_6m.yaml --program examples/pros_projects/minimal_pros4 --start 0,0,90
```
![The example PROS project driving a square](img/cpp_square.png)

The example project's `autonomous()` drives a 24 in square using its own tracking-wheel odometry. Green is the true path. Blue is the pose the code reports.

LemLib projects work too: vexsim builds LemLib from source (see [LemLib](#lemlib)).

## Setup (once)
**Windows:** install MSYS2's MinGW-w64 g++ (the UCRT64 toolchain).
1. Install MSYS2 from https://www.msys2.org into the default folder, `C:\msys64`.
2. In the "MSYS2 UCRT64" terminal, run `pacman -S --needed mingw-w64-ucrt-x86_64-gcc`.
3. Add `C:\msys64\ucrt64\bin` to your PATH, or set `VEXSIM_CXX` to the full path of `g++.exe`. vexsim also finds MSYS2 on its own in `msys64` or `msys2` at the top of any drive (for example `D:\msys2\ucrt64\bin`).

**Linux:** g++ 11 or newer (`sudo apt install g++`). **macOS:** Homebrew's g++, with `VEXSIM_CXX=g++-14` (or whatever version you install).

Then check everything works:
```
vexsim doctor
```
```
[ ok ] compiler   /usr/bin/g++
                  g++ 13.3.0, target x86_64-linux-gnu, thread model posix
[ ok ] build      test program compiled and linked in 2.0 s
[ ok ] run        tasks, delays and mutexes run in lockstep with simulated time
```
On Windows the compiler line shows `C:\msys64\ucrt64\bin\g++.exe` and target `x86_64-w64-mingw32`.

## Build and run
```
vexsim build path/to/project                      # compile only
vexsim run ROBOT.yaml --program path/to/project   # build if needed, then open the viewer
vexsim run ROBOT.yaml --program path/to/project --mode driver    # drive it: keyboard or gamepad
vexsim run ROBOT.yaml --program path/to/project --headless --record run.csv --screenshot end.png
```
- **Builds are incremental.** Only sources whose code or included headers changed are recompiled. The first build also compiles vexsim's runtime once, which takes a few seconds.
- **Your project is never modified.** Build output goes to `%LOCALAPPDATA%\vexsim\build` on Windows, or `~/.cache/vexsim/build` elsewhere (set `VEXSIM_CACHE_DIR` to change it). `vexsim build --debug` compiles without optimization, for a debugger.
- **The PROS SDK in your project is skipped.** `include/api.h`, `include/pros/`, `include/liblvgl/`, `include/display/` and `firmware/` are replaced by vexsim's PROS 4 shim, and so is every header a template lists as its own in `project.pros`. Your own headers and sources are used as they are.
- **Includes work as in PROS.** A source in `src/<folder>/` can include a header in `include/<folder>/` by its bare name, as PROS's makefile allows.
- **The robot config must match your ports.** If the code uses a device on a port where the robot YAML has something else, the call fails with `errno = ENODEV`, as on a robot with a missing device, and the console says what's wrong:
  ```
  vexsim: port 7: the code uses a motor here, but the robot config has nothing on this port (calls fail with errno ENODEV)
  ```
- **The default mode for a PROS project is `autonomous`.**

| `--mode` | What field control does | `competition::get_status()` |
|---|---|---|
| `autonomous` | `initialize` (disabled), then `autonomous`: like a competition switch | connected |
| `driver` | `initialize`, then `opcontrol`: like a robot with no field connection | not connected |
| `match` | `initialize` (disabled), 15 s `autonomous`, 105 s `opcontrol`, then `disabled` | field control |
| `skills` | `initialize` (disabled), 60 s `autonomous`, then `disabled` | field control |

**From Python**
```python
from vexsim.algorithms.localization import Pose
from vexsim.bridge import CppProgram
from vexsim.config import load_robot
from vexsim.runtime.simulation import Simulation

program = CppProgram.from_project("path/to/project")  # builds incrementally
sim = Simulation(load_robot("robot.yaml"), program=program, start=Pose(0, 0, 90))
sim.start("autonomous")
sim.run_until_finished(30)
sim.close()  # ends the robot code's process
print(sim.console, sim.estimated_pose, Pose.from_si(sim.robot.pose))
```
`CppProgram(..., env={"AUTON": "left"})` passes environment variables your code can read with `getenv()`, for example to pick an autonomous routine.

## LemLib
```
vexsim run examples/robots/lemlib_example.yaml --program examples/pros_projects/lemlib_template --start 0,0,90
```
![LemLib's example program in the simulator](img/lemlib_template.png)

`examples/pros_projects/lemlib_template` is LemLib's own example program, unchanged except for one `moveToPoint` back to the start. Its autonomous runs `moveToPose`, `turnToPoint`, `turnToHeading` and `follow` along `static/example.txt`. `examples/robots/lemlib_example.yaml` describes the robot that program configures.

- **LemLib is built from source.** The LemLib template installs LemLib precompiled for the V5's ARM CPU, which can't run on a PC. `vexsim build` reads LemLib's version from `project.pros` and fetches that release's source from GitHub (with git, or as a zip). It then compiles it once per version and compiler, with LemLib's own headers replacing the template's copies. Offline, point `VEXSIM_LEMLIB_SOURCE` at a LemLib checkout. LemLib 0.5.x (for PROS 4) is tested.
- **`ASSET()` paths work.** Every file in `static/` is embedded under the name LemLib's `ASSET()` expects: `static/example.txt` is `ASSET(example_txt)`.
- **LemLib's pose shows up on its own.** Once `chassis.calibrate()` starts LemLib's odometry, the viewer's blue estimate and telemetry's `est_*` columns show LemLib's pose, with no `report_pose` call needed.
- **Start pose:** LemLib's (0, 0, 0) faces +y, so start the simulated robot with `--start 0,0,90`. Otherwise LemLib thinks it faces 90° away from where it really does.

## How simulated time works
The robot code runs in its own process, in **lockstep** with the physics:
- **Code takes no simulated time.** Only one task runs at a time. Simulated time stands still while a task runs, and moves on only once every task is blocked in `pros::delay`, `Task::delay_until`, a mutex or a notification wait. So a run is identical every time with the same seed, at any speed, console output included.
- **Scheduling follows FreeRTOS.** The highest-priority ready task runs first. Among equal priorities, the one that became ready first goes first. A task that makes a higher-priority task ready (by giving a mutex, notifying it, or creating it) is switched out at once.
- **Busy loops.** A task that keeps calling PROS functions without blocking is charged 1 ms of simulated time per 1000 calls, as a busy CPU would be. So `while (pros::millis() < t) {}` works. A loop that calls nothing at all (`while (true) {}`) can never advance time. It is stopped after 5 s of real time with the task's name (`--busy-timeout`; 0 turns this off, for example while paused in a debugger).
- **Crashes don't take the simulator down.** An invalid memory access, an uncaught exception or an `abort` ends the run with the task's name and its last console lines:
  ```
  error: robot code crashed in task 'User Autonomous (PROS)': segmentation fault (invalid memory access)
  ```

**Competition functions behave as on the V5**
- They run in the PROS competition task.
- When a period ends or the mode changes, that task is deleted. Like FreeRTOS, deleting it doesn't run destructors, and a mutex it holds stays held.
- Tasks your code creates keep running across modes.
- While field control has the robot disabled, motor commands are ignored, but the code keeps running.

**The brain has booted at time 0.** The IMU's power-on calibration is already done, so it reads 0° at the start. `imu.reset(true)` recalibrates. That takes about 2 s, so keep the robot still.

## What's simulated
| PROS 4 API | In the simulator |
|---|---|
| `pros::Motor`, `pros::MotorGroup` | Everything: `move*`, getters (and `_all`), brake modes, current and voltage limits, encoder units, gearing, zero position. See the PROS 4 behaviors below. |
| `pros::Imu` | Rotation, heading, yaw, z gyro rate, tare/set offsets, `reset`, `is_calibrating`. Pitch and roll stay 0 (flat field); acceleration reads 0. Heading is clockwise-positive, as on the V5. |
| `pros::Rotation` | Position, angle, velocity, reversal (negative port), `reset`, `set_position`. |
| `pros::Distance` | Distance to the field walls (no game objects yet). Confidence reads 63 and object size 400 when a wall is in range; object velocity reads 0. |
| `pros::Controller` | Master sticks and buttons from the keyboard, a gamepad or `--input`, with `get_digital_new_press` / `_new_release` as in PROS. Screen text is kept (`sim.controller_screen`). The partner controller is not connected. |
| Tasks, `delay`, `delay_until`, `Mutex`, `RecursiveMutex`, `MutexVar`, notifications, `millis`, `micros` | Everything (see above). |
| `pros::battery`, `pros::competition` | Battery voltage, current and charge from the battery model; competition status per mode. |
| `pros::lcd` (LLEMU), `pros::screen::print` | Text lines appear in the viewer's "brain screen" panel. Drawing calls are accepted and ignored. Screen buttons are never pressed. |
| `printf`, `std::cout`, `std::cerr` | Console panel and terminal, stamped with simulated time. |
| `pros::adi::*` (pneumatics, encoders, ...) | Not simulated yet. Outputs remember what was written, so a `Pneumatics` reads back as extended. Inputs and encoders read 0. The first use logs a note. |
| `pros::Optical`, `Gps`, `Vision`, `Link`, `Serial` | Not simulated yet. Calls fail with `errno = ENODEV`, and the first one logs a note. |
| LVGL, SD card, AI Vision | Not available. Code using LVGL or AI Vision headers won't compile. |

**PROS 4 behaviors that are reproduced, so they can bite in the simulator too**
- **Plain `MotorGroup` setters act on the first motor only.** `group.set_brake_mode(...)` and `group.tare_position()` change only the first motor; the `_all` versions change every motor.
- **`set_zero_position(p)` makes the current position read `p`.** The zero belongs to the motor on that port: every object using the port sees it. Like the PROS C API, the zero ignores reversal.
- **The gearing your code declares scales what the motor reports and does.** Declaring `green` on a `blue` cartridge makes `move_velocity(100)` spin it 3× faster than meant, and the motor reports a third of its true speed. The console warns once per port. If the code never declares a gearing, the motor uses the cartridge from the robot config.
- **Reversal is per object.** A negative port flips that object's commands and readings. Brake mode, limits, units, gearing and zero belong to the port.

**Show your own odometry in the viewer.** Call `vexsim::report_pose(x, y, theta)` from your odometry loop. The viewer's blue "estimated pose" and telemetry's `est_*` columns then show your code's estimate. It uses the LemLib convention: inches, with θ in degrees clockwise from +y. The example's `src/drive.cpp` shows the guard that keeps it out of robot builds:
```cpp
#if __has_include("vexsim/sim.hpp")
#include "vexsim/sim.hpp"
#endif
...
#ifdef VEXSIM   // defined by vexsim build
vexsim::report_pose(pose.x, pose.y, pose.theta);
#endif
```
Robot code sees field coordinates as it defines them. The x and y axes are vexsim's, but θ = 0 faces +y. If your code starts at θ = 0, start the simulated robot facing +y with `--start x,y,90`.

## Differences from the robot
- **Compute time is free.** A long calculation takes no simulated time. On the robot it delays everything at its priority and below.
- **Integer sizes.** `int` is 4 bytes everywhere. On the V5 `long` and pointers are 4 bytes. On 64-bit Windows `long` is 4 bytes and pointers 8; on 64-bit Linux and macOS both are 8. Code that assumes `sizeof(long) == 4` or stores pointers in `int` needs fixing.
- **Not modeled:** time slicing among equal-priority busy tasks (busy tasks are charged per call instead), mutex priority inheritance, and the slight delay before the IMU's calibrating flag appears (vexsim waits 5 ms, as PROS's `reset` does).
- **Libraries that ship precompiled for the V5's ARM CPU won't link,** because they are machine code for another processor. LemLib is built from source instead; others, such as OkapiLib, aren't supported.
- **newlib extras.** The V5's C library (newlib) has a few functions PC C libraries lack. vexsim provides the ones robot code and LemLib use (`infinity()`, `infinityf()`, and on Windows `isnanf()`, `isinff()`, `finitef()`).

## Troubleshooting
| Message | What to do |
|---|---|
| `no C++ compiler (g++) found` | Install it (see Setup) and run `vexsim doctor`. |
| `couldn't get LemLib 0.5.6's source` | vexsim needs the internet once per LemLib version. Offline, set `VEXSIM_LEMLIB_SOURCE` to a LemLib checkout of that version. |
| `ASSET(name) needs a file static/...` | Put the path file in the project's `static/` folder, named so its `.` becomes `_` (`static/skills.txt` is `ASSET(skills_txt)`). |
| `... defines autonomous() with C++ linkage, so it is never called` | Include `main.h` in that file. It declares the competition functions `extern "C"`. The V5 would silently skip yours too. |
| `robot code hung: task '...' ran for 5.0 s of real time without calling pros::delay()` | A loop has no `pros::delay`. On the robot it would starve every other task. |
| `port N: the code uses ... but the robot config has ...` | Make the robot YAML's ports match your code. |
| `pros::Optical is not simulated yet` | Expected for now. The call returned `PROS_ERR`. |

## How it works
1. **Staging.** `vexsim build` copies `src/` and `include/` without the SDK headers and template files into a build folder. A quoted `#include "api.h"` searches the including file's own folder first, so a staged copy is the only way to make the project's headers find the shim instead of the SDK.
2. **Compiling.** g++ compiles each source with `-std=gnu++20` (C files: `gnu11`), `-DVEXSIM=1`, and the shim's include folder (`vexsim/bridge/cpp/include`), keeping `-MMD` dependency files for incremental builds. Two generated sources join them: the `static/` files' bytes for `ASSET()`, and for LemLib projects a hook that reads LemLib's pose.
3. **Linking.** The objects are linked with LemLib (if used) and vexsim's runtime (`vexsim/bridge/cpp/runtime`) into a small program, `robot_host`. On Windows it is linked statically, so it needs no MinGW DLLs.
4. **The runtime** implements the PROS C API against a device table, plus a lockstep scheduler where every task is a thread but only the one holding the baton runs. Empty default competition functions are linked only when the code doesn't define its own, like PROS's weak defaults.
5. **The simulator** starts `robot_host` as a child process and talks to it over pipes. Before each run it sends the sensor readings that changed and `RUN <time>`. The host runs every task that's due until all are blocked, then replies with motor commands, console output and the next time it needs to run. Between those times the simulator doesn't call it at all. `robot_host` moves `printf` output off the protocol pipe before any of your code runs, even global constructors.
