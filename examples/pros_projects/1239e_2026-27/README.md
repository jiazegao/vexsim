# 1239E 2026-27, in vexsim

Team 1239E's 2026-27 robot code, from [jiazegao/1239e_2026-27](https://github.com/jiazegao/1239e_2026-27) at `fb5a42a` (2026-10-06): RCL and MCL distance-sensor localization on top of LemLib, a lift and end effector, and nine autonomous routines.

Four changes make it run in the simulator, each marked `// vexsim:` and harmless on the robot:
- `include/custom/Tracking_Util.hpp`: `Timer` reads `pros::micros()` instead of `std::chrono`.
- `src/custom/auton_selector.cpp`: under `#ifdef VEXSIM`, `runAuton()` takes the routine's name from `VEXSIM_AUTON`.
- `src/custom/MclTracking.cpp`: under `#ifdef VEXSIM`, MCL seeds its random numbers from `VEXSIM_SEED`.
- `src/custom/util_funcs.cpp`: under `#ifdef VEXSIM`, `startMcl()` prints the `--start` matching the pose it sets, and `VEXSIM_TRACKING` (`odom`, `rcl`, `mcl` or the default `rcl+mcl`) chooses whether RCL's start reset and MCL run.

Four more, also under `#ifdef VEXSIM`, let the simulated robot write MCL logs, replay a real one, and show its MCL in the browser app ([docs/1239e_real_vs_sim.md](../../../docs/1239e_real_vs_sim.md)):
- `src/custom/util_funcs.cpp`: `initLog()` writes `mcl_log<N>.1239e` to the folder `VEXSIM_SD_DIR` names, which stands in for the SD card.
- `src/custom/auton_selector.cpp`: `VEXSIM_AUTON="startMcl x,y,theta,front,left,back,right"` calls `startMcl()` with those arguments and nothing else; plain `VEXSIM_AUTON=startMcl` calls it with the pose vexsim started the robot at (`VEXSIM_START`) and no resets, for following a real MCL log (`vexsim run --follow`).
- `src/main.cpp`: `VEXSIM_BRAKE=hold` (or `brake`) sets the drive's brake mode in `opcontrol()`, which is otherwise coast.
- `src/custom/MclTracking.cpp`: each update draws what MCL sees on the simulator's field (`vexsim::draw_*`): every sensor's ray to its reading, every 16th particle, and the particles' 2-sigma spread, in the layers the app draws a real MCL log in.

Left out: `firmware/`, the PROS and LVGL headers (`include/api.h`, `include/pros/`, `include/liblvgl/`) and LemLib's `include/fmt/`, which vexsim supplies. `include/lemlib/` is the team's copy, with their edit to `pid.hpp`.

```
vexsim run examples/robots/1239e_2026-27.yaml --program examples/pros_projects/1239e_2026-27 \
    --field examples/fields/1239e_2026-27.yaml --start=60,0,0 --env "VEXSIM_AUTON=Left 40" \
    [--env VEXSIM_TRACKING=odom]
python examples/scripts/evaluate_1239e.py [--tracking rcl+mcl,mcl,rcl,odom]
python examples/scripts/replay_1239e_mcl_log.py mcl_log1040.1239e --out replays
```

The whole port, step by step, and what the simulation found: [docs/porting_1239e.md](../../../docs/porting_1239e.md).
