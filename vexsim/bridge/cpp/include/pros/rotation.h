/* vexsim PROS 4 shim: V5 Rotation Sensor C API (centidegrees). */
#ifndef _PROS_ROTATION_H_
#define _PROS_ROTATION_H_

#include <stdbool.h>
#include <stdint.h>

#define ROTATION_MINIMUM_DATA_RATE 5

#ifdef __cplusplus
extern "C" {
namespace pros {
namespace c {
#endif

int32_t rotation_reset(uint8_t port);
int32_t rotation_set_data_rate(uint8_t port, uint32_t rate);
int32_t rotation_set_position(uint8_t port, int32_t position);
int32_t rotation_reset_position(uint8_t port);
int32_t rotation_get_position(uint8_t port);
int32_t rotation_get_velocity(uint8_t port);
int32_t rotation_get_angle(uint8_t port);
int32_t rotation_set_reversed(uint8_t port, bool value);
int32_t rotation_reverse(uint8_t port);
int32_t rotation_init_reverse(uint8_t port, bool reverse_flag);
int32_t rotation_get_reversed(uint8_t port);

#ifdef __cplusplus
}  // namespace c
}  // namespace pros
}
#endif

#endif
