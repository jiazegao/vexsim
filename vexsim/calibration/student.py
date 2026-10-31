"""A simulated student who runs the calibration program in vexsim the way a student does on
the field (phase 14.3): to test the program, and later the session's tools, without a robot.

The program prints a "#vexsim-cal" line at each step (bridge/cpp/calibration/main.cpp says
which). The student reads them from the simulation's console and does what a person would:
presses the controller's buttons, lays the robot on its side and stands it up, carries it to
the plan's spots, pushes it along the lane and turns it by hand, covers each distance sensor
with a hand, and says which way the wheels spun. It knows the robot config the program was
made from (where that config says each sensor is) and watches the simulated robot, which can
differ from it: a "real" robot with a motor reversed, say.

    student = Student(plan, config, ["device_check", "straight"])
    sim = Simulation(real_robot, program=CppProgram(executable), field=field,
                     input_source=student, start=student.start)
    student.attach(sim)
    sim.start("driver")
    sim.run_until_finished(900)  # done once every test it was given has run
"""

from __future__ import annotations

import bisect
import itertools
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from vexsim.algorithms.localization.base import Pose
from vexsim.calibration.plan import Plan
from vexsim.config.robot import RobotConfig
from vexsim.physics.world import PRIORITY_CONTROL
from vexsim.units import in_to_m, m_to_in

PREFIX = "#vexsim-cal "
REACT_S = 0.3  # how long the student takes to act on what the screen says
PRESS_S = 0.1  # how long a button is held
STILL_RAD = 1.0  # wheels whose motors turned less than this (rad) "didn't turn"
HAND_GAINS = (200.0, 28.0)  # how stiffly a hand moves the robot: 1/s^2, 1/s
COVER_MM = 30.0  # a hand over a distance sensor reads this
TURN_S = 2.0  # seconds a turn by hand takes
PUSH_IN_S = 12.0  # how fast a hand pushes (in/s)
MAX_MENU_PRESSES = 40  # looking for a test the menu doesn't have
MAX_STOPPED = 2  # runs of a test stopped in a row: back to the menu, as a student would
HOT_TRIES = 20  # times it waits for a hot motor to cool


@dataclass
class Hand:
    """A hand moving the robot: from where it is when the hand begins, by ``move`` (in, the
    robot's frame then) and ``turn`` (deg, counter-clockwise), smoothly over ``seconds``;
    ``then`` runs once it lets go."""

    move: tuple[float, float]
    turn: float
    seconds: float
    then: Callable[[float], None]
    begin: float | None = None
    start: tuple[float, float, float] | None = None  # m, m, rad


@dataclass
class Run:
    """A run the program logged: its log's name and test, when it began and ended, how it
    ended, and the robot's true poses meanwhile (x in, y in, heading deg, every 10 ms)."""

    name: str
    test: str
    began: float
    ended: float | None = None
    how: str | None = None
    poses: list[tuple[float, float, float]] = field(default_factory=list)


