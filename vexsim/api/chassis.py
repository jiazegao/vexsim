"""A LemLib-style chassis for Python robot programs.

Motions are generators: ``yield from chassis.move_to_point(24, 0)`` drives
until the motion settles or times out, yielding every 10 ms like a PROS
``delay(10)`` loop. Poses are inches and degrees counter-clockwise in the field
frame (see docs/conventions.md).
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING

from vexsim.algorithms.control.base import ChassisGeometry, Controller, DriveCommand
from vexsim.algorithms.control.motions import Boomerang, MoveToPoint, ProfiledDrive, TurnToHeading
from vexsim.algorithms.control.paths import PurePursuit, Ramsete, generate_trajectory
from vexsim.algorithms.localization.base import Pose
from vexsim.api.devices import MotorGroup

if TYPE_CHECKING:
    from vexsim.runtime.simulation import Simulation

CONTROL_DT = 0.01


class Chassis:
    def __init__(self, sim: Simulation, left: MotorGroup, right: MotorGroup):
        self._sim = sim
        self.left, self.right = left, right
        self.geometry = ChassisGeometry.from_config(sim.robot.config)
        config = sim.robot.config.drivetrain
        self._motor_rpm_per_in_s = {}
        for side in ("left", "right"):
            group = config.gearing[side]
            per_rev = math.pi * self.geometry.wheel_diameter_in * group.speed_ratio
            self._motor_rpm_per_in_s[side] = 60.0 / per_rev
        self.active: Controller | None = None  # the running motion (the viewer draws it)

    # --- pose ------------------------------------------------------------------------

    @property
    def pose(self) -> Pose:
        return self._sim.estimated_pose

    def set_pose(self, x: float, y: float, heading: float) -> None:
        self._sim.reset_localizer(Pose(x, y, heading))

    # --- direct drive ------------------------------------------------------------------

    def apply(self, command: DriveCommand) -> None:
        if command.mode == "voltage":
            self.left.move_voltage(command.left * 1000.0)
            self.right.move_voltage(command.right * 1000.0)
        else:
            self.left.move_velocity(command.left * self._motor_rpm_per_in_s["left"])
            self.right.move_velocity(command.right * self._motor_rpm_per_in_s["right"])

    def tank(self, left: float, right: float) -> None:
        """Joystick-style -127..127 per side."""
        self.apply(DriveCommand(left * 12.0 / 127.0, right * 12.0 / 127.0))

    def arcade(self, throttle: float, turn: float) -> None:
        """Joystick-style -127..127 throttle and turn (positive turn = clockwise, like LemLib)."""
        left, right = throttle + turn, throttle - turn
        biggest = max(abs(left), abs(right), 127.0)
        self.tank(left * 127.0 / biggest, right * 127.0 / biggest)

    def stop(self) -> None:
        self.apply(DriveCommand.stop())

    # --- motions ------------------------------------------------------------------------

    def run(self, controller: Controller, timeout_ms: float | None = None) -> Iterator[None]:
        """Step ``controller`` every 10 ms until it is done (or times out), then stop."""
        elapsed = 0.0
        self.active = controller
        try:
            while not controller.done():
                if timeout_ms is not None and elapsed * 1000.0 >= timeout_ms:
                    break
                frame = self._sim.sensors.frame(self._sim.world.time)
                self.apply(controller.step(self.pose, frame, CONTROL_DT))
                elapsed += CONTROL_DT
                yield
        finally:
            self.active = None
            self.stop()

    def turn_to_heading(self, heading: float, timeout_ms: float = 2000, **kw) -> Iterator[None]:
        return self.run(TurnToHeading(heading, **kw), timeout_ms)

    def turn_to_point(self, x: float, y: float, timeout_ms: float = 2000, **kw) -> Iterator[None]:
        p = self.pose
        return self.turn_to_heading(math.degrees(math.atan2(y - p.y, x - p.x)), timeout_ms, **kw)

    def move_to_point(self, x: float, y: float, timeout_ms: float = 4000, **kw) -> Iterator[None]:
        return self.run(MoveToPoint(x, y, **kw), timeout_ms)

    def move_to_pose(
        self, x: float, y: float, heading: float, timeout_ms: float = 5000, **kw
    ) -> Iterator[None]:
        return self.run(Boomerang(x, y, heading, **kw), timeout_ms)

    def drive(self, distance_in: float, timeout_ms: float = 5000, **kw) -> Iterator[None]:
        """Straight line along the current heading on a motion profile ("trapezoid"/"scurve")."""
        return self.run(ProfiledDrive(distance_in, self.geometry, **kw), timeout_ms)

    def follow(
        self,
        waypoints: Sequence[tuple[float, float]],
        method: str = "pure_pursuit",
        timeout_ms: float = 10000,
        **kw,
    ) -> Iterator[None]:
        """Follow a path through ``waypoints`` with pure pursuit or RAMSETE."""
        if method == "pure_pursuit":
            controller: Controller = PurePursuit(waypoints, self.geometry, **kw)
        elif method == "ramsete":
            gains = {k: kw.pop(k) for k in ("b", "zeta") if k in kw}
            trajectory = generate_trajectory(waypoints, self.geometry, **kw)
            controller = Ramsete(trajectory, self.geometry, **gains)
        else:
            raise ValueError("method must be 'pure_pursuit' or 'ramsete'")
        return self.run(controller, timeout_ms)
