/*
 * vexsim PROS 4 shim: pros::adi. The simulator has no three-wire devices yet:
 * outputs remember what was written (so pneumatics state reads back), inputs
 * and encoders read 0.
 */
#ifndef _PROS_ADI_HPP_
#define _PROS_ADI_HPP_

#include <cstdint>
#include <iostream>
#include <tuple>
#include <utility>
#include <vector>

#include "pros/adi.h"

namespace pros {
namespace adi {

using ext_adi_port_pair_t = std::pair<std::uint8_t, std::uint8_t>;
using ext_adi_port_tuple_t = std::tuple<std::uint8_t, std::uint8_t, std::uint8_t>;

namespace vexsim_detail {
inline std::uint8_t adi_index(std::uint8_t port) {
	if (port >= 'a' && port <= 'h') return static_cast<std::uint8_t>(port - 'a' + 1);
	if (port >= 'A' && port <= 'H') return static_cast<std::uint8_t>(port - 'A' + 1);
	return port;
}
}  // namespace vexsim_detail

class Port {
	public:
	explicit Port(std::uint8_t adi_port, adi_port_config_e_t type = E_ADI_TYPE_UNDEFINED)
	    : _smart_port(INTERNAL_ADI_PORT), _adi_port(vexsim_detail::adi_index(adi_port)) {
		if (type != E_ADI_TYPE_UNDEFINED) set_config(type);
	}
	explicit Port(ext_adi_port_pair_t port_pair, adi_port_config_e_t type = E_ADI_TYPE_UNDEFINED)
	    : _smart_port(port_pair.first), _adi_port(vexsim_detail::adi_index(port_pair.second)) {
		if (type != E_ADI_TYPE_UNDEFINED) set_config(type);
	}
	virtual ~Port() = default;
	std::int32_t get_config() const { return pros::c::ext_adi_port_get_config(_smart_port, _adi_port); }
	std::int32_t get_value() const { return pros::c::ext_adi_port_get_value(_smart_port, _adi_port); }
	std::int32_t set_config(adi_port_config_e_t type) const {
		return pros::c::ext_adi_port_set_config(_smart_port, _adi_port, type);
	}
	std::int32_t set_value(std::int32_t value) const {
		return pros::c::ext_adi_port_set_value(_smart_port, _adi_port, value);
	}
	virtual ext_adi_port_tuple_t get_port() const { return {_smart_port, _adi_port, 0}; }

	protected:
	std::uint8_t _smart_port;
	std::uint8_t _adi_port;
};

class AnalogIn : protected Port {
	public:
	explicit AnalogIn(std::uint8_t adi_port) : Port(adi_port, E_ADI_ANALOG_IN) {}
	explicit AnalogIn(ext_adi_port_pair_t port_pair) : Port(port_pair, E_ADI_ANALOG_IN) {}
	std::int32_t calibrate() const { return get_value(); }
	std::int32_t get_value_calibrated() const { return 0; }
	std::int32_t get_value_calibrated_HR() const { return 0; }
	using Port::get_port;
	using Port::get_value;
};
using LineSensor = AnalogIn;
using LightSensor = AnalogIn;
using Accelerometer = AnalogIn;

class AnalogOut : private Port {
	public:
	explicit AnalogOut(std::uint8_t adi_port) : Port(adi_port, E_ADI_ANALOG_OUT) {}
	explicit AnalogOut(ext_adi_port_pair_t port_pair) : Port(port_pair, E_ADI_ANALOG_OUT) {}
	using Port::get_port;
	using Port::set_value;
};

class DigitalOut : private Port {
	public:
	explicit DigitalOut(std::uint8_t adi_port, bool init_state = LOW) : Port(adi_port, E_ADI_DIGITAL_OUT) {
		set_value(init_state);
	}
	explicit DigitalOut(ext_adi_port_pair_t port_pair, bool init_state = LOW) : Port(port_pair, E_ADI_DIGITAL_OUT) {
		set_value(init_state);
	}
	using Port::get_port;
	using Port::set_value;
};

class DigitalIn : private Port {
	public:
	explicit DigitalIn(std::uint8_t adi_port) : Port(adi_port, E_ADI_DIGITAL_IN) {}
	explicit DigitalIn(ext_adi_port_pair_t port_pair) : Port(port_pair, E_ADI_DIGITAL_IN) {}
	std::int32_t get_new_press() const { return 0; }
	using Port::get_port;
	using Port::get_value;
};
using Button = DigitalIn;

class Motor : private Port {
	public:
	explicit Motor(std::uint8_t adi_port) : Port(adi_port, E_ADI_LEGACY_PWM) {}
	explicit Motor(ext_adi_port_pair_t port_pair) : Port(port_pair, E_ADI_LEGACY_PWM) {}
	std::int32_t stop() const { return set_value(0); }
	using Port::get_port;
	using Port::get_value;
	using Port::set_value;
};

class Encoder : private Port {
	public:
	explicit Encoder(std::uint8_t adi_port_top, std::uint8_t adi_port_bottom, bool reversed = false)
	    : Port(adi_port_top, E_ADI_LEGACY_ENCODER), _reversed(reversed) {
		(void)adi_port_bottom;
	}
	explicit Encoder(ext_adi_port_tuple_t port_tuple, bool reversed = false)
	    : Port(ext_adi_port_pair_t{std::get<0>(port_tuple), std::get<1>(port_tuple)}, E_ADI_LEGACY_ENCODER),
	      _reversed(reversed) {}
	std::int32_t reset() const { return set_value(0); }
	std::int32_t get_value() const { return Port::get_value(); }
	ext_adi_port_tuple_t get_port() const override {
		return {_smart_port, _adi_port, static_cast<std::uint8_t>(_adi_port + 1)};
	}

