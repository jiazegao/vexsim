# 1239E 2026-27, in vexsim

Team 1239E's 2026-27 robot code, from [jiazegao/1239e_2026-27](https://github.com/jiazegao/1239e_2026-27) at `fb5a42a` (2026-10-06): RCL and MCL distance-sensor localization on top of LemLib, a lift and end effector, and nine autonomous routines.

Four changes make it run in the simulator, each marked `// vexsim:` and harmless on the robot:
- `include/custom/Tracking_Util.hpp`: `Timer` reads `pros::micros()` instead of `std::chrono`.
- `src/custom/auton_selector.cpp`: under `#ifdef VEXSIM`, `runAuton()` takes the routine's name from `VEXSIM_AUTON`.
- `src/custom/MclTracking.cpp`: under `#ifdef VEXSIM`, MCL seeds its random numbers from `VEXSIM_SEED`.
- `src/custom/util_funcs.cpp`: under `#ifdef VEXSIM`, `startMcl()` prints the `--start` matching the pose it sets, and `VEXSIM_TRACKING` (`odom`, `rcl`, `mcl` or the default `rcl+mcl`) chooses whether RCL's start reset and MCL run.

Three more, also under `#ifdef VEXSIM`, let the simulated robot follow a real robot's logged path and show its MCL in the browser app:
- `src/custom/auton_selector.cpp`: `VEXSIM_AUTON=startMcl` only starts MCL, with the pose vexsim started the robot at (`VEXSIM_START`) and no resets, for following a real robot's log (`vexsim run --follow`).
- `src/main.cpp`: `VEXSIM_BRAKE=hold` (or `brake`) sets the drive's brake mode in `opcontrol()`, which is otherwise coast.
- `src/custom/MclTracking.cpp`: each update draws what MCL sees on the simulator's field (`vexsim::draw_*`): every sensor's ray to its reading, every 16th particle, and the particles' 2-sigma spread, in the layers the app draws a real MCL log in.

**Logging, with vexsim's logger** (phase 14.2: these run on the robot too). The team's MCL log is gone: `initLog()`, its `mcl_log<N>.1239e` files and `DATA.1239e` counter, `MclTracking::logMcl()` and its logging task, and the `MCL_Log_Format` switch. Instead, each autonomous routine is logged to the SD card with vexsim's logger ([README](../../../README.md#vexsims-logger)):
- `include/vexsim_log.hpp`, `src/vexsim_log.cpp`: the logger, as `vexsim logger add` copies it.
- `src/main.cpp`: `initRoutineLog()` (in `initialize()`) adds LemLib's pose (`lemlib`), MCL's (`mcl`) and MCL's spread (`mcl_spread_x`, `mcl_spread_y`) to every log, and rumbles the controller when there's no card, as `initLog()` did; `autonomous()` saves the log when `runAuton()` returns.
- `src/custom/auton_selector.cpp`: `runAuton()` starts the log, named for the routine it runs (`vexsim_0001_left_40.csv`, `..._skills.csv`), when a card is in.
- `src/custom/MclTracking.cpp`: `updateSpread()` keeps the particles' spread each update, where `logMcl()` logged it.

In vexsim, `--sd FOLDER` stands in for the card, so the simulated routine writes the same log there.

And one comment for the autonomous maker: `include/custom/util_funcs.hpp` says above `moveForward` how it moves the robot (`// vexsim: drive(inches)`), so the maker can draw where a route's `moveForward` steps end. `routes/left_start.yaml` is the start of `left40()` as a route ([README, section 9](../../../README.md#autonomous-routes)).

Left out: `firmware/`, the PROS and LVGL headers (`include/api.h`, `include/pros/`, `include/liblvgl/`) and LemLib's `include/fmt/`, which vexsim supplies. `include/lemlib/` is the team's copy, with their edit to `pid.hpp`.

```
vexsim run examples/robots/1239e_2026-27.yaml --program examples/pros_projects/1239e_2026-27 \
    --field examples/fields/1239e_2026-27.yaml --start=60,0,0 --env "VEXSIM_AUTON=Left 40" \
    [--env VEXSIM_TRACKING=odom]
python examples/scripts/evaluate_1239e.py [--tracking rcl+mcl,mcl,rcl,odom]
vexsim run examples/robots/1239e_2026-27.yaml --program examples/pros_projects/1239e_2026-27 \
    --field examples/fields/1239e_2026-27.yaml --routine left40 --headless --sd card   # its log in card/
```

The whole port, step by step, and what the simulation found: [docs/porting_1239e.md](../../../docs/porting_1239e.md).
