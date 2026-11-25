#ifndef MCLTRACKING_HPP
#define MCLTRACKING_HPP

#include "lemlib/chassis/chassis.hpp"
#include "pros/distance.hpp"
#include "main.h"
#include <vector>
#include <cmath>
#include <random>
#include "Tracking_Util.hpp"
#include "pros/rotation.hpp"

struct Pose { float x, y, theta; };
struct Coord {float x, y; };
struct Circle { float x, y, radius; };
struct Line_ { Pose p1, p2; };
struct Trig { float cos_m, sin_m; };

class MclTracking {
private:

    // --- Configuration Constants ---
    static constexpr int PARTICLE_COUNT = 2048;
    static constexpr float INV_PARTICLE_COUNT = 1.0f / PARTICLE_COUNT;
    static constexpr int RESAMPLE_THRESHOLD = PARTICLE_COUNT / 2;
    static constexpr float MIN_DIST_FROM_RESAMPLE = 5.0f;
    static constexpr float MAX_VELO_RESAMPLE = 100.0f;

    static constexpr float MAX_RANGE = 100.0f;
    static constexpr float DIST_RESAMPLE_VARIANCE = 1.5f;
    static constexpr float THETA_RESAMPLE_VARIANCE = 0.0f; //0.005f;
    static constexpr float MAX_THETA_DEVIATION = 0.0f; //0.08f;
    static constexpr int CONFIDENCE_THRESHOLD = 20;
    static constexpr float CONFIDENCE_SCALING_BASE = 32.0f;
    static constexpr float RIGHT_ANG_MULTIPLIER = 0.5f;
    static constexpr float RIGHT_ANG_CONST = 2.0 / M_PI * RIGHT_ANG_MULTIPLIER;
    static constexpr float SENSOR_COUNT_SCALING = 0.1667f;
    
    static constexpr float TRACKING_WHEEL_VARIANCE = 0.02f;
    static constexpr float IMU_VARIANCE = 0.0f; //0.002f;
    static constexpr float FAULT_TOLERANCE = 0.005f;
    float DIST_SYNC_PROP = 0.015f;
    static constexpr float THETA_SYNC_PROP = 0.000f;
    static constexpr float HORIZ_DEPENDENT_VARIANCE_PROP = 0.05f;
    static constexpr float HORIZ_CONSTANT_NOISE = 0.05f;
    static constexpr float MAX_DIFF_SQR = 400.0f;

    static constexpr float MSPT = 30.0f;
    static constexpr float INV_MSPT = 1.0f / MSPT;
    static constexpr float MINPAUSE = 10.0f;
    
    struct Particle {
        Pose pose;
        float weight;
    };
    
    // Walls
    static constexpr Line_ walls[4] = {
        {{-70.2, -70.2}, { 70.2, -70.2}}, 
        {{ 70.2, -70.2}, { 70.2,  70.2}}, 
        {{ 70.2,  70.2}, {-70.2,  70.2}}, 
        {{-70.2,  70.2}, {-70.2, -70.2}}
    };

    // Field Elements
    static constexpr Line_ match_loaders[12] = {
        // Top Right
        {{70.5, 56.75}, {66.5, 56.75}},
        {{66.5, 56.75}, {66.5, 60.75}},
        {{66.5, 60.75}, {70.5, 60.75}},
        // Top Left
        {{-70.5, 56.75}, {-66.5, 56.75}},
        {{-66.5, 56.75}, {-66.5, 60.75}},
        {{-66.5, 60.75}, {-70.5, 60.75}},
        // Bottom Left
        {{-70.5, -56.75}, {-66.5, -56.75}},
        {{-66.5, -56.75}, {-66.5, -60.75}},
        {{-66.5, -60.75}, {-70.5, -60.75}},
        // Bottom Right
        {{70.5, -56.75}, {66.5, -56.75}},
        {{66.5, -56.75}, {66.5, -60.75}},
        {{66.5, -60.75}, {70.5, -60.75}}
    };

    // > 5 inch is high
    static constexpr Circle high_center_base = {0.0, 0.0, 1.5937075};
    static constexpr Line_ low_center_base[4] = {
        {{2.8056165, 2.8056165},{2.8056165, -2.8056165}},
        {{2.8056165, -2.8056165},{-2.8056165, -2.8056165}},
        {{-2.8056165, -2.8056165},{-2.8056165, 2.8056165}},
        {{-2.8056165, 2.8056165},{2.8056165, 2.8056165}}
    };

