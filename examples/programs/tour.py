"""Example robot program: an autonomous tour of every chassis motion, plus arcade driving.

Run it:
    vexsim run examples/robots/full_omni_6m.yaml --program examples/programs/tour.py
Poses are inches and degrees, counter-clockwise, field frame; the robot starts at (0, 0)
facing +x unless --start says otherwise.
"""

from vexsim.api import delay


def autonomous(bot):
    chassis = bot.chassis
    bot.print("autonomous start")
    # Where the tour stops, numbered on the field (the browser app draws bot.draw's layers)
    for i, (x, y) in enumerate([(30, 0), (30, 24), (0, 40), (-20, -20), (0, 0)], 1):
        bot.draw.point("stops", x, y, size=6)
        bot.draw.text("stops", x + 2.5, y + 2.5, str(i))

    yield from chassis.move_to_point(30, 0)  # PID drive to a point
    yield from chassis.turn_to_heading(90)  # PID turn in place
    yield from chassis.drive(24, profile="scurve")  # jerk-limited straight line
    yield from chassis.move_to_pose(0, 40, 180)  # boomerang to a pose
    bot.print("pose after boomerang:", chassis.pose)

    # Pure pursuit through waypoints, then RAMSETE back along a smooth trajectory.
    yield from chassis.follow([(0, 40), (-30, 40), (-40, 10), (-20, -20)], method="pure_pursuit")
    yield from chassis.turn_to_point(0, 0)
    yield from chassis.follow([(-20, -20), (-5, -30), (10, -15), (0, 0)], method="ramsete")
    yield from chassis.turn_to_heading(0)

    yield delay(200)
    bot.print("autonomous done at", chassis.pose)


def opcontrol(bot):
    # Arcade drive; hold R1 for half speed.
    while True:
        scale = 0.5 if bot.controller.get_digital("R1") else 1.0
        throttle = bot.controller.get_analog("LEFT_Y") * scale
        turn = bot.controller.get_analog("RIGHT_X") * scale
        bot.chassis.arcade(throttle, turn)
        yield delay(10)
