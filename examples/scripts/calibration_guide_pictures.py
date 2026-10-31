"""Make the calibration guide's pictures (docs/calibration_guide.md) with vexsim's own tools,
on team 1239E's robot and field:

- the plan's maps (``vexsim calibration plan``): the push lane, a driving test's spot and a
  distance sweep's;
- the calibration program's screens, the brain's and the controller's, as a simulated
  student (vexsim/calibration/student.py) meets each step of a whole session, on a "real"
  1239E that isn't quite what its config says (the tests' hidden changes: wheels 3.20 in, its
  IMU further off, slipperier omni wheels, voltage commands capped at rated speed, the real
  distance sensors); and the device check of a robot wired other than its config says;
- that session's report (``vexsim calibrate --apply``): the free spin, the held-out run, the
  distance sweeps;
- the autonomous check of Left 40 against the calibrated config (``vexsim calibration
  check-auton``): the paths, and how far apart they come.

    python examples/scripts/calibration_guide_pictures.py            # into docs/img/guide/
    python examples/scripts/calibration_guide_pictures.py --out pics --keep work

It takes about 10 minutes, most of it the session's fit, and needs g++ and matplotlib.
"""

from __future__ import annotations

import argparse
import contextlib
import math
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROBOT = ROOT / "examples" / "robots" / "1239e_2026-27.yaml"
FIELD = ROOT / "examples" / "fields" / "1239e_2026-27.yaml"
PROJECT = ROOT / "examples" / "pros_projects" / "1239e_2026-27"
DAY = "2026-11-07"  # the session's, so the pictures come out the same any day
HIDDEN = {  # what the "real" robot is like, and its config doesn't say
    "wheel.omni.longitudinal_mu": 0.75,
    "wheel.omni.lateral_mu": 0.25,
    "wheel.omni.rolling_resistance": 0.13,
    "motor.voltage_cap": 1.0,
    "sensor.distance.long_noise_fraction": 0.003,
    "sensor.distance.short_noise_mm": 1.5,
    "sensor.distance.max_range_mm": 2300.0,
    "sensor.distance.glancing_miss": 0.9,
    "sensor.distance.glancing_deg": 45.0,
    "sensor.distance.glancing_mm": 1500.0,
    "sensor.distance.confidence_per_m": 8.0,
    "sensor.distance.confidence_per_deg": 0.25,
}
# The screens the guide shows: (picture, the student's event, the first after this one)
SCREENS = [
    ("screen_menu", "menu device_check", None),
    ("screen_device_side", "ask side", None),
    ("screen_device_forward", "ask forward", None),
    ("screen_device_turn", "ask turn left 90", None),
    ("screen_device_cover", "ask cover", None),
    ("screen_device_passed", "ask done passed", None),
    ("screen_free_spin", "ask side", "menu free_spin"),
    ("screen_imu_still", "ask still", None),
    ("screen_imu_turns", "ask line", None),
    ("screen_imu_turning", "ask turn left 3600", None),
    ("screen_imu_saved", "ask next", "log imu_turns_left"),
    ("screen_push_lane", "ask place push", None),
    ("screen_push", "ask lane forward", None),
    ("screen_push_saved", "ask next", "log push_forward"),
    ("screen_place", "ask place straight", None),
    ("screen_countdown", "countdown", "ask place straight"),
    ("screen_saved", "ask next", "log straight"),
    ("screen_sweep", "ask place sweep_1", None),
]


# --- the robots -------------------------------------------------------------------------------


def real_robot(config):
    """1239E as it is: its wheels 3.20 in, its IMU 0.5% off (its config says 0.25%), and
    HIDDEN."""
    wheels = tuple(w.model_copy(update={"diameter_in": 3.20}) for w in config.drivetrain.wheels)
    sensors = tuple(
        s.model_copy(update={"scale_error": 0.005}) if s.type == "imu" else s
        for s in config.sensors
    )
    return config.model_copy(
        update={
            "drivetrain": config.drivetrain.model_copy(update={"wheels": wheels}),
            "sensors": sensors,
            "overrides": {**config.overrides, **HIDDEN},
        }
    )


def miswired(config):
    """1239E with motor 9 the other way round and distance sensors 1 and 8 in each other's
    ports."""
    gearing = dict(config.drivetrain.gearing)
    gearing["left"] = gearing["left"].model_copy(update={"motors": (10, -9)})
    sensors = tuple(
        s.model_copy(update={"port": {1: 8, 8: 1}[s.port]})
        if s.type == "distance" and s.port in (1, 8)
        else s
        for s in config.sensors
    )
    drivetrain = config.drivetrain.model_copy(update={"gearing": gearing})
    return config.model_copy(update={"drivetrain": drivetrain, "sensors": sensors})


def without_pieces(field):
    return field.model_copy(
        update={"elements": tuple(e for e in field.elements if e.type != "piece")}
    )


