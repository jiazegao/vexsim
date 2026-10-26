#pragma once

#include "configs.hpp"

// ----------------- BASIC MOTOR CONTROL -----------------
void startFrontIntake(int velocity = 127);
void reverseFrontIntake(int velocity = 127);
void stopFrontIntake();

void startEffectorIntake(int velocity = 200);
void reverseEffectorIntake(int velocity = 140);
void stopEffectorIntake();

void raiseLift(int velocity = 127);
void lowerLift(int velocity = 60);
void stopLift();

void raiseEffector(int velocity = 127);
void lowerEffector(int velocity = 127);
void stopEffector();

// ----------------- BASIC MOTOR MACROS -----------------
enum EFFECTOR_STAGES {IDLE_ANGLE, LOW_ANGLE, RIGHT_ANGLE, TOGGLE_ANGLE, HIGH_ANGLE, PIN_ANGLE};
constexpr float EFFECTOR_ANGLES[6] = {0.0, 60.0, 90.0, 105.0, 165.0, 86.0};  // Needs manual configuration

enum LIFT_STAGES {IDLE_HEIGHT, FIRST_STACK, SECOND_STACK, THIRD_STACK, FOUTH_STACK, FIFTH_STACK};
constexpr float LIFT_HEIGHTS[6] = {0.0, 10.0, 20.0, 30.0, 40.0, 50.0};    // Needs manual configuration

inline bool enableLiftPID = false;

void initEffectorPID();
/*
    - Must be called within void initialize()
    - Starts the pros::Task that manages effector setpose macro
*/
void setEffector(EFFECTOR_STAGES newTargetEnum);
void setEffector(float newTargetDeg);
void resetEffector();
void hardResetEffector();
void effectorToggle();
void scoreCup(float dropHeight, float raiseHeight);
void scorePin();

void initLiftPID();
void setLift(LIFT_STAGES newTargetEnum);
void setLift(float newTargetInch);
void resetLift();

void updateLiftMotors();