    // <= 5.8 inch is visible
    static constexpr Line_ neutral_bases[16] = {
        // LEFTMOST
        {{-44.5, 26.0},{-44.5, 21.0}},
        {{-44.5, 21.0},{-49.5, 21.0}},
        {{-49.5, 21.0},{-49.5, 26.0}},
        {{-49.5, 26.0},{-44.5, 26.0}},
        // UPMOST
        {{-21.0, 49.5},{-21.0, 44.5}},
        {{-21.0, 44.5},{-26.0, 44.5}},
        {{-26.0, 44.5},{-26.0, 49.5}},
        {{-26.0, 49.5},{-21.0, 49.5}},
        // RIGHTMOST
        {{44.5, -26.0},{44.5, -21.0}},
        {{44.5, -21.0},{49.5, -21.0}},
        {{49.5, -21.0},{49.5, -26.0}},
        {{49.5, -26.0},{44.5, -26.0}},
        // DOWNMOST
        {{21.0, -49.5},{21.0, -44.5}},
        {{21.0, -44.5},{26.0, -44.5}},
        {{26.0, -44.5},{26.0, -49.5}},
        {{26.0, -49.5},{21.0, -49.5}}
    };

    // <= 3.25 inch is visible
    static constexpr Line_ alliance_bases[16] = {
        // LEFTMOST
        {{-44.5, -26.0},{-44.5, -21.0}},
        {{-44.5, -21.0},{-49.5, -21.0}},
        {{-49.5, -21.0},{-49.5, -26.0}},
        {{-49.5, -26.0},{-44.5, -26.0}},
        // DOWNMOST
        {{-21.0, -49.5},{-21.0, -44.5}},
        {{-21.0, -44.5},{-26.0, -44.5}},
        {{-26.0, -44.5},{-26.0, -49.5}},
        {{-26.0, -49.5},{-21.0, -49.5}},
        // RIGHTMOST
        {{44.5, 26.0},{44.5, 21.0}},
        {{44.5, 21.0},{49.5, 21.0}},
        {{49.5, 21.0},{49.5, 26.0}},
        {{49.5, 26.0},{44.5, 26.0}},
        // UPMOST
        {{21.0, 49.5},{21.0, 44.5}},
        {{21.0, 44.5},{26.0, 44.5}},
        {{26.0, 44.5},{26.0, 49.5}},
        {{26.0, 49.5},{21.0, 49.5}}
    };

    static constexpr Line_ pins_and_cups[24] = {
        // Top Left
        {{-49.5, 47.5}, {-45.5, 47.5}},
        {{-47.5, 49.5}, {-47.5, 45.5}},
        {{-25.5, 23.5}, {-21.5, 23.5}},
        {{-23.5, 25.5}, {-23.5, 21.5}},
        // Top Right
        {{49.5, 47.5}, {45.5, 47.5}},
        {{47.5, 49.5}, {47.5, 45.5}},
        {{25.5, 23.5}, {21.5, 23.5}},
        {{23.5, 25.5}, {23.5, 21.5}},
        // Bottom Left
        {{-49.5, -47.5}, {-45.5, -47.5}},
        {{-47.5, -49.5}, {-47.5, -45.5}},
        {{-25.5, -23.5}, {-21.5, -23.5}},
        {{-23.5, -25.5}, {-23.5, -21.5}},
        // Bottom Right
        {{49.5, -47.5}, {45.5, -47.5}},
        {{47.5, -49.5}, {47.5, -45.5}},
        {{25.5, -23.5}, {21.5, -23.5}},
        {{23.5, -25.5}, {23.5, -21.5}},
        // Middle
        {{-2.0, 23.5}, {2.0, 23.5}},
        {{0.0, 25.5}, {0.0, 21.5}},
        {{-2.0, -23.5}, {2.0, -23.5}},
        {{0.0, -25.5}, {0.0, -21.5}},
        {{21.5, 0.0}, {25.5, 0.0}},
        {{23.5, -2.0}, {23.5, 2.0}},
        {{-21.5, 0.0}, {-25.5, 0.0}},
        {{-23.5, -2.0}, {-23.5, 2.0}}
    };
    std::array<bool, 12> cup_and_pin_disabled = {false, false, false, false, false, false, false, false, false, false, false, false};

    // Sensor mounts
    static constexpr int SENSOR_COUNT = 6;
    static constexpr Pose sensor_mounts[SENSOR_COUNT] = {
        // x (fwd/back), y (left/right), theta (angle sensor is pointing)
        // Front, Back, Left, Right, Back Left, Back Right
        {2.754921f, 6.500079f, 0.0},
        {-5.374094f, -4.756890f, std::numbers::pi},
        {0.289449f, 6.759719f, std::numbers::pi/2},
        {0.289449f, -6.759720f, std::numbers::pi*3/2},
        {-5.833577f, 6.104867f, std::numbers::pi*3/4},
        {-5.833577f, -6.104868f, std::numbers::pi*5/4}
    };
    static constexpr bool low_center_base_visible[SENSOR_COUNT] = {false, false, false, false, false, false};
    static constexpr bool neutral_base_visible[SENSOR_COUNT] = {true, true, true, true, true, true};
    static constexpr bool alliance_base_visible[SENSOR_COUNT] = {false, false, false, false, false, false};

