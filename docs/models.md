# Physics models

Every parameter below is labeled by where it comes from:
- **VEX**: published by VEX.
- **Fit**: derived from VEX's published curves by community curve-fitting.
- **Community**: reported on the VEX Forum, not official.
- **Estimate**: our assumption.

Estimates are calibration targets for Phase 10. All of them can be changed per robot through `overrides:` in the robot YAML, e.g. `motor.free_current_a: 0.2`. Run `vexsim validate-config` to see the accepted keys.

## V5 Smart Motor (11W): `vexsim/physics/motor.py`

![Simulated torque, current and power vs. speed, red cartridge](img/motor_curves_red.png)

`vexsim motor-curves --cartridge red --out docs/img/motor_curves_red.png` regenerates this chart. Use `--csv` for the numbers.

### Electrical and mechanical model
The model works at the motor core, before the cartridge. It ignores inductance, because the electrical time constant is far below the 1 ms step.
```
I           = (V - ke * w_core) / R        clamped to the effective current limit
torque_core = kt * I - (coulomb * tanh(w_core / w_s) + viscous * w_core)
torque_out  = G * torque_core,   w_core = G * w_out,   G = 36 / 18 / 6 (red / green / blue)
```
- `kt` and `ke` are fitted separately. `kt` / `ke` ≈ 0.88 absorbs gearbox efficiency.
- The motor reports its electrical draw (`V * I`) to the power system.
- I²R heat goes into the thermal model.

### Calibration targets (red cartridge, output side, 12.8 V)
| Quantity | Value | Source |
|---|---|---|
| Natural (uncapped) free speed | 121 rpm | Fit ([VEX Forum][fit]) |
| Natural stall torque | 3.99 N·m | Fit |
| Natural stall current | 4.69 A | Fit |
| No-load current | 0.15 A | Estimate |
| Coulomb share of no-load friction | 30% | Estimate |
| Current limit | 2.5 A (default and maximum) | VEX / PROS |
| Rotor inertia (core) | 2.0e-6 kg·m² | Estimate |

**Derived constants (core):**
- R = 2.729 Ω
- kt = 0.02386 N·m/A
- ke = 0.02716 V·s/rad
- Coulomb friction 1.07e-3 N·m
- viscous friction 5.5e-6 N·m·s

**Reflected rotor inertia at the output:**
| Cartridge | Inertia |
|---|---|
| red | 2.6e-3 kg·m² |
| green | 6.5e-4 kg·m² |
| blue | 7.2e-5 kg·m² |

### What the fit reproduces (checked in `tests/test_motor.py`)
| VEX statement ([KB][kb]) | Model |
|---|---|
| Stall torque 2.1 N·m (red); 1.05 green, 0.35 blue | 2.15 / 1.07 / 0.36 N·m (within 2.3%) |
| Holds full speed up to ~35% of stall torque | holds 100 rpm up to 0.71 N·m (34%) |
| Peak power ~12.75 W; 11 W+ across ~30% of the speed range | 12.6 W peak; above 11 W across about 30% of the range |
| Free speed is software-limited for motor-to-motor consistency | `move_velocity` capped at 100/200/600 rpm; speed holds on a low battery |

### Firmware behavior modeled
- **Velocity mode (`move_velocity`).** The target is clamped to rated speed. A feedforward plus PI loop runs every step, using a velocity estimate filtered at 2 ms. It can drive up to the full battery voltage, which is what lets it hold rated speed under load.
  - The integral term only accumulates near steady state, while acceleration is below 0.25 rated speeds per second. It only exists to reject load torque, and integrating during the approach would wind up.
  - Result: overshoot ≤ 1.5% and settling in 0.05–0.5 s for drivetrain-like loads (4–40× rotor inertia).
  - A load step of 30% of stall torque recovers fully in about 0.4 s.
  - Gains are an **estimate**; VEX does not publish the internal controller.
- **Voltage mode (`move_voltage`).** Applies the commanded voltage, ±12 V, limited by the battery. It is **not speed-capped**, so 12 V spins about 13% past rated speed (113 rpm on the red cartridge).
  - **Unverified**, and the first thing to measure on a real robot (see below).
