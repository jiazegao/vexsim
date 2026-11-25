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
    frontIntakeMotor.brake();
}

void startClawIntake(int velocity_rpm) {
    clawIntakeMotor.move_velocity(velocity_rpm);
}
void reverseClawIntake(int velocity_rpm) {
    clawIntakeMotor.move_velocity(-velocity_rpm);
}
void stopClawIntake() {
    clawIntakeMotor.brake();
}

void openClaw(float angle, int velocity) {
    if (!clawHomed) return;
    clawGrippersMotor.move_absolute(angle, velocity);
}
void closeClaw(int velocity) {
    if (!clawHomed) return;
    clawGrippersMotor.move_absolute(0, velocity);
}
void stopClaw() {
    if (!clawHomed) return;
    clawGrippersMotor.brake();
}

void raiseLift(int velocity) {
    // hardstop: at/above max height, hold instead of driving up
    if (liftMotors.get_position_all()[0] >= LIFT_MAX_MOTOR_DEG) liftMotors.brake();
    else liftMotors.move(velocity);
}
void lowerLift(int velocity) {
    liftMotors.move(-velocity);
}
void stopLift() {
    liftMotors.brake();
}

bool bothLiftMotorsInstalled() {
    return liftMotor19.is_installed() && liftMotor20.is_installed();
}

pros::Task* liftMacroTask = nullptr;
float liftTargetHeight = 0.0;
std::atomic<bool> liftResetting{false};  // true while lift drives to bottom
std::atomic<bool> liftResetAbort{false}; // set by driver (R1/R2) to cancel a reset
constexpr float LIFT_GEAR_RATIO = 84.0 / 12.0;  // 12:84 gearing -> 7 motor deg per lift-arm deg
void initLiftPID() {
    liftMacroTask = new pros::Task ([](){
        bool wasEnabled = false;
        while (true) {
            bool active = enableLiftPID && !liftResetting;
            if (active) {
                float error = std::fmax(-60.0, liftTargetHeight*LIFT_GEAR_RATIO - liftMotors.get_position_all()[0]);
                if (!wasEnabled) {            // just took over: clear integral, no derivative kick
                    liftPID.reset();
                    liftPID.prevError = error;
                }
                float output = liftPID.update(error);
                // hardstop: never push up past max height
                if (output > 0 && liftMotors.get_position_all()[0] >= LIFT_MAX_MOTOR_DEG) output = 0;
                if (std::fabs(output) > 1.0f) liftMotors.move(output);
                else liftMotors.brake();
            }
            wasEnabled = active;
            pros::delay(20);
        }
    });
}

static float clampLiftTarget(float t) {
    return std::fmin(t, LIFT_MAX_MOTOR_DEG / LIFT_GEAR_RATIO);  // hardstop
}

void setLift(LIFT_STAGES newTargetEnum) {
    liftTargetHeight = clampLiftTarget(LIFT_HEIGHTS[newTargetEnum]);
}

void setLift(float newTargetInch) {
    liftTargetHeight = clampLiftTarget(newTargetInch);
}

pros::Task liftResetTask([](){});
void resetLift() {
    liftTargetHeight = 0.0;
    if (liftResetting) return;  // already going down, don't start again
    liftResetAbort = false;
    liftResetting = true;
    liftResetTask = pros::Task([](){
        liftMotors.move(-127);  // full speed down
        uint32_t start = pros::millis();
        // drive down until lift stalls on bottom, 1.5 s pass, or driver cancels.
        // First 200 ms skip the stall check so the lift can start moving.
        while (!liftResetAbort && pros::millis() - start < 1500 &&
               (pros::millis() - start < 200 ||
                std::fabs(liftMotors.get_actual_velocity()) > 5)) {
            pros::delay(20);
        }
        if (!liftResetAbort) {
            liftMotors.brake();
            liftMotors.tare_position_all();  // bottom = 0 (only if we actually reached it)
        }
        liftResetting = false;
    });
}