# --- the screens ------------------------------------------------------------------------------


def photographer(plan, config, tests):
    """A simulated student that also keeps each screen it met: the brain's when the program
    asked, and the controller's a moment later (the program sends it a line at a time)."""
    from vexsim.calibration.student import Student

    class Photographer(Student):
        def __init__(self):
            super().__init__(plan, config, tests)
            self.shots: list[dict] = []

        def _on(self, words):
            # both screens a moment later (the student takes longer to answer), so that the
            # controller has had time to show its lines and the two status lines agree
            shot = {"event": " ".join(words), "brain": [], "pad": []}
            self.shots.append(shot)
            self._at(
                self.now + 0.25, lambda t, s=shot: s.update(brain=self._brain(), pad=self._pad())
            )
            super()._on(words)

        def _brain(self):
            return [self.sim.lcd.get(k, "").rstrip() for k in range(8)]

        def _pad(self):
            return [self.sim.controller_screen.get(k, "").rstrip() for k in range(3)]

    return Photographer()


def run_session(plan, executable, config, real, field, card: Path, tests):
    """The program on the real robot, the student running ``tests`` (or all of the session's):
    the student, with its screens."""
    from vexsim.bridge.program import CppProgram
    from vexsim.runtime.simulation import Simulation

    student = photographer(plan, config, tests or [k for k, _, _ in plan.session()])
    sim = Simulation(
        real,
        program=CppProgram(executable, env={"VEXSIM_SD_DIR": str(card)}),
        field=field,
        input_source=student,
        start=student.start,
        echo=None,
    )
    student.attach(sim)
    sim.start("driver")
    try:
        if not sim.run_until_finished(900.0):
            raise SystemExit("the session didn't finish")
    finally:
        sim.close()
    if student.error:
        raise SystemExit(f"the student got stuck: {student.error}")
    return student


def draw_screens(brain: list[str], pad: list[str], path: Path) -> Path:
    """The V5 brain's screen and the controller's, side by side, as the program left them."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    fig = plt.figure(figsize=(8.6, 2.95), dpi=100)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
    ax.set_xlim(0, 860)
    ax.set_ylim(-20, 275)
    ax.set_axis_off()
    # the brain: a 480 x 272 screen, 8 lines of 48 characters
    ax.add_patch(FancyBboxPatch((6, 6), 548, 263, boxstyle="round,pad=0,rounding_size=14",
                                fc="#2b2b2b", ec="#111111", lw=1.5))  # fmt: skip
    ax.add_patch(
        FancyBboxPatch((22, 18), 516, 240, boxstyle="square,pad=0", fc="#000000", ec="none")
    )
    for k, line in enumerate(brain[:8]):
        color = "#9fd3ff" if k < 2 else "#ffffff"  # the status lines, then the page
        ax.text(30, 246 - 29.5 * k, line[:48], color=color, family="monospace", fontsize=10.2,
                va="top", ha="left")  # fmt: skip
    ax.text(280, -16, "the brain", ha="center", va="bottom", fontsize=8, color="#555555")
    # the controller: 3 lines of 19 characters
    ax.add_patch(FancyBboxPatch((585, 70), 265, 150, boxstyle="round,pad=0,rounding_size=30",
                                fc="#3a3a3a", ec="#111111", lw=1.5))  # fmt: skip
    ax.add_patch(
        FancyBboxPatch((612, 108), 211, 82, boxstyle="square,pad=0", fc="#b7c4a5", ec="#222222")
    )
    for k, line in enumerate((pad + ["", "", ""])[:3]):
        ax.text(619, 182 - 25 * k, line[:19], color="#111111", family="monospace", fontsize=10.5,
                va="top", ha="left")  # fmt: skip
    ax.text(717, 52, "the controller", ha="center", va="bottom", fontsize=8, color="#555555")
    fig.savefig(path)
    plt.close(fig)
    return path


def screen_pictures(student, out: Path, failed=None) -> list[Path]:
    made = []
    for name, event, after in SCREENS:
        shots = student.shots
        if after is not None:
            at = next((k for k, s in enumerate(shots) if s["event"].startswith(after)), len(shots))
            shots = shots[at + 1 :]
        shot = next((s for s in shots if s["event"].startswith(event)), None)
        if shot is None:
            print(f"  (no {event!r} after {after!r}: {name} left out)")
            continue
        made.append(draw_screens(shot["brain"], shot["pad"], out / f"{name}.png"))
    if failed is not None:
        found = [s for s in failed.shots if s["event"].startswith("ask done failed")]
        if found:
            made.append(
                draw_screens(found[0]["brain"], found[0]["pad"], out / "screen_device_failed.png")
            )
    return made


# --- the rest ---------------------------------------------------------------------------------


def run_left40(real, seed: int, card: Path) -> tuple[Path, tuple[float, float, float]]:
    """1239E's Left 40 on the real robot, logging to ``card`` (the next numbered log, as on
    the brain's card): its log, and where it came to rest."""
    from vexsim.app.runspec import (
        RunSpec,
        build,
        check,
        program_factory,
        routine_start,
        simulation_factory,
    )
    from vexsim.calibration.auton import _pose, settle

    spec = RunSpec(
        robot=str(ROBOT),
        program=str(PROJECT),
        routine="left40",
        field=str(FIELD),
        mode="autonomous",
        start=routine_start(str(PROJECT), "left40"),
        seed=seed,
        sd=str(card),
    )
    prepared = check(spec)
    prepared.config = real
    make, mode = program_factory(prepared, build(prepared, log=None))
    before = set(card.glob("vexsim_*.csv"))
    sim = simulation_factory(prepared, make, mode, echo=None)()
    try:
        sim.run_until_finished(60.0)
        settle(sim)
        end = _pose(sim)
    finally:
        sim.close()
    (log,) = set(card.glob("vexsim_*.csv")) - before
    return log, end


