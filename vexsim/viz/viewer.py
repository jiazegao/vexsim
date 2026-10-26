"""Live top-down viewer (pygame): drive with keyboard or gamepad, watch autonomous, replay logs.

Keys:
  Space pause/resume    .  step one tick (paused)    + / -  speed    R restart
  G ghost (estimated pose)    T trails    F wheel forces    H help    Esc quit
  Driving (virtual V5 controller): W/S left stick Y, A/D right stick X (arcade),
  Up/Down right stick Y (tank), Left/Right left stick X, Shift = half stick,
  Q/Z = L1/L2, E/C = R1/R2, I/L/K/J = X/A/B/Y, T/G/F/H (with Ctrl) = d-pad.
A connected gamepad is used too (Xbox layout mapped to the V5 controller by position).
"""

from __future__ import annotations

import math
import os
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from vexsim.algorithms.localization.base import Pose
from vexsim.config.robot import RobotConfig
from vexsim.runtime.recorder import Log
from vexsim.runtime.simulation import Simulation
from vexsim.units import m_to_in

# Reference palette (dataviz skill) and neutrals.
SURFACE = (252, 252, 251)
PANEL = (244, 243, 240)
TEXT = (11, 11, 11)
TEXT_2 = (82, 81, 78)
GRID = (214, 213, 208)
WALL = (60, 60, 58)
ROBOT = (40, 40, 38)
ESTIMATE = (42, 120, 214)  # series 1
TARGET = (235, 104, 52)  # series 2
TRAIL = (27, 175, 122)  # series 3
SLIP_LOW, SLIP_HIGH = (90, 90, 86), (227, 73, 72)  # wheel color: grip in use -> sliding

SPEEDS = [0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, math.inf]
FIELD_PX = 680
PANEL_PX = 380
MARGIN = 20

KEY_ANALOG = {  # key name -> (channel, sign)
    "w": ("LEFT_Y", 1), "s": ("LEFT_Y", -1),
    "d": ("RIGHT_X", 1), "a": ("RIGHT_X", -1),
    "up": ("RIGHT_Y", 1), "down": ("RIGHT_Y", -1),
    "right": ("LEFT_X", 1), "left": ("LEFT_X", -1),
}  # fmt: skip
KEY_BUTTONS = {
    "q": "L1", "z": "L2", "e": "R1", "c": "R2", "i": "X", "l": "A", "k": "B", "j": "Y",
}  # fmt: skip
CTRL_DPAD = {"t": "UP", "g": "DOWN", "f": "LEFT", "h": "RIGHT"}


@dataclass
class WheelView:
    x: float  # field inches
    y: float
    heading: float  # radians
    length: float  # inches
    slip: float  # 0..1 (share of the friction limit in use)
    lateral_force: float  # N, along the axle (+left)


@dataclass
class Snapshot:
    time: float
    phase: str
    robot_name: str
    footprint: tuple[float, float]
    true_pose: Pose
    est_pose: Pose | None
    speed_in_s: float
    battery_v: float
    battery_soc: float
    motors: list[tuple[int, float, float, bool]]  # port, current A, temperature C, over temp
    wheels: list[WheelView] = field(default_factory=list)
    console: list[str] = field(default_factory=list)
    lcd: list[str] = field(default_factory=list)  # brain screen lines from C++ programs
    overlay_path: np.ndarray | None = None  # (n, 2) inches
    overlay_target: tuple[float, float, float | None] | None = None
    sticks: dict[str, int] = field(default_factory=dict)


