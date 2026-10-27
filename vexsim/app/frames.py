"""What the UI draws: a run's scene (sent once) and its frames (about 60 a second).

Plain dicts of numbers, ready for JSON: the worker process builds them without pydantic's
cost per frame, and ``vexsim.ui.protocol`` describes their shape (tests check one against
the other). Lengths are inches, angles degrees counter-clockwise from +x, in the field
frame, except where a name says otherwise.
"""

from __future__ import annotations

import math
from typing import Any

from vexsim.units import m_to_in


def _r(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def scene_of(sim, *, mode: str, spec: dict, command: str) -> dict[str, Any]:
    """The parts of a run that don't move: the robot's shape and mounts, the field."""
    cfg = sim.robot.config
    wheels = [
        {
            "name": w.name,
            "x": _r(w.pos_in[0]),
            "y": _r(w.pos_in[1]),
            "heading": _r(w.heading_deg),
            "diameter": _r(w.diameter_in),
            "type": w.type,
        }
        for w in cfg.drivetrain.wheels
    ]
    sensors = []
    for s in cfg.sensors:
        if s.type == "rotation":
            continue  # inside the robot; nothing to draw
        heading = getattr(s, "heading_deg", None)
        if heading is None:
            heading = getattr(s, "mount_yaw_deg", 0.0)
        sensors.append(
            {
                "kind": s.type,
                "port": s.port,
                "x": _r(s.pos_in[0]),
                "y": _r(s.pos_in[1]),
                "heading": _r(heading),
            }
        )
    field = sim.field
    obstacles, pieces = [], []
    if sim.arena is not None:
        for shape in sim.arena.obstacles:
            item: dict[str, Any] = {"color": shape.color, "solid": bool(shape.solid)}
            if shape.circle:
                x, y = (m_to_in(v) for v in shape.center)
                item.update(shape="circle", x=_r(x), y=_r(y), radius=_r(m_to_in(shape.half[0])))
            else:
                corners = [[_r(m_to_in(px)), _r(m_to_in(py))] for px, py in shape.corners()]
                item.update(shape="polygon", points=corners)
            obstacles.append(item)
        p = sim.arena.pieces
        pieces = [
            {"radius": _r(m_to_in(r)), "color": color}
            for r, color in zip(p.radius, p.colors, strict=True)
        ]
    return {
        "type": "scene",
        "robot": {
            "name": cfg.name or "robot",
            "footprint": [_r(v) for v in cfg.body.footprint_in],
            "wheels": wheels,
            "sensors": sensors,
        },
        "field": {
            "name": field.name or "field",
            "size": [_r(v) for v in field.size_in],
            "obstacles": obstacles,
            "pieces": pieces,
        },
        "mode": mode,
        "start": list(spec["start"]),
        "seed": spec["seed"],
        "spec": spec,
        "command": command,
    }


def _pose(pose) -> list[float]:
    return [_r(pose.x), _r(pose.y), _r(math.remainder(pose.heading, 360.0), 2)]


def frame_of(sim, *, state: str, speed: float | None, rate: float) -> dict[str, Any]:
    """Where everything is now. ``speed`` None means as fast as possible."""
    from vexsim.algorithms.localization.base import Pose

    robot = sim.robot
    cfg = robot.config
    x, y, h = robot.pose
    c, s = math.cos(h), math.sin(h)
    contacts = robot.contacts
    wheels = []
    for i, w in enumerate(cfg.drivetrain.wheels):
        wx, wy = w.pos_in
        slip = 0.0
        if len(contacts.slip):
            limit = max(robot.grip_mu[i] * contacts.normal[i], 1e-9)
            slip = min(1.0, abs(contacts.traction_force[i]) / limit)
        wheels.append(
            [
                _r(m_to_in(x) + c * wx - s * wy),
                _r(m_to_in(y) + s * wx + c * wy),
                _r(math.degrees(h) + w.heading_deg, 2),
                _r(slip, 2),
            ]
        )
    u, v, _ = robot.body_velocity
    estimated = None
    if sim.localizer_ready or sim.reported_pose is not None:
        estimated = _pose(sim.estimated_pose)
    distance = {}
    for port, device in sim.sensors.devices.items():
        if device.kind == "distance":
            distance[str(port)] = device.value  # mm, or None when it sees nothing
    pieces = []
    if sim.arena is not None:
        pieces = [[_r(m_to_in(px)), _r(m_to_in(py))] for px, py in sim.arena.pieces.position]
    return {
        "type": "frame",
        "t": _r(sim.world.time, 4),
        "phase": sim.phase,
        "state": state,
        "speed": speed,
        "rate": _r(rate, 2),
        "pose": _pose(Pose.from_si(robot.pose)),
        "estimate": estimated,
        "speed_in_s": _r(m_to_in(math.hypot(u, v)), 2),
        "battery": [_r(robot.power.bus_voltage, 2), _r(robot.power.battery.soc, 3)],
        "wheels": wheels,
        "distance": distance,
        "pieces": pieces,
        "contacts": [
            [_r(m_to_in(cp.point[0])), _r(m_to_in(cp.point[1]))] for cp in robot.wall_contacts
        ],
        "motors": [
            [port, _r(abs(m.current), 2), _r(m.temperature_c, 1), bool(m.over_temp)]
            for port, m in sorted(robot.motors.items())
        ],
        "lcd": [sim.lcd[k] for k in sorted(sim.lcd)],
        "controller_screen": [sim.controller_screen[k] for k in sorted(sim.controller_screen)],
    }


def overlay_of(sim) -> dict[str, Any]:
    """What a Python program's chassis motion is aiming at: its path and target, if any."""
    import numpy as np

    path, target = None, None
    chassis = sim.bot.chassis
    active = chassis.active if chassis else None
    if active is not None:
        points = getattr(active, "path", None)
        trajectory = getattr(active, "trajectory", None)
        if points is None and trajectory is not None:
            points = trajectory.states[:, :2]
        if points is not None:
            path = [[_r(px, 2), _r(py, 2)] for px, py in np.asarray(points)[:, :2]]
        if hasattr(active, "x") and hasattr(active, "y"):
            heading = getattr(active, "heading", None)
            target = [_r(active.x), _r(active.y), None if heading is None else _r(heading, 2)]
    return {"type": "overlay", "path": path, "target": target}
