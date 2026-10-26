/* vexsim PROS 4 shim: pros::Gps (not simulated yet: calls fail with ENODEV). */
#ifndef _PROS_GPS_HPP_
#define _PROS_GPS_HPP_

#include <cstdint>
#include <vector>

#include "pros/device.hpp"
#include "pros/error.h"
#include "pros/gps.h"
#include "pros/unsupported.h"

namespace pros {
inline namespace v5 {

class Gps : public Device {
	public:
	explicit Gps(const std::uint8_t port) : Device(port, DeviceType::gps) {}
	explicit Gps(const std::uint8_t port, double xInitial, double yInitial, double headingInitial)
	    : Device(port, DeviceType::gps) {
		(void)xInitial, (void)yInitial, (void)headingInitial;
	}
	explicit Gps(const std::uint8_t port, double xOffset, double yOffset) : Device(port, DeviceType::gps) {
		(void)xOffset, (void)yOffset;
	}
	explicit Gps(const std::uint8_t port, double xInitial, double yInitial, double headingInitial, double xOffset,
	             double yOffset)
	    : Device(port, DeviceType::gps) {
		(void)xInitial, (void)yInitial, (void)headingInitial, (void)xOffset, (void)yOffset;
	}
	Gps(const Device& device) : Gps(device.get_port()) {}
	static std::vector<Gps> get_all_devices() { return {}; }

	virtual std::int32_t initialize_full(double, double, double, double, double) const { return _fail(); }
	virtual std::int32_t set_offset(double, double) const { return _fail(); }
	virtual pros::gps_position_s_t get_offset() const {
		_fail();
		return {PROS_ERR_F, PROS_ERR_F};
	}
	virtual std::int32_t set_position(double, double, double) const { return _fail(); }
	virtual std::int32_t set_data_rate(std::uint32_t) const { return _fail(); }
	virtual double get_error() const { return _fail_f(); }
	virtual pros::gps_status_s_t get_position_and_orientation() const {
		_fail();
		return {PROS_ERR_F, PROS_ERR_F, PROS_ERR_F, PROS_ERR_F, PROS_ERR_F};
	}
	virtual pros::gps_position_s_t get_position() const {
		_fail();
		return {PROS_ERR_F, PROS_ERR_F};
	}
	virtual double get_position_x() const { return _fail_f(); }
	virtual double get_position_y() const { return _fail_f(); }
	virtual pros::gps_orientation_s_t get_orientation() const {
		_fail();
		return {PROS_ERR_F, PROS_ERR_F, PROS_ERR_F};
	}
	virtual double get_pitch() const { return _fail_f(); }
	virtual double get_roll() const { return _fail_f(); }
	virtual double get_yaw() const { return _fail_f(); }
	virtual double get_heading() const { return _fail_f(); }
	virtual double get_heading_raw() const { return _fail_f(); }
	virtual pros::gps_gyro_s_t get_gyro_rate() const {
		_fail();
		return {PROS_ERR_F, PROS_ERR_F, PROS_ERR_F};
	}
	virtual pros::gps_accel_s_t get_accel() const {
		_fail();
		return {PROS_ERR_F, PROS_ERR_F, PROS_ERR_F};
	}

	private:
	static std::int32_t _fail() { return vexsim_unsupported("pros::Gps"); }
	static double _fail_f() {
		vexsim_unsupported("pros::Gps");
		return PROS_ERR_F;
	}
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
