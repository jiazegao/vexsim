#include "custom/auton.hpp"
#include "custom/MclTracking.hpp"
#include "custom/RclTracking.hpp"
#include "custom/configs.hpp"
#include "custom/util_funcs.hpp"
#include "custom/lift_control.hpp"
#include "lemlib/chassis/chassis.hpp"
#include "lemlib/pose.hpp"
#include "pros/motors.h"
#include "pros/rtos.h"
#include "pros/rtos.hpp"
#include <cmath>

void testPid(){
    chassis.setPose(0, 0, 0);
    moveForward(24, 1500, 127, 1, false);
    chassis.turnToHeading(90, 1500, {}, false);
    moveForward(-24, 1500, 127, 1, false);
    chassis.turnToHeading(270, 1500, {}, false);
}
void toggle() {
    moveForward(15, 400, 127, 100, true);
    moveForward(-5, 300, 127, 60, true);
}

void left3pin(){
    chassis.setBrakeMode(pros::E_MOTOR_BRAKE_HOLD);
    chassis.setPose(57, 0, 90);
    closeClaw();
    pros::delay(200);
    MclMain.setObstacles(&leftAutonObstacles, nullptr);
    startMcl(57, 0, 90, false, false, false, false);
    
    enableLiftPID = true;     // lift PID holds the target height
    resetLift();             // drive to bottom + zero encoder; PID waits until it's done
    setLift(LIFT_HEIGHTS[THIRD_STACK] + 200.0f/7); // THIRD_STACK + 200 motor deg
    startClawIntake(80);  // start intaking the pin
    pros::delay(1500);
    //Move to alliance goal and pin drop
    chassis.moveToPoint(47.0, 0, 2000, { .forwards = false, .maxSpeed = 100,}, true);
    setLift(LIFT_HEIGHTS[FIRST_STACK]+3.0f); 
    chassis.turnToPoint(47.0, 22, 500, {.forwards = false}, true);
    chassis.moveToPoint(47.0, 22, 2000, {.forwards = false, .maxSpeed = 50}, true);
    //Drop pin and back up
    pros::delay(800);
    setLift(LIFT_HEIGHTS[IDLE_HEIGHT]);  // drop pin
    pros::delay(500);
    openClaw(-150, 127);  // open wider for the drop
    reverseClawIntake(50);
    pros::delay(1000);
    //back up
    chassis.moveToPoint(44, 10, 1000, { .maxSpeed = 100}, true);
    //get cup and score
    chassis.turnToPoint(23.5, 23.5, 500, {.forwards = false}, true);
    hardResetClaw();
    pros::delay(500);
    chassis.moveToPoint(23.5, 23.5, 1900, { .forwards = false, .maxSpeed = 40,});
    startClawIntake(127);
    pros::delay(300);
    openClaw(150, 127);
    pros::delay(1200);
    closeClaw(127);
    pros::delay(600);
    //score
    setLift(SECOND_STACK);
    chassis.turnToPoint(47, 23.5, 600, {.forwards = false}, true);
    chassis.moveToPoint(47, 23.5, 1700, { .forwards = false, .maxSpeed = 70,}, false);
    pros::delay(200);
    setLift(LIFT_HEIGHTS[IDLE_HEIGHT]);
    pros::delay(1200);
    openClaw(150, 127);
    pros::delay(800);

    moveForward(10, 700, 127, 1, false);
    chassis.turnToHeading(205, 500, {}, false);
    moveForward(-15, 1500);
}

