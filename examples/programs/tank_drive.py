"""Example robot program: tank drive, to drive, or to follow a real robot's log.

The left stick's y drives the left side and the right stick's y the right, as many teams'
driver control does. With --follow, a virtual driver holds the sticks and drives the robot
along the path a real robot's MCL log records:

    vexsim run examples/robots/traction_6m.yaml --program examples/programs/tank_drive.py
    vexsim run examples/robots/traction_6m.yaml --program examples/programs/tank_drive.py \\
        --follow examples/logs/left40_simulated.1239e --headless
"""

from vexsim.api import delay


def opcontrol(bot):
    while True:
        left, right = bot.controller.get_analog("LEFT_Y"), bot.controller.get_analog("RIGHT_Y")
        bot.chassis.tank(left, right)
        yield delay(10)