    std::array<pros::Distance*, SENSOR_COUNT> distance_collection = {nullptr, nullptr, nullptr, nullptr, nullptr, nullptr};
    std::array<Trig, SENSOR_COUNT> mountTrigs;
    std::array<Timer, SENSOR_COUNT> disableTimers;

    // Disabling line obstacles
    std::vector<Line_>* disabling_line_obstacles = nullptr;

    // Disabling circle obstacles
    std::vector<Circle>* disabling_circle_obstacles = nullptr;

    // Gaussian cheatsheeet for dynamic sigma
    static constexpr int GAUSSIAN_LUT_RES = 1024;
    alignas(64) float gaussian_lut[GAUSSIAN_LUT_RES];

    // Particles
    std::array<Particle, PARTICLE_COUNT> particles_array;
    std::array<Particle, PARTICLE_COUNT> new_gen_array;
    std::array<Particle, PARTICLE_COUNT>* particles_ptr = &particles_array;
    std::array<Particle, PARTICLE_COUNT>* new_gen_ptr = &new_gen_array;
    Trig currTrig;
    std::array<Trig, PARTICLE_COUNT> pTrigs = {};
    std::mt19937 gen;
    lemlib::Chassis* chassis;
    lemlib::Drivetrain* dt;
    bool vertical_tracking_mode;
    pros::Task* MclTrackingTask;
    bool autoSync = false;
    float lastImuTheta = 0.0;
    pros::Rotation* vertical_tracking_wheel = nullptr;
    float vert_c = 0.0;
    float vert_offset = 0.0;
    float last_vertical_reading = 0.0;
    pros::Rotation* horizontal_tracking_wheel = nullptr;
    float horiz_c = 0.0;
    float horiz_offset = 0.0;
    float last_horizontal_reading = 0.0;
    Pose lastResamplePose = {0, 0, 0};
    float latest_speed = 0.0;

    lemlib::Pose odomLast = {0, 0, 0};
    Timer t = Timer(MSPT);
    int minPause = MINPAUSE;
    Pose rawMcl = {0, 0, 0};
    Coord spread = {0, 0};  // the particles' standard deviation in x and y (updateSpread)

    // Sensor data access
    std::array<bool, SENSOR_COUNT> valid_sensors;
    std::array<int, SENSOR_COUNT> sensor_readings_mm;
    std::array<float, SENSOR_COUNT> sensor_readings_inch;
    std::array<int, SENSOR_COUNT> sensor_confs;
    std::array<bool, SENSOR_COUNT> disabled_sensors = {false, false, false, false, false, false};

    static constexpr int NOISE_POOL_SIZE = 2048;
    static constexpr int NOISE_MASK = NOISE_POOL_SIZE - 1;

    alignas(64) std::array<float, NOISE_POOL_SIZE> noise_pool;
    std::normal_distribution<float> dist;
    int noise_idx = 0;
    int regen_idx = 0;
    static constexpr int REGEN_PT = 3;

    // Helper to get next noise value
    inline float next_noise() {
        noise_idx = (noise_idx + 123) & NOISE_MASK;
        return noise_pool[noise_idx];
    }

    inline void regen_noise() {
        noise_pool[regen_idx] = dist(gen);
        regen_idx = (regen_idx + 1) & NOISE_MASK;
    }

    float vertical_drift = 0.0;
    float horizontal_drift = 0.0;

    float intersect_line(Coord ray, Line_ wall, float max_range, float rayCos, float raySin);

    float intersect_circle(Coord ray, Circle c, float max_range, float dx, float dy);

public:
    MclTracking(lemlib::Chassis* chassis, lemlib::Drivetrain* dt, std::array<pros::Distance*, SENSOR_COUNT> dist_collection, std::tuple<pros::Rotation*, float, float> vertical_tracking_wheel, std::tuple<pros::Rotation*, float, float> horizontal_tracking_wheel, float start_x, float start_y, float start_vex_theta, bool autoSync_ = true);

    // Update particles and pTrigs
    void predict();

    void update_weights();

    void resample();

    std::pair<Pose, float> get_estimate();

    void set_pose(float x, float y, float vex_theta);

    Pose updateMcl();

    void updateBotPose();

    void startTracking();

    void setDistSyncProp(float newDistSyncProp);

    void stopTracking();

    void updateSpread(Pose around);

    void uniform_reset();

    void enableSens(int sens);

    void disableSens(int sens);

    void disableSensFor(int sens, float ms);

    void setObstacles(std::vector<Line_>* newLineObstaclesPtr = nullptr, std::vector<Circle>* newCirleObstaclesPtr = nullptr);

    void setDrift(float verticalDrift, float horizontalDrift);

    void setPinAndCupVisibility(int index, bool visible);

    float getDTWheelDegrees();

    Pose getRawMcl();

    Coord getSpread();

    ~MclTracking();
};

#endif