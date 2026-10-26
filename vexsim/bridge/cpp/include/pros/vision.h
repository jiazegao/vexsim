/* vexsim PROS 4 shim: V5 Vision Sensor (not simulated yet). */
#ifndef _PROS_VISION_H_
#define _PROS_VISION_H_

#include <stdint.h>

#define VISION_OBJECT_ERR_SIG 255
#define VISION_FOV_WIDTH 316
#define VISION_FOV_HEIGHT 212

#ifdef __cplusplus
extern "C" {
namespace pros {
#endif

typedef enum vision_object_type { E_VISION_OBJECT_NORMAL = 0, E_VISION_OBJECT_COLOR_CODE = 1, E_VISION_OBJECT_LINE = 2 } vision_object_type_e_t;

typedef struct __attribute__((__packed__)) vision_signature {
	uint8_t id;
	uint8_t _pad[3];
	float range;
	int32_t u_min;
	int32_t u_max;
	int32_t u_mean;
	int32_t v_min;
	int32_t v_max;
	int32_t v_mean;
	uint32_t rgb;
	uint32_t type;
} vision_signature_s_t;

typedef uint16_t vision_color_code_t;

typedef struct __attribute__((__packed__)) vision_object {
	uint16_t signature;
	vision_object_type_e_t type;
	int16_t left_coord;
	int16_t top_coord;
	int16_t width;
	int16_t height;
	uint16_t angle;
	int16_t x_middle_coord;
	int16_t y_middle_coord;
} vision_object_s_t;

typedef enum vision_zero { E_VISION_ZERO_TOPLEFT = 0, E_VISION_ZERO_CENTER = 1 } vision_zero_e_t;

#ifdef __cplusplus
}  // namespace pros
}
#endif

#endif