def main() -> None:
    from vexsim.bridge.build import build_project
    from vexsim.calibration.auton import check_auton, load_marks, tape_marks, write_report
    from vexsim.calibration.plan import make_plan, write_plan
    from vexsim.calibration.program import write_program
    from vexsim.calibration.report import apply_changes
    from vexsim.calibration.report import write_report as session_report
    from vexsim.calibration.session import Session, card_logs, collect
    from vexsim.calibration.session_fit import calibrate
    from vexsim.config import load_field, load_robot

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=str(ROOT / "docs" / "img" / "guide"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--keep", help="work in this folder, and keep it (the program, the "
                        "card, the session, the check), to try the commands on")  # fmt: skip
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    config = load_robot(ROBOT)
    field = load_field(FIELD)
    session_field = without_pieces(field)  # the plan says to clear them off
    real = real_robot(config)
    with contextlib.ExitStack() as stack:
        if args.keep:
            work = Path(args.keep).resolve()
            work.mkdir(parents=True, exist_ok=True)
        else:
            work = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="vexsim-guide-")))
        print("the plan")
        plan = make_plan(config, session_field, workers=args.workers)
        maps = [p for p in write_plan(plan, work / "plan") if p.suffix == ".png"]
        for key, name in (
            ("push", "map_push"),
            ("straight", "map_straight"),
            ("sweep_1", "map_sweep"),
        ):
            found = next(p for p in maps if p.stem.endswith(f"_{key}"))
            shutil.copy(found, out / f"{name}.png")
        print("the program, and a session on the real robot")
        write_program(config, plan, work / "program")
        executable = build_project(work / "program").executable
        student = run_session(plan, executable, config, real, session_field, work / "card", None)
        wired = run_session(plan, executable, config, miswired(real), session_field,
                            work / "card_miswired", ["device_check"])  # fmt: skip
        for path in screen_pictures(student, out, wired):
            print(f"  {path.name}")
        print("collecting and fitting it (a few minutes)")
        session = Session.open(work / "sessions" / DAY)
        collect(session, card_logs(work / "card"))
        result = calibrate(config, session, session_field, workers=args.workers, say=print)
        report, writes = session_report(config, result, session.folder / "report", when=DAY)
        text = report.read_text(encoding="utf-8")
        for name in ("free_spin", "held_out", "distance"):
            shutil.copy(report.parent / f"{name}.png", out / f"report_{name}.png")
            text = text.replace(f"]({name}.png)", f"](report_{name}.png)")
        (out / "report_example.md").write_text(text, encoding="utf-8")
        calibrated = work / "1239e_calibrated.yaml"
        text = ROBOT.read_text(encoding="utf-8")
        calibrated.write_text(apply_changes(text, writes, DAY, DAY), encoding="utf-8")
        print("the autonomous check: Left 40, twice on the real robot")
        logs, ends = [], []
        for seed in (1, 3):
            log, end = run_left40(real, seed, work / "auton_card")
            logs.append(log)
            ends.append(tape_marks(config, field, end))
            print(f"  {log.name} ended at {end[0]:.2f}, {end[1]:.2f}, {end[2]:.1f} deg: {ends[-1]}")
        check = check_auton(calibrated, FIELD, PROJECT, logs, ends,
                            marks=load_marks(max_distance_in=2.0, max_heading_deg=4.0),
                            workers=min(args.workers, 3), say=print)  # fmt: skip
        folder = work / "check"
        write_report(check, config, field, folder)
        for name in ("paths", "apart"):
            shutil.copy(folder / f"{name}.png", out / f"check_{name}.png")
        print(f"  {'passes' if check.passed else 'fails'}: {check.failures}")
    for path in sorted(out.iterdir()):
        print(f"wrote {path}")
    print(f"{math.fsum(p.stat().st_size for p in out.iterdir()) / 1e6:.1f} MB")


if __name__ == "__main__":  # its worker processes import this file: only the first runs main()
    main()
