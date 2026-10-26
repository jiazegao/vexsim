#include "main.h"

#include "vexsim_calibration.hpp"

/**
 * The calibration routine for examples/robots/full_omni_6m.yaml. For your robot, run
 *   vexsim calibration-routine YOUR_ROBOT.yaml YOUR_PROS_PROJECT
 * and call vexsim_calibration::run() the same way.
 *
 * On the robot: run autonomous with the robot in the middle of a field (or 3 x 3 m of open
 * floor), facing the longer free direction. The log goes to /usd/vexsim_log.csv on the SD card,
 * or to the terminal (pros terminal) without a card. Then: vexsim calibrate ROBOT.yaml LOG
 *
 * In vexsim: vexsim run examples/robots/full_omni_6m.yaml --program
 *   examples/pros_projects/calibration --headless > run.txt, then vexsim calibrate on run.txt.
 */
void initialize() {}

void disabled() {}

void competition_initialize() {}

void autonomous() { vexsim_calibration::run(); }

/**
 * Press A to run the routine without a competition switch.
 */
void opcontrol() {
	pros::Controller master(pros::E_CONTROLLER_MASTER);
	while (true) {
		if (master.get_digital_new_press(DIGITAL_A)) vexsim_calibration::run();
		pros::delay(20);
	}
}
