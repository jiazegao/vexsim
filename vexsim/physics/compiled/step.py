"""One robot's compiled step: whether it can have one, its block, and the step itself (or
both steps, compared).
"""

from __future__ import annotations

import ctypes
from typing import Any

import numpy as np

from vexsim.physics.battery import Battery, BatterySpec
from vexsim.physics.chassis import NormalLoads
from vexsim.physics.compiled.layout import (
    ARRAYS,
    CHANNELS,
    CONTACTS,
    CORE,
    K_SIZE,
    M_SIZE,
    MAX_DOF,
    MAX_OCV,
    MAX_WHEELS,
    R_SIZE,
    ROBOT,
    SPEC,
    THERMAL,
    WHEEL,
    K,
    M,
    R,
)
from vexsim.physics.compiled.lib import Library, library, reason
from vexsim.physics.compiled.modes import ENV, TOLERANCE, StepMismatch, StepUnavailable, mode
from vexsim.physics.compiled.views import (
    SharedBattery,
    SharedMechanism,
    SharedMotor,
    SharedPower,
    SharedThermal,
    _adopt,
    _contacts_view,
    _release,
)
from vexsim.physics.mechanism import Mechanism
from vexsim.physics.motor import CoreConstants, Motor55Spec, MotorSpec, V5Motor
from vexsim.physics.power import PowerSystem
from vexsim.physics.thermal import MotorThermal, Thermal55Spec, ThermalSpec


class _Arrays(ctypes.Structure):
    _fields_ = [(name, ctypes.c_void_p) for name in ARRAYS]


def _array(value: Any, shape: tuple[int, ...]) -> bool:
    """Whether the C can read (and write) this array where it is."""
    return (
        isinstance(value, np.ndarray)
        and value.dtype == np.float64
        and value.shape == shape
        and value.flags.c_contiguous
        and value.flags.writeable
    )


def why_not(robot: Any) -> str | None:
    """Why this robot steps in Python, if it has to: None when the compiled step can take it."""
    from vexsim.physics.robot import ContactState, DriveGroup, Robot

    if type(robot) is not Robot:
        return f"a {type(robot).__name__} isn't a plain Robot"
    n, wheels = 3 + len(robot.groups), len(robot.wheel_names)
    if n > MAX_DOF or not 1 <= wheels <= MAX_WHEELS:
        return f"{len(robot.groups)} gear groups and {wheels} wheels are more than it's built for"
    if not isinstance(robot.contacts, ContactState) or type(robot.normal_loads) is not NormalLoads:
        return "its contact state or its wheels' loads aren't vexsim's own"
    rows = CHANNELS * wheels
    shapes = {
        "qdot": (n,), "cg_position": (2,), "external_force": (2,), "contact_matrix": (rows, n),
        "mass_matrix": (n, n), "_channel_coeff": (rows,), "_channel_scale": (rows,),
    }  # fmt: skip
    for name, shape in shapes.items():
        if not _array(getattr(robot, name), shape):
            return f"its {name.lstrip('_')} isn't an array of {shape} floats"
    loads = robot.normal_loads
    for name, shape in (("_base", (wheels,)), ("_sens", (wheels, 2)), ("pos", (wheels, 2))):
        if not _array(getattr(loads, name), shape):
            return f"its wheels' loads' {name.lstrip('_')} isn't an array of {shape} floats"
    if not _array(loads.drop, (wheels,)):
        return "its wheels' drops aren't an array of floats"
    seen: set[int] = set()
    for owner in (*robot.groups, *robot.mechanisms.values()):
        if type(owner) not in (DriveGroup, Mechanism, SharedMechanism):
            return f"a {type(owner).__name__} isn't a plain gear group or Mechanism"
        if type(owner) is DriveGroup and not 3 <= owner.index < n:
            return "a gear group's place isn't among the robot's velocities"
        for _, sign, motor in owner.motors:
            if type(motor) not in (V5Motor, SharedMotor) or sign not in (1, -1):
                return f"a {type(motor).__name__} isn't a plain V5Motor"
            if type(motor.thermal) not in (MotorThermal, SharedThermal):
                return f"a {type(motor.thermal).__name__} isn't a plain MotorThermal"
            if type(motor.spec) not in (MotorSpec, Motor55Spec):
                return "a motor's constants aren't vexsim's own"
            if type(motor.core) is not CoreConstants:
                return "a motor's constants aren't vexsim's own"
            if type(motor.thermal.spec) not in (ThermalSpec, Thermal55Spec):
                return "a motor's thermal constants aren't vexsim's own"
            if motor.supply is not robot.power:
                return "a motor's supply isn't the robot's"
            if id(motor) in seen:
                return "a motor is in two places"
            seen.add(id(motor))
    return None


