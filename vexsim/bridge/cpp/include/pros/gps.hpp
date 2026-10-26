/* vexsim PROS 4 shim: pros::Gps. */
#ifndef _PROS_GPS_HPP_
#define _PROS_GPS_HPP_

#include <cstdint>
#include <vector>

#include "pros/device.hpp"
#include "pros/error.h"
#include "pros/gps.h"

namespace pros {
inline namespace v5 {

class Gps : public Device {
	public:
	explicit Gps(const std::uint8_t port) : Device(port, DeviceType::gps) {}
	explicit Gps(const std::uint8_t port, double xInitial, double yInitial, double headingInitial)
	    : Device(port, DeviceType::gps) {
		pros::c::gps_set_position(port, xInitial, yInitial, headingInitial);
	}
	explicit Gps(const std::uint8_t port, double xOffset, double yOffset) : Device(port, DeviceType::gps) {
		pros::c::gps_set_offset(port, xOffset, yOffset);
	}
	explicit Gps(const std::uint8_t port, double xInitial, double yInitial, double headingInitial, double xOffset,
	             double yOffset)
	    : Device(port, DeviceType::gps) {
		pros::c::gps_initialize_full(port, xInitial, yInitial, headingInitial, xOffset, yOffset);
	}
	Gps(const Device& device) : Gps(device.get_port()) {}
	static std::vector<Gps> get_all_devices() {
		std::vector<Gps> out;
		for (std::uint8_t port = 1; port <= 21; port++) {
			if (Device::get_plugged_type(port) == DeviceType::gps) out.emplace_back(port);
		}
		return out;
	}

	virtual std::int32_t initialize_full(double xInitial, double yInitial, double headingInitial, double xOffset,
	                                     double yOffset) const {
		return pros::c::gps_initialize_full(_port, xInitial, yInitial, headingInitial, xOffset, yOffset);
	}
	virtual std::int32_t set_offset(double xOffset, double yOffset) const {
		return pros::c::gps_set_offset(_port, xOffset, yOffset);
	}
	virtual pros::gps_position_s_t get_offset() const { return pros::c::gps_get_offset(_port); }
	virtual std::int32_t set_position(double xInitial, double yInitial, double headingInitial) const {
		return pros::c::gps_set_position(_port, xInitial, yInitial, headingInitial);
	}
	virtual std::int32_t set_data_rate(std::uint32_t rate) const { return pros::c::gps_set_data_rate(_port, rate); }
	virtual double get_error() const { return pros::c::gps_get_error(_port); }
	virtual pros::gps_status_s_t get_position_and_orientation() const {
		return pros::c::gps_get_position_and_orientation(_port);
	}
	virtual pros::gps_position_s_t get_position() const { return pros::c::gps_get_position(_port); }
	virtual double get_position_x() const { return pros::c::gps_get_position_x(_port); }
	virtual double get_position_y() const { return pros::c::gps_get_position_y(_port); }
	virtual pros::gps_orientation_s_t get_orientation() const { return pros::c::gps_get_orientation(_port); }
	virtual double get_pitch() const { return pros::c::gps_get_pitch(_port); }
	virtual double get_roll() const { return pros::c::gps_get_roll(_port); }
	virtual double get_yaw() const { return pros::c::gps_get_yaw(_port); }
	virtual double get_heading() const { return pros::c::gps_get_heading(_port); }
	virtual double get_heading_raw() const { return pros::c::gps_get_heading_raw(_port); }
	virtual pros::gps_gyro_s_t get_gyro_rate() const { return pros::c::gps_get_gyro_rate(_port); }
	virtual double get_gyro_rate_x() const { return pros::c::gps_get_gyro_rate_x(_port); }
	virtual double get_gyro_rate_y() const { return pros::c::gps_get_gyro_rate_y(_port); }
	virtual double get_gyro_rate_z() const { return pros::c::gps_get_gyro_rate_z(_port); }
	virtual pros::gps_accel_s_t get_accel() const { return pros::c::gps_get_accel(_port); }
	virtual double get_accel_x() const { return pros::c::gps_get_accel_x(_port); }
	virtual double get_accel_y() const { return pros::c::gps_get_accel_y(_port); }
	virtual double get_accel_z() const { return pros::c::gps_get_accel_z(_port); }
};

using GPS = Gps;

namespace literals {
inline const pros::Gps operator""_gps(const unsigned long long int g) {
	return pros::Gps(static_cast<std::uint8_t>(g));
}
}  // namespace literals

}  // namespace v5
}  // namespace pros

#endif
