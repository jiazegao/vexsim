/* vexsim PROS 4 shim: V5 GPS Sensor (not simulated yet). */
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
}  // namespace pros
}
#endif

#endif
