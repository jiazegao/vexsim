# Calibrating the simulator to your robot

Most of the physics parameters are estimates: how well your wheels grip the tiles, how freely the omni rollers turn, how much rolling resistance slows a coasting robot. They differ from robot to robot and from field to field. Calibration measures them on your robot, with no extra equipment:

1. **Generate** a short drive routine for your robot.
2. **Run** it on the real robot, which logs everything its sensors measure.
3. **Fit**: vexsim replays the log in the simulator and adjusts the parameters until the simulated sensors read what the real ones did.

![A logged calibration run vs. the simulation, before and after the fit](img/calibration.png)

The black line is the robot's log. Orange dashed is the simulation with the default parameters; blue is the fitted simulation, on top of the log.

## 1. Add the routine to a PROS project
```
vexsim calibration-routine ROBOT.yaml MY_PROS_PROJECT
```
This writes four files into the project:
- `include/vexsim_calibration.hpp`
- `src/vexsim_calibration.cpp`, which holds your robot's ports and the routine's voltages
- `include/vexsim_log.hpp` and `src/vexsim_log.cpp`: vexsim's logger, which the routine logs with (the same two files `vexsim logger add` copies into any project)

Call `vexsim_calibration::run()` from `autonomous()`, or from `opcontrol()` on a button press:
```cpp
#include "vexsim_calibration.hpp"

void autonomous() { vexsim_calibration::run(); }
```
The files use only the PROS 4 C API, so they build with the normal PROS toolchain. They also run unchanged in vexsim, so you can try the whole process before touching the robot (see [Trying it in the simulator](#trying-it-in-the-simulator)). Regenerate them whenever the robot config changes.

## 2. Run it on the robot
The routine first calibrates the IMU, so keep the robot still. Then it drives, with fixed motor voltages and no feedback, for about 7 s (9 s for drivetrains that strafe):

| Step | Measures |
|---|---|
| launch from rest | traction limit and motor torque |
| coast | rolling resistance |
| reverse, then brake | back-EMF braking |
| strafe out and back (X-drive, mecanum, H-drive) | roller resistance |
| spin in place | roller friction and scrub |
| fast arc, then coast | sideways sliding (drift) |

**Before you run it:**
- The straight maneuvers run at about 47 in/s whatever the gearing, and the robot stays within about 4 ft of where it starts. Start in the middle of a field (or 3 x 3 m of open floor), facing the longer free direction.
- The fit assumes the robot touches nothing but the floor. If it hits something, run it again.
- Use the tiles you compete on, and a charged battery.

**Getting the log:** the routine logs with vexsim's logger (`vexsim_log.hpp`, which `calibration-routine` adds to the project with it).
- **With a microSD card** in the brain, the log is saved to `vexsim_0001_calibration.csv`, then `vexsim_0002_calibration.csv` and so on: each run gets the next number (`vexsim_count.txt` on the card keeps it).
- **Without one**, it is printed to the terminal between `#vexsim-log begin` and `#vexsim-log end` lines. Capture it with `pros terminal > run.txt` over USB; a wireless connection is too slow for this.

`vexsim calibrate` accepts either file as it is.

## 3. Fit
```
vexsim calibrate ROBOT.yaml vexsim_0001_calibration.csv --out calibration
```
```
Robot log: 700 rows (7.0 s): 6 motors, 2 rotation sensors, 1 IMU
  timing: the log's readings are 10 ms old
  ...
parameter                           before      after  uncertainty
wheel.omni.longitudinal_mu             0.9     0.7527  +/-0.066%
wheel.omni.lateral_mu                  0.2      0.278  +/-0.027%
wheel.omni.rolling_resistance          0.1     0.1397  +/-0.03%
battery.internal_resistance_ohm                  0.15  from battery voltage vs. current

RMS difference, simulated vs. logged (28 replays):
  motor velocity (rpm): 40.9 -> 3.01
  motor current (A): 0.108 -> 0.00234
  tracking wheels (deg/s): 292 -> 10.5
  heading rate (deg/s): 28.7 -> 0.787

Add to the robot config:
overrides:
  wheel.omni.longitudinal_mu: 0.7527
  ...
```
(That log came from the simulator itself with known parameters: 0.75, 0.28, 0.14 and 0.15 Ω.) Paste the `overrides:` block into your robot YAML; `--out` also saves it as `overrides.yaml`, with the plot (`calibration.png`) and the fitted replay (`simulated.csv`). A fit takes about half a minute; `--workers` sets how many replays run in parallel.

**What it fits.** By default, the wheel parameters for every wheel type on the robot:

| Wheel type | Parameters |
|---|---|
| omni | `longitudinal_mu`, `lateral_mu`, `rolling_resistance` |
| traction | `mu`, `rolling_resistance` |
| mecanum | `grip_mu`, `roller_mu`, `rolling_resistance` |

`--fit` takes any comma-separated list of physics parameters instead (`vexsim validate-config` lists them), e.g. `--fit motor.free_current_a,wheel.omni.rolling_resistance`. The battery's internal resistance is read straight off the log: it is the slope of the battery's voltage against its current.

**Reading the result.**
- The uncertainty is statistical: how sharply the log pins each value down. A parameter marked "poorly determined by this log" hardly changed what the sensors read. For example, `lateral_mu` needs a horizontal tracking wheel or an IMU to show the drift.
- Compare the RMS differences after the fit with the sensors' own noise: a few rpm for motors, around 10 deg/s for tracking wheels, about 1 deg/s for the IMU. A much larger leftover means something the model doesn't capture: the robot touched something, a wheel slipped on a tile seam, or the robot config is off (mass, wheel diameters, ports). Check the plot.

## Checking the model on another run
A fit can match the run it was fitted to and still be wrong. Check it on a different run:
```
vexsim calibrate ROBOT.yaml another_run.csv --fit none
```
This replays the log with the robot config's current parameters and prints the RMS differences, with no fitting. The tests do exactly this with simulated "real" robots (`tests/test_calibration.py`). The fitted model must reproduce a run it never saw within 3° of total turn and about 0.2 in of tracking-wheel travel.

Any program can make such a log with vexsim's logger: `vexsim logger add MY_PROS_PROJECT` copies it in, then `vexsim_log::start("name")` begins a log and `vexsim_log::stop()` saves it (the README's [vexsim's logger](../README.md#vexsims-logger) has the rest). It samples every 10 ms in its own task. It doesn't know what your code commanded (unless the code tells it, with `vexsim_log::command`), so the replay drives each motor with the voltage the motor reported (see [How the replay works](#how-the-replay-works)).

To compare a program's simulated run with its real one, log the simulated run too: run it with a folder standing in for the SD card, and its own logger writes the same file there,
```
vexsim run ROBOT.yaml --program MY_PROS_PROJECT --headless --sd sim_card
```
or have the simulator record what the robot's sensors read, whatever the program does: `--robot-log sim_run.csv`.

## Trying it in the simulator
`examples/pros_projects/calibration` is the routine for `examples/robots/full_omni_6m.yaml`:
```
vexsim run examples/robots/full_omni_6m.yaml --program examples/pros_projects/calibration --headless > run.txt
vexsim calibrate examples/robots/full_omni_6m.yaml run.txt
```
Here the "robot" is the simulator with its default parameters, so the fit leaves them about where they are. To see it find different values, add overrides to a copy of the robot config before `vexsim run`, then calibrate with the original.

## The log format
CSV, one row every 10 ms, written the same way by the robot (vexsim's logger, `vexsim_log.cpp`) and by the simulator (`--robot-log`). Readings are raw, as PROS reports them for a positive port: a motor on a negative config port reads backwards, and a rotation sensor reads as if it weren't reversed.

This is format 2. Before the header, `# key: value` lines say what the log is:
```
# vexsim-log: 2
# name: Left 40
# started_ms: 2350
# mode: autonomous
# battery_pct: 98
# devices: 1 motor, 2 motor, 10 imu, 13 distance
# robot: 1239E 2026-27
time_ms,battery_mv,battery_ma,m1_cmd_mv,...
0,12620,410,...
#mark,500,intake on
```
`name` is the one `vexsim_log::start` was given, `started_ms` the brain's clock then, `mode` the competition mode it started in, `devices` what the logger found on each port; `vexsim_log::info` adds the rest. Among the rows, `#mark,<time_ms>,<text>` lines are the code's marks (`vexsim_log::mark`) and the competition mode's changes (`mode: disabled`). Format 1, the calibration routine's before the logger, is only the header and rows, with `d<p>_mm` alone for a distance sensor; it still reads.

Motors come first, every one of them (the drive's and the mechanisms'), then the other devices, each by port:

| Column | Meaning |
|---|---|
| `time_ms` | since the log started |
| `battery_mv`, `battery_ma` | `pros::battery` |
| `m<p>_cmd_mv` | the voltage command the code gave, raw direction; 0 = stopped with the brake mode; empty if unknown |
| `m<p>_cmd_rpm` | velocity command (`move_velocity`); empty if unknown |
| `m<p>_brake` | brake mode: 0 coast, 1 brake, 2 hold |
| `m<p>_deg`, `m<p>_rpm`, `m<p>_ma`, `m<p>_mv`, `m<p>_temp` | position, actual velocity, current, voltage, temperature |
| `r<p>_cdeg` | rotation sensor position (centidegrees) |
| `imu<p>_deg` | IMU rotation (degrees, clockwise) |
| `d<p>_mm`, `d<p>_conf`, `d<p>_size` | distance sensor (empty when nothing is in range), its confidence (0 to 63) and the object's size (0 to 400) |
| `gps<p>_x_m`, `gps<p>_y_m`, `gps<p>_heading_deg`, `gps<p>_error_m` | GPS |
| `pose_<name>_x_in`, `pose_<name>_y_in`, `pose_<name>_theta_deg` | a pose the code logged (`vexsim_log::pose`), as LemLib has them: inches, and degrees clockwise from +y |
| `val_<name>` | a number the code logged (`vexsim_log::value`) |

## How the replay works
`vexsim/calibration/replay.py` gives the simulated robot the log's motor commands at the log's times and reads its sensors every millisecond. It differs from a normal simulation in four ways:
- **No sensor errors.** Sensors read without noise or per-device errors, which the model can't know for your particular robot.
- **Reading age.** A reading is a few ms old by the time robot code sees it: the sensor's latency, plus however long ago its last 10 ms update was. That depends on the phase between the logger's loop and the sensor, and it stays the same through a run. The replay finds it from the motor currents, which jump the moment a command changes, and compares each row with the state that long before.
- **Battery.** The motors see the battery voltage the log recorded, so battery modeling errors stay out of the fit.
- **Motors without logged commands** are driven with their logged voltage. That voltage is itself a reading, so it is applied a little early; the replay tries leads from 0 to 25 ms and keeps the one that fits.

The robot starts at rest on an endless floor, so start every log with the robot at rest and away from walls.

The fit itself (`vexsim/calibration/fit.py`) is Levenberg-Marquardt over the logarithms of the parameters, so values stay positive and steps are relative. Each step costs one replay per parameter, for a finite-difference Jacobian.

What it compares:
- motor velocity and current for every drive motor;
- tracking-wheel speed and IMU heading rate, each over 30 ms windows.

Rates rather than positions keep the drift every open-loop replay accumulates from swamping the comparison. Each group (motor velocity, current, tracking wheels, heading rate) gets equal weight, however many sensors it has.

## A calibration session: the plan and the program
The routine above needs open floor and fits everything from one run. A session (phase 14) tests each part of the robot on its own, on a field with the season's elements in place, from a program of its own in a spare slot, so calibrating never touches the competition code:
```
vexsim calibration plan ROBOT.yaml FIELD.yaml --out plan
vexsim calibration program ROBOT.yaml FIELD.yaml vexsim_calibration   # in a project made with pros c n
```
`program` plans too (into `vexsim_calibration/plan/`), then writes the program. Put it on the robot with `pros upload --slot 8` and run it from the brain's screen; no competition switch is needed. The fits that read a session's logs are phase 14.4's.

### The plan
`vexsim/calibration/plan.py` finds where each test that moves the robot fits:

- **Driving tests** (`routine.drive_tests`): the routine's maneuvers, each from rest on a spot of its own and ending braked. *Straight*: launch, coast, reverse, brake. *Spin*: turn in place, coast, brake. *Arc*: a fast arc, coast, brake. *Strafe* (drives that can): out and back. Each runs three times.
- **The spread.** The robot isn't calibrated yet, so each test is simulated in five variants of it: as configured; rolling further (rolling resistance x0.6, roller friction x0.7, grip x1.2, motors 10% faster, 15% lighter); stopping sooner (rolling resistance x1.5, grip x0.7, motors 10% slower, 20% heavier); sliding more (roller friction x0.5, grip x0.6); gripping more (roller friction x1.6, grip x1.4).
- **The room.** The robot's shape, swept along every variant's path, must stay `--margin` (6 in) clear of the walls and of every element, those a robot can drive over (`solid: false`) included: a log needs flat tiles. Game pieces are left out; clear them off the field first.
- **The search.** Starts on a 0.5 in grid over the field, headings every 15 degrees: for each heading, an FFT correlates the swept area with the cells too near a wall or element. Square headings win if any fits; then the spot with the most room, in the middle of it. A test with no room is tried at 85%, 70% and 55% of its speed and drive time; below that, the plan names what's in the way at its closest try, and the test is left out.
- **The push lane:** the longest of 96, 84 and 72 in that fits (3 in clear: it's pushed by hand), with tape lines where the robot's front edge starts and ends.
- **Spins in place** (they turn by the IMU, so only with one): the slow spin, 5 turns (robots with tracking wheels), and up to 3 spots for the distance sweep, one turn each (robots with distance sensors), picked one at a time to see the walls and elements at distances, in 100 mm steps, the others don't.
- **The envelope:** each driving test's most motor travel and IMU turn over the variants, times 1.15, plus 20 and 15 degrees. The program stops a run that would leave it.

Each spot is given as distances from two walls, to the half inch (the plan's pose is the one those numbers give): square to the walls, two of the robot's sides, each from the nearer wall unless only the farther one's tape line misses the elements; otherwise two of its corners. `--out` writes `plan.txt`, `plan.yaml` (each spot, its steps, scale and envelope) and a map of each (with matplotlib): the field, the robot on its spot, every variant's path, what they cover and the margin, the measurements and the push lane's tape lines. Maps are numbered as the program's menu numbers its tests.

### The program
`vexsim calibration program` writes into the project:

| File | |
|---|---|
| `src/main.cpp` | the program, the same for every robot (`vexsim/bridge/cpp/calibration/main.cpp`) |
| `include/vexsim_calibration_tests.hpp` | the robot's devices and the plan's tests: drive motors and their groups, every device's port and type, which way tracking wheels count, where each distance sensor is, each driving test's steps (raw millivolts per motor), spot and envelope |
| `include/vexsim_log.hpp`, `src/vexsim_log.cpp` | vexsim's logger |
| `include/main.h` | PROS's, if the project has none |

It writes only into an empty folder, a new PROS project (whose `main.cpp` is PROS's template) or its own; a project with code of its own is refused, and `--force` writes over a `main.cpp` that isn't the program's. It uses only the PROS 4 C API and the logger, so it builds with PROS and runs unchanged in vexsim.

The brain's screen shows the robot, the battery, the hottest drive motor, whether there's a card and how many logs are saved, then the tests in order with how many runs each has done; the controller shows the same in short. UP and DOWN choose, A starts. Each test says what to do on both screens.

| # | Test | The student | Logs |
|---|---|---|---|
| 1 | Device check | lays the robot on its side, says which way each group of wheels spun (A forward, B backward, X didn't); stands it up, turns it a quarter turn left, pushes it forward and left (tracking wheels), covers each distance sensor with a hand | `device_check` |
| 2 | Free spin | lays it on its side: the wheels run at 3, 6, 9 and 12 V for 1.5 s each, brake, then at 50% and 100% in velocity mode | `free_spin` |
| 3 | IMU, still for 60 s | puts it down flat and leaves it; the IMU calibrates first | `imu_still` |
| 4 | IMU, 10 turns by hand each way | lines it up on a tape line, turns it 10 times, lines it up again | `imu_turns_left`, `imu_turns_right` |
| 5 | Push, each way | puts its front edge on the lane's start line and pushes it to the end line, motors coasting; then back | `push_forward`, `push_back` |
| 6.. | Driving tests, 3 runs each | puts it on the test's spot | `straight`, `spin`, `arc`, `strafe` |
| | Slow spin, distance sweeps | puts it on the spot: it turns by the IMU, 5 turns at 120 deg/s, or one at 60 | `slow_spin`, `sweep_1`... |
| | Drive mode | drives it between spots: tank, half speed, sideways with the sticks' x if the drive can; B goes back | (none) |

**The device check:**
- On its side, each group's motors run forward at 3 V, as the config says. If they all turn together, the student says which way the wheels spun ("forward: the top of each wheel moves toward the robot's front", or the way that group's wheels roll); all backward means every motor in the group is reversed in the config. If they don't turn together (one fights the others), each motor runs alone, and a motor that turns the wheels backward is named, with its port as the config should have it ("motor 9 runs backward: make it -9").
- Flat again: the IMU calibrates, then the robot is turned a quarter turn left by hand (an IMU that reads it backward, or not at all, is named); tracking wheels must count the way their `heading_deg` and `reversed` say when it's pushed forward and left.
- Distance sensors: with nothing within a foot, each is covered by hand in turn, by where the config says it is ("the front left, facing forward"); whichever reads under 100 mm is the one at that spot. A sensor on the wrong port, or two swapped ("ports 1 and 8 are swapped"), is named.
- The results are the log's `check` (passed or failed) and `check_<group>`, `check_imu`, `check_tracking` and `check_distance` lines, and the screen lists what to fix.

**Safety:**
- Before each test: every device in the config answers on its port as its type (`get_plugged_type`); the battery is at 80% or more (below, it asks first); no drive motor is over 45 °C.
- A test that turns the wheels waits for the robot to be still (no wheel turning, the IMU steady, for half a second), then counts down from 3 with a rumble each second. A button or stick then cancels it.
- While it runs, any button or a stick past 20% stops every motor at once (braking, within 10 ms). So does leaving the envelope: a run stops when a drive motor's distance from where it started, plus how far it would turn braking from its speed (at 4000 deg/s², on the safe side) if it's moving away, passes the plan's travel; or when the IMU has turned further than the plan's. A spin in place stops at its turns, or if its wheels turn far more than the robot does, or it takes twice as long as it should.
- A stopped run's log is kept, its `ended` line saying why ("stopped: a button or stick", "stopped: went further than planned"); it doesn't count toward the test's runs.

**After each run** the screen says how long it took, the wheels' top speed and the total turn, and warns: wheels that lost 20 in/s within 100 ms while coasting or driving the way they turn (did it hit something?), a drive motor over 50 °C, the battery under 10.8 V, the robot moving while the IMU calibrated (the wheels turned). The IMU turns show how much more or less the IMU read than the 3600 degrees it turned (more than 5% off: not 10 turns, so it doesn't count); the push, how far the wheels say it went.

**Its logs** start with `# key: value` lines: `robot`, `field`, `program` (`vexsim calibration`), `test`, `run`, `ended`, and as they apply `spot` (x, y and heading of where it started, field inches and degrees counter-clockwise from +x), `scale`, `direction`, `turns`, `length_in`, `warning`. Each step is a mark (`launch`, `coast`, `12 V`, `velocity 50%`, `spin left`, `answer: forward`, `stopped: ...`). The program samples them itself, right after each step's command (`Sampling::manual`), as the routine does; while it waits on the student mid-test, every 10 to 50 ms.

**On the terminal**, each step is also a `#vexsim-cal` line: `menu KEY` (the menu, at KEY), `ask WHAT` (waiting for the student: `side`, `flat`, `place KEY`, `forward`, `turn left|right DEG`, `push forward|left IN`, `lane forward|back IN`, `cover PORT`, `uncover`, `open`, `still`, `line`, `ready`, `next`, `done passed|failed`, `battery PCT`, `hot PORT`, `device PORT`), `countdown`, `spin group NAME` or `spin motor PORT`, `log NAME TEST RUN`, `stopped WHY`, `saved HOW`, `problem TEXT`, `imu calibrating`, `imu ready`, `drive`.

### Trying it in vexsim
The program runs unchanged in vexsim, from its menu: `vexsim run ROBOT.yaml --program vexsim_calibration --mode driver --field FIELD.yaml --sd sd`, driven from the app's controller. `vexsim/calibration/student.py` plays the student instead, by those terminal lines: it presses the buttons, lays the robot on its side (`Robot.lifted`: the wheels spin free, nothing moves the robot) and stands it up, puts it on each spot (`Robot.place`), pushes and turns it by hand (a spring and damper on its pose), says which way the wheels it watched spun, and covers a distance sensor (`DistanceDevice.blocked_mm`: it reads 30 mm). It knows the config the program was made for, so it covers the sensor that config says is at a spot, on whichever robot is simulated: a "real" robot with its wiring changed shows what the device check catches.
```python
from vexsim.bridge.build import build_project
from vexsim.bridge.program import CppProgram
from vexsim.calibration.plan import make_plan
from vexsim.calibration.program import write_program
from vexsim.calibration.student import Student
from vexsim.config import load_field, load_robot
from vexsim.runtime.simulation import Simulation

config, field = load_robot("robot.yaml"), load_field("field.yaml")
plan = make_plan(config, field)
write_program(config, plan, "calibration_program")
built = build_project("calibration_program")
student = Student(plan, config, ["device_check", "free_spin", "straight"])
sim = Simulation(config, program=CppProgram(built.executable, env={"VEXSIM_SD_DIR": "/abs/sd"}),
                 field=field, input_source=student, start=student.start)
student.attach(sim)
sim.start("driver")
sim.run_until_finished(900)  # the logs are in /abs/sd; student.runs has each run's true path
```
On 1239E's robot and field, the whole session (every test, 18 logs) takes 4.6 minutes of simulated time, about a minute to run.
