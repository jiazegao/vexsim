#pragma once

#include "configs.hpp"

// ----------------- BASIC MOTOR CONTROL -----------------
void startFrontIntake(int velocity = 127);
void reverseFrontIntake(int velocity = 127);
void stopFrontIntake();

void startClawIntake(int velocity_rpm = 200);
void reverseClawIntake(int velocity_rpm = 200);
void stopClawIntake();

inline float claw_open_position = 140.0;
inline float claw_close_position = 10.0;
// angle = gripper motor degrees from fully closed (defaults to the positions above)
void openClaw(float angle = claw_open_position, int velocity = 127);
void closeClaw(int velocity = 127);
void stopClaw();

void raiseLift(int velocity = 127);
void lowerLift(int velocity = 60);
void stopLift();

// ----------------- BASIC MOTOR MACROS -----------------
enum LIFT_STAGES {IDLE_HEIGHT, FIRST_STACK, SECOND_STACK, THIRD_STACK, FOUTH_STACK, FIFTH_STACK};
// Lift-arm degrees above bottom. Written as (motor deg / 7) so you can tune using the P: value on the controller.
constexpr float LIFT_HEIGHTS[6] = {0.0, 1000.0/7, 2000.0/7, 3000.0/7, 4000.0/7, 4900.0/7};  // max = 5000 motor deg
// Software hardstop: lift will never be driven above this (motor degrees, same units as the P: value).
constexpr float LIFT_MAX_MOTOR_DEG = 4850.0;

inline bool enableLiftPID = false;
inline bool clawHomed = true;

/*
    - Must be called within void initialize()
*/
void initLiftPID();

void setLift(LIFT_STAGES newTargetEnum);
void setLift(float newTargetInch);
void resetLift();
bool isLiftResetting();
void hardResetClaw();

void updateLiftMotors();
