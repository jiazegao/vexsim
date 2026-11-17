"""A first program for a folder that has none: a short autonomous routine and driver
control, written into the workspace for the student to run, read and change. It runs on any
robot the app's *New robot…* makes."""

from __future__ import annotations

from pathlib import Path

FOLDER = "programs"
NAME = "first_program"

PROGRAM = '''\
"""Your first vexsim program: a short autonomous routine, and driver control.

Run it from the app (pick it under Program, then Run), or from a terminal:

    vexsim run ROBOT.yaml --program programs/first_program.py

The run's mode picks what runs: "autonomous" runs autonomous(), "driver" runs opcontrol(),
and "match" runs one and then the other, as a match does. Distances are inches and angles
degrees, counter-clockwise, with 0 along +x. The robot starts at (0, 0) facing +x unless
the run's start says otherwise. vexsim's programming guide (docs/programming.md, or the
app's Guide page) lists every motion, motor and sensor call.

Change something, save, and run it again: with "Run on save" ticked in the app, saving is
enough.
"""

from vexsim.api import delay

SIDE_IN = 24  # how long each side of the square is: try 36


def autonomous(bot):
    if bot.drive.holonomic:
        # A robot that can strafe (an X-drive, a mecanum drive, an H-drive) is driven by
        # power here: forward, strafe and turn, each from -127 to 127.
        bot.print("autonomous: forward for a second, then back")
        bot.drive.move(80, 0, 0)
        yield delay(1000)
        bot.drive.move(-80, 0, 0)
        yield delay(1000)
        bot.drive.move(0, 0, 0)
        return
    chassis = bot.chassis  # a tank drive's motions, like LemLib's
    bot.print("autonomous: a square,", SIDE_IN, "in on a side")
    for corner in range(4):
        yield from chassis.drive(SIDE_IN)  # straight ahead
        yield from chassis.turn_to_heading(90 * (corner + 1))  # a quarter turn to the left
    bot.print("back at", chassis.pose)  # where the robot's code thinks it is now


def opcontrol(bot):
    sticks = bot.controller
    while True:
        # Arcade drive: the left stick drives (and strafes, on a robot that can), the right
        # stick turns. On a keyboard that's W / S to drive and A / D to turn; a gamepad works too.
        forward, strafe = sticks.get_analog("LEFT_Y"), sticks.get_analog("LEFT_X")
        bot.drive.move(forward, strafe, sticks.get_analog("RIGHT_X"))
        # Tank drive instead, a stick a side (W / S and the Up / Down arrows), on a tank drive:
        # bot.chassis.tank(sticks.get_analog("LEFT_Y"), sticks.get_analog("RIGHT_Y"))
        yield delay(10)  # wait 10 ms, like pros::delay(10)
'''


def write_starter(root: str | Path) -> Path:
    """Write the starter program into the workspace's programs/ folder (made if it isn't
    there), never over a file: first_program.py, or first_program_2.py and so on."""
    folder = Path(root) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{NAME}.py"
    number = 2
    while path.exists():
        path = folder / f"{NAME}_{number}.py"
        number += 1
    path.write_text(PROGRAM, encoding="utf-8", newline="\n")
    return path