void left3pinv2(){
    chassis.setBrakeMode(pros::E_MOTOR_BRAKE_HOLD);
    chassis.setPose(57, 0, 90);
    closeClaw();
    pros::delay(200);
    MclMain.setObstacles(&leftAutonObstacles, nullptr);
    startMcl(57, 0, 90, false, false, false, false);
    
    enableLiftPID = true;     // lift PID holds the target height
    resetLift();             // drive to bottom + zero encoder; PID waits until it's done
    setLift(LIFT_HEIGHTS[THIRD_STACK] + 200.0f/7); // THIRD_STACK + 200 motor deg
    startClawIntake(80);  // start intaking the pin
    pros::delay(1200);
    //Move to alliance goal and pin drop
    chassis.moveToPoint(39.5, 0, 1000, { .forwards = false, .maxSpeed = 100,}, true);
    setLift(LIFT_HEIGHTS[FIRST_STACK]+3.0f); 
    chassis.turnToPoint(39.5, 22, 500, {.forwards = false}, true);
    chassis.moveToPoint(39.5, 22, 1600, {.forwards = false, .maxSpeed = 50}, true);
    //Drop pin and back up
    pros::delay(1000);
    setLift(LIFT_HEIGHTS[IDLE_HEIGHT]);  // drop pin
    pros::delay(500);
    openClaw(-150, 127);  // open wider for the drop
    reverseClawIntake(50);
    pros::delay(800);
    //back up
    chassis.moveToPoint(44, 10, 1000, { .maxSpeed = 100}, true);
    //get cup and score
    chassis.turnToPoint(19, 23, 500, {.forwards = false}, true);
    hardResetClaw();
    pros::delay(500);
    openClaw(150, 127);
    chassis.moveToPoint(19, 23, 1900, { .forwards = false, .maxSpeed = 40,});
    startClawIntake(127);
    pros::delay(1200);
    closeClaw(127);
    pros::delay(600);
    //score
    setLift(SECOND_STACK);
    chassis.turnToPoint(44, 34, 600, {.forwards = false}, true);
    chassis.moveToPoint(44, 34, 1700, { .forwards = false, .maxSpeed = 70,}, false);
    pros::delay(200);
    setLift(LIFT_HEIGHTS[IDLE_HEIGHT]);
    pros::delay(1200);
    openClaw(150, 127);
    pros::delay(800);
    MclMain.setDistSyncProp(0.0f);

    moveForward(15, 700, 127, 1, false);
    chassis.turnToHeading(205, 500, {}, false);
    chassis.turnToPoint(47, 47, 500, {.forwards = false}, true);
    hardResetClaw();
    pros::delay(500);
    openClaw(150, 127);
    chassis.moveToPoint(47, 47, 1900, { .forwards = false, .maxSpeed = 40,});
    startClawIntake(127);
    pros::delay(1200);
    closeClaw(127);
    pros::delay(600);
    
    setLift(THIRD_STACK);
    chassis.turnToPoint(44, 34, 600, {.forwards = false}, true);
    chassis.moveToPoint(44, 34, 1700, { .forwards = false, .maxSpeed = 70,}, false);
    pros::delay(200);
    setLift(LIFT_HEIGHTS[IDLE_HEIGHT]);
    pros::delay(1200);
    openClaw(150, 127);
    pros::delay(800);

}

void left5pin() {
    // Initialize
    chassis.setBrakeMode(pros::E_MOTOR_BRAKE_HOLD);
    chassis.setPose(57, 6.75, 90);
    closeClaw();
    MclMain.setObstacles(&leftAutonObstacles, nullptr);
    startMcl(57, 6.75, 90, true, false, false, false);
    
    // Toggle
    enableLiftPID = true;     // lift PID holds the target height
    setLift(LIFT_HEIGHTS[THIRD_STACK] + 140.0f/7); // THIRD_STACK + 200 motor deg
    startClawIntake(80);  // start intaking the pin
    pros::delay(700);

    // Score first pin
    chassis.moveToPoint(43, 23.5, 1000, {.forwards = false, .maxSpeed = 70, .minSpeed = 40}, true);
    pros::delay(200);
    setLift(LIFT_HEIGHTS[IDLE_HEIGHT]);  // drop pin
    pros::delay(1000);
    openClaw(150, 127);
    reverseClawIntake(50);
    pros::delay(100);

    // Back up then grab second pin
    chassis.moveToPoint(40, 12, 900, {}, true);
    chassis.turnToPoint(23.5, 23.5, 500, {.forwards = false}, true);
    hardResetClaw();
    chassis.moveToPoint(23.5, 23.5, 1000, {.forwards = false, .maxSpeed = 40}, true);
    startClawIntake(127);
    pros::delay(300);
    openClaw(150, 127);
    pros::delay(500);
    closeClaw(100);
    pros::delay(200);

    // Score second pin
    MclMain.setPinAndCupVisibility(3, false);
    setLift(LIFT_HEIGHTS[SECOND_STACK]);
    chassis.turnToHeading(250, 400, {}, true);
    chassis.moveToPoint(47, 24, 1100, {.forwards = false, .maxSpeed = 60}, true);
    pros::delay(700);
    setLift(LIFT_HEIGHTS[IDLE_HEIGHT]);
    pros::delay(500);
    openClaw(150, 127);
    reverseClawIntake(50);

    // Grab third pin
    chassis.moveToPoint(38, 38, 1100, {}, true);
    chassis.turnToPoint(47.5, 47.5, 500, {.forwards=false}, true);
    chassis.moveToPoint(47.5, 47.5, 700, {.forwards = false, .maxSpeed = 40}, true);
    startClawIntake(127);
    pros::delay(500);
    closeClaw(100);
    pros::delay(200);

    // Score third pin
    MclMain.setPinAndCupVisibility(2, false);
    setLift(LIFT_HEIGHTS[THIRD_STACK]);
    chassis.turnToHeading(345, 500, {}, true);
    chassis.moveToPoint(49, 23.5, 1100, {.forwards = false, .maxSpeed = 60}, true);
    pros::delay(700);
    setLift(LIFT_HEIGHTS[FIRST_STACK]);
    pros::delay(600);
    openClaw(150, 127);
    reverseClawIntake(50);

    // Grab fourth pin
    MclMain.setDistSyncProp(0.00f);
    chassis.moveToPoint(56, 34, 1000, {}, false);
    setLift(LIFT_HEIGHTS[IDLE_HEIGHT]);
    chassis.turnToHeading(309, 700, {}, false);
    MclMain.setDistSyncProp(0.02f);
    leftMotors.move(-40);
    rightMotors.move(-40);
    closeClaw(127);
    startClawIntake(127);
    pros::delay(650);
    chassis.swingToHeading(280, lemlib::DriveSide::RIGHT, 500, {}, true);
    openClaw(100, 127);
    pros::delay(400);
    closeClaw(127);
    pros::delay(200);

    // Score fourth pin
    chassis.turnToHeading(20, 300, {}, true);
    chassis.moveToPoint(47.5, -23.5, 1000, {.forwards = false}, true);
    pros::delay(200);
    setLift(LIFT_HEIGHTS[SECOND_STACK]);
    chassis.moveToPoint(47.5, -23.5, 1200, {.forwards = false, .maxSpeed = 50}, true);
    pros::delay(200);
    setLift(LIFT_HEIGHTS[IDLE_HEIGHT]);
}

