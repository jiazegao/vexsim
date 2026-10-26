/* C sources in a PROS project include the same api.h and use the C API. */
#include "main.h"

int c_side_check(void) {
	motor_move_velocity(1, 0);
	int32_t ok = motor_get_brake_mode(1) == E_MOTOR_BRAKE_COAST;
	task_delay(5);
	return ok && millis() >= 5 ? (int)millis() : -1;
}
