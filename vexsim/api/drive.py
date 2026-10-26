"""Direct drive for any drivetrain: forward, strafe and turn, like a driver's sticks.

Group speeds come from the drivetrain's kinematics (vexsim/physics/kinematics.py),
so the same call drives a tank drive, an X-drive, a mecanum drive or an H-drive.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vexsim.api.devices import MotorGroup
from vexsim.physics.kinematics import DriveKinematics

if TYPE_CHECKING:
    from vexsim.runtime.simulation import Simulation


def _stick(value: float) -> float:
    return max(-1.0, min(1.0, value / 127.0))


class Drive:
    def __init__(self, sim: Simulation):
        self.kinematics = DriveKinematics.from_config(sim.robot.config)
        gearing = sim.robot.config.drivetrain.gearing
        self.groups = {name: MotorGroup(sim, gear.motors) for name, gear in gearing.items()}

    @property
    def holonomic(self) -> bool:
        """Can strafe while driving and turning (X-drive, mecanum, H-drive)."""
        return self.kinematics.holonomic

    def move(self, forward: float, strafe: float = 0.0, turn: float = 0.0) -> None:
        """Joystick-style -127..127 forward, strafe (positive = right) and turn (positive =
        clockwise), as from LEFT_Y, LEFT_X and RIGHT_X. Each input at 127 is the top speed in
        that direction; when a combination asks too much of a group, all groups slow down
        together so the direction holds. Voltage control, like ``chassis.arcade``. A drive that
        can't strafe ignores ``strafe``."""
        fractions = self.kinematics.fractions(_stick(forward), -_stick(strafe), -_stick(turn))
        for name, fraction in fractions.items():
            self.groups[name].move_voltage(fraction * 12000.0)

    def stop(self) -> None:
        for group in self.groups.values():
            group.move_voltage(0)
