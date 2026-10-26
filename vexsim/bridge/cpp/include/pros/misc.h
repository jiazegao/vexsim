/* vexsim PROS 4 shim: competition status, controller, battery. */
#ifndef _PROS_MISC_H_
#define _PROS_MISC_H_

#include <stdbool.h>
#include <stdint.h>

#define NUM_V5_PORTS (22)

typedef enum {
	COMPETITION_DISABLED = 1 << 0,
	COMPETITION_CONNECTED = 1 << 2,
	COMPETITION_AUTONOMOUS = 1 << 1,
	COMPETITION_SYSTEM = 1 << 3,
} competition_status;

#ifdef __cplusplus
extern "C" {
namespace pros {
namespace c {
#endif

uint8_t competition_get_status(void);
uint8_t competition_is_disabled(void);
uint8_t competition_is_connected(void);
uint8_t competition_is_autonomous(void);
uint8_t competition_is_field(void);
uint8_t competition_is_switch(void);

#ifdef __cplusplus
}  // namespace c
}  // namespace pros
}
#endif

#ifdef __cplusplus
extern "C" {
namespace pros {
#endif

typedef enum { E_CONTROLLER_MASTER = 0, E_CONTROLLER_PARTNER } controller_id_e_t;

typedef enum {
	E_CONTROLLER_ANALOG_LEFT_X = 0,
	E_CONTROLLER_ANALOG_LEFT_Y,
	E_CONTROLLER_ANALOG_RIGHT_X,
	E_CONTROLLER_ANALOG_RIGHT_Y
} controller_analog_e_t;

typedef enum {
	E_CONTROLLER_DIGITAL_L1 = 6,
	E_CONTROLLER_DIGITAL_L2,
	E_CONTROLLER_DIGITAL_R1,
	E_CONTROLLER_DIGITAL_R2,
	E_CONTROLLER_DIGITAL_UP,
	E_CONTROLLER_DIGITAL_DOWN,
	E_CONTROLLER_DIGITAL_LEFT,
	E_CONTROLLER_DIGITAL_RIGHT,
	E_CONTROLLER_DIGITAL_X,
	E_CONTROLLER_DIGITAL_B,
	E_CONTROLLER_DIGITAL_Y,
	E_CONTROLLER_DIGITAL_A,
	E_CONTROLLER_DIGITAL_POWER
} controller_digital_e_t;

#ifdef PROS_USE_SIMPLE_NAMES
#ifndef VEXSIM_PROS_NS
#ifdef __cplusplus
#define VEXSIM_PROS_NS pros::
#else
#define VEXSIM_PROS_NS
#endif
#endif
#define CONTROLLER_MASTER VEXSIM_PROS_NS E_CONTROLLER_MASTER
#define CONTROLLER_PARTNER VEXSIM_PROS_NS E_CONTROLLER_PARTNER
#define ANALOG_LEFT_X VEXSIM_PROS_NS E_CONTROLLER_ANALOG_LEFT_X
#define ANALOG_LEFT_Y VEXSIM_PROS_NS E_CONTROLLER_ANALOG_LEFT_Y
#define ANALOG_RIGHT_X VEXSIM_PROS_NS E_CONTROLLER_ANALOG_RIGHT_X
#define ANALOG_RIGHT_Y VEXSIM_PROS_NS E_CONTROLLER_ANALOG_RIGHT_Y
#define DIGITAL_L1 VEXSIM_PROS_NS E_CONTROLLER_DIGITAL_L1
#define DIGITAL_L2 VEXSIM_PROS_NS E_CONTROLLER_DIGITAL_L2
#define DIGITAL_R1 VEXSIM_PROS_NS E_CONTROLLER_DIGITAL_R1
#define DIGITAL_R2 VEXSIM_PROS_NS E_CONTROLLER_DIGITAL_R2
#define DIGITAL_UP VEXSIM_PROS_NS E_CONTROLLER_DIGITAL_UP
#define DIGITAL_DOWN VEXSIM_PROS_NS E_CONTROLLER_DIGITAL_DOWN
#define DIGITAL_LEFT VEXSIM_PROS_NS E_CONTROLLER_DIGITAL_LEFT
#define DIGITAL_RIGHT VEXSIM_PROS_NS E_CONTROLLER_DIGITAL_RIGHT
#define DIGITAL_X VEXSIM_PROS_NS E_CONTROLLER_DIGITAL_X
#define DIGITAL_B VEXSIM_PROS_NS E_CONTROLLER_DIGITAL_B
#define DIGITAL_Y VEXSIM_PROS_NS E_CONTROLLER_DIGITAL_Y
#define DIGITAL_A VEXSIM_PROS_NS E_CONTROLLER_DIGITAL_A
#define DIGITAL_POWER VEXSIM_PROS_NS E_CONTROLLER_DIGITAL_POWER
#endif

#ifdef __cplusplus
namespace c {
#endif

int32_t controller_is_connected(controller_id_e_t id);
int32_t controller_get_analog(controller_id_e_t id, controller_analog_e_t channel);
int32_t controller_get_battery_capacity(controller_id_e_t id);
int32_t controller_get_battery_level(controller_id_e_t id);
int32_t controller_get_digital(controller_id_e_t id, controller_digital_e_t button);
int32_t controller_get_digital_new_press(controller_id_e_t id, controller_digital_e_t button);
int32_t controller_get_digital_new_release(controller_id_e_t id, controller_digital_e_t button);
int32_t controller_print(controller_id_e_t id, uint8_t line, uint8_t col, const char* fmt, ...);
int32_t controller_set_text(controller_id_e_t id, uint8_t line, uint8_t col, const char* str);
int32_t controller_clear_line(controller_id_e_t id, uint8_t line);
int32_t controller_clear(controller_id_e_t id);
int32_t controller_rumble(controller_id_e_t id, const char* rumble_pattern);

int32_t battery_get_voltage(void);
int32_t battery_get_current(void);
double battery_get_temperature(void);
double battery_get_capacity(void);

int32_t usd_is_installed(void);
int32_t usd_list_files(const char* path, char* buffer, int32_t len);

#ifdef __cplusplus
}  // namespace c
}  // namespace pros
}
#endif

#endif  // _PROS_MISC_H_
