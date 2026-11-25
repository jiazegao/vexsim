# 1239E six-bar, in vexsim

Team 1239E's 2026-27 code for its six-bar robot, from the `six-bar` branch of [jiazegao/1239e_2026-27](https://github.com/jiazegao/1239e_2026-27) at `e625439` (2026-11-25). It has RCL and MCL on six distance sensors and a tracking wheel, on top of LemLib; a six-bar lift with a claw, claw rollers and a front intake; and two match routines (LEFT 5-PIN, RIGHT 5-PIN) and a skills routine. The robot is [`examples/robots/1239e_six_bar.yaml`](../../robots/1239e_six_bar.yaml), the field [`examples/fields/1239e_six_bar.yaml`](../../fields/1239e_six_bar.yaml).

The branch left `main` on 2026-11-11, after the commit the first port copied (`fb5a42a`, in [`1239e_2026-27`](../1239e_2026-27/README.md)). Its RCL, MCL, timer and selector are that code's, changed, so the same edits make it run in the simulator, each marked `// vexsim:` and harmless on the robot:
- `include/custom/Tracking_Util.hpp`: `Timer` reads `pros::micros()` instead of `std::chrono`.
- `src/custom/auton_selector.cpp`: under `#ifdef VEXSIM`, `runAuton()` takes the routine's name from `VEXSIM_AUTON`: `LEFT 5-PIN`, `RIGHT 5-PIN`, or `Skills` for the selector's Skills button (which runs `safe_skills()`). `startMcl` only starts MCL, where vexsim put the robot (`VEXSIM_START`), for following a log (`vexsim run --follow`).
- `src/custom/MclTracking.cpp`: under `#ifdef VEXSIM`, MCL seeds its random numbers from `VEXSIM_SEED`, and each update draws what MCL sees on the simulator's field (`vexsim::draw_*`): every sensor's ray to its reading, every 16th particle, and the particles' 2-sigma spread.
- `src/custom/util_funcs.cpp`: under `#ifdef VEXSIM`, `startMcl()` prints the `--start` matching the pose it sets, and `VEXSIM_TRACKING` (`odom`, `rcl`, `mcl` or the default `rcl+mcl`) chooses whether RCL's start reset and MCL run.
- `src/main.cpp`: under `#ifdef VEXSIM`, `VEXSIM_BRAKE=hold` (or `brake`) sets the drive's brake mode in `opcontrol()`, which is otherwise coast.
- `include/custom/util_funcs.hpp`: `// vexsim: drive(inches)` above `moveForward`, so the autonomous maker can draw where a route's `moveForward` steps end.

**Logging, with vexsim's logger**, as in the first port (these run on the robot too). The team's MCL log is gone: `initLog()`, its `mcl_log<N>.1239e` files and `DATA.1239e` counter, `MclTracking::logMcl()` and its logging task, and the `MCL_Log_Format` switch. Instead:
- `include/vexsim_log.hpp`, `src/vexsim_log.cpp`: the logger, as `vexsim logger add` copies it.
- `src/main.cpp`: `initRoutineLog()` (in `initialize()`) adds LemLib's pose (`lemlib`), MCL's (`mcl`) and MCL's spread (`mcl_spread_x`, `mcl_spread_y`) to every log, and rumbles the controller when there's no card, as `initLog()` did; `autonomous()` saves the log when `runAuton()` returns.
- `src/custom/auton_selector.cpp`: `runAuton()` starts the log, named for the routine it runs (`vexsim_0001_left_5_pin.csv`, `..._skills.csv`), when a card is in.
- `src/custom/MclTracking.cpp`: `updateSpread()` keeps the particles' spread each update, where `logMcl()` logged it.

In vexsim, `--sd FOLDER` stands in for the card.

Left out: `firmware/`, the PROS and LVGL headers (`include/api.h`, `include/pros/`, `include/liblvgl/`) and LemLib's `include/fmt/`, which vexsim supplies. `include/lemlib/` is the team's copy, with their edit to `pid.hpp` (the first port's, unchanged).

## Running it

```
vexsim run examples/robots/1239e_six_bar.yaml --program examples/pros_projects/1239e_six_bar \
    --field examples/fields/1239e_six_bar.yaml --start=57,6.75,0 --env "VEXSIM_AUTON=LEFT 5-PIN"
vexsim run ... --start=6.75,57,90 --env "VEXSIM_AUTON=RIGHT 5-PIN"
vexsim run ... --start=57,0,0 --env VEXSIM_AUTON=Skills [--sd card]   # its log in card/
vexsim run ... --routine left3pinv2                                    # any routine in auton.hpp
```

`--routine` runs any routine `include/custom/auton.hpp` declares (`left5pin`, `right5pin`, `safe_skills`, `left3pin`, `left3pinv2`, `skills`, `testPid`) inside the team's own `autonomous()`, from its `setPose`, without the selector. In `vexsim ui`, the saved runs *1239E six-bar: LEFT 5-PIN*, *RIGHT 5-PIN*, *Skills* and *driver* fill in the run bar, and the sweep *1239E six-bar: RCL + MCL vs odometry* runs the three routines with and without RCL and MCL, six seeds each, from a hand's placement error (0.5 in, 1°).

## The robot and the field

From the code: every port, the drive's 450 rpm and 2.75 in omni wheels (LemLib's horizontal drift 2 is its value for all omni wheels), the 11.41 in track width, the 2.75 in vertical tracking wheel on the center line (rotation sensor 9, reversed), each distance sensor's place, direction and height (`configs.hpp`'s notes, RCL's `RclSensor`s and MCL's `sensor_mounts` agree), the lift's 12:84 and its top (5000 motor degrees), and the claw's angles from its closed stop (`autonomous()` assumes it starts 13° open).

