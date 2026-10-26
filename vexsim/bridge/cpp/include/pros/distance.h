/* vexsim PROS 4 shim: V5 Distance Sensor C API (mm). */
#ifndef _PROS_DISTANCE_H_
#define _PROS_DISTANCE_H_

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
namespace pros {
namespace c {
#endif

int32_t distance_get(uint8_t port);
int32_t distance_get_confidence(uint8_t port);
int32_t distance_get_object_size(uint8_t port);
double distance_get_object_velocity(uint8_t port);

#ifdef __cplusplus
}  // namespace c
}  // namespace pros
}
#endif

#endif
