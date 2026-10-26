/* vexsim PROS 4 shim: pros::MotorGroup. */
#ifndef _PROS_MOTOR_GROUP_HPP_
#define _PROS_MOTOR_GROUP_HPP_

#include <cstdint>
#include <initializer_list>
#include <iostream>
#include <vector>

#include "pros/abstract_motor.hpp"
#include "pros/colors.hpp"
#include "pros/device.hpp"
#include "pros/motors.h"
#include "pros/motors.hpp"
#include "pros/rtos.hpp"

namespace pros {
inline namespace v5 {

class MotorGroup : public vexsim_detail::MotorCommon {
	public:
	MotorGroup(const std::initializer_list<std::int8_t> ports,
	           const pros::v5::MotorGears gearset = pros::v5::MotorGears::invalid,
	           const pros::v5::MotorUnits encoder_units = pros::v5::MotorUnits::invalid)
	    : MotorGroup(std::vector<std::int8_t>(ports), gearset, encoder_units) {}
	MotorGroup(const std::vector<std::int8_t>& ports, const pros::v5::MotorGears gearset = pros::v5::MotorGears::invalid,
	           const pros::v5::MotorUnits encoder_units = pros::v5::MotorUnits::invalid)
	    : MotorCommon(ports) {
		if (gearset != pros::v5::MotorGears::invalid) set_gearing_all(gearset);
		if (encoder_units != pros::v5::MotorUnits::invalid) set_encoder_units_all(encoder_units);
	}
	MotorGroup(AbstractMotor& motor_group) : MotorCommon(motor_group.get_port_all()) {}

	void operator+=(AbstractMotor& other) {
		for (auto port : other.get_port_all()) _ports.push_back(port);
	}
	void append(AbstractMotor& other) { (*this) += other; }
	void erase_port(std::int8_t port) {
		std::int8_t target = port < 0 ? -port : port;
		for (auto it = _ports.begin(); it != _ports.end();) {
			if ((*it < 0 ? -*it : *it) == target) {
				it = _ports.erase(it);
			} else {
				++it;
			}
		}
	}
};

}  // namespace v5
}  // namespace pros

#endif  // _PROS_MOTOR_GROUP_HPP_
