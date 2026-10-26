/* vexsim PROS 4 shim: pros::Motor. */
#ifndef _PROS_MOTORS_HPP_
#define _PROS_MOTORS_HPP_

#include <cstdint>
#include <iostream>
#include <vector>

#include "pros/abstract_motor.hpp"
#include "pros/device.hpp"
#include "pros/motors.h"
#include "pros/rtos.hpp"

namespace pros {
inline namespace v5 {

class Motor : public vexsim_detail::MotorCommon, public Device {
	public:
	Motor(const std::int8_t port, const pros::v5::MotorGears gearset = pros::v5::MotorGears::invalid,
	      const pros::v5::MotorUnits encoder_units = pros::v5::MotorUnits::invalid)
	    : MotorCommon({port}), Device(static_cast<std::uint8_t>(port < 0 ? -port : port), DeviceType::motor) {
		if (gearset != pros::v5::MotorGears::invalid) set_gearing(gearset);
		if (encoder_units != pros::v5::MotorUnits::invalid) set_encoder_units(encoder_units);
	}
	Motor(const Device& device) : Motor(static_cast<std::int8_t>(device.get_port())) {}

	using MotorCommon::get_port;
	static std::vector<Motor> get_all_devices() {
		std::vector<Motor> out;
		for (std::uint8_t port = 1; port <= 21; port++) {
			if (Device::get_plugged_type(port) == DeviceType::motor) out.emplace_back(static_cast<std::int8_t>(port));
		}
		return out;
	}

	friend std::ostream& operator<<(std::ostream& os, pros::Motor& motor) {
		os << "Motor [port: " << static_cast<int>(motor.get_port()) << ", brake mode: "
		   << static_cast<int>(motor.get_brake_mode()) << ", current draw: " << motor.get_current_draw()
		   << ", current limit: " << motor.get_current_limit() << ", direction: " << motor.get_direction()
		   << ", efficiency: " << motor.get_efficiency() << ", encoder units: "
		   << static_cast<int>(motor.get_encoder_units()) << ", gearing: " << static_cast<int>(motor.get_gearing())
		   << ", is over temp: " << motor.is_over_temp() << ", position: " << motor.get_position()
		   << ", reversed: " << motor.is_reversed() << ", temperature: " << motor.get_temperature()
		   << ", torque: " << motor.get_torque() << ", voltage: " << motor.get_voltage() << "]";
		return os;
	}
};

namespace literals {
inline const pros::Motor operator""_mtr(const unsigned long long int m) {
	return pros::Motor(static_cast<std::int8_t>(m));
}
inline const pros::Motor operator""_rmtr(const unsigned long long int m) {
	return pros::Motor(static_cast<std::int8_t>(-static_cast<int>(m)));
}
}  // namespace literals

}  // namespace v5
}  // namespace pros

#endif  // _PROS_MOTORS_HPP_
