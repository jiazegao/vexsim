/* vexsim PROS 4 shim: V5 smart motor C API. */
#ifndef _PROS_MOTORS_H_
#define _PROS_MOTORS_H_

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
namespace pros {
#endif

typedef enum motor_fault_e {
	E_MOTOR_FAULT_NO_FAULTS = 0x00,
	E_MOTOR_FAULT_MOTOR_OVER_TEMP = 0x01,
	E_MOTOR_FAULT_DRIVER_FAULT = 0x02,
	E_MOTOR_FAULT_OVER_CURRENT = 0x04,
	E_MOTOR_FAULT_DRV_OVER_CURRENT = 0x08
} motor_fault_e_t;

typedef enum motor_flag_e {
	E_MOTOR_FLAGS_NONE = 0x00,
	E_MOTOR_FLAGS_BUSY = 0x01,
	E_MOTOR_FLAGS_ZERO_VELOCITY = 0x02,
	E_MOTOR_FLAGS_ZERO_POSITION = 0x04
} motor_flag_e_t;

typedef enum motor_brake_mode_e {
	E_MOTOR_BRAKE_COAST = 0,
	E_MOTOR_BRAKE_BRAKE = 1,
	E_MOTOR_BRAKE_HOLD = 2,
	E_MOTOR_BRAKE_INVALID = INT32_MAX
} motor_brake_mode_e_t;

typedef enum motor_encoder_units_e {
	E_MOTOR_ENCODER_DEGREES = 0,
	E_MOTOR_ENCODER_ROTATIONS = 1,
	E_MOTOR_ENCODER_COUNTS = 2,
	E_MOTOR_ENCODER_INVALID = INT32_MAX
} motor_encoder_units_e_t;

typedef enum motor_gearset_e {
	E_MOTOR_GEARSET_36 = 0,
	E_MOTOR_GEAR_RED = E_MOTOR_GEARSET_36,
	E_MOTOR_GEAR_100 = E_MOTOR_GEARSET_36,
	E_MOTOR_GEARSET_18 = 1,
	E_MOTOR_GEAR_GREEN = E_MOTOR_GEARSET_18,
	E_MOTOR_GEAR_200 = E_MOTOR_GEARSET_18,
	E_MOTOR_GEARSET_06 = 2,
	E_MOTOR_GEAR_BLUE = E_MOTOR_GEARSET_06,
	E_MOTOR_GEAR_600 = E_MOTOR_GEARSET_06,
	E_MOTOR_GEARSET_INVALID = INT32_MAX
} motor_gearset_e_t;

typedef enum motor_type_e {
	E_MOTOR_TYPE_V5 = 0,
	E_MOTOR_TYPE_EXP = 1,
	E_MOTOR_TYPE_INVALID = INT32_MAX
} motor_type_e_t;

#ifdef PROS_USE_SIMPLE_NAMES
#ifndef VEXSIM_PROS_NS
#ifdef __cplusplus
#define VEXSIM_PROS_NS pros::
#else
#define VEXSIM_PROS_NS
#endif
#endif
#define MOTOR_FAULT_NO_FAULTS VEXSIM_PROS_NS E_MOTOR_FAULT_NO_FAULTS
#define MOTOR_FAULT_MOTOR_OVER_TEMP VEXSIM_PROS_NS E_MOTOR_FAULT_MOTOR_OVER_TEMP
#define MOTOR_FAULT_DRIVER_FAULT VEXSIM_PROS_NS E_MOTOR_FAULT_DRIVER_FAULT
#define MOTOR_FAULT_OVER_CURRENT VEXSIM_PROS_NS E_MOTOR_FAULT_DRV_OVER_CURRENT
#define MOTOR_FAULT_DRV_OVER_CURRENT VEXSIM_PROS_NS E_MOTOR_FAULT_DRV_OVER_CURRENT
#define MOTOR_FLAGS_NONE VEXSIM_PROS_NS E_MOTOR_FLAGS_NONE
#define MOTOR_FLAGS_BUSY VEXSIM_PROS_NS E_MOTOR_FLAGS_BUSY
#define MOTOR_FLAGS_ZERO_VELOCITY VEXSIM_PROS_NS E_MOTOR_FLAGS_ZERO_VELOCITY
#define MOTOR_FLAGS_ZERO_POSITION VEXSIM_PROS_NS E_MOTOR_FLAGS_ZERO_POSITION
#define MOTOR_BRAKE_COAST VEXSIM_PROS_NS E_MOTOR_BRAKE_COAST
#define MOTOR_BRAKE_BRAKE VEXSIM_PROS_NS E_MOTOR_BRAKE_BRAKE
#define MOTOR_BRAKE_HOLD VEXSIM_PROS_NS E_MOTOR_BRAKE_HOLD
#define MOTOR_BRAKE_INVALID VEXSIM_PROS_NS E_MOTOR_BRAKE_INVALID
#define MOTOR_ENCODER_DEGREES VEXSIM_PROS_NS E_MOTOR_ENCODER_DEGREES
#define MOTOR_ENCODER_ROTATIONS VEXSIM_PROS_NS E_MOTOR_ENCODER_ROTATIONS
#define MOTOR_ENCODER_COUNTS VEXSIM_PROS_NS E_MOTOR_ENCODER_COUNTS
#define MOTOR_ENCODER_INVALID VEXSIM_PROS_NS E_MOTOR_ENCODER_INVALID
#define MOTOR_GEARSET_36 VEXSIM_PROS_NS E_MOTOR_GEARSET_36
#define MOTOR_GEAR_RED VEXSIM_PROS_NS E_MOTOR_GEAR_RED
#define MOTOR_GEAR_100 VEXSIM_PROS_NS E_MOTOR_GEAR_100
#define MOTOR_GEARSET_18 VEXSIM_PROS_NS E_MOTOR_GEARSET_18
#define MOTOR_GEAR_GREEN VEXSIM_PROS_NS E_MOTOR_GEAR_GREEN
#define MOTOR_GEAR_200 VEXSIM_PROS_NS E_MOTOR_GEAR_200
#define MOTOR_GEARSET_06 VEXSIM_PROS_NS E_MOTOR_GEARSET_06
#define MOTOR_GEARSET_6 VEXSIM_PROS_NS E_MOTOR_GEARSET_06
#define MOTOR_GEAR_BLUE VEXSIM_PROS_NS E_MOTOR_GEAR_BLUE
#define MOTOR_GEAR_600 VEXSIM_PROS_NS E_MOTOR_GEAR_600
#define MOTOR_GEARSET_INVALID VEXSIM_PROS_NS E_MOTOR_GEARSET_INVALID
#define MOTOR_TYPE_V5 VEXSIM_PROS_NS E_MOTOR_TYPE_V5
#define MOTOR_TYPE_EXP VEXSIM_PROS_NS E_MOTOR_TYPE_EXP
#define MOTOR_TYPE_INVALID VEXSIM_PROS_NS E_MOTOR_TYPE_INVALID
#endif

#ifdef __cplusplus
namespace c {
#endif

int32_t motor_move(int8_t port, int32_t voltage);
int32_t motor_brake(int8_t port);
int32_t motor_move_absolute(int8_t port, double position, const int32_t velocity);
int32_t motor_move_relative(int8_t port, double position, const int32_t velocity);
int32_t motor_move_velocity(int8_t port, const int32_t velocity);
int32_t motor_move_voltage(int8_t port, const int32_t voltage);
int32_t motor_modify_profiled_velocity(int8_t port, const int32_t velocity);
double motor_get_target_position(int8_t port);
int32_t motor_get_target_velocity(int8_t port);
double motor_get_actual_velocity(int8_t port);
int32_t motor_get_current_draw(int8_t port);
int32_t motor_get_direction(int8_t port);
double motor_get_efficiency(int8_t port);
int32_t motor_is_over_current(int8_t port);
int32_t motor_is_over_temp(int8_t port);
uint32_t motor_get_faults(int8_t port);
uint32_t motor_get_flags(int8_t port);
int32_t motor_get_raw_position(int8_t port, uint32_t* const timestamp);
double motor_get_position(int8_t port);
double motor_get_power(int8_t port);
double motor_get_temperature(int8_t port);
double motor_get_torque(int8_t port);
int32_t motor_get_voltage(int8_t port);
int32_t motor_set_zero_position(int8_t port, const double position);
int32_t motor_tare_position(int8_t port);
int32_t motor_set_brake_mode(int8_t port, const motor_brake_mode_e_t mode);
int32_t motor_set_current_limit(int8_t port, const int32_t limit);
int32_t motor_set_encoder_units(int8_t port, const motor_encoder_units_e_t units);
int32_t motor_set_gearing(int8_t port, const motor_gearset_e_t gearset);
int32_t motor_set_voltage_limit(int8_t port, const int32_t limit);
motor_brake_mode_e_t motor_get_brake_mode(int8_t port);
int32_t motor_get_current_limit(int8_t port);
motor_encoder_units_e_t motor_get_encoder_units(int8_t port);
motor_gearset_e_t motor_get_gearing(int8_t port);
int32_t motor_get_voltage_limit(int8_t port);
motor_type_e_t motor_get_type(int8_t port);

#ifdef __cplusplus
}  // namespace c
}  // namespace pros
}
#endif

#endif  // _PROS_MOTORS_H_
