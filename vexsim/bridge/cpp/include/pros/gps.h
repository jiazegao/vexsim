/* vexsim PROS 4 shim: V5 GPS Sensor C API (meters, degrees clockwise from the field's +y). */
#ifndef _PROS_GPS_H_
#define _PROS_GPS_H_

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
namespace pros {
#endif

typedef struct __attribute__((__packed__)) gps_position_s {
	double x;
	double y;
} gps_position_s_t;

typedef struct __attribute__((__packed__)) gps_status_s {
	double x;
	double y;
	double pitch;
	double roll;
	double yaw;
} gps_status_s_t;

typedef struct __attribute__((__packed__)) gps_orientation_s {
	double pitch;
	double roll;
	double yaw;
} gps_orientation_s_t;

struct gps_raw_s {
	double x;
	double y;
	double z;
};
typedef struct gps_raw_s gps_accel_s_t;
typedef struct gps_raw_s gps_gyro_s_t;

#ifdef __cplusplus
namespace c {
#endif

int32_t gps_initialize_full(uint8_t port, double xInitial, double yInitial, double headingInitial,
                            double xOffset, double yOffset);
int32_t gps_set_offset(uint8_t port, double xOffset, double yOffset);
gps_position_s_t gps_get_offset(uint8_t port);
int32_t gps_set_position(uint8_t port, double xInitial, double yInitial, double headingInitial);
int32_t gps_set_data_rate(uint8_t port, uint32_t rate);
double gps_get_error(uint8_t port);
gps_status_s_t gps_get_position_and_orientation(uint8_t port);
gps_status_s_t gps_get_status(uint8_t port);
gps_position_s_t gps_get_position(uint8_t port);
double gps_get_position_x(uint8_t port);
double gps_get_position_y(uint8_t port);
gps_orientation_s_t gps_get_orientation(uint8_t port);
double gps_get_pitch(uint8_t port);
double gps_get_roll(uint8_t port);
double gps_get_yaw(uint8_t port);
double gps_get_heading(uint8_t port);
double gps_get_heading_raw(uint8_t port);
gps_gyro_s_t gps_get_gyro_rate(uint8_t port);
double gps_get_gyro_rate_x(uint8_t port);
double gps_get_gyro_rate_y(uint8_t port);
double gps_get_gyro_rate_z(uint8_t port);
gps_accel_s_t gps_get_accel(uint8_t port);
double gps_get_accel_x(uint8_t port);
double gps_get_accel_y(uint8_t port);
double gps_get_accel_z(uint8_t port);

#ifdef __cplusplus
}  // namespace c
}  // namespace pros
}
#endif

#endif
