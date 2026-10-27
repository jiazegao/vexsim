"""New robots and drivetrain presets, for the Design view.

``robot_text`` writes a new robot config: a 15 x 15 in rectangle (a ``body.shape``, ready
to draw over) on one of the usual drivetrains, with comments that say what each section
is. ``preset_changes`` puts one of those drivetrains on a robot that already exists, its
wheels placed in the robot's box and its motors on ports nothing else uses. ``create``
writes a new file and never overwrites one.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from vexsim.app.configs import PatchError, check_text, kind_of
from vexsim.app.yamledit import Change, _flow, _word, apply
from vexsim.config.robot import BodyConfig, _outline
from vexsim.v5 import SMART_PORT_COUNT

PRESETS = {
    "tank4": "4-motor tank drive",
    "tank6": "6-motor tank drive",
    "xdrive": "4-motor X-drive",
    "mecanum": "4-motor mecanum drive",
    "hdrive": "5-motor H-drive",
}
WHEEL_IN = 3.25  # omni wheels; mecanum ones are 4 in
BOX_IN = (15.0, 15.0)  # a new robot's rectangle
MARGIN_IN = 0.5  # a wheel's center at least this far inside the robot's edge


def drivetrain(
    preset: str,
    box: tuple[float, float, float, float],
    ports: list[int],
    on: Callable[[Sequence[float]], bool] | None = None,
    middle: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """A preset's drivetrain (type, wheels, gearing) for a robot whose base spans ``box``
    (min x, min y, max x, max y, inches), its motors on ``ports`` in order. With ``on`` (is
    a point on the robot?), the wheels are drawn in toward the ``middle`` (the box's, if not
    given) until they all are."""
    if preset not in PRESETS:
        raise PatchError(f"no drive preset {preset!r} (there are: {', '.join(PRESETS)})")
    x0, y0, x1, y1 = box
    hx, hy = (x1 - x0) / 2, (y1 - y0) / 2
    ax = max(hx - 2.0, hx / 2)  # wheels this far ahead of and behind the middle
    ay = max(hy - 1.5, hy / 2)  # and this far to the sides
    middle = middle or ((x0 + x1) / 2, (y0 + y1) / 2)
    for _ in range(40):
        drive = _layout(preset, middle, ax, ay, ports)
        if on is None or all(on(wheel["pos_in"]) for wheel in drive["wheels"]):
            break
        ax, ay = ax * 0.9, ay * 0.9
    return drive


def _layout(
    preset: str, middle: tuple[float, float], ax: float, ay: float, ports: list[int]
) -> dict[str, Any]:
    """A preset's drivetrain with its wheels ``ax`` ahead of and behind ``middle`` and ``ay``
    to its sides."""
    cx, cy = middle
    port = iter(ports)

    def at(x: float, y: float) -> list[float]:
        return [round(cx + x, 3), round(cy + y, 3)]

    def omni(name: str, x: float, y: float, heading: float | None = None, **more: Any):
        turned = {} if heading is None else {"heading_deg": heading}
        return {"name": name, "pos_in": at(x, y), **turned, "type": "omni",
                "diameter_in": WHEEL_IN, **more}  # fmt: skip

    def group(motors: int, reversed_: bool, ratio: str, wheels: list[str]) -> dict[str, Any]:
        sign = -1 if reversed_ else 1
        return {
            "motors": [sign * next(port) for _ in range(motors)],
            "cartridge": "blue",
            "ratio": ratio,
            "wheels": wheels,
        }

    if preset in ("tank4", "tank6", "hdrive"):
        middle = preset == "tank6"
        left = ["lf", "lm", "lb"] if middle else ["lf", "lb"]
        right = ["rf", "rm", "rb"] if middle else ["rf", "rb"]
        xs = {"f": ax, "m": 0.0, "b": -ax}
        wheels = [omni(n, xs[n[1]], ay) for n in left] + [omni(n, xs[n[1]], -ay) for n in right]
        gearing = {
            "left": group(len(left), False, "36:48", left),
            "right": group(len(right), True, "36:48", right),
        }
        kind = "differential"
        if preset == "hdrive":
            wheels.append(omni("center", 0.0, 0.0, 90, drop_in=0.04))
            gearing["strafe"] = group(1, False, "36:60", ["center"])
            kind = "hdrive"
        return {"type": kind, "wheels": wheels, "gearing": gearing}
    corners = {"fl": (ax, ay), "fr": (ax, -ay), "bl": (-ax, ay), "br": (-ax, -ay)}
    angles = {"fl": -45, "fr": 45, "bl": 45, "br": -45}
    names = {"fl": "front_left", "fr": "front_right", "bl": "back_left", "br": "back_right"}
    wheels, gearing = [], {}
    for name, (x, y) in corners.items():
        if preset == "xdrive":
            wheels.append(omni(name, x, y, angles[name]))
        else:
            wheels.append(
                {"name": name, "pos_in": at(x, y), "type": "mecanum", "diameter_in": 4.0,
                 "roller_angle_deg": angles[name]}
            )  # fmt: skip
        ratio = "36:60" if preset == "xdrive" else "36:72"
        gearing[names[name]] = group(1, name.endswith("r"), ratio, [name])
    return {"type": preset, "wheels": wheels, "gearing": gearing}


def preset_changes(text: str, preset: str) -> list[Change]:
    """The changes that put a preset's drivetrain on the robot ``text`` describes: its
    wheels in the robot's box, its motors on the lowest ports its mechanisms and sensors
    don't use. The rest of the file stays as it is."""
    checked = check_text(text, "robot")
    config = checked.config
    if config is None:
        raise PatchError("the robot config has errors to fix in the text first")
    used = {abs(p) for m in config.mechanisms.values() for p in m.motors}
    used |= {s.port for s in config.sensors}
    free = [p for p in range(1, SMART_PORT_COUNT + 1) if p not in used]
    needed = {"tank4": 4, "tank6": 6, "xdrive": 4, "mecanum": 4, "hdrive": 5}.get(preset, 0)
    if len(free) < needed:
        raise PatchError(f"a {PRESETS.get(preset, preset)} needs {needed} free ports")
    box, middle, on = base(config.body)
    drive = drivetrain(preset, box, free, on, middle)
    return [
        Change("set", "drivetrain.type", drive["type"]),
        Change("set", "drivetrain.wheels", drive["wheels"]),
        Change("set", "drivetrain.gearing", drive["gearing"]),
    ]


