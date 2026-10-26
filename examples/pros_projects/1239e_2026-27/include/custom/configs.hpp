#pragma once

#include "lemlib/chassis/chassis.hpp" // IWYU pragma: keep
#include "lemlib/chassis/trackingWheel.hpp"
#include "pros/abstract_motor.hpp"
#include "pros/adi.hpp" // IWYU pragma: keep
#include "pros/distance.hpp" // IWYU pragma: keep
#include "pros/imu.hpp" // IWYU pragma: keep
#include "pros/misc.hpp" // IWYU pragma: keep
#include "pros/motor_group.hpp" // IWYU pragma: keep
#include "pros/motors.hpp"   // IWYU pragma: keep
#include "pros/optical.hpp"     // IWYU pragma: keep
#include "pros/rotation.hpp" // IWYU pragma: keep
#include <cmath>
#include <numbers>

#include "custom/RclTracking.hpp"
#include "custom/MclTracking.hpp"

#include <cmath>

class ScaledIMU : public pros::Imu {
private:
    double scale_factor;

public:
    // Constructor: Passes the port to the base pros::Imu class and calculates the scale factor
    ScaledIMU(uint8_t port, double expected_rotation = 360.0, double actual_reading = 360.0) 
        : pros::Imu(port) {
        scale_factor = expected_rotation / actual_reading; 
    }

    // "Override" the rotation method to return the scaled continuous rotation
    double get_rotation() const override {
        double raw_rotation = pros::Imu::get_rotation();
        
        // Check for PROS error return (usually INFINITY for doubles)
        if (std::isinf(raw_rotation)) {
            return raw_rotation; 
        }
        
        return raw_rotation * scale_factor;
    }

    // "Override" the heading method to return a bounded 0-360 degree value
    double get_heading() const override {
        double scaled_rotation = this->get_rotation();
        
        if (std::isinf(scaled_rotation)) {
            return scaled_rotation;
        }

        // Mathematically bound the scaled rotation to 0-360
        double heading = std::fmod(scaled_rotation, 360.0);
        if (heading < 0) {
            heading += 360.0;
        }
        
        return heading;
    }
};

const int tempPort = 21;

// Alliance Color
enum class alliance_color { RED, BLUE, NONE };
inline alliance_color allianceColor = alliance_color::BLUE;

// Controller
inline pros::Controller controller(pros::E_CONTROLLER_MASTER);
inline pros::Controller partner_controller(pros::E_CONTROLLER_PARTNER);

// Motors
inline pros::MotorGroup leftMotors({10, 9}, pros::MotorGearset::blue);
inline pros::MotorGroup rightMotors({-19, -17}, pros::MotorGearset::blue);
inline pros::MotorGroup liftMotors({-7, 21}, pros::MotorGearset::blue);
inline pros::Motor frontIntakeMotor(20, pros::MotorGearset::blue);
inline pros::Motor effectorIntakeMotor(-5, pros::MotorGearset::green);
inline pros::Motor effectorRotateMotor(-4, pros::MotorGearset::green);
inline lemlib::PID effectorPID(1.2, 0.0, 0.5);
inline lemlib::PID liftPID(1.2, 0.0, 0.5);

inline lemlib::Drivetrain drivetrain(&leftMotors,
                              &rightMotors,
                              10.400,
                              3.25,
                              450,
                              2
);

// IMU
inline ScaledIMU imu(16, 360.0, 360.91); // Adjust actual_reading based on your IMU's behavior

// Optical
inline pros::Optical frontOptic(3);

// Odometry
inline lemlib::OdomSensors sensors( nullptr,
                                    nullptr,
                                    nullptr,
                                    nullptr,
                                    &imu
);

// Lateral PID controller
inline lemlib::ControllerSettings lateral_controller(
                                              10.0, // proportional gain (kP)
                                              0, // integral gain (kI)
                                              20.0, // derivative gain (kD)
                                              0, // anti windup
                                              0, // small error range, in inches
                                              0, // small error range timeout, in milliseconds
                                              0, // large error range, in inches
                                              0, // large error range timeout, in milliseconds
                                              0 // maximum acceleration (slew)
);

