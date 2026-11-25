#ifndef TRACKING_UTIL_HPP
#define TRACKING_UTIL_HPP

#include <chrono>
#include <cstdint>
#include <math.h>
#include "pros/rtos.hpp"

// Timer
enum class TimeUnit { SECOND, MILLISECOND };

static constexpr float INV_PI = 1.0f / M_PI;
static constexpr float INV_180 = 1.0f / 180.0f;
static constexpr float PIF = M_PI;
static constexpr float HALF_PIF = M_PI / 2.0;
static constexpr float QTR_PIF = M_PI / 4.0;

// vexsim: Timer reads the brain's clock (pros::micros()) instead of std::chrono's. In the
// simulator the robot's time is simulated, so wall-clock time is unrelated to it; on the
// robot both clocks agree, so this behaves the same there.
class Timer {
    public:
        Timer(float timeoutMs_ = 0) : timeoutMs(timeoutMs_), startTime(pros::micros()) {};

        void reset() {
            startTime = pros::micros();
        };

        void hardReset(float newTimeoutMs) {
            timeoutMs = newTimeoutMs;
            reset();
        };

        bool timeIsUp() const {
            return elapsedMs() > timeoutMs;
        };

        float timeLeft(TimeUnit unit = TimeUnit::MILLISECOND) const {
            float e = elapsedMs();
            if (unit == TimeUnit::SECOND) return e < timeoutMs ? ((timeoutMs - e) * 0.001f) : 0.0f;
            return e < timeoutMs ? (timeoutMs - e) : 0;
        };

        float elapsed(TimeUnit unit = TimeUnit::MILLISECOND) const {
            float ms = elapsedMs();
            return (unit == TimeUnit::SECOND) ? (ms * 0.001f) : ms;
        };
    
        float timeoutMs;
        std::uint64_t startTime;  // vexsim: microseconds (was a std::chrono time_point)

        float elapsedMs() const {
            return (pros::micros() - startTime) * 0.001f;
        };
};

// Consts
constexpr float mmToInch = 0.039370078740157;
constexpr float MAX_OBSTACLE_DURATION = 1e12;         // ms
constexpr float FIELD_HALF_LENGTH = 70.2;         // inches
constexpr float FIELD_NEG_HALF_LENGTH = -70.2;

// Util funcs
inline float botToTrig(float ang) {
    float result = 90.0 - ang;
    while (result > 360.0) result -= 360.0;
    while (result < 0) result += 360.0;
    return result;
}
inline float vexToStd(float vexDegrees) {
    float rads = (90.0 - vexDegrees) * (M_PI * INV_180);
    while (rads > M_PI) rads -= 2 * M_PI;
    while (rads < -M_PI) rads += 2 * M_PI;
    return rads;
}
inline float stdToVex(float stdRads) {
    float deg = 90.0 - (stdRads * 180.0 * INV_PI);
    while (deg < 0) deg += 360;
    while (deg >= 360) deg -= 360;
    return deg;
}

// Utility conversions
inline float degToRad(float deg) { return deg * M_PI * INV_180; }

#endif