Assumed, so measure them: the mass (7 kg), the footprint (14 × 14.5 in), the CG height, three wheels a side 4.5 in apart, the mechanisms' loads, inertias and friction, and where the claw stops opening. Then calibrate the drive against the real robot ([docs/calibration_guide.md](../../../docs/calibration_guide.md)). Until then, read the results as "how this code behaves on a robot like this".

Three things the simulator can't do as the robot is built:
- **The drive's 5.5 W motors.** The team's README says the third motor a side (13 and 10) is a 5.5 W motor; vexsim simulates the 11 W motor only, so all six are 11 W blue motors at 36:48. The simulated drive has the same top speed and about a fifth more torque.
- **Motor 20** is plugged in for skills only, so the robot config is the match robot, with the lift on motor 19. The code's calls to motor 20 fail with `ENODEV`, as on the robot without it. For skills with both, add 20 to `lift`'s motors.
- **Picking up pins and cups.** vexsim's mechanisms don't pick anything up. As movable pieces, the pins a routine grabs were pushed and flung across the field, and one flung into a sensor's beam pulled MCL 18 in off. So the field has the 12 pins and cups as fixed elements every sensor sees and the robot drives through, where MCL's map has them.

The field is the six-bar code's MCL map and RCL obstacles. Its notes say how tall the bases are, by which sensors see over them: the center base 5 in ("> 5 inch is high"), the neutral bases 5.8 in, the alliance bases 3.25 in. The six-bar's sensors are 2.1 to 5.5 in high, so these heights decide what each one sees. The first port's field (`1239e_2026-27.yaml`) made every base 6 in, which only had to fall between that robot's 4.19 and 9.12 in sensors.

## What the simulation found

The sweep above, averaged over its six seeds (position error between LemLib's pose and the truth, inches):

| Routine | Time (s) | RCL + MCL: mean / max / final | Odometry only |
|---|---:|---:|---:|
| LEFT 5-PIN | 14.6 | 2.5 / 8.6 / 4.8 | 3.9 / 7.5 / 5.6 |
| RIGHT 5-PIN | 14.6 | 3.6 / 8.3 / 3.1 | 3.4 / 7.4 / 7.1 |
| Skills (`safe_skills`) | 14.1 | 0.6 / 1.4 / 1.0 | 1.2 / 1.9 / 1.5 |

All three routines run to the end on every seed. With RCL and MCL, each ends closer to the truth than with odometry alone, on average; in the middle of the match routines, the worst moments are a little further off with them than without (8.3 to 8.6 in, against 7.4 to 7.5).

Worth checking on the robot:
- **The bases MCL ignores.** Since 11/23, `low_center_base_visible` and `alliance_base_visible` are false for every sensor; on 11/22 they were true for the four low sensors (front, back, left and right, 2.1 to 3.3 in high), as the notes' heights say. If the bases are as tall as the notes say, those four see the center base, and all but the front one (3.33 in) see the alliance bases, while MCL's map says they see over them. On RIGHT 5-PIN, one seed in six loses track that way: turning in place at about (11, 42), 13 in from the alliance base at (23.5, 47), with the left, right and back sensors reading the base, LemLib's pose, pulled toward MCL's estimate, moved 4 in in half a second, and went on to be 23 in off at worst (12 in on average). With the alliance bases too low for any sensor to see, the same run averages 2.8 in. With the 11/22 flags, RIGHT 5-PIN's mean error is 1.9 in instead of 3.6 (max 6.7 instead of 8.3, though it ends 4.0 in off instead of 3.1), and LEFT 5-PIN and Skills come out about the same (2.5 / 8.8 / 5.0 and 0.6 / 1.4 / 0.5); with the simulated IMU's scale error taken out, 2.0 in instead of 4.7. If the flags were turned off for a reason on the real field, the heights in the field config are what to correct.
- **`setPinAndCupVisibility()` does the opposite of its name.** It stores `visible` in `cup_and_pin_disabled[index]`, so the routines' `setPinAndCupVisibility(3, false)` leaves pin 3 in MCL's map after the robot takes it, and `true` would take it out. `cup_and_pin_disabled[index] = !visible;` matches the name. (The simulation can't show the effect: its pins stay where they start.)
- **`set_gearing(green, 0)` sets the first motor of each side, not the third.** `initialize()` sets `leftMotors` and `rightMotors` index 0 to green, which is ports 15 and 8; the team's README says the 5.5 W motors are 13 and 10, which is index 2. vexsim prints it on every run: `port 15: the code declares the green (200 rpm) cartridge, but the robot config has blue (600 rpm)`. LemLib drives by voltage, and odometry here comes from the tracking wheel, so it only changes what those two motors report; it would matter to `move_velocity` and to their encoders.
