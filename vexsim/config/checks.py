"""Cross-field checks on a structurally valid robot config.

Errors make the robot unsimulatable or are near-certain mistakes. Warnings flag
things that are legal but suspicious.
"""

from __future__ import annotations

import math

from vexsim.config.issues import ConfigIssue, Severity
from vexsim.config.robot import RobotConfig
from vexsim.physics.kinematics import DriveKinematics
from vexsim.physics.params import check_overrides
from vexsim.v5 import MOTOR_11W_POWER_W, MOTOR_POWER_BUDGET_W, STARTING_SIZE_LIMIT_IN

_EPS = 1e-9
PLAUSIBLE_MASS_KG = (2.0, 15.0)
TANK_GROUPS = ("left", "right")
USUAL_WHEELS = {"xdrive": "omni", "mecanum": "mecanum"}


def _fmt(xy: tuple[float, ...]) -> str:
    return "(" + ", ".join(f"{v:g}" for v in xy) + ")"


def _cross(o: tuple[float, ...], a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Counter-clockwise convex hull (monotone chain); collinear points are dropped."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts
    lower: list[tuple[float, float]] = []
    upper: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= _EPS:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= _EPS:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _inside_convex(point: tuple[float, ...], hull: list[tuple[float, float]]) -> bool:
    return all(_cross(hull[i], hull[(i + 1) % len(hull)], point) >= -_EPS for i in range(len(hull)))


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
        if wheel.type == "mecanum" and wheel.roller_angle_deg is None:
            add(
                "error",
                f"{loc}.roller_angle_deg",
                f"mecanum wheel {wheel.name!r} needs roller_angle_deg: the angle of its ground "
                "rollers' axis from the rolling direction (usually -45 or 45)",
            )
        elif wheel.type != "mecanum" and wheel.roller_angle_deg is not None:
            add(
                "error",
                f"{loc}.roller_angle_deg",
                f"only mecanum wheels have angled rollers ({wheel.name!r} is {wheel.type})",
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
    for mname, mech in cfg.mechanisms.items():
        for j, port in enumerate(mech.motors):
            claim(port, f"mechanisms.{mname}.motors[{j}]")
    for k, sensor in enumerate(cfg.sensors):
        claim(sensor.port, f"sensors[{k}]")

    # Sensor placement
    for k, sensor in enumerate(cfg.sensors):
        if sensor.type in ("imu", "distance", "gps") and not inside(sensor.pos_in):
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
    if dt.type in ("differential", "hdrive"):
        _check_tank(cfg, wheel_index, add)
    usual = USUAL_WHEELS.get(dt.type)
    if usual is not None:
        others = sorted({w.name for w in dt.wheels if w.type != usual})
        if others:
            add(
                "warning",
                "drivetrain.wheels",
                f"{dt.type} drivetrains normally use {usual} wheels; "
                f"{', '.join(repr(n) for n in others)} are not",
            )
    groups_ok = all(w in wheel_index for g in dt.gearing.values() for w in g.wheels)
    if dt.type != "differential" and groups_ok and not any(i.severity == "error" for i in issues):
        if not DriveKinematics.from_config(cfg).holonomic:
            angles = ", wheel headings and roller angles" if dt.type == "mecanum" else ""
            add(
                "error",
                "drivetrain",
                f"this {dt.type} can't strafe independently of driving and turning; "
                f"check the gearing groups{angles or ' and wheel headings'}",
            )

    # Support polygon: the CG must sit over the wheels or the robot tips over.
    if len(wheel_index) >= 1:
        contacts = [dt.wheels[i].pos_in for i in wheel_index.values()]
        hull = _convex_hull(contacts)
        if len(hull) < 3:
            add(
                "error",
                "drivetrain.wheels",
                "wheels must not all lie on one line; the robot would tip over",
            )
        elif not _inside_convex(body.cg_in[:2], hull):
            add(
                "error",
                "body.cg_in",
                f"center of gravity {_fmt(body.cg_in[:2])} is outside the polygon formed by "
                "the wheels; the robot would tip over",
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


def _check_tank(cfg: RobotConfig, wheel_index: dict[str, int], add) -> None:
    """Left/right sides of a differential drive, or of an H-drive plus its strafe groups."""
    dt = cfg.drivetrain
    groups = set(dt.gearing)
    if dt.type == "differential" and groups != set(TANK_GROUPS):
        add(
            "error",
            "drivetrain.gearing",
            "a differential drivetrain needs exactly the gearing groups 'left' and 'right' "
            f"(found: {', '.join(dt.gearing)})",
        )
    if dt.type == "hdrive" and (not groups > set(TANK_GROUPS)):
        add(
            "error",
            "drivetrain.gearing",
            "an H-drive needs the gearing groups 'left' and 'right' plus a strafe group "
            f"(found: {', '.join(dt.gearing)})",
        )
    for gname, group in dt.gearing.items():
        sideways = gname not in TANK_GROUPS
        for wname in group.wheels:
            if wname not in wheel_index:
                continue
            i = wheel_index[wname]
            heading = dt.wheels[i].heading_deg
            if not sideways and not _parallel_to_x(heading):
                add(
                    "warning",
                    f"drivetrain.wheels[{i}].heading_deg",
                    f"wheel {wname!r} is not parallel to the robot's x axis "
                    "(left and right wheels normally use heading 0)",
                )
            if sideways and not _parallel_to_x(heading - 90.0):
                add(
                    "warning",
                    f"drivetrain.wheels[{i}].heading_deg",
                    f"strafe wheel {wname!r} is not perpendicular to the robot's x axis "
                    "(strafe wheels normally use heading 90)",
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
