#include "custom/lift_control.hpp"
#include "custom/configs.hpp"
#include <atomic>
#include <queue>
#include "custom/util_funcs.hpp"
#include "pros/abstract_motor.hpp"
#include "pros/adi.h"
#include "pros/misc.h"
#include "string"


// BASIC MOTOR FUNCTIONS
void startFrontIntake(int velocity) {
    frontIntakeMotor.move(velocity);
}
void reverseFrontIntake(int velocity) {
    frontIntakeMotor.move(-velocity);
}
void stopFrontIntake() {
    frontIntakeMotor.move(0);
}

void startEffectorIntake(int velocity) {
    effectorIntakeMotor.move_velocity(velocity);
}
void reverseEffectorIntake(int velocity) {
    effectorIntakeMotor.move_velocity(-velocity);
}
void stopEffectorIntake() {
    effectorIntakeMotor.move(0);
}

void raiseLift(int velocity) {
    liftMotors.move(velocity);
}
void lowerLift(int velocity) {
    liftMotors.move(-velocity);
}
void stopLift() {
    liftMotors.move(0);
}

void raiseEffector(int velocity) {
    effectorRotateMotor.move(velocity);
}
void lowerEffector(int velocity) {
    effectorRotateMotor.move(-velocity);
}
void stopEffector() {
    effectorRotateMotor.move(0);
}

pros::Task* effectorPIDTask = nullptr;
float effectorTargetDeg = 0.0;
constexpr float EFFECTOR_GEAR_RATIO = 4.0;  // Deg motor / Deg end effector
bool hardResettingEffector = false;
void initEffectorPID() {
    effectorPIDTask = new pros::Task ([](){
        while (true) {
            if (!hardResettingEffector) {
                float output = effectorPID.update(effectorTargetDeg*EFFECTOR_GEAR_RATIO - effectorRotateMotor.get_position());
                effectorRotateMotor.move(output);
            }
            pros::delay(20);
        }
    });
}

void hardResetEffector() {
    pros::Task([](){
        hardResettingEffector = true;
        pros::delay(200);
        effectorRotateMotor.move(-127);
        pros::delay(1000);
        effectorRotateMotor.set_zero_position(0.0);
        hardResettingEffector = false;
        effectorTargetDeg = 0.0;
        effectorRotateMotor.move(0);
    });
}

void setEffector(EFFECTOR_STAGES newTargetEnum) {
    if (!hardResettingEffector) effectorTargetDeg = EFFECTOR_ANGLES[newTargetEnum];
}

void setEffector(float newTargetDeg) {
    if (!hardResettingEffector) effectorTargetDeg = newTargetDeg;
}

void resetEffector() {
    if (!hardResettingEffector) effectorTargetDeg = 0.0;
}

pros::Task* liftMacroTask = nullptr;
float liftTargetHeight = 0.0;
constexpr float LIFT_GEAR_RATIO = 120.0;  // Deg / Inch height
void initLiftPID() {
    liftMacroTask = new pros::Task ([](){
        while (true) {
            if (enableLiftPID) {
                float output = liftPID.update(std::fmax(-60.0, liftTargetHeight*LIFT_GEAR_RATIO - liftMotors.get_position_all()[0]));
                liftMotors.move(output);
            }
            pros::delay(20);
        }
    });
}

void setLift(LIFT_STAGES newTargetEnum) {
    liftTargetHeight = LIFT_HEIGHTS[newTargetEnum];
}

void setLift(float newTargetInch) {
    liftTargetHeight = newTargetInch;
}

void resetLift() {
    liftTargetHeight = 0.0;
}

pros::Task L1Macro([](){});
bool effectorIntakeOccupied = false;
void updateLiftMotors() {
    // L1 Macro - Outtake end effector for 500ms, then lift up end effector
    if (controller.get_digital_new_press(pros::E_CONTROLLER_DIGITAL_L1)) {
        effectorIntakeOccupied = true;
        L1Macro = pros::Task([](){
            reverseEffectorIntake();
            pros::delay(300);
            setEffector(HIGH_ANGLE);
            effectorIntakeOccupied = false;
        });
    }

    // R1 Macro - Prime end effector (horizontal), then lift on hold
    if (controller.get_digital(pros::E_CONTROLLER_DIGITAL_R1)) {
        enableLiftPID = false;
        setEffector(RIGHT_ANGLE);
        effectorIntakeMotor.move(50);
        if (effectorRotateMotor.get_position() > 320.0) raiseLift();
        if (liftMotors.get_position() > 3300.0) setEffector(TOGGLE_ANGLE);
    }
    // R2 Macro - Lower lift on hold
    else if (controller.get_digital(pros::E_CONTROLLER_DIGITAL_R2)) {
        enableLiftPID = false;
        effectorIntakeMotor.move(50);
        lowerLift();
        if (liftMotors.get_position() < 3300.0) setEffector(RIGHT_ANGLE);
    }
    else {
        enableLiftPID = true;
    }

    // Use PID to maintain height
    if (controller.get_digital_new_release(pros::E_CONTROLLER_DIGITAL_R1) || controller.get_digital_new_release(pros::E_CONTROLLER_DIGITAL_R2)) {
        setLift(liftMotors.get_position()/LIFT_GEAR_RATIO);
    }

    // L2 Macro - Reset lift & end effector, then intake and spin end effector
    if (controller.get_digital(pros::E_CONTROLLER_DIGITAL_L2)) {
        enableLiftPID = true;
        startFrontIntake();
        startEffectorIntake();
        resetLift();
        resetEffector();
    }
    // B Macro - Outtake both front intake and end effector
    else if (controller.get_digital(pros::E_CONTROLLER_DIGITAL_B)) {
        reverseFrontIntake();
        reverseEffectorIntake();
    }
    // Down Macro - Toggle using end effector
    else if (controller.get_digital(pros::E_CONTROLLER_DIGITAL_DOWN)) {
        setEffector(TOGGLE_ANGLE);
        stopFrontIntake();
        reverseEffectorIntake();
    }
    else {
        stopFrontIntake();
        if (!effectorIntakeOccupied && !controller.get_digital(pros::E_CONTROLLER_DIGITAL_R1)) stopEffectorIntake();

        // Y only changes the angle when no existing mechanism macro owns it.
        if (controller.get_digital(pros::E_CONTROLLER_DIGITAL_Y) &&
            !effectorIntakeOccupied &&
            !controller.get_digital(pros::E_CONTROLLER_DIGITAL_L1) &&
            !controller.get_digital(pros::E_CONTROLLER_DIGITAL_R1) &&
            !controller.get_digital(pros::E_CONTROLLER_DIGITAL_R2)) {
            setEffector(PIN_ANGLE);
        }
    }

}

void effectorToggle() {
    pros::Task([](){
        reverseEffectorIntake();
        pros::delay(800);
        stopEffectorIntake();
    });
}

// Lift end effector and lift before calling this
void scoreCup(float dropHeight, float raiseHeight) {
    pros::Task([dropHeight, raiseHeight](){
        setLift(dropHeight);
        while (liftMotors.get_position() > dropHeight*LIFT_GEAR_RATIO+100) {pros::delay(20);}
        reverseEffectorIntake();
        pros::delay(100);
        setLift(raiseHeight);
    });
}

// Set effector to right angle before calling this
void scorePin() {
    pros::Task([](){
        reverseEffectorIntake();
        pros::delay(400);
        stopEffectorIntake();
    });
}