- **Position mode and hold.** A position P loop (15 /s) produces a velocity target, which feeds the velocity loop above. `HOLD` captures the position at the moment the motor stops, holds it within 1° under half of stall torque, and springs back after overshooting.
- **Zero commands.** `move_voltage(0)` and `move_velocity(0)` stop the motor using its brake mode.
  - The PROS docs state this for `brake()` and velocity 0. For voltage 0 it's an **assumption**, to be verified in Phase 7.
- **Brake modes:**
  - `COAST`: windings open, so zero current.
  - `BRAKE`: windings shorted, so back-EMF brakes the motor, with a time constant of about 0.13 s at typical loads.
  - `HOLD`: closed-loop hold of the stopped position.

## Thermal model and derating: `vexsim/physics/thermal.py`
The model has two nodes:
- **Winding:** I²R heat enters here (heat capacity 12 J/K).
- **Housing/PCB:** where the temperature sensor sits (50 J/K).

Thermal resistances are 1.5 K/W from winding to housing and 4 K/W from housing to ambient, with ambient at 25 °C.

| Behavior | Value | Source |
|---|---|---|
| Derating steps | current × 1/2, 1/4, 1/8, then 0 | Community ([VEX Forum][derate]) |
| First step | 55 °C sensor temperature | Community (observed, not exact) |
| Spacing between steps | 5 °C | Estimate |
| Thermal capacities and resistances | see above | Estimate |
| Sensor reads the PCB / average, with lag | housing node, lagging the winding | Community |

With these values, a fully stalled motor (17 W of heat) reaches the first derating step after about 160 s, then cycles at the 50% step around 55 °C. Cruising unloaded stays near ambient.

## Battery: `vexsim/physics/battery.py`
| Quantity | Value | Source |
|---|---|---|
| Capacity | 1100 mAh | VEX |
| Nominal voltage | 12.8 V (4 LiFePO4 cells in series) | VEX |
| Open-circuit curve | 13.5 V full, 13.1 V at 50%, 12.6 V at 10%, 11.2 V empty | Estimate (generic LiFePO4 shape) |
| Internal resistance (cells + BMS + wiring) | 0.10 Ω | Estimate |

State of charge is tracked by counting charge, and the sim never charges the battery.

## Power distribution: `vexsim/physics/power.py`
- **Bus voltage:** the battery's terminal voltage under the total draw, plus the brain's 0.3 A (**estimate**). Motors see the previous step's bus voltage. That 1 ms lag stands in for bus capacitance and avoids an algebraic loop.
- **Current sharing:** with more than 8 motors plugged in, each motor's current limit becomes 20 A ÷ N. Community-reported ([VEX Forum][share]), not official.
- **Regeneration:** a motor generating power can feed other motors on the bus, but never charges the battery.

## Calibrating against a real robot (Phase 10, or sooner)
A few quick experiments would replace the biggest estimates.

1. **Voltage-mode free speed.** Run `move_voltage(12000)` on a motor with nothing attached and log `get_actual_velocity()` for 3 s.
   - About 113% of rated speed confirms the model.
   - About 100% means voltage mode is also capped, so set the cap in the model.
2. **Thermal timing.** Stall a motor against a hard stop with `move_velocity(max)` and log `get_temperature()` and `is_over_temp()` every second until it derates. Fit the thermal capacities and the derating onset.
3. **Battery sag.** Log `pros::battery::get_voltage()` and `get_current()` while all drive motors push against a wall. Fit the internal resistance.
4. **Velocity loop.** Step `move_velocity` from 0 to max on the robot's drivetrain and log the velocity. Fit `velocity_kp` and `velocity_ki`.

[fit]: https://www.vexforum.com/t/v5-smart-motor-estimating-performance-parameters/135200
[kb]: https://kb.vex.com/hc/en-us/articles/360044325872-Understanding-V5-Smart-Motor-Performance
[derate]: https://www.vexforum.com/t/v5-overheating-threshold/64984
[share]: https://www.vexforum.com/t/10-motor-current-limiting-question/113733
