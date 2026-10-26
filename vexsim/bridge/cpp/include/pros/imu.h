/* vexsim PROS 4 shim: V5 Inertial Sensor C API. */
#ifndef _PROS_IMU_H_
#define _PROS_IMU_H_

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
namespace pros {
#endif

typedef enum imu_status_e {
	E_IMU_STATUS_READY = 0,
	E_IMU_STATUS_CALIBRATING = 1,
	E_IMU_STATUS_ERROR = 0xFF,
} imu_status_e_t;

typedef enum imu_orientation_e {
	E_IMU_Z_UP = 0,
	E_IMU_Z_DOWN = 1,
	E_IMU_X_UP = 2,
	E_IMU_X_DOWN = 3,
	E_IMU_Y_UP = 4,
	E_IMU_Y_DOWN = 5,
	E_IMU_ORIENTATION_ERROR = 0xFF
} imu_orientation_e_t;

typedef struct __attribute__((__packed__)) quaternion_s {
	double x;
	double y;
	double z;
	double w;
} quaternion_s_t;

struct imu_raw_s {
	double x;
	double y;
	double z;
};
typedef struct imu_raw_s imu_raw_s;
typedef struct imu_raw_s imu_gyro_s_t;
typedef struct imu_raw_s imu_accel_s_t;

typedef struct __attribute__((__packed__)) euler_s {
	double pitch;
	double roll;
	double yaw;
} euler_s_t;

#ifdef __cplusplus
#define IMU_STATUS_CALIBRATING pros::E_IMU_STATUS_CALIBRATING
#define IMU_STATUS_ERROR pros::E_IMU_STATUS_ERROR
#else
#define IMU_STATUS_CALIBRATING E_IMU_STATUS_CALIBRATING
#define IMU_STATUS_ERROR E_IMU_STATUS_ERROR
#endif

#ifdef __cplusplus
namespace c {
#endif

int32_t imu_reset(uint8_t port);
int32_t imu_reset_blocking(uint8_t port);
int32_t imu_set_data_rate(uint8_t port, uint32_t rate);
double imu_get_rotation(uint8_t port);
double imu_get_heading(uint8_t port);
quaternion_s_t imu_get_quaternion(uint8_t port);
euler_s_t imu_get_euler(uint8_t port);
double imu_get_pitch(uint8_t port);
double imu_get_roll(uint8_t port);
double imu_get_yaw(uint8_t port);
imu_gyro_s_t imu_get_gyro_rate(uint8_t port);
imu_accel_s_t imu_get_accel(uint8_t port);
imu_status_e_t imu_get_status(uint8_t port);
imu_orientation_e_t imu_get_physical_orientation(uint8_t port);
int32_t imu_tare(uint8_t port);
int32_t imu_tare_euler(uint8_t port);
int32_t imu_tare_heading(uint8_t port);
int32_t imu_tare_rotation(uint8_t port);
int32_t imu_tare_pitch(uint8_t port);
int32_t imu_tare_roll(uint8_t port);
int32_t imu_tare_yaw(uint8_t port);
int32_t imu_set_euler(uint8_t port, euler_s_t target);
int32_t imu_set_rotation(uint8_t port, double target);
int32_t imu_set_heading(uint8_t port, double target);
int32_t imu_set_pitch(uint8_t port, double target);
int32_t imu_set_roll(uint8_t port, double target);
int32_t imu_set_yaw(uint8_t port, double target);

#ifdef __cplusplus
}  // namespace c
}  // namespace pros
}
#endif

#endif  // _PROS_IMU_H_
