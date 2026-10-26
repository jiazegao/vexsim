/* vexsim PROS 4 shim: pros::Optical (not simulated yet: calls fail with ENODEV). */
#ifndef _PROS_OPTICAL_HPP_
#define _PROS_OPTICAL_HPP_

#include <cstdint>
#include <vector>

#include "pros/device.hpp"
#include "pros/optical.h"
#include "pros/unsupported.h"

namespace pros {
inline namespace v5 {

class Optical : public Device {
	public:
	Optical(const std::uint8_t port) : Device(port, DeviceType::optical) {}
	Optical(const Device& device) : Optical(device.get_port()) {}
	static std::vector<Optical> get_all_devices() { return {}; }
	virtual double get_hue() { return _fail_f(); }
	virtual double get_saturation() { return _fail_f(); }
	virtual double get_brightness() { return _fail_f(); }
	virtual std::int32_t get_proximity() { return _fail(); }
	virtual std::int32_t set_led_pwm(uint8_t value) {
		(void)value;
		return _fail();
	}
	virtual std::int32_t get_led_pwm() { return _fail(); }
	virtual pros::c::optical_rgb_s_t get_rgb() {
		_fail();
		return {PROS_ERR_F, PROS_ERR_F, PROS_ERR_F, PROS_ERR_F};
	}
	virtual pros::c::optical_raw_s_t get_raw() {
		_fail();
		return {PROS_ERR, PROS_ERR, PROS_ERR, PROS_ERR};
	}
	virtual pros::c::optical_direction_e_t get_gesture() {
		_fail();
		return pros::c::ERROR;
	}
	virtual pros::c::optical_gesture_s_t get_gesture_raw() {
		_fail();
		return {};
	}
	virtual std::int32_t enable_gesture() { return _fail(); }
	virtual std::int32_t disable_gesture() { return _fail(); }
	double get_integration_time() { return _fail_f(); }
	std::int32_t set_integration_time(double time) {
		(void)time;
		return _fail();
	}

	private:
	static std::int32_t _fail() { return vexsim_unsupported("pros::Optical"); }
	static double _fail_f() {
		vexsim_unsupported("pros::Optical");
		return PROS_ERR_F;
	}
};

namespace literals {
inline const pros::Optical operator""_opt(const unsigned long long int o) {
	return pros::Optical(static_cast<std::uint8_t>(o));
}
}  // namespace literals

}  // namespace v5
}  // namespace pros

#endif
