#include "main.h"

#include "drive.hpp"

/**
 * Runs initialization code. This occurs as soon as the program is started.
 */
void initialize() {
	pros::lcd::initialize();
	pros::lcd::set_text(1, "minimal_pros4");

	imu.reset(true);  // blocks for ~2 s while the IMU calibrates; keep the robot still
	left_drive.set_brake_mode_all(pros::MotorBrake::brake);
	right_drive.set_brake_mode_all(pros::MotorBrake::brake);
	start_odometry();
	printf("initialized at %u ms, battery %d mV\n", (unsigned)pros::millis(), pros::battery::get_voltage());
}

void disabled() {}

void competition_initialize() {}

/**
 * Drives a square: forward 24 in, turn right 90 degrees, four times.
 */
void autonomous() {
	set_pose({0, 0, 0});
	for (int side = 0; side < 4; side++) {
		drive_distance(24, 400);
		turn_to(90.0 * (side + 1));
	}
	Pose end = get_pose();
	std::cout << "autonomous done at " << pros::millis() << " ms: x " << end.x << " y " << end.y << " theta "
	          << end.theta << std::endl;
}

/**
 * Arcade drive: left stick forward/back, right stick turns.
 */
void opcontrol() {
	pros::Controller master(pros::E_CONTROLLER_MASTER);
	while (true) {
		int dir = master.get_analog(ANALOG_LEFT_Y);
		int turn = master.get_analog(ANALOG_RIGHT_X);
		left_drive.move(dir + turn);
		right_drive.move(dir - turn);

		Pose pose = get_pose();
		pros::lcd::print(2, "x %.1f y %.1f theta %.1f", pose.x, pose.y, pose.theta);
		if (master.get_digital_new_press(DIGITAL_A)) autonomous();
		pros::delay(20);
	}
}
