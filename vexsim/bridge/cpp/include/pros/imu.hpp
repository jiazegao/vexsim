/* vexsim PROS 4 shim: pros::Imu. Heading is clockwise-positive, as on the V5. */
#ifndef _PROS_IMU_HPP_
#define _PROS_IMU_HPP_

#include <cstdint>
#include <iostream>
#include <vector>

#include "pros/device.hpp"
#include "pros/imu.h"
#include "pros/error.h"

namespace pros {

enum class ImuStatus { ready = 0, calibrating = 19, error = 0xFF };

inline namespace v5 {

class Imu : public Device {
	public:
	Imu(const std::uint8_t port) : Device(port, DeviceType::imu) {}
	Imu(const Device& device) : Imu(device.get_port()) {}

	static Imu get_imu() {
		for (std::uint8_t port = 1; port <= 21; port++) {
			if (Device::get_plugged_type(port) == DeviceType::imu) return Imu(port);
		}
		errno = ENODEV;
		return Imu(static_cast<std::uint8_t>(PROS_ERR_BYTE));
	}
	static std::vector<Imu> get_all_devices() {
		std::vector<Imu> out;
		for (std::uint8_t port = 1; port <= 21; port++) {
			if (Device::get_plugged_type(port) == DeviceType::imu) out.emplace_back(port);
		}
		return out;
	}

	virtual std::int32_t reset(bool blocking = false) const {
		return blocking ? pros::c::imu_reset_blocking(_port) : pros::c::imu_reset(_port);
	}
	virtual std::int32_t set_data_rate(std::uint32_t rate) const { return pros::c::imu_set_data_rate(_port, rate); }
	virtual double get_rotation() const { return pros::c::imu_get_rotation(_port); }
	virtual double get_heading() const { return pros::c::imu_get_heading(_port); }
	virtual pros::quaternion_s_t get_quaternion() const { return pros::c::imu_get_quaternion(_port); }
	virtual pros::euler_s_t get_euler() const { return pros::c::imu_get_euler(_port); }
	virtual double get_pitch() const { return pros::c::imu_get_pitch(_port); }
	virtual double get_roll() const { return pros::c::imu_get_roll(_port); }
	virtual double get_yaw() const { return pros::c::imu_get_yaw(_port); }
	virtual pros::imu_gyro_s_t get_gyro_rate() const { return pros::c::imu_get_gyro_rate(_port); }
	virtual std::int32_t tare_rotation() const { return pros::c::imu_tare_rotation(_port); }
	virtual std::int32_t tare_heading() const { return pros::c::imu_tare_heading(_port); }
	virtual std::int32_t tare_pitch() const { return pros::c::imu_tare_pitch(_port); }
	virtual std::int32_t tare_yaw() const { return pros::c::imu_tare_yaw(_port); }
	virtual std::int32_t tare_roll() const { return pros::c::imu_tare_roll(_port); }
	virtual std::int32_t tare() const { return pros::c::imu_tare(_port); }
	virtual std::int32_t tare_euler() const { return pros::c::imu_tare_euler(_port); }
	virtual std::int32_t set_heading(const double target) const { return pros::c::imu_set_heading(_port, target); }
	virtual std::int32_t set_rotation(const double target) const { return pros::c::imu_set_rotation(_port, target); }
	virtual std::int32_t set_yaw(const double target) const { return pros::c::imu_set_yaw(_port, target); }
	virtual std::int32_t set_pitch(const double target) const { return pros::c::imu_set_pitch(_port, target); }
	virtual std::int32_t set_roll(const double target) const { return pros::c::imu_set_roll(_port, target); }
	virtual std::int32_t set_euler(const pros::euler_s_t target) const { return pros::c::imu_set_euler(_port, target); }
	virtual pros::imu_accel_s_t get_accel() const { return pros::c::imu_get_accel(_port); }
	virtual pros::ImuStatus get_status() const { return static_cast<pros::ImuStatus>(pros::c::imu_get_status(_port)); }
	virtual bool is_calibrating() const {
		return (pros::c::imu_get_status(_port) & pros::E_IMU_STATUS_CALIBRATING) &&
		       pros::c::imu_get_status(_port) != pros::E_IMU_STATUS_ERROR;
	}
	virtual imu_orientation_e_t get_physical_orientation() const {
		return pros::c::imu_get_physical_orientation(_port);
	}

	friend std::ostream& operator<<(std::ostream& os, const pros::Imu& imu) {
		os << "Imu [port: " << static_cast<int>(imu._port) << ", rotation: " << imu.get_rotation()
		   << ", heading: " << imu.get_heading() << ", pitch: " << imu.get_pitch() << ", roll: " << imu.get_roll()
		   << ", yaw: " << imu.get_yaw() << ", gyro rate: {" << imu.get_gyro_rate().x << ", "
		   << imu.get_gyro_rate().y << ", " << imu.get_gyro_rate().z << "}]";
		return os;
	}
};

namespace literals {
inline const pros::Imu operator""_imu(const unsigned long long int i) {
	return pros::Imu(static_cast<std::uint8_t>(i));
}
}  // namespace literals

using IMU = Imu;

}  // namespace v5
}  // namespace pros

#endif  // _PROS_IMU_HPP_
