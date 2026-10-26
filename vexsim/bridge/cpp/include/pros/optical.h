/* vexsim PROS 4 shim: V5 Optical Sensor (not simulated yet). */
#ifndef _PROS_OPTICAL_H_
#define _PROS_OPTICAL_H_

#include <stdint.h>

#include "pros/error.h"

#ifdef __cplusplus
extern "C" {
namespace pros {
namespace c {
#endif

typedef enum optical_direction_e { NO_GESTURE = 0, UP = 1, DOWN = 2, RIGHT = 3, LEFT = 4, ERROR = PROS_ERR } optical_direction_e_t;

typedef struct optical_rgb_s {
	double red;
	double green;
	double blue;
	double brightness;
} optical_rgb_s_t;

typedef struct optical_raw_s {
	uint32_t clear;
	uint32_t red;
	uint32_t green;
	uint32_t blue;
} optical_raw_s_t;

typedef struct optical_gesture_s {
	uint8_t udata;
	uint8_t ddata;
	uint8_t ldata;
	uint8_t rdata;
	uint8_t type;
	uint8_t pad;
	uint16_t count;
	uint32_t time;
} optical_gesture_s_t;

#ifdef __cplusplus
}  // namespace c
}  // namespace pros
}
#endif

#endif
