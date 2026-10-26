/* vexsim PROS 4 shim: motor enums and the AbstractMotor interface. */
#ifndef _PROS_ABSTRACT_MOTORS_HPP_
#define _PROS_ABSTRACT_MOTORS_HPP_

#include <cerrno>
#include <cstdint>
#include <iostream>
#include <utility>
#include <vector>

#include "pros/device.hpp"
#include "pros/error.h"
#include "pros/motors.h"
#include "pros/rtos.hpp"

namespace pros {
inline namespace v5 {

enum class MotorBrake { coast = 0, brake = 1, hold = 2, invalid = INT32_MAX };

enum class MotorEncoderUnits { degrees = 0, deg = 0, rotations = 1, counts = 2, invalid = INT32_MAX };
using MotorUnits = MotorEncoderUnits;

enum class MotorGears {
	ratio_36_to_1 = 0,
	red = ratio_36_to_1,
	rpm_100 = ratio_36_to_1,
	ratio_18_to_1 = 1,
	green = ratio_18_to_1,
	rpm_200 = ratio_18_to_1,
	ratio_6_to_1 = 2,
	blue = ratio_6_to_1,
	rpm_600 = ratio_6_to_1,
	invalid = INT32_MAX
};

enum class MotorType { v5 = 0, exp = 1, invalid = INT32_MAX };

using MotorGearset = MotorGears;
using MotorCart = MotorGears;
using MotorCartridge = MotorGears;
using MotorGear = MotorGears;

class AbstractMotor {
	public:
	virtual ~AbstractMotor() = default;
	virtual std::int32_t move(std::int32_t voltage) const = 0;
	virtual std::int32_t move_absolute(const double position, const std::int32_t velocity) const = 0;
	virtual std::int32_t move_relative(const double position, const std::int32_t velocity) const = 0;
	virtual std::int32_t move_velocity(const std::int32_t velocity) const = 0;
	virtual std::int32_t move_voltage(const std::int32_t voltage) const = 0;
	virtual std::int32_t brake(void) const = 0;
	virtual std::int32_t modify_profiled_velocity(const std::int32_t velocity) const = 0;
	virtual double get_target_position(const std::uint8_t index = 0) const = 0;
	virtual std::vector<double> get_target_position_all(void) const = 0;
	virtual std::int32_t get_target_velocity(const std::uint8_t index = 0) const = 0;
	virtual std::vector<std::int32_t> get_target_velocity_all(void) const = 0;
	virtual double get_actual_velocity(const std::uint8_t index = 0) const = 0;
	virtual std::vector<double> get_actual_velocity_all(void) const = 0;
	virtual std::int32_t get_current_draw(const std::uint8_t index = 0) const = 0;
	virtual std::vector<std::int32_t> get_current_draw_all(void) const = 0;
	virtual std::int32_t get_direction(const std::uint8_t index = 0) const = 0;
	virtual std::vector<std::int32_t> get_direction_all(void) const = 0;
	virtual double get_efficiency(const std::uint8_t index = 0) const = 0;
	virtual std::vector<double> get_efficiency_all(void) const = 0;
	virtual std::uint32_t get_faults(const std::uint8_t index = 0) const = 0;
	virtual std::vector<std::uint32_t> get_faults_all(void) const = 0;
	virtual std::uint32_t get_flags(const std::uint8_t index = 0) const = 0;
	virtual std::vector<std::uint32_t> get_flags_all(void) const = 0;
	virtual double get_position(const std::uint8_t index = 0) const = 0;
	virtual std::vector<double> get_position_all(void) const = 0;
	virtual double get_power(const std::uint8_t index = 0) const = 0;
	virtual std::vector<double> get_power_all(void) const = 0;
	virtual std::int32_t get_raw_position(std::uint32_t* const timestamp, const std::uint8_t index = 0) const = 0;
	virtual std::vector<std::int32_t> get_raw_position_all(std::uint32_t* const timestamp) const = 0;
	virtual double get_temperature(const std::uint8_t index = 0) const = 0;
	virtual std::vector<double> get_temperature_all(void) const = 0;
	virtual double get_torque(const std::uint8_t index = 0) const = 0;
	virtual std::vector<double> get_torque_all(void) const = 0;
	virtual std::int32_t get_voltage(const std::uint8_t index = 0) const = 0;
	virtual std::vector<std::int32_t> get_voltage_all(void) const = 0;
	virtual std::int32_t is_over_current(const std::uint8_t index = 0) const = 0;
	virtual std::vector<std::int32_t> is_over_current_all(void) const = 0;
	virtual std::int32_t is_over_temp(const std::uint8_t index = 0) const = 0;
	virtual std::vector<std::int32_t> is_over_temp_all(void) const = 0;
	virtual MotorBrake get_brake_mode(const std::uint8_t index = 0) const = 0;
	virtual std::vector<MotorBrake> get_brake_mode_all(void) const = 0;
	virtual std::int32_t get_current_limit(const std::uint8_t index = 0) const = 0;
	virtual std::vector<std::int32_t> get_current_limit_all(void) const = 0;
	virtual MotorUnits get_encoder_units(const std::uint8_t index = 0) const = 0;
	virtual std::vector<MotorUnits> get_encoder_units_all(void) const = 0;
	virtual MotorGears get_gearing(const std::uint8_t index = 0) const = 0;
	virtual std::vector<MotorGears> get_gearing_all(void) const = 0;
	virtual std::vector<std::int8_t> get_port_all(void) const = 0;
	virtual std::int32_t get_voltage_limit(const std::uint8_t index = 0) const = 0;
	virtual std::vector<std::int32_t> get_voltage_limit_all(void) const = 0;
	virtual std::int32_t is_reversed(const std::uint8_t index = 0) const = 0;
	virtual std::vector<std::int32_t> is_reversed_all(void) const = 0;
	virtual MotorType get_type(const std::uint8_t index = 0) const = 0;
	virtual std::vector<MotorType> get_type_all(void) const = 0;
	virtual std::int32_t set_brake_mode(const MotorBrake mode, const std::uint8_t index = 0) const = 0;
	virtual std::int32_t set_brake_mode(const pros::motor_brake_mode_e_t mode, const std::uint8_t index = 0) const = 0;
	virtual std::int32_t set_brake_mode_all(const MotorBrake mode) const = 0;
	virtual std::int32_t set_brake_mode_all(const pros::motor_brake_mode_e_t mode) const = 0;
	virtual std::int32_t set_current_limit(const std::int32_t limit, const std::uint8_t index = 0) const = 0;
	virtual std::int32_t set_current_limit_all(const std::int32_t limit) const = 0;
	virtual std::int32_t set_encoder_units(const MotorUnits units, const std::uint8_t index = 0) const = 0;
	virtual std::int32_t set_encoder_units(const pros::motor_encoder_units_e_t units, const std::uint8_t index = 0) const = 0;
	virtual std::int32_t set_encoder_units_all(const MotorUnits units) const = 0;
	virtual std::int32_t set_encoder_units_all(const pros::motor_encoder_units_e_t units) const = 0;
	virtual std::int32_t set_gearing(const MotorGears gearset, const std::uint8_t index = 0) const = 0;
	virtual std::int32_t set_gearing(const pros::motor_gearset_e_t gearset, const std::uint8_t index = 0) const = 0;
	virtual std::int32_t set_gearing_all(const MotorGears gearset) const = 0;
	virtual std::int32_t set_gearing_all(const pros::motor_gearset_e_t gearset) const = 0;
	virtual std::int32_t set_reversed(const bool reverse, const std::uint8_t index = 0) = 0;
	virtual std::int32_t set_reversed_all(const bool reverse) = 0;
	virtual std::int32_t set_voltage_limit(const std::int32_t limit, const std::uint8_t index = 0) const = 0;
	virtual std::int32_t set_voltage_limit_all(const std::int32_t limit) const = 0;
	virtual std::int32_t set_zero_position(const double position, const std::uint8_t index = 0) const = 0;
	virtual std::int32_t set_zero_position_all(const double position) const = 0;
	virtual std::int32_t tare_position(const std::uint8_t index = 0) const = 0;
	virtual std::int32_t tare_position_all(void) const = 0;
	virtual std::int8_t get_port(const std::uint8_t index = 0) const = 0;
	virtual std::int8_t size(void) const = 0;
};

namespace vexsim_detail {

/*
 * One implementation behind pros::Motor and pros::MotorGroup, following the
 * PROS 4 kernel: a port list whose signs mean "reversed". Plain calls act on
 * the motor at `index` (default 0, the first motor); `_all` calls act on
 * every motor and report the first motor's result. A pros::Motor is a list
 * of one, where any index but 0 fails with EOVERFLOW.
 */
class MotorCommon : public virtual AbstractMotor {
	protected:
	std::vector<std::int8_t> _ports;

	explicit MotorCommon(std::vector<std::int8_t> ports) : _ports(std::move(ports)) {}

	bool _ok(std::uint8_t index) const {
		if (_ports.empty()) {
			errno = EDOM;
			return false;
		}
		if (index >= _ports.size()) {
			errno = EOVERFLOW;
			return false;
		}
		return true;
	}
	template <class F>
	std::int32_t _all(F f) const {
		if (_ports.empty()) {
			errno = EDOM;
			return PROS_ERR;
		}
		for (std::size_t i = 1; i < _ports.size(); i++) f(_ports[i]);
		return f(_ports[0]);
	}
	template <class T, class F>
	std::vector<T> _each(T err, F f) const {
		std::vector<T> out;
		if (_ports.empty()) {
			errno = EDOM;
			out.push_back(err);
			return out;
		}
		for (auto p : _ports) out.push_back(static_cast<T>(f(p)));
		return out;
	}
	template <class T, class F>
	T _one(std::uint8_t index, T err, F f) const {
		return _ok(index) ? static_cast<T>(f(_ports[index])) : err;
	}

	public:
	std::int32_t move(std::int32_t voltage) const override {
		return _all([&](std::int8_t p) { return c::motor_move(p, voltage); });
	}
	std::int32_t move_absolute(const double position, const std::int32_t velocity) const override {
		return _all([&](std::int8_t p) { return c::motor_move_absolute(p, position, velocity); });
	}
	std::int32_t move_relative(const double position, const std::int32_t velocity) const override {
		return _all([&](std::int8_t p) { return c::motor_move_relative(p, position, velocity); });
	}
	std::int32_t move_velocity(const std::int32_t velocity) const override {
		return _all([&](std::int8_t p) { return c::motor_move_velocity(p, velocity); });
	}
	std::int32_t move_voltage(const std::int32_t voltage) const override {
		return _all([&](std::int8_t p) { return c::motor_move_voltage(p, voltage); });
	}
	std::int32_t brake(void) const override {
		return _all([&](std::int8_t p) { return c::motor_brake(p); });
	}
	std::int32_t modify_profiled_velocity(const std::int32_t velocity) const override {
		return _all([&](std::int8_t p) { return c::motor_modify_profiled_velocity(p, velocity); });
	}

	double get_target_position(const std::uint8_t index = 0) const override {
		return _one<double>(index, PROS_ERR_F, c::motor_get_target_position);
	}
	std::vector<double> get_target_position_all(void) const override {
		return _each<double>(PROS_ERR_F, c::motor_get_target_position);
	}
	std::int32_t get_target_velocity(const std::uint8_t index = 0) const override {
		return _one<std::int32_t>(index, PROS_ERR, c::motor_get_target_velocity);
	}
	std::vector<std::int32_t> get_target_velocity_all(void) const override {
		return _each<std::int32_t>(PROS_ERR, c::motor_get_target_velocity);
	}
	double get_actual_velocity(const std::uint8_t index = 0) const override {
		return _one<double>(index, PROS_ERR_F, c::motor_get_actual_velocity);
	}
	std::vector<double> get_actual_velocity_all(void) const override {
		return _each<double>(PROS_ERR_F, c::motor_get_actual_velocity);
	}
	std::int32_t get_current_draw(const std::uint8_t index = 0) const override {
		return _one<std::int32_t>(index, PROS_ERR, c::motor_get_current_draw);
	}
	std::vector<std::int32_t> get_current_draw_all(void) const override {
		return _each<std::int32_t>(PROS_ERR, c::motor_get_current_draw);
	}
	std::int32_t get_direction(const std::uint8_t index = 0) const override {
		return _one<std::int32_t>(index, PROS_ERR, c::motor_get_direction);
	}
	std::vector<std::int32_t> get_direction_all(void) const override {
		return _each<std::int32_t>(PROS_ERR, c::motor_get_direction);
	}
	double get_efficiency(const std::uint8_t index = 0) const override {
		return _one<double>(index, PROS_ERR_F, c::motor_get_efficiency);
	}
	std::vector<double> get_efficiency_all(void) const override {
		return _each<double>(PROS_ERR_F, c::motor_get_efficiency);
	}
	std::uint32_t get_faults(const std::uint8_t index = 0) const override {
		return _one<std::uint32_t>(index, PROS_ERR, c::motor_get_faults);
	}
	std::vector<std::uint32_t> get_faults_all(void) const override {
		return _each<std::uint32_t>(PROS_ERR, c::motor_get_faults);
	}
	std::uint32_t get_flags(const std::uint8_t index = 0) const override {
		return _one<std::uint32_t>(index, PROS_ERR, c::motor_get_flags);
	}
	std::vector<std::uint32_t> get_flags_all(void) const override {
		return _each<std::uint32_t>(PROS_ERR, c::motor_get_flags);
	}
	double get_position(const std::uint8_t index = 0) const override {
		return _one<double>(index, PROS_ERR_F, c::motor_get_position);
	}
	std::vector<double> get_position_all(void) const override {
		return _each<double>(PROS_ERR_F, c::motor_get_position);
	}
	double get_power(const std::uint8_t index = 0) const override {
		return _one<double>(index, PROS_ERR_F, c::motor_get_power);
	}
	std::vector<double> get_power_all(void) const override {
		return _each<double>(PROS_ERR_F, c::motor_get_power);
	}
	std::int32_t get_raw_position(std::uint32_t* const timestamp, const std::uint8_t index = 0) const override {
		return _one<std::int32_t>(index, PROS_ERR, [&](std::int8_t p) { return c::motor_get_raw_position(p, timestamp); });
	}
	std::vector<std::int32_t> get_raw_position_all(std::uint32_t* const timestamp) const override {
		return _each<std::int32_t>(PROS_ERR, [&](std::int8_t p) { return c::motor_get_raw_position(p, timestamp); });
	}
	double get_temperature(const std::uint8_t index = 0) const override {
		return _one<double>(index, PROS_ERR_F, c::motor_get_temperature);
	}
	std::vector<double> get_temperature_all(void) const override {
		return _each<double>(PROS_ERR_F, c::motor_get_temperature);
	}
	double get_torque(const std::uint8_t index = 0) const override {
		return _one<double>(index, PROS_ERR_F, c::motor_get_torque);
	}
	std::vector<double> get_torque_all(void) const override {
		return _each<double>(PROS_ERR_F, c::motor_get_torque);
	}
	std::int32_t get_voltage(const std::uint8_t index = 0) const override {
		return _one<std::int32_t>(index, PROS_ERR, c::motor_get_voltage);
	}
	std::vector<std::int32_t> get_voltage_all(void) const override {
		return _each<std::int32_t>(PROS_ERR, c::motor_get_voltage);
	}
	std::int32_t is_over_current(const std::uint8_t index = 0) const override {
		return _one<std::int32_t>(index, PROS_ERR, c::motor_is_over_current);
	}
	std::vector<std::int32_t> is_over_current_all(void) const override {
		return _each<std::int32_t>(PROS_ERR, c::motor_is_over_current);
	}
	std::int32_t is_over_temp(const std::uint8_t index = 0) const override {
		return _one<std::int32_t>(index, PROS_ERR, c::motor_is_over_temp);
	}
	std::vector<std::int32_t> is_over_temp_all(void) const override {
		return _each<std::int32_t>(PROS_ERR, c::motor_is_over_temp);
	}
	MotorBrake get_brake_mode(const std::uint8_t index = 0) const override {
		return _one(index, MotorBrake::invalid, c::motor_get_brake_mode);
	}
	std::vector<MotorBrake> get_brake_mode_all(void) const override {
		return _each(MotorBrake::invalid, c::motor_get_brake_mode);
	}
	std::int32_t get_current_limit(const std::uint8_t index = 0) const override {
		return _one<std::int32_t>(index, PROS_ERR, c::motor_get_current_limit);
	}
	std::vector<std::int32_t> get_current_limit_all(void) const override {
		return _each<std::int32_t>(PROS_ERR, c::motor_get_current_limit);
	}
	MotorUnits get_encoder_units(const std::uint8_t index = 0) const override {
		return _one(index, MotorUnits::invalid, c::motor_get_encoder_units);
	}
	std::vector<MotorUnits> get_encoder_units_all(void) const override {
		return _each(MotorUnits::invalid, c::motor_get_encoder_units);
	}
	MotorGears get_gearing(const std::uint8_t index = 0) const override {
		return _one(index, MotorGears::invalid, c::motor_get_gearing);
	}
	std::vector<MotorGears> get_gearing_all(void) const override {
		return _each(MotorGears::invalid, c::motor_get_gearing);
	}
	std::vector<std::int8_t> get_port_all(void) const override { return _ports; }
	std::int32_t get_voltage_limit(const std::uint8_t index = 0) const override {
		return _one<std::int32_t>(index, PROS_ERR, c::motor_get_voltage_limit);
	}
	std::vector<std::int32_t> get_voltage_limit_all(void) const override {
		return _each<std::int32_t>(PROS_ERR, c::motor_get_voltage_limit);
	}
	std::int32_t is_reversed(const std::uint8_t index = 0) const override {
		return _ok(index) ? (_ports[index] < 0) : PROS_ERR;
	}
	std::vector<std::int32_t> is_reversed_all(void) const override {
		return _each<std::int32_t>(PROS_ERR, [](std::int8_t p) { return p < 0; });
	}
	MotorType get_type(const std::uint8_t index = 0) const override {
		return _one(index, MotorType::invalid, c::motor_get_type);
	}
	std::vector<MotorType> get_type_all(void) const override {
		return _each(MotorType::invalid, c::motor_get_type);
	}

	std::int32_t set_brake_mode(const MotorBrake mode, const std::uint8_t index = 0) const override {
		return set_brake_mode(static_cast<pros::motor_brake_mode_e_t>(mode), index);
	}
	std::int32_t set_brake_mode(const pros::motor_brake_mode_e_t mode, const std::uint8_t index = 0) const override {
		return _one<std::int32_t>(index, PROS_ERR, [&](std::int8_t p) { return c::motor_set_brake_mode(p, mode); });
	}
	std::int32_t set_brake_mode_all(const MotorBrake mode) const override {
		return set_brake_mode_all(static_cast<pros::motor_brake_mode_e_t>(mode));
	}
	std::int32_t set_brake_mode_all(const pros::motor_brake_mode_e_t mode) const override {
		return _all([&](std::int8_t p) { return c::motor_set_brake_mode(p, mode); });
	}
	std::int32_t set_current_limit(const std::int32_t limit, const std::uint8_t index = 0) const override {
		return _one<std::int32_t>(index, PROS_ERR, [&](std::int8_t p) { return c::motor_set_current_limit(p, limit); });
	}
	std::int32_t set_current_limit_all(const std::int32_t limit) const override {
		return _all([&](std::int8_t p) { return c::motor_set_current_limit(p, limit); });
	}
	std::int32_t set_encoder_units(const MotorUnits units, const std::uint8_t index = 0) const override {
		return set_encoder_units(static_cast<pros::motor_encoder_units_e_t>(units), index);
	}
	std::int32_t set_encoder_units(const pros::motor_encoder_units_e_t units, const std::uint8_t index = 0) const override {
		return _one<std::int32_t>(index, PROS_ERR, [&](std::int8_t p) { return c::motor_set_encoder_units(p, units); });
	}
	std::int32_t set_encoder_units_all(const MotorUnits units) const override {
		return set_encoder_units_all(static_cast<pros::motor_encoder_units_e_t>(units));
	}
	std::int32_t set_encoder_units_all(const pros::motor_encoder_units_e_t units) const override {
		return _all([&](std::int8_t p) { return c::motor_set_encoder_units(p, units); });
	}
	std::int32_t set_gearing(const MotorGears gearset, const std::uint8_t index = 0) const override {
		return set_gearing(static_cast<pros::motor_gearset_e_t>(gearset), index);
	}
	std::int32_t set_gearing(const pros::motor_gearset_e_t gearset, const std::uint8_t index = 0) const override {
		return _one<std::int32_t>(index, PROS_ERR, [&](std::int8_t p) { return c::motor_set_gearing(p, gearset); });
	}
	std::int32_t set_gearing_all(const MotorGears gearset) const override {
		return set_gearing_all(static_cast<pros::motor_gearset_e_t>(gearset));
	}
	std::int32_t set_gearing_all(const pros::motor_gearset_e_t gearset) const override {
		return _all([&](std::int8_t p) { return c::motor_set_gearing(p, gearset); });
	}
	std::int32_t set_reversed(const bool reverse, const std::uint8_t index = 0) override {
		if (!_ok(index)) return PROS_ERR;
		std::int8_t port = _ports[index] < 0 ? -_ports[index] : _ports[index];
		_ports[index] = reverse ? -port : port;
		return PROS_SUCCESS;
	}
	std::int32_t set_reversed_all(const bool reverse) override {
		if (_ports.empty()) {
			errno = EDOM;
			return PROS_ERR;
		}
		for (auto& p : _ports) {
			std::int8_t port = p < 0 ? -p : p;
			p = reverse ? -port : port;
		}
		return PROS_SUCCESS;
	}
	std::int32_t set_voltage_limit(const std::int32_t limit, const std::uint8_t index = 0) const override {
		return _one<std::int32_t>(index, PROS_ERR, [&](std::int8_t p) { return c::motor_set_voltage_limit(p, limit); });
	}
	std::int32_t set_voltage_limit_all(const std::int32_t limit) const override {
		return _all([&](std::int8_t p) { return c::motor_set_voltage_limit(p, limit); });
	}
	std::int32_t set_zero_position(const double position, const std::uint8_t index = 0) const override {
		return _one<std::int32_t>(index, PROS_ERR, [&](std::int8_t p) { return c::motor_set_zero_position(p, position); });
	}
	std::int32_t set_zero_position_all(const double position) const override {
		return _all([&](std::int8_t p) { return c::motor_set_zero_position(p, position); });
	}
	std::int32_t tare_position(const std::uint8_t index = 0) const override {
		return _one<std::int32_t>(index, PROS_ERR, c::motor_tare_position);
	}
	std::int32_t tare_position_all(void) const override {
		return _all([](std::int8_t p) { return c::motor_tare_position(p); });
	}
	std::int8_t get_port(const std::uint8_t index = 0) const override {
		return _ok(index) ? _ports[index] : static_cast<std::int8_t>(PROS_ERR_BYTE);
	}
	std::int8_t size(void) const override { return static_cast<std::int8_t>(_ports.size()); }
};

}  // namespace vexsim_detail
}  // namespace v5
}  // namespace pros

#endif
