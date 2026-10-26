/* vexsim PROS 4 shim: the Device base class. */
#ifndef _PROS_DEVICE_HPP_
#define _PROS_DEVICE_HPP_

#include <cstdint>
#include <vector>

#include "pros/device.h"

namespace pros {
inline namespace v5 {

enum class DeviceType {
	none = 0,
	motor = 2,
	rotation = 4,
	imu = 6,
	distance = 7,
	radio = 8,
	vision = 11,
	adi = 12,
	optical = 16,
	gps = 20,
	aivision = 29,
	serial = 129,
	undefined = 255
};

class Device {
	public:
	explicit Device(const std::uint8_t port) : _port(port) {}
	virtual ~Device() = default;
	std::uint8_t get_port(void) const { return _port; }
	virtual bool is_installed() {
		return static_cast<int>(get_plugged_type()) == static_cast<int>(_deviceType) && _deviceType != DeviceType::none;
	}
	pros::DeviceType get_plugged_type() const { return get_plugged_type(_port); }
	static pros::DeviceType get_plugged_type(std::uint8_t port) {
		return static_cast<pros::DeviceType>(pros::c::get_plugged_type(port));
	}
	static std::vector<Device> get_all_devices(pros::DeviceType device_type = pros::DeviceType::undefined) {
		std::vector<Device> out;
		for (std::uint8_t port = 1; port <= 21; port++) {
			auto type = get_plugged_type(port);
			if (type != DeviceType::none && (device_type == DeviceType::undefined || type == device_type)) {
				out.push_back(Device(port, type));
			}
		}
		return out;
	}

	protected:
	Device(const std::uint8_t port, const enum DeviceType deviceType) : _port(port), _deviceType(deviceType) {}
	const std::uint8_t _port;
	const enum DeviceType _deviceType = pros::DeviceType::none;
};

}  // namespace v5
}  // namespace pros

#endif
