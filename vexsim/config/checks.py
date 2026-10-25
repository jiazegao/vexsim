"""Cross-field checks on a structurally valid robot config.

Errors make the robot unsimulatable or are near-certain mistakes. Warnings flag
things that are legal but suspicious, or not simulated yet.
"""

from __future__ import annotations

import math

from vexsim.config.issues import ConfigIssue, Severity
from vexsim.config.robot import RobotConfig
from vexsim.physics.params import check_overrides
from vexsim.v5 import MOTOR_11W_POWER_W, MOTOR_POWER_BUDGET_W, STARTING_SIZE_LIMIT_IN

_EPS = 1e-9
SIMULATED_DRIVETRAINS = {"differential"}
SIMULATED_WHEEL_TYPES = {"omni"}
PLAUSIBLE_MASS_KG = (2.0, 15.0)


def _fmt(xy: tuple[float, ...]) -> str:
    return "(" + ", ".join(f"{v:g}" for v in xy) + ")"


def _parallel_to_x(heading_deg: float, tol_deg: float = 0.5) -> bool:
    off = math.remainder(heading_deg, 180.0)
    return abs(off) <= tol_deg


def check_robot(cfg: RobotConfig) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []

    def add(severity: Severity, location: str, message: str) -> None:
        issues.append(ConfigIssue(severity, location, message))

    body = cfg.body
    dt = cfg.drivetrain
    length, width = body.footprint_in
    footprint = f"{length:g} x {width:g} in footprint"

    def inside(xy: tuple[float, float]) -> bool:
        return abs(xy[0]) <= length / 2 + _EPS and abs(xy[1]) <= width / 2 + _EPS

    # Body
    if not inside(body.cg_in[:2]):
        add(
            "error",
            "body.cg_in",
            f"center of gravity {_fmt(body.cg_in[:2])} is outside the {footprint}",
        )
    if max(body.footprint_in) > STARTING_SIZE_LIMIT_IN + _EPS:
        add(
            "warning",
            "body.footprint_in",
            f"{footprint} exceeds the {STARTING_SIZE_LIMIT_IN:g} in starting size limit",
        )
    lo, hi = PLAUSIBLE_MASS_KG
    if not lo <= body.mass_kg <= hi:
        add("warning", "body.mass_kg", f"{body.mass_kg:g} kg is outside the usual {lo:g}-{hi:g} kg")

    # Wheels
    wheel_index: dict[str, int] = {}
    for i, wheel in enumerate(dt.wheels):
        loc = f"drivetrain.wheels[{i}]"
        if wheel.name in wheel_index:
            add(
                "error",
                f"{loc}.name",
                f"duplicate wheel name {wheel.name!r} "
                f"(also drivetrain.wheels[{wheel_index[wheel.name]}])",
            )
            continue
        wheel_index[wheel.name] = i
        if not inside(wheel.pos_in):
            add(
                "error",
                f"{loc}.pos_in",
                f"wheel {wheel.name!r} at {_fmt(wheel.pos_in)} is outside the {footprint}",
            )

    # Gearing groups
    owner: dict[str, str] = {}
    for gname, group in dt.gearing.items():
        gloc = f"drivetrain.gearing.{gname}"
        for j, wname in enumerate(group.wheels):
            if wname not in wheel_index:
                known = ", ".join(wheel_index) or "none"
                add(
                    "error",
                    f"{gloc}.wheels[{j}]",
                    f"unknown wheel {wname!r} (defined wheels: {known})",
                )
            elif wname in owner:
                add(
                    "error",
                    f"{gloc}.wheels[{j}]",
                    f"wheel {wname!r} is already driven by group {owner[wname]!r}",
                )
            else:
                owner[wname] = gname
        diameters = sorted(
            {dt.wheels[wheel_index[w]].diameter_in for w in group.wheels if w in wheel_index}
        )
        if len(diameters) > 1:
            add(
                "warning",
                gloc,
                "wheels geared together have different diameters "
                f"({', '.join(f'{d:g}' for d in diameters)} in) and will scrub against each other",
            )
    for name, i in wheel_index.items():
        if name not in owner:
            add(
                "error",
                f"drivetrain.wheels[{i}]",
                f"wheel {name!r} is not driven by any gearing group",
            )

    # Ports: one device per smart port, motors and sensors together
    claimed: dict[int, str] = {}

    def claim(port: int, location: str) -> None:
        p = abs(port)
        if p in claimed:
            add("error", location, f"port {p} is already used by {claimed[p]}")
        else:
            claimed[p] = location

    for gname, group in dt.gearing.items():
        for j, port in enumerate(group.motors):
            claim(port, f"drivetrain.gearing.{gname}.motors[{j}]")
    for k, sensor in enumerate(cfg.sensors):
        claim(sensor.port, f"sensors[{k}]")

    # Sensor placement
    for k, sensor in enumerate(cfg.sensors):
        if sensor.type in ("imu", "distance") and not inside(sensor.pos_in):
            add(
                "error",
                f"sensors[{k}].pos_in",
                f"{sensor.type} at {_fmt(sensor.pos_in)} is outside the {footprint}",
            )
        if sensor.type == "rotation" and sensor.tracking_wheel is not None:
            tw = sensor.tracking_wheel
            if not inside(tw.pos_in):
                add(
                    "error",
                    f"sensors[{k}].tracking_wheel.pos_in",
                    f"tracking wheel at {_fmt(tw.pos_in)} is outside the {footprint}",
                )

    # Drivetrain layout
    if dt.type == "differential":
        groups = set(dt.gearing)
        if groups != {"left", "right"}:
            add(
                "error",
                "drivetrain.gearing",
                "a differential drivetrain needs exactly the gearing groups 'left' and 'right' "
                f"(found: {', '.join(dt.gearing)})",
            )
        for i, wheel in enumerate(dt.wheels):
            if not _parallel_to_x(wheel.heading_deg):
                add(
                    "warning",
                    f"drivetrain.wheels[{i}].heading_deg",
                    f"wheel {wheel.name!r} is not parallel to the robot's x axis "
                    "(differential wheels normally use heading 0)",
                )
        for side, sign in (("left", 1), ("right", -1)):
            group = dt.gearing.get(side)
            if group is None:
                continue
            for wname in group.wheels:
                if wname in wheel_index:
                    y = dt.wheels[wheel_index[wname]].pos_in[1]
                    if y * sign <= 0:
                        add(
                            "warning",
                            f"drivetrain.gearing.{side}",
                            f"wheel {wname!r} is in group {side!r} but sits at y={y:g} in "
                            "(+y is the robot's left side)",
                        )
    if dt.type not in SIMULATED_DRIVETRAINS:
        add(
            "warning",
            "drivetrain.type",
            f"{dt.type!r} drivetrains are not simulated yet (planned for Phase 9)",
        )
    for wtype in sorted({w.type for w in dt.wheels} - SIMULATED_WHEEL_TYPES):
        add(
            "warning",
            "drivetrain.wheels",
            f"{wtype!r} wheels are not simulated yet (planned for Phase 9)",
        )

    # Motor budget
    n_motors = sum(len(g.motors) for g in dt.gearing.values())
    if n_motors * MOTOR_11W_POWER_W > MOTOR_POWER_BUDGET_W + _EPS:
        add(
            "warning",
            "drivetrain.gearing",
            f"{n_motors} drive motors ({n_motors * MOTOR_11W_POWER_W:g} W) exceed the usual "
            f"{MOTOR_POWER_BUDGET_W:g} W V5RC motor budget; check this season's game manual",
        )

    # Model parameter overrides
    for severity, key, message in check_overrides(cfg.overrides):
        add(severity, f"overrides.{key}", message)

    return issues