class KeyboardInput:
    """Virtual V5 controller driven by held keys (and a gamepad, if one is connected)."""

    def __init__(self) -> None:
        self.held: set[str] = set()
        self.gamepad = None

    def poll(self, time_s: float) -> tuple[dict[str, float], set[str]]:
        scale = 63.0 if {"left shift", "right shift"} & self.held else 127.0
        ctrl = {"left ctrl", "right ctrl"} & self.held
        analog: dict[str, float] = {}
        digital: set[str] = set()
        for key in self.held:
            if ctrl and key in CTRL_DPAD:
                digital.add(CTRL_DPAD[key])
            elif key in KEY_ANALOG and not ctrl:
                channel, sign = KEY_ANALOG[key]
                analog[channel] = analog.get(channel, 0.0) + sign * scale
            elif key in KEY_BUTTONS:
                digital.add(KEY_BUTTONS[key])
        if self.gamepad is not None:
            pad_analog, pad_digital = self.gamepad.poll()
            for k, v in pad_analog.items():
                if abs(v) > abs(analog.get(k, 0.0)):
                    analog[k] = v
            digital |= pad_digital
        return analog, digital


class Gamepad:
    """First connected game controller, through SDL's GameController mapping."""

    BUTTONS = {  # SDL button -> V5 button, matched by position on the controller
        "a": "B", "b": "A", "x": "Y", "y": "X",
        "leftshoulder": "L1", "rightshoulder": "R1",
        "dpup": "UP", "dpdown": "DOWN", "dpleft": "LEFT", "dpright": "RIGHT",
    }  # fmt: skip

    def __init__(self, controller) -> None:
        self.c = controller

    @classmethod
    def first(cls):
        try:
            from pygame._sdl2 import controller as sdl_controller

            sdl_controller.init()
            for i in range(sdl_controller.get_count()):
                if sdl_controller.is_controller(i):
                    return cls(sdl_controller.Controller(i))
        except (ImportError, AttributeError, Exception):  # optional; keyboard still works
            return None
        return None

    def poll(self) -> tuple[dict[str, float], set[str]]:
        import pygame

        def axis(a: int) -> float:
            value = self.c.get_axis(a) / 32767.0
            return 0.0 if abs(value) < 0.08 else value * 127.0

        analog = {
            "LEFT_X": axis(pygame.CONTROLLER_AXIS_LEFTX),
            "LEFT_Y": -axis(pygame.CONTROLLER_AXIS_LEFTY),
            "RIGHT_X": axis(pygame.CONTROLLER_AXIS_RIGHTX),
            "RIGHT_Y": -axis(pygame.CONTROLLER_AXIS_RIGHTY),
        }
        digital = set()
        for name, v5 in self.BUTTONS.items():
            if self.c.get_button(getattr(pygame, f"CONTROLLER_BUTTON_{name.upper()}")):
                digital.add(v5)
        if self.c.get_axis(pygame.CONTROLLER_AXIS_TRIGGERLEFT) > 16000:
            digital.add("L2")
        if self.c.get_axis(pygame.CONTROLLER_AXIS_TRIGGERRIGHT) > 16000:
            digital.add("R2")
        return analog, digital


