"""PROS 4-style device classes for Python robot programs.

Names and units follow PROS 4 (``move_voltage`` in mV, ``move_velocity`` in
rpm, positions in degrees, rotation sensors in centidegrees), so a Python
prototype maps line for line onto C++. A negative port reverses the device,
as in PROS 4. Readings come from the sampled, noisy devices; a reading that
doesn't exist yet returns ``PROS_ERR_F`` (infinity), as PROS does.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING

from vexsim.devices.devices import DistanceDevice, ImuDevice, MotorDevice, RotationDevice
from vexsim.physics.motor import BrakeMode
from vexsim.units import rpm_to_rad_s

if TYPE_CHECKING:
    from vexsim.runtime.simulation import Simulation

PROS_ERR_F = math.inf
DISTANCE_NO_OBJECT = 9999  # mm reported when nothing is in range (VEX convention)

ANALOG = ("LEFT_X", "LEFT_Y", "RIGHT_X", "RIGHT_Y")
DIGITAL = ("L1", "L2", "R1", "R2", "UP", "DOWN", "LEFT", "RIGHT", "X", "B", "Y", "A")
_BRAKE_MODES = {"coast": BrakeMode.COAST, "brake": BrakeMode.BRAKE, "hold": BrakeMode.HOLD}


def _device(sim: Simulation, port: int, kind: type):
    device = sim.sensors.devices.get(abs(port))
    if not isinstance(device, kind):
        found = type(device).__name__ if device else "nothing"
        raise ValueError(f"port {abs(port)} has {found}, not a {kind.__name__}")
    return device


class Motor:
    def __init__(self, sim: Simulation, port: int):
        self._device: MotorDevice = _device(sim, port, MotorDevice)
        self.port = abs(port)
        self._sign = -1.0 if port < 0 else 1.0

    # movement
    def move(self, voltage: float) -> None:
        """-127..127, like PROS ``move``."""
        self.move_voltage(max(-127.0, min(127.0, voltage)) * 12000.0 / 127.0)

    def move_voltage(self, millivolts: float) -> None:
        self._device.motor.set_voltage(self._sign * millivolts / 1000.0)

    def move_velocity(self, rpm: float) -> None:
        self._device.motor.set_velocity(self._sign * rpm_to_rad_s(rpm))

    def move_absolute(self, position_deg: float, velocity_rpm: float) -> None:
        raw = self._sign * position_deg + self._device.zero_deg
        self._device.motor.set_position(math.radians(raw), rpm_to_rad_s(abs(velocity_rpm)))

    def move_relative(self, delta_deg: float, velocity_rpm: float) -> None:
        self.move_absolute(self.get_position() + delta_deg, velocity_rpm)

    def brake(self) -> None:
        self._device.motor.stop()

    def set_brake_mode(self, mode: str | BrakeMode) -> None:
        self._device.motor.brake_mode = (
            _BRAKE_MODES.get(mode, mode) if isinstance(mode, str) else mode
        )

    def set_current_limit(self, milliamps: float) -> None:
        self._device.motor.current_limit_a = milliamps / 1000.0

    def tare_position(self) -> None:
        self.set_zero_position(0.0)

    def set_zero_position(self, position_deg: float) -> None:
        """Make the current position read ``position_deg``, as PROS 4 does.

        The zero belongs to the motor on that port, not to this object. Like the
        PROS C API, it ignores reversal: a reversed motor then reads the negative.
        """
        r = self._reading()
        raw = 0.0 if r is None else r.position_deg
        self._device.zero_deg = raw - position_deg

    # telemetry
    def _reading(self):
        return self._device.value

    def get_position(self) -> float:
        r = self._reading()
        return PROS_ERR_F if r is None else self._sign * (r.position_deg - self._device.zero_deg)

    def get_actual_velocity(self) -> float:
        r = self._reading()
        return PROS_ERR_F if r is None else self._sign * r.velocity_rpm

    def get_current_draw(self) -> float:
        r = self._reading()
        return PROS_ERR_F if r is None else r.current_ma

    def get_voltage(self) -> float:
        r = self._reading()
        return PROS_ERR_F if r is None else self._sign * r.voltage_mv

    def get_temperature(self) -> float:
        r = self._reading()
        return PROS_ERR_F if r is None else r.temperature_c

    def get_torque(self) -> float:
        r = self._reading()
        return PROS_ERR_F if r is None else self._sign * r.torque_nm

    def get_power(self) -> float:
        r = self._reading()
        return PROS_ERR_F if r is None else r.power_w

    def is_over_temp(self) -> bool:
        r = self._reading()
        return bool(r and r.over_temp)


class MotorGroup:
    """Several motors commanded together; getters report the first motor, like PROS 4."""

    def __init__(self, sim: Simulation, ports: Sequence[int]):
        self.motors = [Motor(sim, p) for p in ports]

    def __getattr__(self, name: str):
        if name.startswith(("move", "brake", "set_", "tare")):

            def broadcast(*args, **kwargs):
                for m in self.motors:
                    getattr(m, name)(*args, **kwargs)

            return broadcast
        if name.startswith(("get_", "is_")):
            return getattr(self.motors[0], name)
        raise AttributeError(name)

    def get_position_all(self) -> list[float]:
        return [m.get_position() for m in self.motors]


class Imu:
    """Heading is clockwise-positive degrees, as on the V5 Inertial Sensor."""

    def __init__(self, sim: Simulation, port: int):
        self._sim = sim
        self._device: ImuDevice = _device(sim, port, ImuDevice)
        self._offset = 0.0

    def reset(self) -> None:
        """Start calibrating (~2 s; keep the robot still). Poll ``is_calibrating``."""
        self._device.calibrate(self._sim.world.clock.us)
        self._offset = 0.0

    def is_calibrating(self) -> bool:
        return self._device.calibrating or self._device.value is None

    def get_rotation(self) -> float:
        r = self._device.value
        return (
            PROS_ERR_F if r is None or self._device.calibrating else r.rotation_deg + self._offset
        )

    def get_heading(self) -> float:
        rotation = self.get_rotation()
        return PROS_ERR_F if rotation == PROS_ERR_F else rotation % 360.0

    def get_gyro_rate_z(self) -> float:
        r = self._device.value
        return PROS_ERR_F if r is None else r.gyro_z_deg_s

    def set_rotation(self, degrees: float) -> None:
        r = self._device.value
        if r is not None:
            self._offset = degrees - r.rotation_deg

    def set_heading(self, degrees: float) -> None:
        self.set_rotation(degrees)

    def tare_rotation(self) -> None:
        self.set_rotation(0.0)


class Rotation:
    """Positions in centidegrees, as PROS returns them."""

    def __init__(self, sim: Simulation, port: int):
        self._device: RotationDevice = _device(sim, port, RotationDevice)
        self._sign = -1 if port < 0 else 1
        self._zero = 0

    def get_position(self) -> int | float:
        r = self._device.value
        return PROS_ERR_F if r is None else self._sign * r.position_cdeg - self._zero

    def get_angle(self) -> int | float:
        position = self.get_position()
        return PROS_ERR_F if position == PROS_ERR_F else int(position) % 36000

    def get_velocity(self) -> float:
        r = self._device.value
        return PROS_ERR_F if r is None else self._sign * r.velocity_cdeg_s

    def reset_position(self) -> None:
        self._zero += self.get_position()

    def set_reversed(self, reversed_: bool) -> None:
        self._sign = -1 if reversed_ else 1


class Distance:
    def __init__(self, sim: Simulation, port: int):
        self._device: DistanceDevice = _device(sim, port, DistanceDevice)

    def get(self) -> int:
        """Distance in mm; 9999 when nothing is in range."""
        value = self._device.value
        return DISTANCE_NO_OBJECT if value is None else value


class Controller:
    """The V5 controller. Fed each tick by an input source (keyboard, gamepad, script)."""

    def __init__(self) -> None:
        self.analog = dict.fromkeys(ANALOG, 0)
        self.digital: set[str] = set()
        self._previous: set[str] = set()

    def update(self, analog: dict[str, float], digital: set[str]) -> None:
        self._previous = self.digital
        self.analog = {k: int(max(-127, min(127, round(analog.get(k, 0))))) for k in ANALOG}
        self.digital = {b for b in digital if b in DIGITAL}

    def get_analog(self, channel: str) -> int:
        return self.analog[channel.upper().removeprefix("ANALOG_")]

    def get_digital(self, button: str) -> bool:
        return button.upper().removeprefix("DIGITAL_") in self.digital

    def get_digital_new_press(self, button: str) -> bool:
        b = button.upper().removeprefix("DIGITAL_")
        return b in self.digital and b not in self._previous
