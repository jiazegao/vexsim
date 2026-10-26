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
    static constexpr int LOG_AMOUNT = 1;
    static constexpr int LOG_RATIO = PARTICLE_COUNT / LOG_AMOUNT;
    static constexpr float ODOM_MULTIPLIER = 0.25f;
    static constexpr float RPM_MULTIPLIER = 0.0016666666667f;

    static constexpr float MAX_RANGE = 100.0f;
    static constexpr float DIST_RESAMPLE_VARIANCE = 1.0f;
    static constexpr float THETA_RESAMPLE_VARIANCE = 0.0f; //0.005f;
    static constexpr float MAX_THETA_DEVIATION = 0.0f; //0.08f;
    static constexpr int CONFIDENCE_THRESHOLD = 20;
    static constexpr float CONFIDENCE_SCALING_BASE = 32.0f;
    static constexpr float RIGHT_ANG_MULTIPLIER = 0.5f;
    static constexpr float RIGHT_ANG_CONST = 2.0 / M_PI * RIGHT_ANG_MULTIPLIER;
    static constexpr float SENSOR_COUNT_SCALING = 0.20f;
    
    static constexpr float TRACKING_WHEEL_VARIANCE = 0.05f;
    static constexpr float IMU_VARIANCE = 0.0f; //0.002f;
    static constexpr float FAULT_TOLERANCE = 0.005f;
    float DIST_SYNC_PROP = 0.05f;
    static constexpr float THETA_SYNC_PROP = 0.000f;
    static constexpr float HORIZ_DEPENDENT_VARIANCE_PROP = 0.02f;
    static constexpr float HORIZ_CONSTANT_NOISE = 0.02f;

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

    // Universal elements
    static constexpr Line_ universal_match_loaders[12] = {
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

    // HIGH field elements
    static constexpr Circle high_center_base = {0.0, 0.0, 1.5937075};

    // LOW field elements
    static constexpr Line_ low_center_base[4] = {
        {{2.8056165, 2.8056165},{2.8056165, -2.8056165}},
        {{2.8056165, -2.8056165},{-2.8056165, -2.8056165}},
        {{-2.8056165, -2.8056165},{-2.8056165, 2.8056165}},
        {{-2.8056165, 2.8056165},{2.8056165, 2.8056165}}
    };

    static constexpr Line_ low_neutral_bases[16] = {
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
        // BOTTOMMOST
        {{21.0, -49.5},{21.0, -44.5}},
        {{21.0, -44.5},{26.0, -44.5}},
        {{26.0, -44.5},{26.0, -49.5}},
        {{26.0, -49.5},{21.0, -49.5}}
    };

    // Sensor mounts
    static constexpr int SENSOR_COUNT = 5;
    static constexpr Pose sensor_mounts[SENSOR_COUNT] = {
        // x (fwd/back), y (left/right), theta (angle sensor is pointing)
        {4.656207f, 5.6937585f, 0.0f},      // FRONT LEFT; 9.12" high
        {4.656207f, -5.6937585f, 0.0f},     // FRONT RIGHT; 9.12" high
        {-2.999773f, 5.857102f, std::numbers::pi/2}, // LEFT BACK; 4.19" high
        {-0.920094f, 5.6937585f, std::numbers::pi},   // BACK LEFT; 9.12" high
        {-2.999773f, -5.857102f, std::numbers::pi*3/2}   // RIGHT BACK; 4.19" high
    };
    static constexpr bool high_sensor[SENSOR_COUNT] = {true, true, false, true, false};
    std::array<pros::Distance*, SENSOR_COUNT> distance_collection = {nullptr, nullptr, nullptr, nullptr, nullptr};
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

    // Sensor data access
    std::array<bool, SENSOR_COUNT> valid_sensors;
    std::array<int, SENSOR_COUNT> sensor_readings_mm;
    std::array<float, SENSOR_COUNT> sensor_readings_inch;
    std::array<int, SENSOR_COUNT> sensor_confs;
    std::array<bool, SENSOR_COUNT> disabled_sensors = {false, false, false, false, false};

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

    void logMcl();

    void uniform_reset();

    void enableSens(int sens);

    void disableSens(int sens);

    void disableSensFor(int sens, float ms);

    void startAsyncLogger();

    void stopAsyncLogger();

    void setObstacles(std::vector<Line_>* newLineObstaclesPtr = nullptr, std::vector<Circle>* newCirleObstaclesPtr = nullptr);

    void setDrift(float verticalDrift, float horizontalDrift);

    float getDTWheelDegrees();

    Pose getRawMcl();

    ~MclTracking();
};

#endif