class LiveSource:
    """Snapshots of a running Simulation; ``factory`` rebuilds it for restart."""

    def __init__(self, factory: Callable[[], Simulation]):
        self.factory = factory
        self.sim = factory()

    def restart(self) -> None:
        self.sim.close()
        self.sim = self.factory()

    @property
    def time(self) -> float:
        return self.sim.world.time

    def advance(self, seconds: float) -> None:
        for _ in range(max(0, round(seconds * 1000))):
            self.sim.world.step()

    def snapshot(self) -> Snapshot:
        sim, robot = self.sim, self.sim.robot
        cfg = robot.config
        x, y, h = robot.pose
        c, s = math.cos(h), math.sin(h)
        contacts = robot.contacts
        spec = robot.params.omni_wheel
        wheels = []
        for i, w in enumerate(cfg.drivetrain.wheels):
            wx, wy = w.pos_in
            limit = max(spec.longitudinal_mu * contacts.normal[i], 1e-9)
            slip = min(1.0, abs(contacts.traction_force[i]) / limit) if len(contacts.slip) else 0.0
            wheels.append(
                WheelView(
                    x=m_to_in(x) + c * wx - s * wy,
                    y=m_to_in(y) + s * wx + c * wy,
                    heading=h + math.radians(w.heading_deg),
                    length=w.diameter_in,
                    slip=slip,
                    lateral_force=float(contacts.lateral_force[i]) if len(contacts.slip) else 0.0,
                )
            )
        u, v, _ = robot.body_velocity
        overlay_path, overlay_target = None, None
        chassis = sim.bot.chassis
        active = chassis.active if chassis else None
        if active is not None:
            path = getattr(active, "path", None)
            trajectory = getattr(active, "trajectory", None)
            if path is not None:
                overlay_path = np.asarray(path)
            elif trajectory is not None:
                overlay_path = trajectory.states[:, :2]
            if hasattr(active, "x") and hasattr(active, "y"):
                overlay_target = (active.x, active.y, getattr(active, "heading", None))
        return Snapshot(
            time=sim.world.time,
            phase=sim.phase,
            robot_name=cfg.name or "robot",
            footprint=cfg.body.footprint_in,
            true_pose=Pose.from_si(robot.pose),
            est_pose=(
                sim.estimated_pose if sim.localizer_ready or sim.reported_pose is not None else None
            ),
            speed_in_s=m_to_in(math.hypot(u, v)),
            battery_v=robot.power.bus_voltage,
            battery_soc=robot.power.battery.soc,
            motors=[
                (p, abs(m.current), m.temperature_c, m.over_temp)
                for p, m in sorted(robot.motors.items())
            ],
            wheels=wheels,
            console=sim.console[-8:],
            lcd=[sim.lcd[k] for k in sorted(sim.lcd) if sim.lcd[k].strip()],
            overlay_path=overlay_path,
            overlay_target=overlay_target,
            sticks=dict(sim.controller.analog),
        )


