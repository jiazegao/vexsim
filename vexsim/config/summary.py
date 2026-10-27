"""Human-readable summaries of configs (ASCII only, so Windows consoles never choke)."""

from __future__ import annotations

import math
from collections import Counter

from vexsim.config.field import FieldConfig
from vexsim.config.robot import RobotConfig
from vexsim.physics.kinematics import DriveKinematics
from vexsim.units import kg_to_lb, m_to_in
from vexsim.v5 import CARTRIDGE_FREE_RPM


def _xy(v: tuple[float, ...]) -> str:
    return "(" + ", ".join(f"{c:.1f}" for c in v) + ") in"


def robot_summary(cfg: RobotConfig) -> list[str]:
    body, dt = cfg.body, cfg.drivetrain
    lines = []
    if cfg.name:
        lines.append(f"  name        {cfg.name}")
    if body.shape is None:
        inertia_note = "auto: uniform box" if body.inertia_kgm2 == "auto" else "explicit"
        size = f"footprint {body.footprint_in[0]:.1f} x {body.footprint_in[1]:.1f} in"
    else:
        inertia_note = "auto: uniform over the shape" if body.inertia_kgm2 == "auto" else "explicit"
        parts = len(body.shape)
        size = (
            f"shape {body.size_in[0]:.1f} x {body.size_in[1]:.1f} in "
            f"({parts} part{'s' * (parts != 1)}, {body.outline.area:.0f} sq in)"
        )
    lines += [
        f"  body        {body.mass_kg:.2f} kg ({kg_to_lb(body.mass_kg):.1f} lb), {size}, "
        f"CG {_xy(body.cg_in)}",
        f"              yaw inertia {body.yaw_inertia_kgm2():.3f} kg*m^2 ({inertia_note})",
    ]

    types = Counter(w.type for w in dt.wheels)
    type_text = ", ".join(f"{n} {t}" for t, n in types.items())
    lines.append(f"  drivetrain  {dt.type}, {len(dt.wheels)} wheels ({type_text})")
    names = {w.name: w for w in dt.wheels}
    width = max(9, *(len(g) for g in dt.gearing))
    for gname, group in dt.gearing.items():
        ports = ", ".join(str(p) for p in group.motors)
        diameters = sorted({names[w].diameter_in for w in group.wheels if w in names})
        speeds = ", ".join(
            f"{d:g} in -> {group.wheel_free_rpm / 60.0 * math.pi * d:.1f} in/s" for d in diameters
        )
        lines.append(
            f"    {gname:<{width}} motors {ports} | {group.cartridge} {group.motor_free_rpm:g} rpm"
            f" | ratio {group.ratio} -> {group.wheel_free_rpm:g} rpm | {speeds} free speed"
        )
    if all(w in names for g in dt.gearing.values() for w in g.wheels):
        forward, sideways, turn = DriveKinematics.from_config(cfg).top_speeds()
        strafe = f", sideways {m_to_in(sideways):.1f} in/s" if sideways else ""
        lines.append(
            f"    top speed forward {m_to_in(forward):.1f} in/s{strafe}, "
            f"turning {math.degrees(turn):.0f} deg/s (kinematic, rated motor speed)"
        )

    for k, (mname, mech) in enumerate(cfg.mechanisms.items()):
        label = "  mechanisms  " if k == 0 else "              "
        ports = ", ".join(str(p) for p in mech.motors)
        output_rpm = CARTRIDGE_FREE_RPM[mech.cartridge] * mech.speed_ratio
        detail = f"motors {ports} | {mech.cartridge} | ratio {mech.ratio} -> {output_rpm:g} rpm"
        if mech.range_deg is not None:
            detail += f" | stops at {mech.range_deg[0]:g} and {mech.range_deg[1]:g} deg"
        if mech.load_torque_nm:
            detail += f" | load {mech.load_torque_nm:g} N*m"
        lines.append(f"{label}{mname}: {detail}")

    if not cfg.sensors:
        lines.append("  sensors     none")
    for k, s in enumerate(cfg.sensors):
        label = "  sensors     " if k == 0 else "              "
        if s.type == "imu":
            detail = f"at {_xy(s.pos_in)}, mount yaw {s.mount_yaw_deg:g} deg"
            if s.scale_error is not None:
                detail += f", scale error {s.scale_error * 100:+.3g}%"
        elif s.type == "distance":
            detail = f"at {_xy(s.pos_in)}, facing {s.heading_deg:g} deg"
            if s.height_in is not None:
                detail += f", {s.height_in:g} in high"
        elif s.type == "gps":
            detail = f"at {_xy(s.pos_in)}, camera facing {s.mount_yaw_deg:g} deg"
        elif s.tracking_wheel is not None:
            tw = s.tracking_wheel
            detail = (
                f"tracking wheel {tw.diameter_in:.2f} in at {_xy(tw.pos_in)}, "
                f"heading {tw.heading_deg:g} deg"
            )
        else:
            detail = "not a tracking wheel"
        if s.type == "rotation" and s.reversed:
            detail += ", reversed"
        lines.append(f"{label}port {s.port:<3} {s.type:<9} {detail}, noise {s.noise}")

    if cfg.overrides:
        lines.append(f"  overrides   {', '.join(f'{k}={v}' for k, v in cfg.overrides.items())}")
    return lines


def field_summary(cfg: FieldConfig) -> list[str]:
    lines = [f"  {cfg.name}, {cfg.size_in[0]:.1f} x {cfg.size_in[1]:.1f} in inside the walls"]
    obstacles, pieces = cfg.obstacles, cfg.pieces
    if obstacles or pieces:
        mass = sum(p.mass_kg for p in pieces)
        low = sum(not o.solid for o in obstacles)
        over = f" ({low} the robot drives over)" if low else ""
        lines.append(
            f"  {len(obstacles)} obstacle(s){over}, {len(pieces)} piece(s) ({mass:.2f} kg in all)"
        )
    return lines
