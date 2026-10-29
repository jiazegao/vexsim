// vexsim's motions (vexsim/motions.hpp): how they plan where to go. An arc, or a smooth path
// through points, timed on a speed profile that keeps each side's wheels, the robot's speeding
// up and slowing down, and its turning at speed within limits. Plain C++17, nothing of PROS or
// LemLib's, so it can be tried anywhere. vexsim's Python (vexsim/algorithms/control/
// trajectory.py) and its autonomous maker plan the same way, step for step.
//
// Inches, seconds, and headings in radians counter-clockwise from +x (LemLib's own convention
// is degrees clockwise from +y: vexsim/motions.hpp turns one into the other).
#pragma once

#include <algorithm>
#include <cmath>
#include <vector>

namespace vexsim {

/** A moment of a planned motion: when (s), how far along its way (in), where (in, and the robot's
 * heading), how fast it goes (forward speed, negative when it drives backwards, in/s; turning,
 * rad/s) and how fast that changes (in/s^2, rad/s^2). */
struct State {
	double t = 0, s = 0, x = 0, y = 0, heading = 0, v = 0, omega = 0, a = 0, alpha = 0;
};

/** What a plan keeps to: the fastest either side's wheels may go, how fast the robot may speed
 * up and slow down along its way, how hard it may turn at speed (speed squared times
 * curvature), and how far apart its left and right wheels are. */
struct Limits {
	double maxVelocity = 60;      // in/s
	double maxAccel = 120;        // in/s^2
	double maxLateralAccel = 60;  // in/s^2
	double trackWidth = 12;       // in
};

struct Waypoint {
	double x = 0, y = 0;
};

using Trajectory = std::vector<State>;

namespace trajectory_detail {

constexpr double PI = 3.14159265358979323846;
constexpr double STEP = 0.25;  // inches between the samples a path is timed at

/** A point of a path: how far along it (in), where, which way it goes, and how it bends
 * (radians per inch, counter-clockwise positive). */
struct Sample {
	double s, x, y, heading, curvature;
};

inline double wrap(double angle) {  // into (-pi, pi]
	angle = std::fmod(angle + PI, 2 * PI);
	if (angle <= 0) angle += 2 * PI;
	return angle - PI;
}

inline double distance(double x0, double y0, double x1, double y1) {
	return std::sqrt((x1 - x0) * (x1 - x0) + (y1 - y0) * (y1 - y0));
}

/** The path's samples timed: as fast as the limits let it go at each sample, from a standstill
 * to a standstill, with the states every `dt` seconds (and at the end). */
inline Trajectory profile(const std::vector<Sample>& path, bool forwards, double speed, const Limits& limits,
                          double dt) {
	const std::size_t n = path.size();
	const double side = forwards ? 1.0 : -1.0;
	if (n < 2) {
		State still;
		if (n == 1) {
			still.x = path[0].x;
			still.y = path[0].y;
			still.heading = path[0].heading - (forwards ? 0 : PI);
		}
		return {still};
	}
	std::vector<double> v(n), t(n, 0.0), accel(n, 0.0);
	for (std::size_t j = 0; j < n; j++) {
		double bend = std::fabs(path[j].curvature);
		double cap = std::min(speed, limits.maxVelocity / (1 + bend * limits.trackWidth / 2));
		if (bend > 1e-9) cap = std::min(cap, std::sqrt(limits.maxLateralAccel / bend));
		v[j] = cap;
	}
	v[0] = v[n - 1] = 0;
	for (std::size_t j = 1; j < n; j++)  // speeding up
		v[j] = std::min(v[j], std::sqrt(v[j - 1] * v[j - 1] + 2 * limits.maxAccel * (path[j].s - path[j - 1].s)));
	for (std::size_t j = n - 1; j-- > 0;)  // slowing down
		v[j] = std::min(v[j], std::sqrt(v[j + 1] * v[j + 1] + 2 * limits.maxAccel * (path[j + 1].s - path[j].s)));
	for (std::size_t j = 1; j < n; j++) {
		double ds = path[j].s - path[j - 1].s;
		double sum = v[j] + v[j - 1];
		t[j] = t[j - 1] + (sum > 1e-12 ? 2 * ds / sum : 0.0);
		accel[j] = ds > 1e-12 ? (v[j] * v[j] - v[j - 1] * v[j - 1]) / (2 * ds) : 0.0;
	}
	Trajectory states;
	const double end = t[n - 1];
	std::size_t j = 1;  // the samples j - 1 and j bracket the time
	for (long k = 0;; k++) {
		double time = std::min(k * dt, end);
		while (j < n - 1 && t[j] < time) j++;
		double tau = time - t[j - 1];
		double s = path[j - 1].s + v[j - 1] * tau + 0.5 * accel[j] * tau * tau;
		s = std::max(path[j - 1].s, std::min(path[j].s, s));
		double speedNow = std::max(0.0, v[j - 1] + accel[j] * tau);
		double ds = path[j].s - path[j - 1].s;
		double f = ds > 1e-12 ? (s - path[j - 1].s) / ds : 0.0;
		const Sample& p = path[j - 1];
		const Sample& q = path[j];
		State state;
		state.t = time;
		state.s = s;
		state.x = p.x + f * (q.x - p.x);
		state.y = p.y + f * (q.y - p.y);
		state.heading = p.heading + f * (q.heading - p.heading) - (forwards ? 0 : PI);
		double curvature = p.curvature + f * (q.curvature - p.curvature);
		state.v = side * speedNow;
		state.omega = curvature * speedNow;
		state.a = side * accel[j];
		state.alpha = curvature * accel[j];
		if (time >= end) {  // stopped
			state.v = state.omega = state.a = state.alpha = 0;
		}
		states.push_back(state);
		if (time >= end) break;
	}
	return states;
}

}  // namespace trajectory_detail

/** An arc from (x, y), facing `heading`: `radius` inches, turning the robot `turn` radians
 * (counter-clockwise positive), driving forwards or backwards, at most `speed` in/s. */
inline Trajectory planArc(double x, double y, double heading, double radius, double turn, bool forwards, double speed,
                          const Limits& limits, double dt = 0.01) {
	using namespace trajectory_detail;
	const double length = std::fabs(radius * turn);
	const int count = std::max(1, static_cast<int>(std::ceil(length / STEP)));
	const double travel = heading + (forwards ? 0 : PI);  // the way it goes
	const double bend = length > 1e-12 ? turn / length : 0.0;
	std::vector<Sample> path;
	for (int i = 0; i <= count; i++) {
		double s = length * i / count;
		double h = travel + bend * s;
		double px = x + s * std::cos(travel), py = y + s * std::sin(travel);
		if (std::fabs(bend) > 1e-12) {
			px = x + (std::sin(h) - std::sin(travel)) / bend;
			py = y - (std::cos(h) - std::cos(travel)) / bend;
		}
		path.push_back({s, px, py, h, bend});
	}
	return profile(path, forwards, speed, limits, dt);
}

/** A smooth path from (x, y), facing `heading`, through `points`: it sets off the way the robot
 * faces (backwards: the way it faces away from), bends through each point (a Catmull-Rom curve's
 * tangent there), and ends facing `endHeading` (radians, the robot's), or, if that's NaN, the
 * way the last stretch goes. At most `speed` in/s. */
inline Trajectory planPath(double x, double y, double heading, const std::vector<Waypoint>& points, bool forwards,
                           double endHeading, double speed, const Limits& limits, double dt = 0.01) {
	using namespace trajectory_detail;
	std::vector<Waypoint> q{{x, y}};
	for (const Waypoint& p : points)
		if (distance(q.back().x, q.back().y, p.x, p.y) > 1e-6) q.push_back(p);
	const double travel = heading + (forwards ? 0 : PI);
	if (q.size() < 2) return profile({{0, x, y, travel, 0}}, forwards, speed, limits, dt);
	const std::size_t m = q.size() - 1;  // pieces, each a cubic Hermite curve
	std::vector<Waypoint> tangent(q.size());
	double first = distance(q[0].x, q[0].y, q[1].x, q[1].y);
	tangent[0] = {std::cos(travel) * first, std::sin(travel) * first};
	for (std::size_t i = 1; i < m; i++)
		tangent[i] = {(q[i + 1].x - q[i - 1].x) / 2, (q[i + 1].y - q[i - 1].y) / 2};
	if (std::isnan(endHeading)) {
		tangent[m] = {q[m].x - q[m - 1].x, q[m].y - q[m - 1].y};
	} else {
		double last = distance(q[m - 1].x, q[m - 1].y, q[m].x, q[m].y);
		double end = endHeading + (forwards ? 0 : PI);
		tangent[m] = {std::cos(end) * last, std::sin(end) * last};
	}
	std::vector<Sample> path;
	double s = 0, previous = travel;
	for (std::size_t i = 0; i < m; i++) {
		const Waypoint &p0 = q[i], &p1 = q[i + 1], &m0 = tangent[i], &m1 = tangent[i + 1];
		int count = std::max(4, static_cast<int>(std::ceil(distance(p0.x, p0.y, p1.x, p1.y) / STEP)));
		for (int k = i == 0 ? 0 : 1; k <= count; k++) {
			double u = static_cast<double>(k) / count, u2 = u * u, u3 = u2 * u;
			double h00 = 2 * u3 - 3 * u2 + 1, h10 = u3 - 2 * u2 + u, h01 = -2 * u3 + 3 * u2, h11 = u3 - u2;
			double d00 = 6 * u2 - 6 * u, d10 = 3 * u2 - 4 * u + 1, d01 = -6 * u2 + 6 * u, d11 = 3 * u2 - 2 * u;
			double e00 = 12 * u - 6, e10 = 6 * u - 4, e01 = -12 * u + 6, e11 = 6 * u - 2;
			double px = h00 * p0.x + h10 * m0.x + h01 * p1.x + h11 * m1.x;
			double py = h00 * p0.y + h10 * m0.y + h01 * p1.y + h11 * m1.y;
			double dx = d00 * p0.x + d10 * m0.x + d01 * p1.x + d11 * m1.x;
			double dy = d00 * p0.y + d10 * m0.y + d01 * p1.y + d11 * m1.y;
			double ex = e00 * p0.x + e10 * m0.x + e01 * p1.x + e11 * m1.x;
			double ey = e00 * p0.y + e10 * m0.y + e01 * p1.y + e11 * m1.y;
			double rate = std::sqrt(dx * dx + dy * dy);
			double h = rate > 1e-12 ? previous + wrap(std::atan2(dy, dx) - previous) : previous;
			double bend = rate > 1e-12 ? (dx * ey - dy * ex) / (rate * rate * rate) : 0.0;
			if (!path.empty()) s += distance(path.back().x, path.back().y, px, py);
			path.push_back({s, px, py, h, bend});
			previous = h;
		}
	}
	return profile(path, forwards, speed, limits, dt);
}

/** Where a plan has the robot `time` seconds in: between the states either side, or the first
 * or last. */
inline State sample(const Trajectory& plan, double time) {
	if (plan.empty()) return State{};
	if (time <= plan.front().t) return plan.front();
	if (time >= plan.back().t) return plan.back();
	std::size_t i = std::upper_bound(plan.begin(), plan.end(), time,
	                                 [](double t, const State& s) { return t < s.t; }) -
	                plan.begin();
	const State &p = plan[i - 1], &q = plan[i];
	double f = q.t > p.t ? (time - p.t) / (q.t - p.t) : 0.0;
	State s;
	s.t = time;
	s.s = p.s + f * (q.s - p.s);
	s.x = p.x + f * (q.x - p.x);
	s.y = p.y + f * (q.y - p.y);
	s.heading = p.heading + f * (q.heading - p.heading);
	s.v = p.v + f * (q.v - p.v);
	s.omega = p.omega + f * (q.omega - p.omega);
	s.a = p.a + f * (q.a - p.a);
	s.alpha = p.alpha + f * (q.alpha - p.alpha);
	return s;
}

}  // namespace vexsim
