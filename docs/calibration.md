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
This writes two files into the project:
- `include/vexsim_calibration.hpp`
- `src/vexsim_calibration.cpp`, which holds your robot's ports and the routine's voltages

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

**Getting the log:**
- **With a microSD card** in the brain, the log is saved to `/usd/vexsim_log.csv`.
- **Without one**, it is printed to the terminal between `#vexsim-log begin` and `#vexsim-log end` lines. Capture it with `pros terminal > run.txt` over USB; a wireless connection is too slow for this.

`vexsim calibrate` accepts either file as it is.

## 3. Fit
```
vexsim calibrate ROBOT.yaml vexsim_log.csv --out calibration
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

Any program can make such a log. Call `vexsim_calibration::start_logging()` when it starts and `vexsim_calibration::save()` at the end; the logger samples every 10 ms in its own task. It doesn't know what your code commanded, so the replay drives each motor with the voltage the motor reported (see [How the replay works](#how-the-replay-works)).

To compare a program's simulated run with its real one, log the simulated run too:
```
vexsim run ROBOT.yaml --program MY_PROS_PROJECT --headless --robot-log sim_run.csv
```

## Trying it in the simulator
`examples/pros_projects/calibration` is the routine for `examples/robots/full_omni_6m.yaml`:
```
vexsim run examples/robots/full_omni_6m.yaml --program examples/pros_projects/calibration --headless > run.txt
vexsim calibrate examples/robots/full_omni_6m.yaml run.txt
```
Here the "robot" is the simulator with its default parameters, so the fit leaves them about where they are. To see it find different values, add overrides to a copy of the robot config before `vexsim run`, then calibrate with the original.

## The log format
CSV, one row every 10 ms, written the same way by the robot (`vexsim_calibration.cpp`) and by the simulator (`--robot-log`). Readings are raw, as PROS reports them for a positive port: a motor on a negative config port reads backwards, and rotation sensors are read with reversal off.

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
| `d<p>_mm` | distance sensor (empty when nothing is in range) |
| `gps<p>_x_m`, `gps<p>_y_m`, `gps<p>_heading_deg`, `gps<p>_error_m` | GPS |

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
