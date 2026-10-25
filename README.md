# vexsim

A VEX V5 robot mechanics simulator. It models:
- drive physics, including wheel slip and drift on omni wheels
- the V5 motor, including current limiting, heat and battery sag
- sensors and odometry, with realistic noise

It's built to test localization and motion-control algorithms, and eventually to run unmodified PROS 4 / LemLib robot code.

**Status: Phase 1 of 10 is done** (scaffolding, configs, world loop). There is no physics yet. See [PLAN.md](PLAN.md) for the full roadmap.

## Install

Requires Python 3.11 or newer.

**Windows (PowerShell)**
```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

**Linux / macOS**
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Use

Check a robot config and see what the simulator will build from it:
```
vexsim validate-config examples/robots/full_omni_6m.yaml --field examples/fields/v5rc_empty.yaml
```
```
Robot  examples/robots/full_omni_6m.yaml
  name        Example 6-motor full omni
  body        6.50 kg (14.3 lb), footprint 15.0 x 15.0 in, CG (0.0, 0.0, 3.5) in
              yaw inertia 0.157 kg*m^2 (auto: uniform box)
  drivetrain  differential, 6 wheels (6 omni)
    left      motors 1, 2, 3 | blue 600 rpm | ratio 36:48 -> 450 rpm | 3.25 in -> 76.6 in/s free speed
    right     motors -4, -5, -6 | blue 600 rpm | ratio 36:48 -> 450 rpm | 3.25 in -> 76.6 in/s free speed
  sensors     port 10  imu       at (0.0, 0.0) in, mount yaw 0 deg, noise default
              ...
Result: OK (0 error(s), 0 warning(s))
```
Exit codes: `0` means valid, `1` means there are errors. Add `--strict` to treat warnings as failures, and `-q` to print problems only.

**Writing a robot config**
- Copy `examples/robots/full_omni_6m.yaml`. Its comments explain every field.
- [docs/conventions.md](docs/conventions.md) covers frames, units, gear ratios and port rules.

**Using it from Python**
```python
from vexsim.config import load_robot
from vexsim.physics import World, PRIORITY_SENSOR

robot = load_robot("examples/robots/full_omni_6m.yaml")
world = World(seed=1)  # 1 ms physics step
world.every(10, lambda w: print(w.time), priority=PRIORITY_SENSOR)
world.run_for(0.05)
```

## Develop
```
pytest          # tests
ruff check .    # lint
ruff format .   # format
```
CI runs on Windows and Linux with Python 3.11 and 3.13 (`.github/workflows/ci.yml`).

## Layout
```
vexsim/
  config/    robot + field schemas, strict YAML loading, cross-field checks, summaries
  core/      integer-microsecond clock, deterministic event scheduler, named RNG streams
  physics/   world loop (motor, battery, chassis, wheel models arrive in Phases 2-3)
  cli.py     `vexsim` command
examples/    robot and field configs
docs/        conventions
tests/
```
