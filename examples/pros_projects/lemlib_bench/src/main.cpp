// LemLib motions as benchmark controllers: `vexsim bench` passes each trial's task
// (vexsim::benchmark_task()) and this autonomous runs it with LemLib. Configured for
// examples/robots/full_omni_6m.yaml, starting from LemLib's example gains.

#include "main.h"

#include "lemlib/api.hpp"
#include "vexsim/sim.hpp"

pros::MotorGroup leftMotors({1, 2, 3}, pros::MotorGearset::blue);
pros::MotorGroup rightMotors({-4, -5, -6}, pros::MotorGearset::blue);
pros::Imu imu(10);
pros::Rotation verticalEnc(11);
pros::Rotation horizontalEnc(12);
// 2 in wheels: vertical 1.5 in right of center (+), horizontal 3 in behind it (-)
lemlib::TrackingWheel vertical(&verticalEnc, 2.0, 1.5);
lemlib::TrackingWheel horizontal(&horizontalEnc, 2.0, -3.0);

lemlib::Drivetrain drivetrain(&leftMotors, &rightMotors,
                              12,  // track width, in
                              lemlib::Omniwheel::NEW_325,
                              450,  // rpm: blue cartridge, 36:48
                              2);   // horizontal drift (omni wheels)

lemlib::ControllerSettings linearController(10, 0, 3, 3, 1, 100, 3, 500, 20);
lemlib::ControllerSettings angularController(2, 0, 10, 3, 1, 100, 3, 500, 0);
lemlib::OdomSensors sensors(&vertical, nullptr, &horizontal, nullptr, &imu);
lemlib::Chassis chassis(drivetrain, linearController, angularController, sensors);

void initialize() { chassis.calibrate(); }

void disabled() {}

void competition_initialize() {}

void autonomous() {
	vexsim::Task& task = vexsim::benchmark_task();
	if (!task) return;
	chassis.setPose(task.start_x, task.start_y, task.start_theta);
	int timeout = task.timeout_ms;
	float max_speed = task.option("max_speed", 127);
	if (task.type == "move_to_point") {
		chassis.moveToPoint(task.x, task.y, timeout, {.forwards = task.forwards, .maxSpeed = max_speed});
	} else if (task.type == "move_to_pose") {
		chassis.moveToPose(task.x, task.y, task.theta, timeout,
		                   {.lead = static_cast<float>(task.option("lead", 0.6)), .maxSpeed = max_speed});
	} else if (task.type == "turn_to_heading") {
		chassis.turnToHeading(task.theta, timeout, {.maxSpeed = static_cast<int>(max_speed)});
	} else if (task.type == "drive") {
		lemlib::Pose start = chassis.getPose(true);
		chassis.moveToPoint(start.x + task.distance * std::sin(start.theta),
		                    start.y + task.distance * std::cos(start.theta), timeout,
		                    {.forwards = task.distance >= 0, .maxSpeed = max_speed});
	} else if (task.type == "follow") {
		static asset path{reinterpret_cast<uint8_t*>(task.path.data()), task.path.size()};
		chassis.follow(path, task.option("lookahead", 15), timeout);
	}
	chassis.waitUntilDone();
}

void opcontrol() {}
