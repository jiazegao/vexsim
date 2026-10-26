/*
 * vexsim PROS 4 shim: three-wire (ADI) ports. The simulator has no ADI
 * devices yet: outputs (pneumatics, LEDs, motors) remember what was written,
 * inputs read 0, and the first use logs a one-time note in the console.
 */
#ifndef _PROS_ADI_H_
#define _PROS_ADI_H_

#include <stdbool.h>
#include <stdint.h>

#include "pros/error.h"

#ifdef __cplusplus
extern "C" {
namespace pros {
#endif

typedef enum adi_port_config_e {
	E_ADI_ANALOG_IN = 0,
	E_ADI_ANALOG_OUT = 1,
	E_ADI_DIGITAL_IN = 2,
	E_ADI_DIGITAL_OUT = 3,
	E_ADI_SMART_BUTTON = E_ADI_DIGITAL_IN,
	E_ADI_SMART_POT = E_ADI_ANALOG_IN,
	E_ADI_LEGACY_BUTTON = E_ADI_DIGITAL_IN,
	E_ADI_LEGACY_POT = E_ADI_ANALOG_IN,
	E_ADI_LEGACY_LINE_SENSOR = E_ADI_ANALOG_IN,
	E_ADI_LEGACY_LIGHT_SENSOR = E_ADI_ANALOG_IN,
	E_ADI_LEGACY_GYRO = 10,
	E_ADI_LEGACY_ACCELEROMETER = E_ADI_ANALOG_IN,
	E_ADI_LEGACY_SERVO = 12,
	E_ADI_LEGACY_PWM = 13,
	E_ADI_LEGACY_ENCODER = 14,
	E_ADI_LEGACY_ULTRASONIC = 15,
	E_ADI_TYPE_UNDEFINED = 255,
	E_ADI_ERR = PROS_ERR
} adi_port_config_e_t;

typedef enum adi_potentiometer_type_e { E_ADI_POT_EDR = 0, E_ADI_POT_V2 } adi_potentiometer_type_e_t;

#ifdef PROS_USE_SIMPLE_NAMES
#ifdef __cplusplus
#define ADI_ANALOG_IN pros::E_ADI_ANALOG_IN
#define ADI_ANALOG_OUT pros::E_ADI_ANALOG_OUT
#define ADI_DIGITAL_IN pros::E_ADI_DIGITAL_IN
#define ADI_DIGITAL_OUT pros::E_ADI_DIGITAL_OUT
#define ADI_LEGACY_GYRO pros::E_ADI_LEGACY_GYRO
#define ADI_LEGACY_SERVO pros::E_ADI_LEGACY_SERVO
#define ADI_LEGACY_PWM pros::E_ADI_LEGACY_PWM
#define ADI_LEGACY_ENCODER pros::E_ADI_LEGACY_ENCODER
#define ADI_LEGACY_ULTRASONIC pros::E_ADI_LEGACY_ULTRASONIC
#define ADI_TYPE_UNDEFINED pros::E_ADI_TYPE_UNDEFINED
#define ADI_ERR pros::E_ADI_ERR
#else
#define ADI_ANALOG_IN E_ADI_ANALOG_IN
#define ADI_ANALOG_OUT E_ADI_ANALOG_OUT
#define ADI_DIGITAL_IN E_ADI_DIGITAL_IN
#define ADI_DIGITAL_OUT E_ADI_DIGITAL_OUT
#define ADI_LEGACY_GYRO E_ADI_LEGACY_GYRO
#define ADI_LEGACY_SERVO E_ADI_LEGACY_SERVO
#define ADI_LEGACY_PWM E_ADI_LEGACY_PWM
#define ADI_LEGACY_ENCODER E_ADI_LEGACY_ENCODER
#define ADI_LEGACY_ULTRASONIC E_ADI_LEGACY_ULTRASONIC
#define ADI_TYPE_UNDEFINED E_ADI_TYPE_UNDEFINED
#define ADI_ERR E_ADI_ERR
#endif
#endif

#define INTERNAL_ADI_PORT 22
#define NUM_ADI_PORTS 8
#define HIGH 1
#define LOW 0
#define INPUT 0x00
#define OUTPUT 0x01
#define INPUT_ANALOG 0x02
#define OUTPUT_ANALOG 0x03

#ifdef __cplusplus
namespace c {
#endif

typedef int32_t adi_encoder_t;
typedef int32_t adi_ultrasonic_t;
typedef int32_t adi_gyro_t;
typedef int32_t adi_potentiometer_t;
typedef int32_t adi_led_t;

/* Every ADI call goes through these; smart_port 22 is the brain's own ADI ports. */
adi_port_config_e_t ext_adi_port_get_config(uint8_t smart_port, uint8_t adi_port);
int32_t ext_adi_port_get_value(uint8_t smart_port, uint8_t adi_port);
int32_t ext_adi_port_set_config(uint8_t smart_port, uint8_t adi_port, adi_port_config_e_t type);
int32_t ext_adi_port_set_value(uint8_t smart_port, uint8_t adi_port, int32_t value);

adi_port_config_e_t adi_port_get_config(uint8_t port);
int32_t adi_port_get_value(uint8_t port);
int32_t adi_port_set_config(uint8_t port, adi_port_config_e_t type);
int32_t adi_port_set_value(uint8_t port, int32_t value);
int32_t adi_analog_calibrate(uint8_t port);
int32_t adi_analog_read(uint8_t port);
int32_t adi_analog_read_calibrated(uint8_t port);
int32_t adi_analog_read_calibrated_HR(uint8_t port);
int32_t adi_digital_read(uint8_t port);
int32_t adi_digital_get_new_press(uint8_t port);
int32_t adi_digital_write(uint8_t port, bool value);
int32_t adi_pin_mode(uint8_t port, uint8_t mode);
int32_t adi_motor_set(uint8_t port, int8_t speed);
int32_t adi_motor_get(uint8_t port);
int32_t adi_motor_stop(uint8_t port);
int32_t adi_encoder_get(adi_encoder_t enc);
adi_encoder_t adi_encoder_init(uint8_t port_top, uint8_t port_bottom, bool reverse);
int32_t adi_encoder_reset(adi_encoder_t enc);
int32_t adi_encoder_shutdown(adi_encoder_t enc);
int32_t adi_ultrasonic_get(adi_ultrasonic_t ult);
adi_ultrasonic_t adi_ultrasonic_init(uint8_t port_ping, uint8_t port_echo);
int32_t adi_ultrasonic_shutdown(adi_ultrasonic_t ult);
double adi_gyro_get(adi_gyro_t gyro);
adi_gyro_t adi_gyro_init(uint8_t port, double multiplier);
int32_t adi_gyro_reset(adi_gyro_t gyro);
int32_t adi_gyro_shutdown(adi_gyro_t gyro);
adi_potentiometer_t adi_potentiometer_init(uint8_t port);
adi_potentiometer_t adi_potentiometer_type_init(uint8_t port, adi_potentiometer_type_e_t potentiometer_type);
double adi_potentiometer_get_angle(adi_potentiometer_t potentiometer);

#ifdef __cplusplus
}  // namespace c
}  // namespace pros
}
#endif

#endif  // _PROS_ADI_H_
