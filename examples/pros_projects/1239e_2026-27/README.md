# 1239E 2026-27, in vexsim

Team 1239E's 2026-27 robot code, from [jiazegao/1239e_2026-27](https://github.com/jiazegao/1239e_2026-27) at `fb5a42a` (2026-10-06): RCL and MCL distance-sensor localization on top of LemLib, a lift and end effector, and nine autonomous routines.

Three changes make it run in the simulator, each marked `// vexsim:` and harmless on the robot:
- `include/custom/Tracking_Util.hpp`: `Timer` reads `pros::micros()` instead of `std::chrono`.
- `src/custom/auton_selector.cpp`: under `#ifdef VEXSIM`, `runAuton()` takes the routine's name from `VEXSIM_AUTON`.
- `src/custom/MclTracking.cpp`: under `#ifdef VEXSIM`, MCL seeds its random numbers from `VEXSIM_SEED`.

Left out: `firmware/`, the PROS and LVGL headers (`include/api.h`, `include/pros/`, `include/liblvgl/`) and LemLib's `include/fmt/`, which vexsim supplies. `include/lemlib/` is the team's copy, with their edit to `pid.hpp`.

```
vexsim run examples/robots/1239e_2026-27.yaml --program examples/pros_projects/1239e_2026-27 \
    --field examples/fields/1239e_2026-27.yaml --start=60,0,0 --env "VEXSIM_AUTON=Left 40"
python examples/scripts/evaluate_1239e.py
```

The whole port, step by step, and what the simulation found: [docs/porting_1239e.md](../../../docs/porting_1239e.md).