def base(
    body: BodyConfig,
) -> tuple[
    tuple[float, float, float, float], tuple[float, float], Callable[[Sequence[float]], bool]
]:
    """Where a drive goes on a robot: the box around the biggest part of its shape (its
    base, not the intake sticking out of it) and that part's middle (its centroid), and
    whether a point is well inside the robot."""
    outline = body.outline
    biggest = outline
    if body.shape:
        biggest = max((_outline(None, (part,)) for part in body.shape), key=lambda o: o.area)
    _, (mx, my), _ = biggest.moments

    def on(point: Sequence[float]) -> bool:
        return outline.signed_distance(point)[0] <= -MARGIN_IN

    return biggest.bounds, (round(mx, 6), round(my, 6)), on


def robot_text(name: str, preset: str = "tank4") -> str:
    """A new robot config: a rectangle to draw over, on a preset's drivetrain."""
    half_x, half_y = BOX_IN[0] / 2, BOX_IN[1] / 2
    drive = drivetrain(preset, (-half_x, -half_y, half_x, half_y), list(range(1, 22)))
    lines = [
        f"# {name}: a robot made in vexsim's Design view. Change it there (its shape, drive,",
        "# mechanisms and sensors) or here: the Design view keeps what you write, comments too.",
        "#",
        "# Units: inches, degrees, kg, rpm. Robot frame: +x forward, +y left, angles",
        "# counter-clockwise from +x; the shape's parts are placed around the robot's origin.",
        "# See docs/conventions.md for the full reference.",
        "",
        "version: 1",
        f"name: {_word(name)}",
        "",
        "body:",
        "  mass_kg: 6.5                  # the whole robot",
        "  inertia_kgm2: auto            # auto = uniform over the shape, or a number in kg*m^2",
        "  shape:                        # seen from above; where parts overlap they merge",
        f"    - {{type: rect, pos_in: [0, 0], size_in: [{BOX_IN[0]:g}, {BOX_IN[1]:g}]}}",
        "  cg_in: [0, 0, 3.5]            # x, y, height above the floor",
        "  battery: v5_default",
        "",
        "drivetrain:",
        f"  type: {drive['type']:<24}# differential | xdrive | mecanum | hdrive",
        "  wheels:                       # every wheel, listed explicitly",
        *(f"    - {_flow(wheel)}" for wheel in drive["wheels"]),
        "  gearing:                      # motors geared to wheels; a negative port is reversed",
        *(f"    {group}: {_flow(gear)}" for group, gear in drive["gearing"].items()),
        "",
        "mechanisms: {}                  # other motors: an intake, a lift, an arm",
        "",
        "sensors: []                     # imu, rotation (tracking wheels), distance, gps",
        "",
        "# Optional model tuning (docs/models.md lists every parameter):",
        "# overrides:",
        "#   wheel.omni.lateral_mu: 0.25",
        "",
    ]
    return "\n".join(lines)


def file_name(name: str) -> str:
    """A robot's file name from its name: ``Test bot #2`` -> ``test_bot_2.yaml``."""
    stem = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"{stem or 'robot'}.yaml"


def create(path: Path, name: str, preset: str = "tank4", copy: Path | None = None) -> str:
    """Write a new robot config at ``path`` (never over a file): a rectangle on a preset's
    drivetrain, or a copy of the robot at ``copy`` under its new name. Returns its text."""
    if path.suffix.lower() not in (".yaml", ".yml"):
        raise PatchError(f"{path.name} isn't a YAML file name (it should end in .yaml)")
    if copy is not None:
        try:
            text = copy.read_text(encoding="utf-8").replace("\r\n", "\n")
        except FileNotFoundError:
            raise PatchError(f"{copy.name} isn't there to copy") from None
        if kind_of(text) != "robot":
            raise PatchError(f"{copy.name} isn't a robot config")
        text = apply(text, [Change("set", "name", name)])
    else:
        text = robot_text(name, preset)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as file:
            file.write(text)
    except FileExistsError:
        raise PatchError(f"{path.name} is already there: pick another name") from None
    return text