bool isLiftResetting() { return liftResetting; }
pros::Task clawResetTask([](){});
void hardResetClaw() {
    clawHomed = false;
    clawResetTask = pros::Task([](){
        clawGrippersMotor.move(-127);
        pros::delay(500);
        clawGrippersMotor.brake();
        clawGrippersMotor.set_zero_position(0.0);
        clawHomed = true;
    });
}

float passive_height = 0.0;
bool liftOnPID = false;

void updateLiftMotors() {

    // EMERGENCY: UP + X together -> hard reset claw and lift to the bottom.
    // Fires once per press (holding it won't restart the reset over and over).
    static bool prevShift = false;
    bool shift = controller.get_digital(pros::E_CONTROLLER_DIGITAL_UP) &&
                 controller.get_digital(pros::E_CONTROLLER_DIGITAL_X);
    if (shift && !prevShift) {
        stopClawIntake();
        stopFrontIntake();
        hardResetClaw();
        liftOnPID = true;   // hold lift at bottom (0) after reset finishes
        resetLift();
    }
    prevShift = shift;
    if (shift) return;  // ignore other buttons while the combo is held

    // DOWN lift at set "passive" toggle height
    if (controller.get_digital(pros::E_CONTROLLER_DIGITAL_DOWN)) {
        liftOnPID = true;
        setLift(passive_height);
    }
    //L2 reset lift spin intake, spin claw roller intake,
    // rotate grippers to grab position, keep claw rollers intaking at 50 rpm until L1,
    // or B are pressed
    static bool prevL2Reset = false;
    bool l2Held = controller.get_digital(pros::E_CONTROLLER_DIGITAL_L2);
    if (l2Held && !prevL2Reset) {   // only reset once per press, not every tick
        liftOnPID = true;
        resetLift();
    }
    prevL2Reset = l2Held;

    if (l2Held) {
        closeClaw();
        startFrontIntake(127);
        startClawIntake(127);
    }
    /*L1 open grippers to open position, outtake claw roller at full speed*/
    else if (controller.get_digital(pros::E_CONTROLLER_DIGITAL_L1)) {
        reverseClawIntake();
        openClaw();
    }
    // B outtake claw roller, reverse/outtake ground intake
    else if (controller.get_digital(pros::E_CONTROLLER_DIGITAL_B)) {
        stopClawIntake();
        openClaw();
        reverseFrontIntake();
    }
    /*RIGHT open claw, spin front intake, claw rollers intake at 50 rpm
    (rollers keep intaking after release until L1 or B are pressed)*/
    else if (controller.get_digital(pros::E_CONTROLLER_DIGITAL_RIGHT)) {
        openClaw();
        startFrontIntake();
        startClawIntake(50);
    }
    else {
        stopFrontIntake();
    }

    // Y open claw
    if (controller.get_digital(pros::E_CONTROLLER_DIGITAL_Y)) {
        openClaw(200);
        
    }

    // L2 let go -> claw rollers back to 50 rpm intake
    static bool prevL2 = false;
    bool l2 = controller.get_digital(pros::E_CONTROLLER_DIGITAL_L2);
    bool b  = controller.get_digital(pros::E_CONTROLLER_DIGITAL_B);
    if (prevL2 && !l2 && !b) startClawIntake(50);
    prevL2 = l2;

    bool r1 = controller.get_digital(pros::E_CONTROLLER_DIGITAL_R1);
    bool r2 = controller.get_digital(pros::E_CONTROLLER_DIGITAL_R2);

    // Driver can interrupt a reset instantly with R1/R2
    if (liftResetting) {
        if (r1 || r2) liftResetAbort = true;
        else return;  // reset task owns the lift right now
    }

    if (r1 || r2) liftOnPID = false;
    enableLiftPID = liftOnPID;
    if (r2) lowerLift(bothLiftMotorsInstalled() ? 76 : 127);
    else if (r1) raiseLift();
    else if (!liftOnPID) stopLift();
}
