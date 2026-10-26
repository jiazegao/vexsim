#pragma once
#include "main.h"

// Drivetrain of the example robot (examples/robots/full_omni_6m.yaml):
// 6 blue motors, 36:48 to 3.25 in omni wheels, right side mounted reversed.
extern pros::MotorGroup left_drive;
extern pros::MotorGroup right_drive;
extern pros::Imu imu;
extern pros::Rotation vertical_tracker;
extern pros::Rotation horizontal_tracker;

struct Pose {
	double x = 0, y = 0, theta = 0;  // inches; degrees, clockwise from +y (LemLib convention)
};

Pose get_pose();
void set_pose(Pose pose);
void start_odometry();
void drive_distance(double inches, int max_rpm);
void turn_to(double theta_deg);