	private:
	bool _reversed;
};

class Ultrasonic : private Port {
	public:
	explicit Ultrasonic(std::uint8_t adi_port_ping, std::uint8_t adi_port_echo)
	    : Port(adi_port_ping, E_ADI_LEGACY_ULTRASONIC) {
		(void)adi_port_echo;
	}
	explicit Ultrasonic(ext_adi_port_tuple_t port_tuple)
	    : Port(ext_adi_port_pair_t{std::get<0>(port_tuple), std::get<1>(port_tuple)}, E_ADI_LEGACY_ULTRASONIC) {}
	std::int32_t get_value() const { return Port::get_value(); }
	using Port::get_port;
};

class Gyro : private Port {
	public:
	explicit Gyro(std::uint8_t adi_port, double multiplier = 1) : Port(adi_port, E_ADI_LEGACY_GYRO) {
		(void)multiplier;
	}
	explicit Gyro(ext_adi_port_pair_t port_pair, double multiplier = 1) : Port(port_pair, E_ADI_LEGACY_GYRO) {
		(void)multiplier;
	}
	double get_value() const { return Port::get_value(); }
	std::int32_t reset() const { return set_value(0); }
	using Port::get_port;
};

class Potentiometer : public AnalogIn {
	public:
	explicit Potentiometer(std::uint8_t adi_port, adi_potentiometer_type_e_t potentiometer_type = E_ADI_POT_EDR)
	    : AnalogIn(adi_port) {
		(void)potentiometer_type;
	}
	explicit Potentiometer(ext_adi_port_pair_t port_pair,
	                       adi_potentiometer_type_e_t potentiometer_type = E_ADI_POT_EDR)
	    : AnalogIn(port_pair) {
		(void)potentiometer_type;
	}
	double get_angle() const { return 0.0; }
	using AnalogIn::calibrate;
	using AnalogIn::get_port;
	using AnalogIn::get_value;
	using AnalogIn::get_value_calibrated;
};

class Led : protected Port {
	public:
	explicit Led(std::uint8_t adi_port, std::uint32_t length) : Port(adi_port, E_ADI_DIGITAL_OUT), _buffer(length) {}
	explicit Led(ext_adi_port_pair_t port_pair, std::uint32_t length)
	    : Port(port_pair, E_ADI_DIGITAL_OUT), _buffer(length) {}
	std::uint32_t& operator[](size_t i) { return _buffer[i]; }
	std::int32_t clear_all() {
		for (auto& c : _buffer) c = 0;
		return PROS_SUCCESS;
	}
	std::int32_t clear() { return clear_all(); }
	std::int32_t update() const { return PROS_SUCCESS; }
	std::int32_t set_all(uint32_t color) {
		for (auto& c : _buffer) c = color;
		return PROS_SUCCESS;
	}
	std::int32_t set_pixel(uint32_t color, uint32_t pixel_position) {
		if (pixel_position >= _buffer.size()) return PROS_ERR;
		_buffer[pixel_position] = color;
		return PROS_SUCCESS;
	}
	std::int32_t clear_pixel(uint32_t pixel_position) { return set_pixel(0, pixel_position); }
	std::int32_t length() { return static_cast<std::int32_t>(_buffer.size()); }
	using Port::get_port;

	protected:
	std::vector<uint32_t> _buffer;
};
using LED = Led;

class Pneumatics : public DigitalOut {
	public:
	explicit Pneumatics(std::uint8_t adi_port, bool start_extended, bool extended_is_low = false)
	    : DigitalOut(adi_port, start_extended != extended_is_low), state(start_extended != extended_is_low),
	      extended_is_low(extended_is_low) {}
	explicit Pneumatics(ext_adi_port_pair_t port_pair, bool start_extended, bool extended_is_low = false)
	    : DigitalOut(port_pair, start_extended != extended_is_low), state(start_extended != extended_is_low),
	      extended_is_low(extended_is_low) {}
	std::int32_t extend() {
		state = !extended_is_low;
		return set_value(state);
	}
	std::int32_t retract() {
		state = extended_is_low;
		return set_value(state);
	}
	std::int32_t toggle() {
		state = !state;
		return set_value(state);
	}
	bool is_extended() const { return state != extended_is_low; }

	private:
	bool state;
	bool extended_is_low;
};

}  // namespace adi

using ADIPort = pros::adi::Port;
using ADIAnalogIn = pros::adi::AnalogIn;
using ADIAnalogOut = pros::adi::AnalogOut;
using ADIDigitalIn = pros::adi::DigitalIn;
using ADIDigitalOut = pros::adi::DigitalOut;
using ADIMotor = pros::adi::Motor;
using ADIEncoder = pros::adi::Encoder;
using ADIUltrasonic = pros::adi::Ultrasonic;
using ADIGyro = pros::adi::Gyro;
using ADIPotentiometer = pros::adi::Potentiometer;
using ADILineSensor = pros::adi::LineSensor;
using ADILightSensor = pros::adi::LightSensor;
using ADIAccelerometer = pros::adi::Accelerometer;
using ADIButton = pros::adi::Button;
using ADILed = pros::adi::Led;
using ADILED = pros::adi::Led;

}  // namespace pros

#endif  // _PROS_ADI_HPP_
