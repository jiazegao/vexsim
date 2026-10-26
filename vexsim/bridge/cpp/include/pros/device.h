/* vexsim PROS 4 shim: smart port device types. */
#ifndef _PROS_DEVICE_H_
#define _PROS_DEVICE_H_

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
namespace pros {
namespace c {
#endif

typedef enum v5_device_e {
	E_DEVICE_NONE = 0,
	E_DEVICE_MOTOR = 2,
	E_DEVICE_ROTATION = 4,
	E_DEVICE_IMU = 6,
	E_DEVICE_DISTANCE = 7,
	E_DEVICE_RADIO = 8,
	E_DEVICE_VISION = 11,
	E_DEVICE_ADI = 12,
	E_DEVICE_OPTICAL = 16,
	E_DEVICE_GPS = 20,
	E_DEVICE_AIVISION = 29,
	E_DEVICE_SERIAL = 129,
	E_DEVICE_GENERIC __attribute__((deprecated("use E_DEVICE_SERIAL instead"))) = E_DEVICE_SERIAL,
	E_DEVICE_UNDEFINED = 255
} v5_device_e_t;

v5_device_e_t get_plugged_type(uint8_t port);

#ifdef __cplusplus
}  // namespace c
}  // namespace pros
}
#endif

#endif
