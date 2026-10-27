#include "main.h"
#include "custom/RclTracking.hpp"
#include "custom/Tracking_Util.hpp"
#include "custom/configs.hpp"
#include "custom/auton.hpp"

#include "custom/util_funcs.hpp"
#include "custom/auton_selector.hpp" // IWYU pragma: keep
#include "liblvgl/llemu.hpp"
#include "pros/abstract_motor.hpp"
#include "pros/misc.h"
#include "pros/motors.h"
#include "pros/motors.h"

#include "custom/lift_control.hpp"
#include <cstdlib>  // vexsim
#include <string>  // vexsim

void initialize() {
	// pros::lcd::initialize();
    chassis.calibrate();
    chassis.setPose(0, 0, 0);

	init_auton_selector();
	initControllerDisplay();
	initLog();	// Critical; DO NOT REMOVE
	initEffectorPID();
	initLiftPID();
	//initBrainDisplay();

	effectorRotateMotor.set_encoder_units(pros::MotorEncoderUnits::degrees);
	liftMotors.set_brake_mode(pros::E_MOTOR_BRAKE_HOLD);
	liftMotors.set_encoder_units(pros::MotorEncoderUnits::degrees);
	liftMotors.set_zero_position(0.0);
}

void disabled() {}

void competition_initialize() {}

void autonomous() {
	enableLiftPID = true;
	chassis.setBrakeMode(pros::E_MOTOR_BRAKE_HOLD);
	
	hardResetEffector();
	// left30();
	runAuton();
	
}

void opcontrol() {

	chassis.setBrakeMode(pros::E_MOTOR_BRAKE_COAST);
#ifdef VEXSIM
	// vexsim: VEXSIM_BRAKE=hold makes a replayed autonomous path stop as autonomous does
	if (const char* brake = std::getenv("VEXSIM_BRAKE")) {
		if (std::string(brake) == "hold") chassis.setBrakeMode(pros::E_MOTOR_BRAKE_HOLD);
		if (std::string(brake) == "brake") chassis.setBrakeMode(pros::E_MOTOR_BRAKE_BRAKE);
	}
#endif
	enableLiftPID = false;
	startBrainFBDisplay();

	while (true) {

		updateTankDrive();
		updateLiftMotors();

		pros::delay(20);
	}
}