void right5pin() {
    // Initialize
    chassis.setBrakeMode(pros::E_MOTOR_BRAKE_HOLD);
    chassis.setPose(6.75, 57, 0);
    closeClaw();
    MclMain.setObstacles(&rightAutonObstacles, nullptr);
    startMcl(6.75, 57, 0, true, false, false, false);
     
    // Toggle
    enableLiftPID = true;     // lift PID holds the target height
    setLift(LIFT_HEIGHTS[THIRD_STACK]+140.0f/7);	 // THIRD_STACK + 200 motor deg
    startClawIntake(80);	  // start intaking the pin
    pros::delay(700);

    // Score first pin
    chassis.moveToPoint(23.5, 43, 1000, {.forwards=false, .maxSpeed=70, .minSpeed=40}, true);
    pros::delay(200);
    setLift(LIFT_HEIGHTS[IDLE_HEIGHT]);	  // drop pin
    pros::delay(1000);
    openClaw(150, 127);
    reverseClawIntake(50);
    pros::delay(100);

    // Back up then grab second pin
    chassis.moveToPoint(12, 40, 900, {}, true);
    chassis.turnToPoint(23.5, 23.5, 500, {.forwards=false}, true);
    hardResetClaw();
    chassis.moveToPoint(23.5, 23.5, 1000, {.forwards=false, .maxSpeed=40}, true);
    startClawIntake(127);
    pros::delay(300);
    openClaw(150, 127);
    pros::delay(500);
    closeClaw(100);
    pros::delay(200);

    // Score second pin
    MclMain.setPinAndCupVisibility(3, false);
    setLift(LIFT_HEIGHTS[SECOND_STACK]);
    chassis.turnToHeading(200, 400, {}, true);
    chassis.moveToPoint(24, 47, 1100, {.forwards=false, .maxSpeed=60}, true);
    pros::delay(700);
    setLift(LIFT_HEIGHTS[IDLE_HEIGHT]);
    pros::delay(500);
    openClaw(150, 127);
    reverseClawIntake(50);

    // Grab third pin
    chassis.moveToPoint(38, 38, 1100, {}, true);
    chassis.turnToPoint(47.5, 47.5, 500, {.forwards=false}, true);
    chassis.moveToPoint(47.5, 47.5, 700, {.forwards=false, .maxSpeed=40}, true);
    startClawIntake(127);
    pros::delay(500);
    closeClaw(100);
    pros::delay(200);

    // Score third pin
    MclMain.setPinAndCupVisibility(2, false);
    setLift(LIFT_HEIGHTS[THIRD_STACK]);
    chassis.turnToHeading( 105, 500, {}, true);
    chassis.moveToPoint(23.5, 49, 1100, {.forwards=false, .maxSpeed=60}, true);
    pros::delay(700);
    setLift(LIFT_HEIGHTS[FIRST_STACK]);
    pros::delay(600);
    openClaw(150, 127);
    reverseClawIntake(50);

    // Grab fourth pin
    MclMain.setDistSyncProp(0.00f);
    chassis.moveToPoint(34, 56, 1000, {}, false);
    setLift(LIFT_HEIGHTS[IDLE_HEIGHT]);
    chassis.turnToHeading(141, 700, {}, false);
    MclMain.setDistSyncProp(0.02f);
    leftMotors.move(-40);
    rightMotors.move(-40);
    closeClaw(127);
    startClawIntake(127);
    pros::delay(650);
    chassis.swingToHeading(170, lemlib::DriveSide::LEFT, 500, {}, true);
    openClaw(100, 127);
    pros::delay(400);
    closeClaw(127);
    pros::delay(200);

    // Score fourth pin
    chassis.turnToHeading(70, 300, {}, true);
    chassis.moveToPoint(-23.5, 47.5, 1000, {.forwards=false}, true);
    pros::delay(200);
    setLift(LIFT_HEIGHTS[SECOND_STACK]);
    chassis.moveToPoint(-23.5, 47.5, 1200, {.forwards=false, .maxSpeed=50}, true);
    pros::delay(200);
    setLift(LIFT_HEIGHTS[IDLE_HEIGHT]);
}


