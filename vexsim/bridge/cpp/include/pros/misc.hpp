/* vexsim PROS 4 shim: pros::Controller, pros::battery, pros::competition. */
#ifndef _PROS_MISC_HPP_
#define _PROS_MISC_HPP_

#include <cstdint>
#include <string>

#include "pros/misc.h"

namespace pros {
inline namespace v5 {

class Controller {
	public:
	explicit Controller(controller_id_e_t id) : _id(id) {}
	std::int32_t is_connected(void) { return pros::c::controller_is_connected(_id); }
	std::int32_t get_analog(controller_analog_e_t channel) { return pros::c::controller_get_analog(_id, channel); }
	std::int32_t get_battery_capacity(void) { return pros::c::controller_get_battery_capacity(_id); }
	std::int32_t get_battery_level(void) { return pros::c::controller_get_battery_level(_id); }
	std::int32_t get_digital(controller_digital_e_t button) { return pros::c::controller_get_digital(_id, button); }
	std::int32_t get_digital_new_press(controller_digital_e_t button) {
		return pros::c::controller_get_digital_new_press(_id, button);
	}
	std::int32_t get_digital_new_release(controller_digital_e_t button) {
		return pros::c::controller_get_digital_new_release(_id, button);
	}
	template <typename T>
	T convert_args(T arg) {
		return arg;
	}
	const char* convert_args(const std::string& arg) { return arg.c_str(); }
	template <typename... Params>
	std::int32_t print(std::uint8_t line, std::uint8_t col, const char* fmt, Params... args) {
		return pros::c::controller_print(_id, line, col, fmt, convert_args(args)...);
	}
	std::int32_t set_text(std::uint8_t line, std::uint8_t col, const char* str) {
		return pros::c::controller_set_text(_id, line, col, str);
	}
	std::int32_t set_text(std::uint8_t line, std::uint8_t col, const std::string& str) {
		return pros::c::controller_set_text(_id, line, col, str.c_str());
	}
	std::int32_t clear_line(std::uint8_t line) { return pros::c::controller_clear_line(_id, line); }
	std::int32_t rumble(const char* rumble_pattern) { return pros::c::controller_rumble(_id, rumble_pattern); }
	std::int32_t clear(void) { return pros::c::controller_clear(_id); }

	private:
	controller_id_e_t _id;
};

}  // namespace v5

namespace battery {
inline double get_capacity(void) { return pros::c::battery_get_capacity(); }
inline int32_t get_current(void) { return pros::c::battery_get_current(); }
inline double get_temperature(void) { return pros::c::battery_get_temperature(); }
inline int32_t get_voltage(void) { return pros::c::battery_get_voltage(); }
}  // namespace battery

namespace competition {
inline std::uint8_t get_status(void) { return pros::c::competition_get_status(); }
inline std::uint8_t is_autonomous(void) { return pros::c::competition_is_autonomous(); }
inline std::uint8_t is_connected(void) { return pros::c::competition_is_connected(); }
inline std::uint8_t is_disabled(void) { return pros::c::competition_is_disabled(); }
inline std::uint8_t is_field_control(void) { return pros::c::competition_is_field(); }
inline std::uint8_t is_competition_switch(void) { return pros::c::competition_is_switch(); }
}  // namespace competition

namespace usd {
inline std::int32_t is_installed(void) { return pros::c::usd_is_installed(); }
inline std::int32_t list_files(const char* path, char* buffer, std::int32_t len) {
	return pros::c::usd_list_files(path, buffer, len);
}
}  // namespace usd

}  // namespace pros

#endif  // _PROS_MISC_HPP_
