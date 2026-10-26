/* vexsim PROS 4 shim: pros::Rotation. A negative port reverses the sensor. */
#ifndef _PROS_ROTATION_HPP_
#define _PROS_ROTATION_HPP_

#include <cstdint>
#include <iostream>
#include <vector>

#include "pros/device.hpp"
#include "pros/rotation.h"

namespace pros {
inline namespace v5 {

class Rotation : public Device {
	public:
	Rotation(const std::int8_t port) : Device(static_cast<std::uint8_t>(port < 0 ? -port : port), DeviceType::rotation) {
		pros::c::rotation_set_reversed(_port, port < 0);
	}
	Rotation(const Device& device) : Rotation(static_cast<std::int8_t>(device.get_port())) {}

	virtual std::int32_t reset() { return pros::c::rotation_reset(_port); }
	virtual std::int32_t set_data_rate(std::uint32_t rate) const { return pros::c::rotation_set_data_rate(_port, rate); }
	virtual std::int32_t set_position(std::int32_t position) const {
		return pros::c::rotation_set_position(_port, position);
	}
	virtual std::int32_t reset_position(void) const { return pros::c::rotation_reset_position(_port); }
	static std::vector<Rotation> get_all_devices() {
		std::vector<Rotation> out;
		for (std::uint8_t port = 1; port <= 21; port++) {
			if (Device::get_plugged_type(port) == DeviceType::rotation) {
				out.emplace_back(static_cast<std::int8_t>(pros::c::rotation_get_reversed(port) == 1 ? -port : port));
			}
		}
		return out;
	}
	virtual std::int32_t get_position() const { return pros::c::rotation_get_position(_port); }
	virtual std::int32_t get_velocity() const { return pros::c::rotation_get_velocity(_port); }
	virtual std::int32_t get_angle() const { return pros::c::rotation_get_angle(_port); }
	virtual std::int32_t set_reversed(bool value) const { return pros::c::rotation_set_reversed(_port, value); }
	virtual std::int32_t reverse() const { return pros::c::rotation_reverse(_port); }
	virtual std::int32_t get_reversed() const { return pros::c::rotation_get_reversed(_port); }

	friend std::ostream& operator<<(std::ostream& os, const pros::Rotation& rotation) {
		os << "Rotation [port: " << static_cast<int>(rotation._port) << ", position: " << rotation.get_position()
		   << ", velocity: " << rotation.get_velocity() << ", angle: " << rotation.get_angle()
		   << ", reversed: " << rotation.get_reversed() << "]";
		return os;
	}
};

namespace literals {
inline const pros::Rotation operator""_rot(const unsigned long long int r) {
	return pros::Rotation(static_cast<std::int8_t>(r));
}
}  // namespace literals

}  // namespace v5
}  // namespace pros

#endif
