/* vexsim PROS 4 shim: pros::Distance. */
#ifndef _PROS_DISTANCE_HPP_
#define _PROS_DISTANCE_HPP_

#include <cstdint>
#include <iostream>
#include <vector>

#include "pros/device.hpp"
#include "pros/distance.h"

namespace pros {
inline namespace v5 {

class Distance : public Device {
	public:
	Distance(const std::uint8_t port) : Device(port, DeviceType::distance) {}
	Distance(const Device& device) : Distance(device.get_port()) {}

	virtual std::int32_t get() { return pros::c::distance_get(_port); }
	virtual std::int32_t get_distance() { return get(); }
	static std::vector<Distance> get_all_devices() {
		std::vector<Distance> out;
		for (std::uint8_t port = 1; port <= 21; port++) {
			if (Device::get_plugged_type(port) == DeviceType::distance) out.emplace_back(port);
		}
		return out;
	}
	virtual std::int32_t get_confidence() { return pros::c::distance_get_confidence(_port); }
	virtual std::int32_t get_object_size() { return pros::c::distance_get_object_size(_port); }
	virtual double get_object_velocity() { return pros::c::distance_get_object_velocity(_port); }

	friend std::ostream& operator<<(std::ostream& os, pros::Distance& distance) {
		os << "Distance [port: " << static_cast<int>(distance._port) << ", distance: " << distance.get()
		   << ", confidence: " << distance.get_confidence() << ", object size: " << distance.get_object_size()
		   << ", object velocity: " << distance.get_object_velocity() << "]";
		return os;
	}
};

namespace literals {
inline const pros::Distance operator""_dist(const unsigned long long int d) {
	return pros::Distance(static_cast<std::uint8_t>(d));
}
}  // namespace literals

}  // namespace v5
}  // namespace pros

#endif
