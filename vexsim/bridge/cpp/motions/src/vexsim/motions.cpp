// vexsim's motions for a LemLib 0.5 chassis (vexsim/motions.hpp).
#include "vexsim/motions.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>

#include "pros/rtos.hpp"

namespace vexsim {
namespace {

constexpr double PI = 3.14159265358979323846;
constexpr double M_PER_IN = 0.0254;  // RAMSETE's gains are in SI units
constexpr double TURNING = 0.15;     // rad/s: turning faster than this, the scrub is all there

// LemLib keeps its chassis' motion queue, and the drivetrain it drives, protected: a class
// derived from the chassis may name them, and the pointers to members it makes work on any
// chassis.
struct Access : lemlib::Chassis {
	static void request(lemlib::Chassis& c) { (c.*&Access::requestMotionStart)(); }
	static void release(lemlib::Chassis& c) { (c.*&Access::endMotion)(); }
	static bool running(lemlib::Chassis& c) { return c.*&Access::motionRunning; }
	static float& travelled(lemlib::Chassis& c) { return c.*&Access::distTraveled; }
	static lemlib::Drivetrain& wheels(lemlib::Chassis& c) { return c.*&Access::drivetrain; }
};

double radians(double degrees) { return degrees * PI / 180; }

// LemLib's theta (degrees clockwise from +y) as vexsim/trajectory.hpp has headings
double standard(double theta) { return PI / 2 - radians(theta); }

double top_speed(const lemlib::Drivetrain& d) {  // in/s, at full power
	return d.rpm * PI * d.wheelDiameter / 60;
}

// How fast a side's wheels go (in/s): its motors' mean, each geared as the drivetrain's rpm
// says (NaN if none of them answers)
double wheel_speed(pros::MotorGroup& motors, const lemlib::Drivetrain& d) {
	std::vector<double> rpm = motors.get_actual_velocity_all();
	std::vector<pros::MotorGears> gears = motors.get_gearing_all();
	double sum = 0;
	int count = 0;
	for (std::size_t k = 0; k < rpm.size() && k < gears.size(); k++) {
		double cartridge = gears[k] == pros::MotorGears::red     ? 100
		                   : gears[k] == pros::MotorGears::green ? 200
		                   : gears[k] == pros::MotorGears::blue  ? 600
		                                                         : 0;
		if (cartridge == 0 || !std::isfinite(rpm[k]) || rpm[k] == PROS_ERR_F) continue;
		sum += rpm[k] * d.rpm / cartridge;
		count++;
	}
	return count ? sum / count * PI * d.wheelDiameter / 60 : NAN;
}

}  // namespace

Limits Motions::limits() const {
	const lemlib::Drivetrain& d = Access::wheels(chassis);
	Limits l;
	l.maxVelocity = drive.maxVelocity > 0 ? drive.maxVelocity : 0.8 * top_speed(d);
	l.maxAccel = drive.maxAccel > 0 ? drive.maxAccel : 120;
	l.maxLateralAccel = drive.maxLateralAccel > 0 ? drive.maxLateralAccel : 20;
	l.trackWidth = d.trackWidth;
	return l;
}

void Motions::moveArc(float radius, float degrees, int timeout, ArcParams params, bool async) {
	Access::request(chassis);  // after the motions before it, as LemLib's own motions wait
	if (!Access::running(chassis)) return;  // cancelled while it waited
	if (async) {  // as LemLib does it: a task of its own, started while the queue is held
		Motions self = *this;
		pros::Task task([self, radius, degrees, timeout, params]() mutable {
			self.moveArc(radius, degrees, timeout, params, false);
		});
		Access::release(chassis);
		pros::delay(10);  // time for it to take its place in the queue
		return;
	}
	Limits l = limits();
	if (params.maxAccel > 0) l.maxAccel = params.maxAccel;
	double speed = params.maxVelocity > 0 ? params.maxVelocity : l.maxVelocity;
	lemlib::Pose p = chassis.getPose(true, true);  // radians, counter-clockwise from +x
	follow(planArc(p.x, p.y, p.theta, std::fabs(radius), -radians(degrees), params.forwards, speed, l), timeout);
}

void Motions::ramsete(const std::vector<Waypoint>& points, int timeout, PathParams params, bool async) {
	Access::request(chassis);
	if (!Access::running(chassis)) return;
	if (async) {
		Motions self = *this;
		std::vector<Waypoint> copy = points;
		pros::Task task([self, copy, timeout, params]() mutable { self.ramsete(copy, timeout, params, false); });
		Access::release(chassis);
		pros::delay(10);
		return;
	}
	Limits l = limits();
	if (params.maxAccel > 0) l.maxAccel = params.maxAccel;
	double speed = params.maxVelocity > 0 ? params.maxVelocity : l.maxVelocity;
	double end = std::isnan(params.endHeading) ? std::nan("") : standard(params.endHeading);
	lemlib::Pose p = chassis.getPose(true, true);
	follow(planPath(p.x, p.y, p.theta, points, params.forwards, end, speed, l), timeout);
}

void Motions::follow(const Trajectory& plan, int timeout) {
	lemlib::Drivetrain& d = Access::wheels(chassis);
	const double half = d.trackWidth / 2;
	const double kV = drive.kV > 0 ? drive.kV : 12 / top_speed(d);
	const double kP = drive.kP > 0 ? drive.kP : 4 * kV;
	// A side's volts: the model, for its wheels at v (in/s) speeding up at a (in/s^2) while the
	// robot turns at w (rad/s, `side` -1 left, 1 right), and how far its wheels are behind
	auto volts = [&](double v, double a, double w, double side, double now) {
		double sign = v > 1e-3 ? 1.0 : v < -1e-3 ? -1.0 : 0.0;
		double behind = std::isfinite(now) ? v - now : 0.0;
		return drive.kS * sign + kV * v + drive.kA * a + side * drive.kT * std::tanh(w / TURNING) + kP * behind;
	};
	const std::uint32_t start = pros::millis();
	lemlib::Pose last = chassis.getPose();
	float& travelled = Access::travelled(chassis);  // what waitUntil() looks at, as LemLib's motions keep it
	travelled = 0;
	while (Access::running(chassis)) {
		std::uint32_t elapsed = pros::millis() - start;
		double t = elapsed / 1000.0;
		if (elapsed >= static_cast<std::uint32_t>(timeout) || t >= plan.back().t) break;
		State want = sample(plan, t);
		lemlib::Pose pose = chassis.getPose(true, true);
		// RAMSETE: the planned speeds, corrected by how far the robot is from where the plan has
		// it, in the robot's own frame
		double c = std::cos(pose.theta), s = std::sin(pose.theta);
		double dx = want.x - pose.x, dy = want.y - pose.y;
		double ex = (c * dx + s * dy) * M_PER_IN, ey = (-s * dx + c * dy) * M_PER_IN;
		double eh = std::remainder(want.heading - pose.theta, 2 * PI);
		double vd = want.v * M_PER_IN, wd = want.omega;
		double k = 2 * zeta * std::sqrt(wd * wd + b * vd * vd);
		double sinc = std::fabs(eh) > 1e-6 ? std::sin(eh) / eh : 1.0;
		double v = (vd * std::cos(eh) + k * ex) / M_PER_IN;
		double w = wd + k * eh + b * vd * sinc * ey;
		double left = volts(v - w * half, want.a - want.alpha * half, w, -1, wheel_speed(*d.leftMotors, d));
		double right = volts(v + w * half, want.a + want.alpha * half, w, 1, wheel_speed(*d.rightMotors, d));
		double biggest = std::max(std::fabs(left), std::fabs(right));
		if (biggest > 12) {  // the turn first: both sides scaled down together
			left *= 12 / biggest;
			right *= 12 / biggest;
		}
		d.leftMotors->move_voltage(static_cast<std::int32_t>(std::lround(left * 1000)));
		d.rightMotors->move_voltage(static_cast<std::int32_t>(std::lround(right * 1000)));
		lemlib::Pose now = chassis.getPose();
		travelled += now.distance(last);
		last = now;
		pros::delay(10);
	}
	d.leftMotors->move(0);
	d.rightMotors->move(0);
	travelled = -1;  // over, as LemLib's motions say it
	Access::release(chassis);
}

}  // namespace vexsim