void skills () {
    chassis.setBrakeMode(pros::E_MOTOR_BRAKE_HOLD);
    chassis.setPose(-59, -35, 225);
    closeClaw();
    resetLift();
    pros::delay(200);
    //startMcl(-59, -35, 225, false, true, false, false);
    
    // Score first pin
    pros::delay(200);
    setLift(LIFT_HEIGHTS[FIRST_STACK]);
    moveForward(-15, 1500, 60, 1, true);
    pros::delay(1200);
    resetLift();
    pros::delay(1500);
    openClaw(150, 127);
    pros::delay(500);
    chassis.moveToPoint(-40, -58, 2000, {.maxSpeed = 100 }, true);
    chassis.turnToHeading(90, 700, {}, true);
    pros::delay(800);

    // Cycle
    for (int i = 0; i < 6; i ++) {
        moveForward(-15, 1300, 60, 1, true);
        pros::delay(1000);
        closeClaw(127);
        pros::delay(500);
        moveForward(10, 1300, 60, 1, true);
        pros::delay(300);
        setLift(LIFT_HEIGHTS[i]);
        chassis.turnToHeading(180, 700, {}, true);
        chassis.moveToPoint(-47, -47, 1300, {.forwards=false, .maxSpeed = 60}, true);
        setLift(LIFT_HEIGHTS[IDLE_HEIGHT]);
        pros::delay(1500);
        openClaw(150, 127);
        pros::delay(500);
        chassis.moveToPoint(-42, -58, 1000, {.maxSpeed = 100 }, true);
        chassis.turnToHeading(90, 700, {}, true);
    }

    // Go to mid
    moveForward(20, 1300, 60, 1, true);
    chassis.moveToPoint(0, -10, 2000, {.maxSpeed = 100 }, true);
}

void safe_skills() {
    chassis.setBrakeMode(pros::E_MOTOR_BRAKE_HOLD);
    chassis.setPose(57, 0, 90);
    closeClaw();
    pros::delay(200);
    MclMain.setObstacles(&leftAutonObstacles, nullptr);
    startMcl(57, 0, 90, false, false, false, false);
    
    enableLiftPID = true;     // lift PID holds the target height
    resetLift();             // drive to bottom + zero encoder; PID waits until it's done
    setLift(LIFT_HEIGHTS[THIRD_STACK] + 200.0f/7); // THIRD_STACK + 200 motor deg
    startClawIntake(80);  // start intaking the pin
    pros::delay(1500);
    //Move to alliance goal and pin drop
    chassis.moveToPoint(39.5, 0, 1000, { .forwards = false, .maxSpeed = 100,}, true);
    setLift(LIFT_HEIGHTS[FIRST_STACK]+3.0f); 
    chassis.turnToPoint(39.5, 22, 500, {.forwards = false}, true);
    chassis.moveToPoint(39.5, 22, 1600, {.forwards = false, .maxSpeed = 50}, true);
    //Drop pin and back up
    pros::delay(800);
    setLift(LIFT_HEIGHTS[IDLE_HEIGHT]);  // drop pin
    pros::delay(500);
    openClaw(-150, 127);  // open wider for the drop
    reverseClawIntake(50);
    pros::delay(1000);
    //back up
    chassis.moveToPoint(44, 10, 1000, { .maxSpeed = 100}, true);
    //get cup and score
    chassis.turnToPoint(20, 25, 500, {.forwards = false}, true);
    hardResetClaw();
    pros::delay(500);
    openClaw(150, 127);
    chassis.moveToPoint(20, 25, 1900, { .forwards = false, .maxSpeed = 40,});
    startClawIntake(127);
    pros::delay(1200);
    closeClaw(127);
    pros::delay(600);
    //score
    setLift(SECOND_STACK);
    chassis.turnToPoint(44, 34, 600, {.forwards = false}, true);
    chassis.moveToPoint(44, 34, 1700, { .forwards = false, .maxSpeed = 70,}, false);
    pros::delay(200);
    setLift(LIFT_HEIGHTS[IDLE_HEIGHT]);
    pros::delay(1200);
    openClaw(150, 127);
    pros::delay(800);

    moveForward(10, 700, 127, 1, false);
    chassis.moveToPoint(0, 0, 2000, {.maxSpeed=50}, true);
}