def _motors(robot: Any) -> tuple[list[tuple], list[tuple]]:
    """A robot's motors in the order the step takes them, each as (motor, mount sign,
    place): the drive's, with their group's place in qdot, then the mechanisms', with their
    mechanism's number."""
    drive = [(m, sign, group.index) for group in robot.groups for _, sign, m in group.motors]
    driven = [
        (m, sign, k)
        for k, mechanism in enumerate(robot.mechanisms.values())
        for _, sign, m in mechanism.motors
    ]
    return drive, driven


class Compiled:
    """One robot's compiled step: its block, and the step that runs on it."""

    def __init__(self, robot: Any, lib: Library, *, check: bool = False):
        self.robot = robot
        self.lib = lib
        self.check = check
        self.worst = 0.0  # the largest difference a check has seen (a part of the number's size)
        self.stale = False
        self.usable = False
        self.why = ""
        groups, mechanisms = robot.groups, list(robot.mechanisms.values())
        self.drive, self.driven = _motors(robot)
        self.mechanisms = mechanisms
        motors = len(self.drive) + len(self.driven)
        self.wheels = wheels = len(robot.wheel_names)
        self.motors_at = R_SIZE
        self.mechanisms_at = self.motors_at + motors * M_SIZE
        self.wheels_at = self.mechanisms_at + len(mechanisms) * K_SIZE
        size = self.wheels_at + len(WHEEL) * wheels

        self.block = (ctypes.c_double * size)()
        self.address = ctypes.addressof(self.block)
        self.v = v = memoryview(self.block).cast("B").cast("d")  # plain floats in and out
        self.numbers = np.frombuffer(self.block, dtype=np.float64)
        self.arrays = _Arrays()
        self.arrays_address = ctypes.addressof(self.arrays)
        n, rows = 3 + len(groups), CHANNELS * wheels
        self.shapes = ((n,), (2,), (2,), (rows, n), (n, n), (rows,), (rows,))  # ARRAYS'
        self.bound: tuple = ()  # the robot's arrays and objects the block points at or copies
        self.power: Any = None
        self.external = False  # the supply isn't the stock one: it steps in Python
        self.supply: tuple = ()  # the power system and battery whose numbers are in the block
        v[R["dof"]], v[R["wheels"]] = n, wheels
        v[R["drive_motors"]], v[R["motors"]] = len(self.drive), motors
        v[R["mechanisms"]] = len(mechanisms)
        v[R["motors_at"]], v[R["mechanisms_at"]] = self.motors_at, self.mechanisms_at
        v[R["wheels_at"]] = self.wheels_at

        first = len(self.drive)
        for k, mechanism in enumerate(mechanisms):
            at = self.mechanisms_at + k * K_SIZE
            _adopt(mechanism, SharedMechanism, self, _v=v[at : at + K_SIZE])
            v[at + K["first_motor"]], v[at + K["motor_count"]] = first, len(mechanism.motors)
            first += len(mechanism.motors)
        for i, (motor, _, _) in enumerate(self.drive + self.driven):
            at = self.motors_at + i * M_SIZE
            _adopt(motor, SharedMotor, self, _v=v[at : at + M_SIZE])
        self.thermals: list[Any] = [None] * motors
        columns = self.numbers[self.wheels_at :].reshape(len(WHEEL), wheels)
        self.columns = {name: columns[i] for i, name in enumerate(WHEEL)}
        shown = [self.columns[name] for name in CONTACTS]
        _adopt(robot.contacts, _contacts_view(), self, _columns=shown)
        self.contacts = robot.contacts
        self.refresh()

    # --- what the step reads that isn't a number in the block ---------------------------------

    def refresh(self) -> None:
        """Read again what the block holds a copy of, or a pointer to: constants, which
        arrays, which supply. Before a robot's first compiled step, and whenever one of
        those was replaced."""
        robot = self.robot
        v, loads = self.v, robot.normal_loads
        self.stale = False
        self.usable = False
        self.power = robot.power
        self.bound = (
            robot.qdot, robot.cg_position, robot.external_force, robot.contact_matrix,
            robot.mass_matrix, robot._channel_coeff, robot._channel_scale, loads, robot.contacts,
        )  # fmt: skip
        self.why = why_not(robot) or self._structure() or ""
        if self.why:
            return
        for name, array in zip(ARRAYS, self.bound, strict=False):
            setattr(self.arrays, name, array.ctypes.data)

        columns = self.columns
        columns["base"][:], columns["drop"][:] = loads._base, loads.drop
        columns["sens_x"][:], columns["sens_y"][:] = loads._sens[:, 0], loads._sens[:, 1]
        columns["pos_x"][:], columns["pos_y"][:] = loads.pos[:, 0], loads.pos[:, 1]
        columns["coupled"][:] = 0.0
        for row in robot._coupled_rows:
            columns["coupled"][row // CHANNELS] = 1.0
        v[R["stiffness"]], v[R["weight"]] = loads.stiffness, loads.weight
        v[R["cg_height"]] = loads.cg_height

        for i, (motor, sign, place) in enumerate(self.drive + self.driven):
            at = self.motors_at + i * M_SIZE
            thermal, old = motor.thermal, self.thermals[i]
            if old is not thermal:
                if type(old) is SharedThermal:
                    _release(old)  # one that was replaced keeps its numbers
                _adopt(thermal, SharedThermal, self, _v=motor._v)
                self.thermals[i] = thermal
            v[at + M["sign"]] = sign
            v[at + M["dof"]] = place if i < len(self.drive) else -1
            v[at + M["gear"]] = motor.gear
            v[at + M["ratio"]], v[at + M["rated_speed"]] = motor.ratio, motor.rated_speed
            for name in CORE:
                v[at + M[name]] = getattr(motor.core, name)
            for name in SPEC:
                v[at + M[name]] = getattr(motor.spec, name)
            for name in THERMAL:
                v[at + M[name]] = getattr(thermal.spec, name)
        self._supply()
        self.usable = True

    def rebind(self) -> None:
        """Point the C at the robot's arrays as they are now. One was replaced: ``place``
        makes a new ``cg_position``, a push a new ``external_force`` every step."""
        robot = self.robot
        now = (
            robot.qdot, robot.cg_position, robot.external_force, robot.contact_matrix,
            robot.mass_matrix, robot._channel_coeff, robot._channel_scale,
        )  # fmt: skip
        old, self.bound = self.bound, (*now, *self.bound[len(now) :])
        for name, array, was, shape in zip(ARRAYS, now, old, self.shapes, strict=False):
            if array is was:
                continue
            if not _array(array, shape):  # the Python step takes it, whatever it is
                self.why, self.usable = f"its {name} isn't an array of {shape} floats", False
                return
            setattr(self.arrays, name, array.ctypes.data)

    def _structure(self) -> str | None:
        """The robot's motors and mechanisms are the ones the block was laid out for."""
        mechanisms = list(self.robot.mechanisms.values())
        same = len(mechanisms) == len(self.mechanisms) and all(
            a is b for a, b in zip(mechanisms, self.mechanisms, strict=True)
        )
        for now, then in zip(_motors(self.robot), (self.drive, self.driven), strict=True):
            same = same and len(now) == len(then)
            same = same and all(
                a[0] is b[0] and a[1:] == b[1:] for a, b in zip(now, then, strict=False)
            )
        return None if same else "its motors or mechanisms changed after its first step"

    def _supply(self) -> None:
        """The stock power system and battery step in the C; any other supply is asked its
        voltage before a step and given the load after it, in Python."""
        power, v = self.power, self.v
        battery = getattr(power, "battery", None)
        native = (
            type(power) in (PowerSystem, SharedPower)
            and type(battery) in (Battery, SharedBattery)
            and type(battery.spec) is BatterySpec
            and len(battery.spec.ocv_soc) <= MAX_OCV
        )
        keep = (power, battery) if native else ()
        for old in self.supply:
            if all(old is not kept for kept in keep):
                _release(old)  # a supply that was replaced keeps its numbers
        self.supply, self.external = keep, not native
        v[R["external_supply"]] = 0.0 if native else 1.0
        if not native:
            return
        _adopt(power, SharedPower, self, _v=v)
        _adopt(battery, SharedBattery, self, _v=v)
        spec = battery.spec
        v[R["capacity_mah"]] = spec.capacity_mah
        v[R["internal_resistance_ohm"]] = spec.internal_resistance_ohm
        v[R["ocv_points"]] = len(spec.ocv_soc)
        for i, (soc, volts) in enumerate(zip(spec.ocv_soc, spec.ocv_v, strict=True)):
            v[R["ocv_soc"] + i], v[R["ocv_v"] + i] = soc, volts

    # --- the step --------------------------------------------------------------------------------

    def step(self, dt: float) -> None:
        """One step of the robot, up to the walls (what ``Robot._step_python`` does)."""
        robot = self.robot
        bound = self.bound
        if (
            self.stale
            or robot.power is not self.power
            or robot.normal_loads is not bound[7]
            or robot.contacts is not bound[8]
        ):
            self.refresh()
        elif (
            robot.qdot is not bound[0]
            or robot.cg_position is not bound[1]
            or robot.external_force is not bound[2]
            or robot.contact_matrix is not bound[3]
            or robot.mass_matrix is not bound[4]
            or robot._channel_coeff is not bound[5]
            or robot._channel_scale is not bound[6]
        ):
            if self.usable:
                self.rebind()
            else:  # it wasn't taking the robot: whether it can now is looked at whole
                self.refresh()
        if not self.usable:
            robot._step_python(dt)
            return
        if self.check:
            self._step_checked(dt)
            return
        v = self.v
        self._pack(v, robot)
        if self.external:
            v[R_BUS_VOLTAGE] = robot.power.bus_voltage
            v[R_LOAD_W] = 0.0
        if self.lib.step(self.address, self.arrays_address, dt):
            raise np.linalg.LinAlgError("Singular matrix")
        robot.heading = v[R_HEADING]
        robot.time += dt
        robot._ground_force = (v[R_GROUND_FX], v[R_GROUND_FY])
        if self.external:
            power = robot.power
            power.add_load(v[R_LOAD_W])
            power.end_step(dt)

    @staticmethod
    def _pack(v: memoryview, robot: Any) -> None:
        """The robot's own numbers (they stay plain attributes) into the block."""
        v[R_MASS] = robot.mass
        v[R_HEADING] = robot.heading
        v[R_LIFTED] = 1.0 if robot.lifted else 0.0
        v[R_EXTERNAL_TORQUE] = robot.external_torque
        v[R_GROUND_FX], v[R_GROUND_FY] = robot._ground_force

    def _step_checked(self, dt: float) -> None:
        """Both steps from the same state; the Python step's result stands, and the
        compiled step's has to be within ``TOLERANCE`` of it."""
        robot, v, numbers = self.robot, self.v, self.numbers
        qdot, cg = robot.qdot, robot.cg_position
        self._pack(v, robot)
        if self.external:
            v[R_BUS_VOLTAGE] = robot.power.bus_voltage
            v[R_LOAD_W] = 0.0
        before = (numbers.copy(), qdot.copy(), cg.copy())
        failed = self.lib.step(self.address, self.arrays_address, dt)
        compiled = np.concatenate([numbers, qdot, cg])
        numbers[:], qdot[:], cg[:] = before
        try:
            robot._step_python(dt)
        except np.linalg.LinAlgError:
            if failed:
                raise
            raise StepMismatch(
                "the Python step's system was singular, the compiled step's not"
            ) from None
        if failed:
            raise StepMismatch("the compiled step's system was singular, the Python step's not")
        self._pack(v, robot)
        python = np.concatenate([numbers, qdot, cg])
        if self.external:  # the load went to the supply, in Python
            python[R_LOAD_W] = compiled[R_LOAD_W]
        same = (python == compiled) | (np.isnan(python) & np.isnan(compiled))
        with np.errstate(invalid="ignore"):
            size = np.maximum(1.0, np.maximum(np.abs(python), np.abs(compiled)))
            apart = np.where(same, 0.0, np.abs(python - compiled) / size)
        bad = ~(apart <= TOLERANCE)
        if bad.any():
            names = self.names()
            shown = [
                f"{names[i]}: {python[i]!r} in Python, {compiled[i]!r} compiled"
                for i in np.flatnonzero(bad)[:8]
            ]
            raise StepMismatch(
                f"the compiled step isn't the Python step's (t = {robot.time:.3f} s): "
                + "; ".join(shown)
            )
        self.worst = max(self.worst, float(apart.max()))

    def names(self) -> list[str]:
        """What each number a check compares is: the block's, then qdot's and the CG's."""
        robot = self.robot
        out = [""] * len(self.numbers)
        for entry in ROBOT:
            name, count = entry if isinstance(entry, tuple) else (entry, 1)
            for i in range(count):
                out[R[name] + i] = f"robot {name}" + (f"[{i}]" if count > 1 else "")
        ports = {id(m): port for port, m in robot.motors.items()}
        for i, (motor, _, _) in enumerate(self.drive + self.driven):
            for name, at in M.items():
                out[self.motors_at + i * M_SIZE + at] = f"motor {ports.get(id(motor), i)} {name}"
        for k, mechanism in enumerate(self.mechanisms):
            for name, at in K.items():
                out[self.mechanisms_at + k * K_SIZE + at] = f"mechanism {mechanism.name} {name}"
        for c, column in enumerate(WHEEL):
            for i, wheel in enumerate(robot.wheel_names):
                out[self.wheels_at + c * self.wheels + i] = f"wheel {wheel} {column}"
        out += [f"qdot[{i}]" for i in range(len(robot.qdot))] + ["cg x", "cg y"]
        return out


engaged = {"compiled": 0, "python": 0}  # robots that took their first step with each, here
refused: list[str] = []  # why robots that could have had the compiled step didn't (the last few)

R_MASS, R_HEADING, R_LIFTED = R["mass"], R["heading"], R["lifted"]
R_EXTERNAL_TORQUE, R_GROUND_FX, R_GROUND_FY = R["external_torque"], R["ground_fx"], R["ground_fy"]
R_BUS_VOLTAGE, R_LOAD_W = R["bus_voltage"], R["load_w"]


def engage(robot: Any) -> Compiled | bool:
    """A robot's compiled step, or False where it steps in Python: decided at its first step."""
    chosen = mode()
    if chosen == "python":
        engaged["python"] += 1
        return False
    lib = library()
    if lib is None:
        if chosen != "auto":
            raise StepUnavailable(f"{ENV}={chosen}, but there's no compiled step: {reason()}")
        engaged["python"] += 1
        return False
    why = why_not(robot)
    if why is not None:
        refused.append(why)
        del refused[:-20]
        engaged["python"] += 1
        return False
    engaged["compiled"] += 1
    return Compiled(robot, lib, check=chosen == "check")
