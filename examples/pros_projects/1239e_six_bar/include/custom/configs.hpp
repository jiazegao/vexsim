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
inline pros::MotorGroup leftMotors({-15, -14, -13}, pros::MotorGearset::blue);
inline pros::MotorGroup rightMotors({8, 7, 10}, pros::MotorGearset::blue);
inline pros::MotorGroup liftMotors({-19, 20}, pros::MotorGearset::blue);  // 19 first: always plugged in, used for position/velocity. 20 = skills only
inline pros::Motor liftMotor19(-19, pros::MotorGearset::blue);
inline pros::Motor liftMotor20(20, pros::MotorGearset::blue);
inline pros::Motor frontIntakeMotor(17, pros::MotorGearset::blue);
inline pros::Motor clawGrippersMotor(18, pros::MotorGearset::green);
inline pros::Motor clawIntakeMotor(-16, pros::MotorGearset::green);
inline lemlib::PID liftPID(1.2, 0.0, 0.5);

inline lemlib::Drivetrain drivetrain(&leftMotors,
                              &rightMotors,
                              11.413500,
                              2.75,
                              450,
                              2
);

// IMU
inline ScaledIMU imu(6, 360.0, 360.0); // Adjust actual_reading based on your IMU's behavior

// Odometry
inline pros::Rotation vertRotation(-9);
inline lemlib::TrackingWheel vertPod(&vertRotation, 2.75, 0);

inline lemlib::OdomSensors sensors( &vertPod,
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
enum DISTSENSORS {FRONT, BACK, LEFT, RIGHT, BACK_LEFT, BACK_RIGHT};
// No distance sensors mounted right now -> all on tempPort. Real ports in comments.
inline bool distanceSensorsEnabled = true;  // set true once distance sensors are mounted
inline pros::Distance front_dist(2);
inline pros::Distance back_dist(21);
inline pros::Distance left_dist(3);
inline pros::Distance right_dist(5);
inline pros::Distance back_left_dist(4);
inline pros::Distance back_right_dist(11);

inline std::array<pros::Distance*, 6> DISTANCE_COLLECTION = {&front_dist, &back_dist, &left_dist, &right_dist, &back_left_dist, &back_right_dist};

// Rcl setup
/*front
2.754921 forward, 6.500079 left, 3.327301 high

left
0.289449 forward, 6.759719 left, 2.077872 high

backLeft
5.833577 back, 6.104867 left, 5.525000 high, 45deg angle facing back left corner

back
5.374094 back, 4.756890 right, 3.025004 high

backRight
5.833577 back, 6.104868 right, 5.525000 high, 45deg angle facing back right corner

right
0.289449 forward, 6.759720 right, 2.077872 high 
*/
inline RclSensor front_rcl(&front_dist, -6.500079, 2.754921, 0.0, 15.0);
inline RclSensor back_rcl(&back_dist, 4.756890, -5.374094, 180.0, 15.0);
inline RclSensor left_rcl(&left_dist, -6.759720, 0.289449, 270.0, 15.0);
inline RclSensor right_rcl(&right_dist, 6.759720, 0.289449, 90.0, 15.0);
inline RclSensor back_left_rcl(&back_left_dist, -6.104867, -5.833577, 225.0, 15.0);
inline RclSensor back_right_rcl(&back_right_dist, 6.104868, -5.833577, 135.0, 15.0);

inline RclTracking RclMain(&chassis, 1, false, 0.5, 4.0, 200.0, 6.0, 50);
inline MclTracking MclMain(&chassis, &drivetrain, DISTANCE_COLLECTION, {&vertRotation, 2.75, 0.0}, {nullptr, 0.0, 0.0}, 0, 0, 0, true);

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

// Match loaders: 4" boxes on the left and right walls, same as match_loaders in MclTracking.hpp.
// Radius leaves the same 1.5" margin past the flat sides as the base circles.
inline Circle_Obstacle match_loader1(68.5, 58.75, 3.5);    // top right
inline Circle_Obstacle match_loader2(-68.5, 58.75, 3.5);   // top left
inline Circle_Obstacle match_loader3(-68.5, -58.75, 3.5);  // bottom left
inline Circle_Obstacle match_loader4(68.5, -58.75, 3.5);   // bottom right

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
