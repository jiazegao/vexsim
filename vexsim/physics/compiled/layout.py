"""Where each number of a compiled robot lives: the tables its block of doubles is laid out
by, and step_layout.h, which is written from them for the C.
"""

from __future__ import annotations

import zlib
from pathlib import Path

from vexsim.physics.motor import BrakeMode, ControlMode

MAX_DOF = 16  # the body's three and a gear group each
MAX_WHEELS = 32
MAX_OCV = 32  # points of a battery's open-circuit curve
CHANNELS = 3


# The robot's record, at the block's start. (name, count) is an array.
ROBOT: tuple[str | tuple[str, int], ...] = (
    # sizes, and where the other records start (set once)
    "dof", "wheels", "drive_motors", "motors", "mechanisms",
    "motors_at", "mechanisms_at", "wheels_at",
    # the body: read from the robot before each step, heading and ground force back after
    "mass", "heading", "lifted", "external_torque", "ground_fx", "ground_fy",
    # the wheels' loads (NormalLoads)
    "stiffness", "weight", "cg_height",
    # the supply: the stock PowerSystem and Battery, or (external) any other, in Python
    "external_supply", "bus_voltage", "load_w", "battery_current_a", "quiescent_a",
    "soc", "charge_used_mah", "capacity_mah", "internal_resistance_ohm", "ocv_points",
    ("ocv_soc", MAX_OCV), ("ocv_v", MAX_OCV),
)  # fmt: skip

# A motor's record: its state (V5Motor's and its MotorThermal's), where it sits, and its
# constants (CoreConstants, MotorSpec, ThermalSpec)
MOTOR: tuple[str, ...] = (
    "position", "velocity", "current", "voltage", "torque", "power_in", "current_limited",
    "mode", "brake_mode", "voltage_cmd", "velocity_cmd", "position_cmd", "max_speed",
    "hold_target", "integral_v", "velocity_est", "accel_est", "current_limit",
    "supply_current_cap", "winding_c", "housing_c",
    "sign", "dof",
    "ratio", "rated_speed",
    "resistance_ohm", "kt", "ke", "coulomb_nm", "viscous_nm_s", "smoothing_rad_s",
    "velocity_kp", "velocity_ki", "velocity_filter_s", "integral_gate", "position_kp",
    "voltage_cap",
    "ambient_c", "winding_heat_capacity_j_per_k", "housing_heat_capacity_j_per_k",
    "winding_to_housing_k_per_w", "housing_to_ambient_k_per_w", "derate_start_c",
    "derate_step_c",
)  # fmt: skip
CORE = ("resistance_ohm", "kt", "ke", "coulomb_nm", "viscous_nm_s", "smoothing_rad_s")
SPEC = ("velocity_kp", "velocity_ki", "velocity_filter_s", "integral_gate", "position_kp",
        "voltage_cap")  # fmt: skip
THERMAL = MOTOR[MOTOR.index("ambient_c") :]

MECHANISM: tuple[str, ...] = (
    "angle", "speed", "inertia", "load", "friction", "low", "high", "first_motor", "motor_count",
)  # fmt: skip

# The wheels' columns: each is one double a wheel
WHEEL: tuple[str, ...] = (
    "base", "sens_x", "sens_y", "pos_x", "pos_y", "drop", "coupled",
    "normal", "slip", "lateral_velocity", "traction_force", "lateral_force",
)  # fmt: skip
CONTACTS = WHEEL[WHEEL.index("normal") :]  # ContactState's arrays

# The robot's NumPy arrays the C reaches by pointer
ARRAYS: tuple[str, ...] = (
    "qdot", "cg", "external_force", "contact_matrix", "mass_matrix", "channel_coeff",
    "channel_scale",
)  # fmt: skip


def _offsets(fields: tuple) -> tuple[dict[str, int], int]:
    at, where = 0, {}
    for entry in fields:
        name, count = entry if isinstance(entry, tuple) else (entry, 1)
        where[name] = at
        at += count
    return where, at


R, R_SIZE = _offsets(ROBOT)
M, M_SIZE = _offsets(MOTOR)
K, K_SIZE = _offsets(MECHANISM)
COLUMN = {name: i for i, name in enumerate(WHEEL)}


def layout_id() -> int:
    """A number for the tables as they are: a library built for other ones isn't used."""
    modes = [[m.name for m in enum] for enum in (ControlMode, BrakeMode)]
    tables = (ROBOT, MOTOR, MECHANISM, WHEEL, ARRAYS, MAX_DOF, MAX_WHEELS, MAX_OCV, modes)
    return zlib.crc32(repr(tables).encode())


def header() -> str:
    """step_layout.h: the tables, for the C."""

    def enum(prefix: str, names: dict[str, int], last: str, size: int) -> list[str]:
        rows = [f"\t{prefix}_{name.upper()} = {at}," for name, at in names.items()]
        return ["enum {", *rows, f"\t{prefix}_{last} = {size},", "};", ""]

    lines = [
        "/* Where each number of a robot lives in its block of doubles, for step.c.",
        " * Written by `python -m vexsim.physics.compiled` from the tables in layout.py:",
        " * change those, not this. */",
        "#ifndef VEXSIM_STEP_LAYOUT_H",
        "#define VEXSIM_STEP_LAYOUT_H",
        "",
        f"#define VEXSIM_LAYOUT 0x{layout_id():08x}u",
        f"#define VEXSIM_MAX_DOF {MAX_DOF}",
        f"#define VEXSIM_MAX_WHEELS {MAX_WHEELS}",
        f"#define VEXSIM_MAX_OCV {MAX_OCV}",
        "",
        "/* the robot's record, at the block's start */",
        *enum("R", R, "SIZE", R_SIZE),
        "/* a motor's record */",
        *enum("M", M, "SIZE", M_SIZE),
        "/* a mechanism's record */",
        *enum("K", K, "SIZE", K_SIZE),
        "/* the wheels' columns: column c of wheel i is at wheels_at + c * wheels + i */",
        *enum("W", COLUMN, "COLUMNS", len(WHEEL)),
        "/* V5Motor's control and brake modes */",
        "enum { " + ", ".join(f"MODE_{m.name}" for m in ControlMode) + " };",
        "enum { " + ", ".join(f"BRAKE_{m.name}" for m in BrakeMode) + " };",
        "",
        "/* the robot's NumPy arrays */",
        "typedef struct {",
        *[f"\tdouble *{name};" for name in ARRAYS],
        "} vexsim_arrays;",
        "",
        "#endif",
    ]
    return "\n".join(lines) + "\n"


SOURCE = Path(__file__).with_name("step.c")
HEADER = Path(__file__).with_name("step_layout.h")