// Angular PID controller
inline lemlib::ControllerSettings angular_controller(3.0, // proportional gain (kP)
                                            0, // integral gain (kI)
                                              19.5, // derivative gain (kD)
                                              0, // anti windup
                                              0, // small error range, in degrees
                                              0, // small error range timeout, in milliseconds
                                              0, // large error range, in degrees
                                              0, // large error range timeout, in milliseconds
                                              0 // maximum acceleration (slew)
);

// Throttle curve   
inline lemlib::ExpoDriveCurve throttle_curve(
    15,    // deadband
    20,    // minOutput
    1.05   // curve
);

// Steer curve
inline lemlib::ExpoDriveCurve steer_curve(
    10,    // deadband
    30,    // minOutput
    1.3    // curve
);


// Chassis
inline lemlib::Chassis chassis( drivetrain, // drivetrain settings
                        lateral_controller, // lateral PID settings
                        angular_controller, // angular PID settings
                        sensors // odometry sensors
);

// Distance
enum DISTSENSORS {FRONT_L, FRONT_R, LEFT, BACK, RIGHT};
inline pros::Distance frontL_dist(1);
inline pros::Distance frontR_dist(8);
inline pros::Distance left_dist(18);
inline pros::Distance back_dist(2);
inline pros::Distance right_dist(3);

inline std::array<pros::Distance*, 5> DISTANCE_COLLECTION = {&frontL_dist, &frontR_dist, &left_dist, &back_dist, &right_dist};

// Rcl setup
inline RclSensor frontL_rcl(&frontL_dist, -5.6937585, 4.656207, 0, 15.0);
inline RclSensor frontR_rcl(&frontR_dist, 5.6937585, 4.656207, 0, 15.0);
inline RclSensor left_rcl(&left_dist, -5.857102, -2.999773, 270.0, 15.0);
inline RclSensor back_rcl(&back_dist, -5.6937585, -0.920094, 180.0, 15.0);
inline RclSensor right_rcl(&right_dist, 5.857102, -2.999773, 90.0, 15.0);
inline RclTracking RclMain(&chassis, 1, false, 0.5, 4.0, 200.0, 6.0, 50);
inline MclTracking MclMain(&chassis, &drivetrain, DISTANCE_COLLECTION, {nullptr, 0.0, 0.0}, {nullptr, 0.0, 0.0}, 0, 0, 0, true);

enum MCL_Log_Format {DISABLED, SDCARD, SCREEN};
inline MCL_Log_Format mclLogType = SDCARD;
inline std::ofstream* mclLog = nullptr;
inline Timer mclLogTimer(100000000.0f);

// RCL obstacles
inline Circle_Obstacle neutral_base1(0.0, 0.0, 4.0);
inline Circle_Obstacle neutral_base2(-47.0, 23.5, 4.0);
inline Circle_Obstacle neutral_base3(-23.5, 47.0, 4.0);
inline Circle_Obstacle neutral_base4(47.0, -23.5, 4.0);
inline Circle_Obstacle neutral_base5(23.5, -47.0, 4.0);

inline Circle_Obstacle alliance_base1(23.5, 47.0, 4.0);
inline Circle_Obstacle alliance_base2(47.0, 23.5, 4.0);
inline Circle_Obstacle alliance_base3(-23.5, -47.0, 4.0);
inline Circle_Obstacle alliance_base4(-47.0, -23.5, 4.0);

inline std::vector<Line_> leftAutonObstacles = {
    {{-72.0, 72.0}, {32.0, -32.0}},
    {{32.0, 32.0}, {-72.0, -72.0}},
    {{32.0, -32.0}, {32.0, -72.0}},
    {{32.0, 32.0}, {32.0, 72.0}}
};

inline std::vector<Line_> rightAutonObstacles = {
    {{-72.0, -72.0}, {32.0, 32.0}},
    {{32.0, 32.0}, {72.0, 32.0}},
    {{72.0, -72.0}, {-32.0, 32.0}},
    {{-32.0, 32.0}, {-72.0, 32.0}}
};

// Disable Line
// inline Line_Obstacle disableLine(-72.0, 72.0, 72.0, -72.0);