class ReplaySource:
    """Snapshots read back from a telemetry log."""

    def __init__(self, config: RobotConfig, log: Log):
        self.config, self.log = config, log
        self._t = float(log["time_s"][0])

    def restart(self) -> None:
        self._t = float(self.log["time_s"][0])

    @property
    def time(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t = min(self._t + seconds, float(self.log["time_s"][-1]))

    def snapshot(self) -> Snapshot:
        log = self.log
        i = int(np.searchsorted(log["time_s"], self._t, side="right")) - 1
        i = max(0, min(i, len(log) - 1))
        est = Pose(log["est_x_in"][i], log["est_y_in"][i], log["est_heading_deg"][i])
        return Snapshot(
            time=float(log["time_s"][i]),
            phase=log.phase[i] + " (replay)",
            robot_name=self.config.name or "robot",
            footprint=self.config.body.footprint_in,
            true_pose=Pose(log["x_in"][i], log["y_in"][i], log["heading_deg"][i]),
            est_pose=None if math.isnan(est.x) else est,
            speed_in_s=float(log["speed_in_s"][i]),
            battery_v=float(log["battery_v"][i]),
            battery_soc=float(log["battery_soc"][i]),
            motors=[
                (p, float(log[f"motor{p}_current_a"][i]), float(log[f"motor{p}_temp_c"][i]), False)
                for p in log.motor_ports
            ],
        )

    @property
    def finished(self) -> bool:
        return self._t >= float(self.log["time_s"][-1])


class Viewer:
    def __init__(self, source, *, headless: bool = False, speed: float = 1.0):
        if headless:
            os.environ["SDL_VIDEODRIVER"] = "dummy"
            os.environ["SDL_AUDIODRIVER"] = "dummy"
        import pygame

        self.pg = pygame
        pygame.init()
        pygame.display.set_caption("vexsim")
        self.screen = pygame.display.set_mode((FIELD_PX + PANEL_PX, FIELD_PX))
        # pygame's default font. Not SysFont: on Windows, pygame 2.6 crashes scanning the
        # registry's font list when an entry isn't text.
        self.font = pygame.font.Font(None, 19)
        self.small = pygame.font.Font(None, 16)
        self.big = pygame.font.Font(None, 24)
        self.source = source
        self.keyboard = KeyboardInput()
        self.keyboard.gamepad = None if headless else Gamepad.first()
        if isinstance(source, LiveSource):
            self._attach_input()
        speed = math.inf if speed <= 0 else speed
        self.speed_index = min(range(len(SPEEDS)), key=lambda i: abs(SPEEDS[i] - speed))
        self.paused = False
        self.show_ghost = self.show_trails = self.show_forces = True
        self.show_help = False
        self.running = True
        self.trail_true: deque = deque(maxlen=4000)
        self.trail_est: deque = deque(maxlen=4000)
        self._last_trail_t = -1.0
        self._clock = pygame.time.Clock()
        self.actual_rate = 0.0

    # --- control ----------------------------------------------------------------------

    def _attach_input(self) -> None:
        self.source.sim.input_source = self.keyboard

    @property
    def speed(self) -> float:
        return SPEEDS[self.speed_index]

    def handle(self, event) -> None:
        pg = self.pg
        if event.type == pg.QUIT:
            self.running = False
        elif event.type in (pg.KEYDOWN, pg.KEYUP):
            name = pg.key.name(event.key)
            if event.type == pg.KEYUP:
                self.keyboard.held.discard(name)
                return
            self.keyboard.held.add(name)
            ctrl = bool({"left ctrl", "right ctrl"} & self.keyboard.held)
            if name == "escape":
                self.running = False
            elif name == "space":
                self.paused = not self.paused
            elif name == "." and self.paused:
                self.source.advance(0.001)
            elif name in ("=", "+", "[+]"):
                self.speed_index = min(self.speed_index + 1, len(SPEEDS) - 1)
            elif name in ("-", "[-]"):
                self.speed_index = max(self.speed_index - 1, 0)
            elif name == "r":
                self.source.restart()
                if isinstance(self.source, LiveSource):
                    self._attach_input()
                self.trail_true.clear()
                self.trail_est.clear()
            elif ctrl:
                return
            elif name == "g" and not ctrl:
                self.show_ghost = not self.show_ghost
            elif name == "t":
                self.show_trails = not self.show_trails
            elif name == "f":
                self.show_forces = not self.show_forces
            elif name == "h":
                self.show_help = not self.show_help

    def frame(self, wall_dt: float) -> None:
        """Advance by ``wall_dt`` seconds of wall time (scaled by the speed) and draw."""
        for event in self.pg.event.get():
            self.handle(event)
        if not self.paused:
            before = self.source.time
            if math.isinf(self.speed):
                budget = self.pg.time.get_ticks() + 30  # run flat out for ~30 ms of wall time
                while self.pg.time.get_ticks() < budget:
                    self.source.advance(0.01)
            else:
                self.source.advance(min(wall_dt * self.speed, 0.25))
            if wall_dt > 0:
                self.actual_rate = (self.source.time - before) / wall_dt
        self.draw(self.source.snapshot())

    def run(self) -> None:
        while self.running:
            wall_dt = self._clock.tick(60) / 1000.0
            self.frame(wall_dt)
            self.pg.display.flip()
            if isinstance(self.source, ReplaySource) and self.source.finished:
                self.paused = True
        self.pg.quit()

    def save(self, path: str) -> None:
        self.pg.image.save(self.screen, path)

    def prefill_trails(self, true_xy, est_xy=()) -> None:
        """Seed the trails with a recorded path (inches), e.g. for a still frame."""
        self.trail_true.extend(self._to_px(x, y) for x, y in true_xy)
        self.trail_est.extend(self._to_px(x, y) for x, y in est_xy if x == x)  # skip NaN

    # --- drawing ------------------------------------------------------------------------

    def _to_px(self, x: float, y: float) -> tuple[int, int]:
        scale = (FIELD_PX - 2 * MARGIN) / 144.0
        return round(MARGIN + (x + 72.0) * scale), round(MARGIN + (72.0 - y) * scale)

    def _polygon(self, pose: Pose, length: float, width: float) -> list[tuple[int, int]]:
        h = math.radians(pose.heading)
        c, s = math.cos(h), math.sin(h)
        corners = [
            (length / 2, width / 2),
            (length / 2, -width / 2),
            (-length / 2, -width / 2),
            (-length / 2, width / 2),
        ]
        return [self._to_px(pose.x + c * a - s * b, pose.y + s * a + c * b) for a, b in corners]

    def draw(self, snap: Snapshot) -> None:
        pg, scr = self.pg, self.screen
        scr.fill(SURFACE)
        scale = (FIELD_PX - 2 * MARGIN) / 144.0
        for k in range(7):  # 24 in tiles
            a = MARGIN + round(k * 24 * scale)
            pg.draw.line(scr, GRID, (a, MARGIN), (a, FIELD_PX - MARGIN))
            pg.draw.line(scr, GRID, (MARGIN, a), (FIELD_PX - MARGIN, a))
        pg.draw.rect(scr, WALL, (MARGIN, MARGIN, FIELD_PX - 2 * MARGIN, FIELD_PX - 2 * MARGIN), 3)

        if snap.time - self._last_trail_t >= 0.03 or snap.time < self._last_trail_t:
            self.trail_true.append(self._to_px(snap.true_pose.x, snap.true_pose.y))
            if snap.est_pose is not None:
                self.trail_est.append(self._to_px(snap.est_pose.x, snap.est_pose.y))
            self._last_trail_t = snap.time
        if self.show_trails:
            if len(self.trail_true) > 1:
                pg.draw.lines(scr, TRAIL, False, list(self.trail_true), 2)
            if self.show_ghost and len(self.trail_est) > 1:
                pg.draw.lines(scr, ESTIMATE, False, list(self.trail_est), 1)

        if snap.overlay_path is not None and len(snap.overlay_path) > 1:
            pg.draw.lines(scr, TARGET, False, [self._to_px(x, y) for x, y in snap.overlay_path], 2)
        if snap.overlay_target is not None:
            tx, ty, th = snap.overlay_target
            px, py = self._to_px(tx, ty)
            pg.draw.circle(scr, TARGET, (px, py), 7, 2)
            if th is not None:
                end = self._to_px(
                    tx + 8 * math.cos(math.radians(th)), ty + 8 * math.sin(math.radians(th))
                )
                pg.draw.line(scr, TARGET, (px, py), end, 2)

        length, width = snap.footprint
        if self.show_ghost and snap.est_pose is not None:
            pg.draw.polygon(scr, ESTIMATE, self._polygon(snap.est_pose, length, width), 2)
        body = self._polygon(snap.true_pose, length, width)
        overlay = pg.Surface(scr.get_size(), pg.SRCALPHA)
        pg.draw.polygon(overlay, (*ROBOT, 70), body)
        scr.blit(overlay, (0, 0))
        pg.draw.polygon(scr, ROBOT, body, 2)
        h = math.radians(snap.true_pose.heading)
        nose = self._to_px(
            snap.true_pose.x + length / 2 * math.cos(h), snap.true_pose.y + length / 2 * math.sin(h)
        )
        pg.draw.line(scr, ROBOT, self._to_px(snap.true_pose.x, snap.true_pose.y), nose, 3)

        for w in snap.wheels:
            k = w.slip
            color = tuple(
                round(lo + (hi - lo) * k) for lo, hi in zip(SLIP_LOW, SLIP_HIGH, strict=True)
            )
            half = w.length / 2
            a = self._to_px(w.x - half * math.cos(w.heading), w.y - half * math.sin(w.heading))
            b = self._to_px(w.x + half * math.cos(w.heading), w.y + half * math.sin(w.heading))
            pg.draw.line(scr, color, a, b, 6)
            if self.show_forces and abs(w.lateral_force) > 0.2:
                n = w.heading + math.pi / 2
                d = w.lateral_force * 0.6  # inches per newton
                end = self._to_px(w.x + d * math.cos(n), w.y + d * math.sin(n))
                pg.draw.line(scr, TARGET, self._to_px(w.x, w.y), end, 2)

        self._draw_panel(snap)

    def _text(self, text: str, pos: tuple[int, int], font=None, color=TEXT) -> int:
        surface = (font or self.font).render(text, True, color)
        self.screen.blit(surface, pos)
        return pos[1] + surface.get_height() + 3

    def _draw_panel(self, snap: Snapshot) -> None:
        pg, scr = self.pg, self.screen
        x0 = FIELD_PX
        pg.draw.rect(scr, PANEL, (x0, 0, PANEL_PX, FIELD_PX))
        x = x0 + 16
        y = self._text(snap.robot_name, (x, 14), self.big)
        speed = "max" if math.isinf(self.speed) else f"{self.speed:g}x"
        state = "PAUSED" if self.paused else f"{speed} (actual {self.actual_rate:.1f}x)"
        y = self._text(f"t = {snap.time:6.2f} s   {snap.phase}", (x, y + 4))
        y = self._text(state, (x, y), color=TEXT_2)

        t, e = snap.true_pose, snap.est_pose
        y = self._text(f"true  x {t.x:7.1f}  y {t.y:7.1f}  h {t.heading % 360:6.1f}", (x, y + 8))
        if e is not None:
            err = e.distance_to(t)
            y = self._text(
                f"est   x {e.x:7.1f}  y {e.y:7.1f}  h {e.heading % 360:6.1f}",
                (x, y),
                color=ESTIMATE,
            )
            y = self._text(f"odometry error {err:5.2f} in", (x, y), color=TEXT_2)
        y = self._text(f"speed {snap.speed_in_s:5.1f} in/s", (x, y))
        y = self._text(f"battery {snap.battery_v:5.2f} V  {snap.battery_soc * 100:5.1f} %", (x, y))

        y += 8
        y = self._text("motor   current            temp", (x, y), self.small, TEXT_2)
        for port, amps, temp, hot in snap.motors:
            self._text(f"{port:>3}", (x, y), self.small)
            bar_w = 150
            pg.draw.rect(scr, GRID, (x + 40, y + 2, bar_w, 10))
            pg.draw.rect(
                scr,
                TARGET if hot else ESTIMATE,
                (x + 40, y + 2, round(bar_w * min(amps / 2.5, 1.0)), 10),
            )
            self._text(f"{amps:4.2f} A", (x + 196, y), self.small)
            y = self._text(f"{temp:5.1f} C", (x + 252, y), self.small, TARGET if hot else TEXT)

        if snap.sticks:
            s = snap.sticks
            y = self._text(
                f"sticks  LY {s.get('LEFT_Y', 0):4d}  LX {s.get('LEFT_X', 0):4d}  "
                f"RY {s.get('RIGHT_Y', 0):4d}  RX {s.get('RIGHT_X', 0):4d}",
                (x, y + 8),
                self.small,
                TEXT_2,
            )
        if snap.lcd:
            y = self._text("brain screen", (x, y + 8), self.small, TEXT_2)
            for line in snap.lcd[:8]:
                y = self._text(line[:58], (x, y), self.small)
        y = self._text("console", (x, y + 8), self.small, TEXT_2)
        for line in snap.console[-8:]:
            y = self._text(line[:58], (x, y), self.small)
        hint = "H help   Space pause   +/- speed   R restart   Esc quit"
        self._text(hint, (x, FIELD_PX - 24), self.small, TEXT_2)
        if self.show_help:
            self._draw_help()

    def _draw_help(self) -> None:
        pg = self.pg
        lines = (__doc__ or "").strip().splitlines()
        box = pg.Surface((FIELD_PX - 80, 24 + 20 * len(lines)), pg.SRCALPHA)
        box.fill((*SURFACE, 240))
        self.screen.blit(box, (40, 40))
        y = 52
        for line in lines:
            y = self._text(line, (56, y), self.small)
