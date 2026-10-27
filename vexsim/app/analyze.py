"""The Analyze page's jobs: ``vexsim motor-curves``, ``drift`` and ``odometry`` as data.

Each runs in a job's process (see jobs.py) and returns what its charts draw, rounded,
rather than the PNG and CSV the commands write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vexsim.app.chartdata import every, rounded

if TYPE_CHECKING:
    from vexsim.app.jobs import Report
    from vexsim.config.robot import RobotConfig

MAX_POINTS = 2000  # samples per series, at most


def motor_curves(params: dict, report: Report) -> dict:
    """Torque, current and output power against speed, under move_velocity(max) and
    move_voltage(12000), on the simulated dynamometer."""
    from vexsim.physics.motor import V5Motor
    from vexsim.units import rad_s_to_rpm
    from vexsim.viz.motor_curves import LABELS, compute

    cartridge = params.get("cartridge", "green")
    volts = float(params.get("supply_voltage", 12.8))
    curves = compute(cartridge, volts, points=int(params.get("points", 61)))
    return {
        "cartridge": cartridge,
        "supply_voltage": volts,
        "current_limit_a": V5Motor(cartridge).spec.current_limit_a,
        "curves": [
            {
                "command": c.command,
                "label": LABELS[c.command],
                "speed_rpm": rounded([rad_s_to_rpm(w) for w in c.speed], 2),
                "torque_nm": rounded(c.torque, 4),
                "current_a": rounded(c.current, 4),
                "power_w": rounded(c.power_out, 3),
            }
            for c in curves
        ],
    }


def drift(params: dict, report: Report) -> dict:
    """An arc at fixed side speeds, for each roller friction: the true path against what
    drive-encoder odometry believes."""
    from vexsim.viz.drift import run_arc

    config = robot_config(params)
    if config.drivetrain.type != "differential":
        raise ValueError(
            f"drift runs need a differential drivetrain, and {_name(params)} is "
            f"{config.drivetrain.type}"
        )
    left, right = float(params.get("left", 1.0)), float(params.get("right", 0.4))
    seconds = float(params.get("seconds", 1.5))
    runs = []
    for mu in params.get("lateral_mu", [0.4, 0.2, 0.1]):
        run = run_arc(config, float(mu), left=left, right=right, seconds=seconds)
        runs.append(
            {
                "lateral_mu": float(mu),
                "true": rounded(run.true_xy[every(len(run.true_xy), MAX_POINTS)], 3),
                "odometry": rounded(run.odom_xy[every(len(run.odom_xy), MAX_POINTS)], 3),
                "final_error_in": round(run.final_error_in, 3),
            }
        )
        report(
            f"roller friction {mu:g}: drive-encoder odometry off by "
            f"{run.final_error_in:.1f} in after {seconds:g} s"
        )
    return {"left": left, "right": right, "seconds": seconds, "runs": runs}


def odometry(params: dict, report: Report) -> dict:
    """A scripted drive, and every baseline localizer the robot's sensors allow, against
    the truth."""
    from vexsim.algorithms.localization.runner import run_odometry

    config = robot_config(params)
    script = params.get("script", "aggressive")
    noise = params.get("noise") or None
    seed = int(params.get("seed", 0))
    run = run_odometry(config, script, seed=seed, noise=noise)
    if not run.estimates:
        raise ValueError(f"{_name(params)} has no sensors any baseline localizer can use")
    keep = every(len(run.time), MAX_POINTS)
    estimates = []
    for name, path in run.estimates.items():
        position, heading = run.errors(name)
        estimates.append(
            {
                "name": name,
                "path": rounded(path[keep], 3),
                "position_error_in": rounded(position[keep], 3),
                "heading_error_deg": rounded(heading[keep], 3),
                "final_in": round(float(position[-1]), 3),
                "final_deg": round(float(heading[-1]), 3),
                "worst_in": round(float(position.max()), 3),
            }
        )
    return {
        "script": script,
        "noise": noise,
        "seed": seed,
        "time_s": rounded(run.time[keep], 3),
        "truth": rounded(run.truth[keep], 3),
        "estimates": estimates,
    }


def robot_config(params: dict) -> RobotConfig:
    from vexsim.config.loader import validate_robot

    checked = validate_robot(params["robot"])
    if checked.ok and checked.config is not None:
        return checked.config
    problems = "; ".join(
        f"{i.location}: {i.message}" if i.location else i.message for i in checked.errors[:3]
    )
    raise ValueError(f"{_name(params)} isn't a valid robot config: {problems}")


def _name(params: dict) -> str:
    return params.get("robot_name") or params["robot"]
