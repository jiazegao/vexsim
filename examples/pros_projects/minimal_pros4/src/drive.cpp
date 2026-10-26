#include "drive.hpp"

#include <algorithm>
#include <cmath>

#if __has_include("vexsim/sim.hpp")
#include "vexsim/sim.hpp"
#endif

pros::MotorGroup left_drive({1, 2, 3}, pros::MotorGearset::blue);
pros::MotorGroup right_drive({-4, -5, -6}, pros::MotorGearset::blue);
pros::Imu imu(10);
pros::Rotation vertical_tracker(11);
pros::Rotation horizontal_tracker(12);

namespace {
constexpr double kTrackerDiameter = 2.0;     // in
constexpr double kVerticalOffset = -1.5;     // in: the vertical wheel sits 1.5 in right of center
constexpr double kHorizontalOffset = -3.0;   // in: the horizontal wheel sits 3 in behind center

pros::Mutex pose_mutex;
Pose pose;
double theta_offset = 0;  // pose.theta minus the IMU's rotation, degrees

double tracker_inches(pros::Rotation& tracker) {
	return tracker.get_position() / 36000.0 * M_PI * kTrackerDiameter;
}

// Odometry from two tracking wheels and the IMU, every 10 ms. The horizontal
// wheel counts up when the robot slides left.
void odometry_task() {
	double last_v = tracker_inches(vertical_tracker);
	double last_h = tracker_inches(horizontal_tracker);
	double last_rotation = imu.get_rotation();
	uint32_t now = pros::millis();
	while (true) {
		double v = tracker_inches(vertical_tracker), h = tracker_inches(horizontal_tracker);
		double rotation = imu.get_rotation();
		double dv = v - last_v, dh = h - last_h;
		double dtheta = (rotation - last_rotation) * M_PI / 180.0;  // clockwise
		last_v = v, last_h = h, last_rotation = rotation;

		// Travel of the robot's center: remove what turning in place adds at each wheel.
		double forward = dv - dtheta * kVerticalOffset;
		double right = -(dh + dtheta * kHorizontalOffset);
		pose_mutex.take();
		double heading = (rotation + theta_offset) * M_PI / 180.0;
		double mid = heading - dtheta / 2.0;
		pose.x += forward * std::sin(mid) + right * std::cos(mid);
		pose.y += forward * std::cos(mid) - right * std::sin(mid);
		pose.theta = rotation + theta_offset;
		Pose snapshot = pose;
		pose_mutex.give();
#ifdef VEXSIM
		vexsim::report_pose(snapshot.x, snapshot.y, snapshot.theta);
#endif
		pros::Task::delay_until(&now, 10);
	}
}
}  // namespace

Pose get_pose() {
	pose_mutex.take();
	Pose copy = pose;
	pose_mutex.give();
	return copy;
}

void set_pose(Pose p) {
	pose_mutex.take();
	pose = p;
	theta_offset = p.theta - imu.get_rotation();
	pose_mutex.give();
}

void start_odometry() {
	static pros::Task task(odometry_task, "odometry");
}

void drive_distance(double inches, int max_rpm) {
	Pose start = get_pose();
	double heading = start.theta;
	double traveled = 0;
	while (std::abs(inches - traveled) > 0.5) {
		Pose now = get_pose();
		traveled = std::hypot(now.x - start.x, now.y - start.y) * (inches < 0 ? -1 : 1);
		double error = inches - traveled;
		double speed = std::clamp(error * 25.0, -double(max_rpm), double(max_rpm));
		double correction = (heading - now.theta) * 4.0;
		left_drive.move_velocity(static_cast<int>(speed + correction));
		right_drive.move_velocity(static_cast<int>(speed - correction));
		pros::delay(10);
	}
	left_drive.brake();
	right_drive.brake();
}

void turn_to(double theta_deg) {
	uint32_t settled = 0;
	while (settled < 100) {
		double error = theta_deg - get_pose().theta;
		double volts = std::clamp(error * 300.0, -9000.0, 9000.0);
		if (std::abs(error) > 1.0) volts += error > 0 ? 1200.0 : -1200.0;
		left_drive.move_voltage(static_cast<int>(volts));
		right_drive.move_voltage(static_cast<int>(-volts));
		settled = std::abs(error) < 1.5 ? settled + 10 : 0;
		pros::delay(10);
	}
	left_drive.brake();
	right_drive.brake();
}
