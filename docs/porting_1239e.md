# Porting a team's code: 1239E's RCL, MCL and autonomous routines

This guide ports team 1239E's 2026-27 robot code ([jiazegao/1239e_2026-27](https://github.com/jiazegao/1239e_2026-27), commit `fb5a42a`) into vexsim, step by step. The same steps work for any PROS 4 project. The result:
- the team's code, in `examples/pros_projects/1239e_2026-27`, with three marked edits;
- the robot, in `examples/robots/1239e_2026-27.yaml`;
- the field as the team's localization models it, in `examples/fields/1239e_2026-27.yaml`;
- `examples/scripts/evaluate_1239e.py`, which runs every routine and measures the localization against the simulated truth.

All nine routines run to the end. With RCL and MCL, LemLib's pose ends within 1.5 in of the truth on every left-side routine and on skills, against 4–6 in with odometry alone. The simulation also turned up a likely bug in the right-side routines' MCL setup: see [step 9](#9-what-the-simulation-found).

![LemLib's pose vs. the true pose through each routine, with and without RCL and MCL](img/1239e_localization.png)

## What the code does
| Part | Files | What it does |
|---|---|---|
| LemLib chassis | `include/custom/configs.hpp` | Tank drive, 2 blue motors a side at 450 rpm on 3.25 in omni wheels; odometry from the drive motors and an IMU (no tracking wheels). The team edited LemLib's `pid.hpp` so PID gains are public and writable. |
| **RCL** (wall resets) | `RclTracking.hpp/.cpp` | Five distance sensors. A reading that looks square at a wall, and whose beam misses the listed obstacles, sets LemLib's x or y. The routines call it once at the start, with the front-left sensor (`startMcl(..., resetFront)`). |
| **MCL** (particle filter) | `MclTracking.hpp/.cpp` | 2048 particles every 30 ms. Motion from the drive motors and the IMU heading; weights from the five distance sensors against a map of walls, match loaders and bases. High sensors (9.12 in) see over the low bases, low ones (4.19 in) don't. Each update pulls LemLib's x and y 5% of the way to the estimate. Per routine, "masks" (lines) disable sensors whose beam would cross into the other half of the field. |
| Mechanisms | `lift_control.cpp` | A two-motor lift (120 motor degrees per inch) and an end effector (a 4:1 wrist and an intake), each with a PID task. `hardResetEffector()` homes the wrist against its stop. |
| Routines | `src/auton.cpp`, `auton_selector.cpp` | Nine routines, picked on an LVGL brain-screen selector: LemLib motions plus lift and effector macros. |
| Screen, logging | `util_funcs.cpp`, `FB_Logo.c` | Controller and brain displays, a logo image, MCL logs to the SD card. |

## 1. Take stock of what the code needs
List every device, library and system call, and check each against [what vexsim simulates](cpp.md#whats-simulated):

| The code uses | In vexsim | Action |
|---|---|---|
| Motors, IMU, distance sensors, controller, tasks, mutexes | Simulated | None |
| LemLib 0.5.6 | Built from source | None |
| LemLib with an edited `pid.hpp` | Wasn't supported | vexsim now compiles a project against its own complete copy of LemLib's headers when it differs, as the robot does |
| Lift, intake, wrist motors | Motors outside the drivetrain failed with `ENODEV`: the lift read `PROS_ERR_F` (infinity), so `scoreCup()`'s task would wait forever for it to come down | vexsim gained **mechanisms** |
| Low bases that only the 4.19 in sensors see | Elements blocked every beam, and the robot | Elements gained `height_in` and `solid: false`; distance sensors gained `height_in` |
| The IMU reads 360.91° per turn (`ScaledIMU`) | A random scale error per IMU | IMUs gained a measured `scale_error` |
| LVGL 9 selector, buttons and logo image | Didn't compile | vexsim gained an LVGL stand-in |
| `std::sqrtf`, `std::sinf` (newlib's `<cmath>`) | Missing in g++ 13's library | Added for g++ before 14 |
| `std::chrono` timers (`Timer`) | Wall-clock time, not simulated time | Edit the code (step 3) |
| Auton choice on the brain screen | Nobody can tap it | Edit the code (step 3) |
| `std::random_device` in MCL | Different every run | Edit the code (step 3) |
| SD card logs | No card: files don't open | None: `initLog()` turns logging off when it can't open its file |
| Optical sensor (port 3) | Not simulated | None: only a debug display reads it. Note that the right distance sensor is also on port 3 in the code; one of them is on the wrong port. |

## 2. Copy the code and build it
Copy what the team wrote, and leave out what PROS installs:
```
mkdir -p examples/pros_projects/1239e_2026-27/include
cp -r TEAM/src TEAM/project.pros examples/pros_projects/1239e_2026-27/
cp -r TEAM/include/main.h TEAM/include/custom TEAM/include/lemlib examples/pros_projects/1239e_2026-27/include/
vexsim build examples/pros_projects/1239e_2026-27
```
- Left out: `firmware/`, `include/api.h`, `include/pros/`, `include/liblvgl/` (vexsim's shim replaces them) and `include/fmt/` (LemLib's, unchanged).
- `include/lemlib/` is copied because the team edited `pid.hpp`. The build says so:
  ```
  note: the project's LemLib headers differ from LemLib 0.5.6's (include/lemlib/pid.hpp); its code compiles against its own copies, as on the robot
  ```
  The edit only drops `protected:` and `const`, so the classes keep their layout and LemLib's own build links with them, as the robot's precompiled LemLib does.

The first builds stopped at `liblvgl/lvgl.h`, at `std::sqrtf`, and at `PID::kP` being protected (before vexsim used the team's `pid.hpp`). All three are handled in vexsim now, so the build succeeds.

## 3. Make three small edits, marked `// vexsim:`
Each edit is harmless on the robot.

**Time from the brain's clock.** `Tracking_Util.hpp`'s `Timer` read `std::chrono::high_resolution_clock`, your computer's clock. In the simulator, the robot's time runs at whatever speed the simulation does, so RCL's and MCL's loop timing and sensor timeouts would be wrong. It now reads `pros::micros()`, which on the robot is the same clock:
```cpp
Timer(float timeoutMs_ = 0) : timeoutMs(timeoutMs_), startTime(pros::micros()) {};
float elapsedMs() const { return (pros::micros() - startTime) * 0.001f; };
```

**Pick the routine by name.** `runAuton()` reads the routine from `VEXSIM_AUTON`:
```cpp
#ifdef VEXSIM
    if (const char* name = std::getenv("VEXSIM_AUTON")) { /* set autonCount to the routine named */ }
#endif
```
`vexsim run --env "VEXSIM_AUTON=Right 40"` sets it. A name that doesn't match prints `VEXSIM_AUTON: no routine named "..."`.

**Repeatable randomness.** MCL seeded its particles from `std::random_device`, so no two runs matched. Under `#ifdef VEXSIM` it seeds from `VEXSIM_SEED`, which vexsim always sets to the simulation's `--seed`.

## 4. Describe the robot
`examples/robots/1239e_2026-27.yaml` comes from the code wherever the code says, and is marked "assumed" where it doesn't.

| From the code | Robot config |
|---|---|
| `leftMotors({10, 9})`, `rightMotors({-19, -17})`, blue, 450 rpm, 3.25 in | `gearing`: blue, `ratio: "36:48"`; omni wheels at y = ±5.2 (10.4 in track width) |
| "6 wheels, 3 on each side" (`getDTWheelDegrees`), horizontal drift 2 | 6 omni wheels; the 5 in spacing is assumed |
| `ScaledIMU imu(16, 360.0, 360.91)` | IMU on port 16 with `scale_error: 0.002528`, so the team's correction has the error it was measured for |
| `RclSensor(&frontL_dist, -5.69, 4.66, 0, ...)` | `{type: distance, port: 1, pos_in: [4.66, 5.69], heading_deg: 0, height_in: 9.12}` |
| `liftMotors({-7, 21})`, `LIFT_GEAR_RATIO 120` deg/in, heights 0–50 in | mechanism `lift`: blue, stops at 0 and 6300°, a 0.3 N·m load (assumed: about 2.5 kg on a 1 in spool) |
| `effectorRotateMotor(-4)`, 4 motor degrees per wrist degree, 0–165° | mechanism `effector_wrist`: green, `ratio: "12:48"`, stops at 0 and 190° (upper stop assumed) |
| `frontIntakeMotor(20)`, `effectorIntakeMotor(-5)` | mechanisms `front_intake` (blue), `effector_intake` (green) |

**Converting sensor mounts.** RCL gives `(h, v, a)`: inches right and forward of the center, and an angle clockwise from forward. vexsim uses inches forward and left, and degrees counter-clockwise: `pos_in: [v, -h]`, `heading_deg: -a`. MCL's `sensor_mounts` table (forward, left, counter-clockwise radians) gives the same numbers, which checks the conversion. Its comments give each sensor's height.

**Assumed, so measure them:** mass (7 kg), footprint (14 × 12.5 in), CG height, wheel spacing, and the mechanisms' loads, stops and friction. Then calibrate the drivetrain against the real robot ([calibration.md](calibration.md)). Until then, read the results as "how this code behaves on a robot like this", not as predictions for the real one.

## 5. Describe the field
`examples/fields/1239e_2026-27.yaml` is the field MCL's map describes, so the simulated sensors see what MCL expects:

| MCL / RCL | Field element |
|---|---|
| Walls at ±70.2 in (`FIELD_HALF_LENGTH`, their measured field) | `size_in: [140.4, 140.4]` |
| `universal_match_loaders`: 4 × 4 in boxes at the side walls | 4 solid rects, cut off at the wall |
| `high_center_base`: a 3.19 in circle every sensor sees | a solid circle with no height |
| `low_center_base` and `low_neutral_bases`: 5.6 in and 5 in squares only low sensors see | rects with `height_in: 6` (between the two sensor heights) and `solid: false`, since the routines drive onto the bases |
| RCL's `alliance_base` circles (MCL leaves them out) | 5 × 5 in rects like the neutral bases (assumed) |

Game pieces (cups and pins) are left out. vexsim's mechanisms don't pick anything up, and nothing in the localization depends on pieces.

Check both files: `vexsim validate-config examples/robots/1239e_2026-27.yaml --field examples/fields/1239e_2026-27.yaml`.

## 6. Run a routine
The routines start with `chassis.setPose(60, 0, 90)` (left side) or `(-60, 0, -90)` (right side, and `alliance1pin`). LemLib's θ is clockwise from +y, so vexsim's heading is 90 − θ:
```
vexsim run examples/robots/1239e_2026-27.yaml --program examples/pros_projects/1239e_2026-27 \
    --field examples/fields/1239e_2026-27.yaml --start=60,0,0 --env "VEXSIM_AUTON=Left 40"
```
For a right-side routine, use `--start=-60,0,180`. `--headless` prints how far LemLib's pose was from the truth:
```
autonomous finished at t = 17.37 s
  true pose      x   42.50  y   19.66  heading  207.6
  estimated pose x   42.37  y   21.51  heading  207.7
  the robot code's pose vs. the true one during autonomous: mean 1.66 in, max 7.00 in (at 7.3 s), final 1.78 in; heading mean 0.53, max 4.3 deg
```
`--record run.csv` logs the true pose, LemLib's (`est_*`), every motor, and each mechanism's angle (`lift_deg`, `effector_wrist_deg`, ...). For example, in Left 40 the wrist steps through the code's 90°, 165° and 60° angles, and `setLift(8)` raises the lift to about 960 motor degrees.

## 7. Evaluate the localization
```
python examples/scripts/evaluate_1239e.py --seeds 6 --plot errors.png
```
The script runs every routine twice per seed, from the same slightly-off start (hand placement: σ 0.5 in in x and y, 1° in heading) and with the same sensor noise:
- **RCL + MCL**: the robot as configured.
- **Odometry only**: the same robot with its distance sensors unplugged. RCL and MCL get no readings and change nothing, so LemLib's drive-motor odometry runs alone. Unplugging needs no code change: an unplugged sensor reads `PROS_ERR`, which both reject.

Results with 6 seeds (position error between LemLib's pose and the truth, inches; mean over the seeds):

| Routine | Time (s) | RCL + MCL: mean / max / final | Odometry only: mean / max / final |
|---|---:|---:|---:|
| Left 40 | 15.4 | **1.6** / 7.5 / **1.5** | 4.6 / 7.3 / 5.9 |
| Left 30 | 13.7 | **2.6** / 7.8 / **0.8** | 4.1 / 5.7 / 4.2 |
| Left 30_10 | 16.9 | **1.2** / 5.7 / **0.3** | 3.7 / 6.4 / 5.8 |
| skills | 17.3 | **1.3** / 6.9 / **0.6** | 3.8 / 5.4 / 5.3 |
| Right 40 | 15.7 | 3.8 / 9.9 / 5.6 | 5.1 / 8.1 / 6.3 |
| Right 30 | 13.3 | 6.2 / 16.2 / 8.9 | 4.4 / 6.2 / 5.9 |
| Right 30_10 | 15.5 | 10.4 / 25.4 / 16.1 | 2.0 / 4.5 / 3.6 |
| Right 20_10 | 13.7 | 6.8 / 16.8 / 2.5 | 3.7 / 6.2 / 5.9 |
| alliance1pin | 8.1 | 1.6 / 3.9 / 0.8 | 1.3 / 2.0 / 1.3 |

The plot at the top shows seed 0. The 108 runs take about 2 minutes on 4 cores.

## 8. Read the results with their limits in mind
- **Assumed robot and field.** The mass, wheel spacing and element heights are guesses (steps 4 and 5). How far an omni-wheel robot slides in a hard turn depends on them, so the odometry errors are this simulated robot's, not the real one's.
- **The distance sensor is a ray.** The real sensor has a cone of view, so it catches edges the ray misses. Its confidence reads 63 whenever it sees something; RCL rejects readings below 60, and MCL widens its error model as confidence drops, so on the robot both see fewer, noisier readings at long range and steep angles.
- **Sensor timing.** Distance readings come about every 33 ms, 10 ms old; the IMU every 10 ms, 5 ms old (estimates, [models.md](models.md#sensors-vexsimdevices)). MCL compares old readings with the current heading, which matters in fast turns.
- **No other robots, no game pieces,** and no compute time: on the brain, 2048 particles take part of each 30 ms cycle.

## 9. What the simulation found
**On the left side, RCL and MCL do their job.** LemLib's drive-motor odometry ends 4–6 in off, mostly from fast turns, when the omni wheels skid sideways and the motor encoders can't tell. MCL pulls it back to within 1.5 in by the end. Mid-routine peaks of 6–8 in, right after the hardest turns, last about a second.

**On the right side, MCL often makes it worse than odometry alone.** `Right 30_10` averages 10.4 in with MCL and 2.0 in without. The likely cause is `rightAutonObstacles`, the masks for the right-side routines. They are `leftAutonObstacles` rotated **90°**: every point (x, y) becomes (−y, x). But the right-side start, (−60, 0) facing −x, is the left-side start rotated **180°**. So the masks fit a robot starting at the top of the field. At the right-side start they leave MCL two of its five sensors, where the left side gets four, and as the robot moves they hide some useful beams while letting through some that cross the far half.

Rotating the left masks 180° instead, `(x, y) -> (-x, -y)`, gives:
```cpp
inline std::vector<Line_> rightAutonObstacles = {
    {{72.0, -72.0}, {-32.0, 32.0}},
    {{-32.0, -32.0}, {72.0, 72.0}},
    {{-32.0, 32.0}, {-32.0, 72.0}},
    {{-32.0, -32.0}, {-32.0, -72.0}}
};
```
With those masks, same seeds:

| Routine | Team's masks: mean / max / final | 180° masks: mean / max / final |
|---|---:|---:|
| Right 30 | 6.2 / 16.2 / 8.9 | **1.3** / 6.5 / 4.4 |
| Right 30_10 | 10.4 / 25.4 / 16.1 | **0.9** / 3.8 / **0.6** |
| alliance1pin | 1.6 / 3.9 / 0.8 | **0.4** / 1.1 / **0.6** |
| Right 20_10 | 6.8 / 16.8 / 2.5 | 5.1 / 16.5 / 2.5 |
| Right 40 | 3.8 / 9.9 / 5.6 | 4.2 / 12.6 / **2.0** |

The port keeps the team's masks, since this is their call. The fix is worth trying on the real robot: compare MCL's SD-card logs for a right-side routine with each set of masks.

**MCL can lose track after a fast turn, and then can't find its way back.** The remaining bad runs (4 of the 30 with the 180° masks averaged over 5 in; it happens on the left side too, as in Left 30 with seed 2) follow one pattern:
1. During a fast turn, the drive-motor odometry slides several inches, and the distance readings, up to about 40 ms old, are compared with the current heading.
2. The particle cloud ends up a few inches from the truth with none of its 2048 particles near the robot. With most beams masked, the few valid readings can't pull it back. Every particle disagrees with them about equally, so resampling changes nothing.
3. Each update pulls LemLib toward the wrong estimate. In the Left 30 trace, the robot sits against the center post at x = 8.5 while LemLib's x walks from 25 to 30, though the back sensor, the only one unmasked, reads the wall 61 in away, where it really is.

Ideas to try, in the simulator first: skip MCL updates (or LemLib syncing) while turning fast; inject a few random particles, or call `uniform_reset()`, when every particle's weight collapses. Also, nothing in RCL or MCL corrects the heading (`THETA_SYNC_PROP` and `IMU_VARIANCE` are 0), so a robot placed 1° off stays 1° off all routine; the front pair, both facing the wall at the start, could measure it.

## 10. Keep the port up to date
The port is a copy of commit `fb5a42a`. To bring in newer code, copy the team's `src/` and `include/custom/` again, then reapply the three `// vexsim:` edits. Or apply them in the team's own repository: each is inert on the robot (`#ifdef VEXSIM`, or `pros::micros()`), so the team's code would then run in vexsim unchanged.

## Porting your own team's code
The same steps apply:
1. Take stock of devices, libraries and system calls ([cpp.md](cpp.md#whats-simulated)).
2. Copy `src/` and your own headers, and run `vexsim build`.
3. Replace wall-clock time with `pros::millis()`/`micros()`, and read the routine's name from an environment variable under `#ifdef VEXSIM`.
4. Write the robot config from your code's ports and offsets; measure the rest, then [calibrate](calibration.md).
5. Write the field config, with element heights if your sensors care about them.
6. Run each routine, and compare the pose your code believes with the truth.