class Student:
    """An input source for a Simulation running the calibration program (see the module).
    ``tests`` are the menu's keys to run, in order; ``press_during`` presses B that many
    seconds into a test's first run (a test's key to seconds), to stop it."""

    def __init__(
        self,
        plan: Plan,
        config: RobotConfig,
        tests: Sequence[str],
        *,
        press_during: dict[str, float] | None = None,
    ):
        self.plan, self.config = plan, config
        self.todo = list(tests)
        self.press_during = dict(press_during or {})
        self.sim = None
        self.done = False  # Simulation.finished reads it
        self.error: str | None = None
        self.events: list[tuple[float, str]] = []  # every "#vexsim-cal" line, and when
        self.runs: list[Run] = []
        self.problems: list[str] = []  # what the device check said to fix
        self.pressed: list[tuple[float, str]] = []  # every button press, and when
        self.screens: list[tuple[float, str, list[str]]] = []  # the brain's screen at each ask
        self.now = 0.0
        self._seen = 0
        self._current: str | None = None
        self._menu_presses = 0
        self._hot = 0
        self._actions: list[tuple[float, int, Callable[[float], None]]] = []
        self._order = itertools.count()
        self._held: set[str] = set()
        self._release_at = 0.0
        self._free_at = 0.0
        self._hand: Hand | None = None
        self._watching: list[str] = []  # the robot's drive groups it watches spin
        self._turned = 0.0  # how far they turned (motor rad, forward +)

    @property
    def start(self) -> Pose:
        """Where to start the simulation: an open spot of the plan's (the spin's)."""
        spots = {t.key: t.spot for t in self.plan.tests if t.spot}
        spot = spots.get("spin") or next(iter(spots.values()), None)
        x, y, heading = spot.pose if spot else (0.0, 0.0, 0.0)
        return Pose(x, y, heading)

    def attach(self, sim) -> None:
        self.sim = sim
        sim.world.every(1, self._hand_step, priority=PRIORITY_CONTROL - 2, name="student's hand")

    # --- an input source ---------------------------------------------------------------------

    def poll(self, time_s: float) -> tuple[dict[str, float], set[str]]:
        if self.sim is None or self.done:
            return {}, set()
        self.now = time_s
        self._read()
        while self._actions and self._actions[0][0] <= time_s:
            _, _, action = self._actions.pop(0)
            action(time_s)
        if self._held and time_s >= self._release_at:
            self._held = set()
        robot = self.sim.robot
        for name in self._watching:
            self._turned += robot.group_speed(name) * 0.01
        if self.runs and self.runs[-1].ended is None:
            x, y, heading = robot.pose
            self.runs[-1].poses.append((m_to_in(x), m_to_in(y), math.degrees(heading)))
        return {}, set(self._held)

    def _at(self, when: float, action: Callable[[float], None]) -> None:
        bisect.insort(self._actions, (when, next(self._order), action), key=lambda a: a[:2])

    def _press(self, button: str, after: float = REACT_S) -> None:
        when = max(self.now + after, self._free_at)
        self._free_at = when + PRESS_S + 0.05
        self._at(when, lambda t: self._hold(button, t))

    def _hold(self, button: str, t: float) -> None:
        self._held = {button}
        self._release_at = t + PRESS_S
        self.pressed.append((t, button))

    # --- reading the program ----------------------------------------------------------------

    def _read(self) -> None:
        console = self.sim.console
        while self._seen < len(console):
            text = console[self._seen].split("] ", 1)[-1]
            self._seen += 1
            if text.startswith(PREFIX):
                event = text[len(PREFIX) :].strip()
                self.events.append((self.now, event))
                self._on(event.split())

    def _on(self, words: list[str]) -> None:
        kind, args = words[0], words[1:]
        if kind == "menu":
            self._menu(args[0])
        elif kind == "ask":
            lcd = self.sim.lcd
            self.screens.append(
                (self.now, " ".join(args), [lcd.get(k, "").rstrip() for k in range(8)])
            )
            self._ask(args)
        elif kind == "spin":
            self._watch(args)
        elif kind == "log":
            name, test, _ = args
            self.runs.append(Run(name, test, self.now))
            if test in self.press_during:
                self._at(self.now + self.press_during.pop(test), lambda t: self._hold("B", t))
        elif kind == "saved" and self.runs:
            self.runs[-1].ended, self.runs[-1].how = self.now, " ".join(args)
        elif kind == "problem":
            self.problems.append(" ".join(args))
        elif kind == "drive":
            self._press("B")

    def _menu(self, key: str) -> None:
        if self._current is not None:  # back from a test
            self.todo.pop(0)
            self._current = None
            self._menu_presses = 0
        if not self.todo:
            self.done = True
            return
        if key == self.todo[0]:
            self._current = key
            self._press("A")
            return
        self._menu_presses += 1
        if self._menu_presses > MAX_MENU_PRESSES:
            self.error = f"the menu has no {self.todo[0]}"
            self.done = True
            return
        self._press("DOWN")

    def _ask(self, args: list[str]) -> None:
        what = args[0]
        robot = self.sim.robot
        if what == "side":
            self._at(self.now + 0.5, lambda t: setattr(robot, "lifted", True))
            self._press("A", 1.0)
        elif what == "flat":
            self._at(self.now + 0.5, lambda t: setattr(robot, "lifted", False))
            self._press("A", 1.0)
        elif what == "place":
            self._at(self.now + 0.5, lambda t: self._place(args[1]))
            self._press("A", 1.5)
        elif what == "open":
            self._at(self.now + 0.5, lambda t: robot.place(self._si(self.start)))
            self._press("A", 1.5)
        elif what == "forward":
            self._watching = []
            if abs(self._turned) < STILL_RAD:
                self._press("X")
            else:
                self._press("A" if self._turned > 0 else "B")
        elif what == "turn":  # left|right degrees
            degrees = float(args[2]) * (1 if args[1] == "left" else -1)
            seconds = max(1.0, abs(degrees) / 360 * TURN_S)
            self._move((0.0, 0.0), degrees, seconds)
        elif what in ("push", "lane"):  # forward|left|back inches
            inches = float(args[2])
            move = {"forward": (inches, 0.0), "back": (-inches, 0.0), "left": (0.0, inches)}
            self._move(move[args[1]], 0.0, max(1.0, inches / PUSH_IN_S))
        elif what == "cover":
            self._at(self.now + 0.3, lambda t: self._cover(int(args[1])))
            self._press("A", 1.0)
        elif what == "uncover":
            self._cover(None)
            self._press("A")
        elif what == "hot":
            self._hot += 1
            self._press("A" if self._hot < HOT_TRIES else "B", 15.0)
        elif what == "device":
            self.problems.append(f"port {args[1]}: the device doesn't answer")
            self._press("B")
        elif what == "next" and self._stopped_in_a_row() >= MAX_STOPPED:
            self._press("B")  # something's wrong: back to the menu
        else:  # still, line, ready, next, done, battery: go on
            self._press("A")

    def _stopped_in_a_row(self) -> int:
        n = 0
        for run in reversed(self.runs):
            if run.test != self._current or not (run.how or "").startswith("stopped"):
                break
            n += 1
        return n

    # --- handling the robot -----------------------------------------------------------------

    def _si(self, pose: Pose | tuple[float, float, float]) -> tuple[float, float, float]:
        x, y, heading = (pose.x, pose.y, pose.heading) if isinstance(pose, Pose) else pose
        return in_to_m(x), in_to_m(y), math.radians(heading)

    def _spot(self, key: str):
        for test in self.plan.tests:
            if test.key == key and test.spot is not None:
                return test.spot
        raise KeyError(f"the plan has no spot for {key}")

    def _place(self, key: str) -> None:
        self.sim.robot.place(self._si(self._spot(key).pose))

    def _watch(self, args: list[str]) -> None:
        """The program spins a group of the config's (or one motor): watch the real robot's
        wheels that turn with it."""
        robot = self.sim.robot
        if args[0] == "group":
            groups = [g.name for g in robot.groups if g.name == args[1]]
        else:
            port = int(args[1])
            groups = [g.name for g in robot.groups if any(p == port for p, _, _ in g.motors)]
        self._watching, self._turned = groups, 0.0

    def _cover(self, port: int | None) -> None:
        """A hand over the distance sensor the config says is on ``port`` (where the config
        says it is), on the real robot; None takes the hand away."""
        devices = [d for d in self.sim.sensors.devices.values() if d.kind == "distance"]
        for device in devices:
            device.blocked_mm = None
        if port is None:
            return
        sensor = next(s for s in self.config.sensors if s.type == "distance" and s.port == port)
        mount = np.array([in_to_m(v) for v in sensor.pos_in])
        heading = math.radians(sensor.heading_deg)
        for device in devices:
            near = np.hypot(*(np.array(device.mount) - mount)) < in_to_m(0.5)
            if near and abs(math.remainder(device.heading - heading, math.tau)) < 0.1:
                device.blocked_mm = COVER_MM

    def _move(self, move: tuple[float, float], turn: float, seconds: float) -> None:
        def then(t: float) -> None:
            self._press("A", 0.2)

        def begin(t: float) -> None:
            self._hand = Hand(move, turn, seconds, then)

        self._at(self.now + 0.5, begin)

    def _hand_step(self, world) -> None:
        hand = self._hand
        if hand is None:
            return
        robot, t = self.sim.robot, world.time
        if hand.begin is None:
            hand.begin, hand.start = t, robot.pose
        x0, y0, h0 = hand.start
        tau = min(t - hand.begin, hand.seconds)
        phase = math.pi * tau / hand.seconds
        s, ds = 0.5 - 0.5 * math.cos(phase), 0.5 * math.pi / hand.seconds * math.sin(phase)
        c, n = math.cos(h0), math.sin(h0)
        dx, dy = in_to_m(hand.move[0]), in_to_m(hand.move[1])
        fx, fy, turn = c * dx - n * dy, n * dx + c * dy, math.radians(hand.turn)
        x, y, h = robot.pose
        vx, vy = robot.field_velocity
        w = robot.body_velocity[2]
        kp, kd = HAND_GAINS
        robot.external_force = robot.mass * np.array(
            [
                kp * (x0 + fx * s - x) + kd * (fx * ds - vx),
                kp * (y0 + fy * s - y) + kd * (fy * ds - vy),
            ]
        )
        robot.external_torque = robot.yaw_inertia * (
            kp * (h0 + turn * s - h) + kd * (turn * ds - w)
        )
        if t - hand.begin > hand.seconds + 0.5:  # held still a moment, then let go
            robot.external_force = np.zeros(2)
            robot.external_torque = 0.0
            self._hand = None
            hand.then(t)
