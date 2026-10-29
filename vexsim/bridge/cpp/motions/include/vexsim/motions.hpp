// vexsim's motions for a LemLib 0.5 chassis: RAMSETE along a smooth path through points, and an
// arc of a given radius through a given angle, each planned on a speed profile
// (vexsim/trajectory.hpp) and driven with a feedforward model of the drive, corrected by RAMSETE
// from the chassis' odometry. They queue with LemLib's own motions, as LemLib's motions queue
// with each other, and chassis.waitUntil(), waitUntilDone() and cancelMotion() work on them.
//
//   vexsim::Motions motions(chassis, {.kS = 0.9, .kV = 0.16, .kA = 0.03});
//   chassis.setPose(0, 0, 0);
//   motions.ramsete({{24, 24}, {48, 0}}, 3000);              // through (24, 24) to (48, 0)
//   motions.moveArc(18, -90, 2000, {.forwards = false});    // 18 in back, turning 90° left
//
// Poses and headings are LemLib's: inches, and degrees clockwise from +y. vexsim's autonomous
// maker writes these calls when it exports a route; this file is a copy of vexsim's, to read
// and change as you like.
#pragma once

#include <cmath>
#include <vector>

#include "lemlib/api.hpp"
#include "vexsim/trajectory.hpp"

namespace vexsim {

/** How the drive answers voltage, each side on its own: volts = kS * sign(v) + kV * v + kA * a,
 * for the side's wheel speed v (in/s) and acceleration a (in/s^2), and kT more on the outside of a
 * turn (less on the inside) against the wheels' scrub; and kP more volts for each in/s its wheels
 * are slower than that (from its motors' speeds), for what the model leaves out. And the limits
 * the motions plan within. vexsim works them out from the robot's config; its Calibrate page fits
 * them to a real robot's log. One left at 0 takes the default after it. */
struct Drive {
	float kS = 0;               // volts that get it moving
	float kV = 0;               // volts per in/s (0: 12 volts at the drivetrain's top speed)
	float kA = 0;               // volts per in/s^2
	float kT = 0;               // volts each side pushes against the scrub in a turn
	float kP = 0;               // volts per in/s the wheels are behind (0: 4 kV)
	float maxVelocity = 0;      // in/s, either side's wheels (0: 80% of the drivetrain's top speed)
	float maxAccel = 0;         // in/s^2, speeding up and slowing down (0: 120)
	float maxLateralAccel = 0;  // in/s^2, turning at speed: speed squared times curvature (0: 20)
};

/** moveArc's options. */
struct ArcParams {
	bool forwards = true;
	float maxVelocity = 0;  // in/s, the robot's own speed (0: the drive's)
	float maxAccel = 0;     // in/s^2 (0: the drive's)
};

/** ramsete's options. */
struct PathParams {
	bool forwards = true;
	float maxVelocity = 0;   // in/s (0: the drive's)
	float maxAccel = 0;      // in/s^2 (0: the drive's)
	float endHeading = NAN;  // degrees (LemLib's theta) at the last point (NAN: the way the path goes there)
};

/** vexsim's motions, on `chassis`, with `drive`'s model of how it answers voltage. */
class Motions {
	public:
	Motions(lemlib::Chassis& chassis, Drive drive) : chassis(chassis), drive(drive) {}

	/** Drive along an arc of `radius` inches, turning `degrees` (clockwise positive, as LemLib's
	 * theta), forwards or backwards. It's over when the plan is, or after `timeout` ms. */
	void moveArc(float radius, float degrees, int timeout, ArcParams params = {}, bool async = true);

	/** Follow a smooth path from where the robot is through `points`, setting off the way it
	 * faces (or away, backwards), with RAMSETE. It's over when the plan is, or after `timeout`
	 * ms. */
	void ramsete(const std::vector<Waypoint>& points, int timeout, PathParams params = {}, bool async = true);

	/** The limits the motions plan within: the drive's, worked out from the chassis' drivetrain
	 * where the drive leaves them at 0. */
	Limits limits() const;

	/** RAMSETE's gains, in SI units (1/m^2, and a damping ratio), as the textbook has them. */
	float b = 2.0f;
	float zeta = 0.7f;

	private:
	void follow(const Trajectory& plan, int timeout);
	lemlib::Chassis& chassis;
	Drive drive;
};

}  // namespace vexsim
