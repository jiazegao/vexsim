// vexsim robot host: the PROS device C API, backed by readings the simulator
// sends before each run and commands it applies after.
//
// Semantics follow the PROS 4 kernel: a negative port reverses one call
// (positions, velocities and voltages change sign); zero positions, brake
// modes, gearing and units are settings of the device on that port, shared by
// every object using it. As on the V5, the gearing the code declares scales
// what the motor reports: declaring green on a blue cartridge makes it read
// and move 3x slower than intended.

#include <algorithm>
#include <array>
#include <cerrno>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#include "api.h"
#include "internal.hpp"
#include "pros/unsupported.h"

namespace vexsim {
namespace {

enum class Kind { none, motor, imu, rotation, distance, gps };

const char* kind_name(Kind k) {
	switch (k) {
		case Kind::motor:
			return "a motor";
		case Kind::imu:
			return "an IMU";
		case Kind::rotation:
			return "a rotation sensor";
		case Kind::distance:
			return "a distance sensor";
		case Kind::gps:
			return "a GPS sensor";
		default:
			return "nothing";
	}
}

enum class Mode { none, voltage, velocity, position };

struct MotorPort {
	int cartridge = 0;  // physical gear ratio (36, 18, 6) from the robot config; 0 before INIT
	int gearset = -1;   // motor_gearset_e_t the code declared; -1 = never set (matches the cartridge)
	int units = pros::E_MOTOR_ENCODER_DEGREES;
	int brake = pros::E_MOTOR_BRAKE_COAST;
	int current_limit = 2500;
	int voltage_limit = 0;
	double zero_deg = 0.0;  // device zero, in declared-gearing output degrees
	Mode mode = Mode::none;
	double target_pos = 0.0;  // device units, unsigned frame
	std::int32_t target_vel = 0;
	// latest reading, raw: physical output shaft, config-port direction
	double raw_deg = 0, raw_rpm = 0, temp = 25, torque = 0, power = 0;
	std::int32_t cur_ma = 0, volt_mv = 0;
	bool over_temp = false, over_current = false;
	std::uint64_t read_us = 0;
	std::string pending, pending_brake, pending_limit;
};

struct ImuPort {
	bool calibrating = true;  // the V5 IMU calibrates at power-on
	double rot = 0, gyro = 0;
	double rot_off = 0, head_off = 0, yaw_off = 0, pitch_off = 0, roll_off = 0;
};

struct RotationPort {
	bool reversed = false;
	std::int64_t raw = 0, offset = 0;  // offset in the raw frame
	std::int32_t vel = 0;
};

struct DistancePort {
	std::int32_t mm = -1;
	std::int32_t confidence = 63;
};

struct GpsPort {
	bool have = false;  // the sensor has had a fix (readings arrive from then on)
	double x = 0, y = 0, heading = 0, rotation = 0, error = 0, gyro = 0;  // the sensor's own
	double off_x = 0, off_y = 0;  // set by the code: the sensor relative to the robot's center
	bool initial = false;  // set_position: where the robot starts, until the first fix
	double ix = 0, iy = 0, ih = 0;
};

struct Controller {
	std::array<std::int32_t, 4> analog{};
	std::uint32_t buttons = 0;
	std::array<bool, 13> pressed{};
	std::array<bool, 13> released{true, true, true, true, true, true, true, true, true, true, true, true, true};
	std::array<std::string, 3> screen{std::string(19, ' '), std::string(19, ' '), std::string(19, ' ')};
};

struct State {
	bool ready = false;  // robot config received; before that, accept every port silently
	std::array<Kind, 22> kind{};
	std::array<MotorPort, 22> motor{};
	std::array<ImuPort, 22> imu{};
	std::array<RotationPort, 22> rotation{};
	std::array<DistancePort, 22> distance{};
	std::array<GpsPort, 22> gps{};
	Controller controller;
	std::uint8_t competition = 0;
	std::int32_t battery_mv = 12800, battery_ma = 0;
	double battery_pct = 100.0;
	bool lcd_on = false;
	std::array<std::string, 8> lcd{};
	std::array<std::array<std::int32_t, 9>, 23> adi_value{};
	std::array<std::array<std::int32_t, 9>, 23> adi_config{};
};

State& D() {
	static State* s = new State();
	return *s;
}

int ratio_of(int gearset) { return gearset == 0 ? 36 : gearset == 2 ? 6 : 18; }
const char* cartridge_name(int ratio) { return ratio == 36 ? "red (100 rpm)" : ratio == 6 ? "blue (600 rpm)" : "green (200 rpm)"; }

std::string fmt(double v) {
	char buf[64];
	std::snprintf(buf, sizeof buf, "%.10g", v);
	return buf;
}

// Look up a smart port the code uses as `want`; nullptr (errno set) if the robot has no such device.
bool check_port(int port, Kind want) {
	api_call();
	if (port < 1 || port > 21) {
		errno = ENXIO;
		return false;
	}
	if (!D().ready || D().kind[port] == want) return true;
	errno = ENODEV;
	host_warn_once("port" + std::to_string(port) + kind_name(want),
	               "port " + std::to_string(port) + ": the code uses " + kind_name(want) +
	                   " here, but the robot config has " + kind_name(D().kind[port]) +
	                   " on this port (calls fail with errno ENODEV)");
	return false;
}

MotorPort* motor(std::int8_t port) {
	int p = std::abs(port);
	return check_port(p, Kind::motor) ? &D().motor[p] : nullptr;
}

int sign(std::int8_t port) { return port < 0 ? -1 : 1; }

int declared_ratio(const MotorPort& m) {
	if (m.gearset >= 0) return ratio_of(m.gearset);
	return m.cartridge ? m.cartridge : 18;
}

// Declared-gearing output per physical output (the firmware only knows the declared ratio).
double scale(const MotorPort& m) {
	int cartridge = m.cartridge ? m.cartridge : declared_ratio(m);
	return double(cartridge) / declared_ratio(m);
}

double to_units(const MotorPort& m, double deg) {
	switch (m.units) {
		case pros::E_MOTOR_ENCODER_ROTATIONS:
			return deg / 360.0;
		case pros::E_MOTOR_ENCODER_COUNTS:
			return deg * 50.0 * declared_ratio(m) / 360.0;
		default:
			return deg;
	}
}

double from_units(const MotorPort& m, double value) {
	switch (m.units) {
		case pros::E_MOTOR_ENCODER_ROTATIONS:
			return value * 360.0;
		case pros::E_MOTOR_ENCODER_COUNTS:
			return value * 360.0 / (50.0 * declared_ratio(m));
		default:
			return value;
	}
}

double reported_deg(const MotorPort& m) { return m.raw_deg * scale(m); }
double reported_rpm(const MotorPort& m) { return m.raw_rpm * scale(m); }
double device_position(const MotorPort& m) { return to_units(m, reported_deg(m) - m.zero_deg); }

void command_position(MotorPort& m, double target_units, std::int32_t velocity) {
	m.mode = Mode::position;
	m.target_pos = target_units;
	m.target_vel = velocity;
	double raw_target = (from_units(m, target_units) + m.zero_deg) / scale(m);
	m.pending = "p " + fmt(raw_target) + " " + fmt(std::abs(velocity) / scale(m));
}

ImuPort* imu(std::uint8_t port) { return check_port(port, Kind::imu) ? &D().imu[port] : nullptr; }

bool imu_ready(ImuPort* i) {
	if (!i) return false;
	if (i->calibrating) {
		errno = EAGAIN;
		return false;
	}
	return true;
}

double wrap360(double deg) {
	double h = std::fmod(deg, 360.0);
	return h < 0 ? h + 360.0 : h;
}

double raw_yaw(const ImuPort& i) {
	double y = std::fmod(i.rot, 360.0);
	if (y > 180.0) y -= 360.0;
	if (y <= -180.0) y += 360.0;
	return y;
}

RotationPort* rotation(std::uint8_t port) {
	return check_port(port, Kind::rotation) ? &D().rotation[port] : nullptr;
}

std::int64_t rotation_sign(const RotationPort& r) { return r.reversed ? -1 : 1; }

GpsPort* gps(std::uint8_t port) { return check_port(port, Kind::gps) ? &D().gps[port] : nullptr; }

// The robot center's position and heading, with the code's offset applied.
bool gps_state(std::uint8_t port, double* x, double* y, double* heading) {
	GpsPort* g = gps(port);
	if (!g) return false;
	if (!g->have) {
		if (!g->initial) {
			errno = EAGAIN;
			return false;
		}
		*x = g->ix, *y = g->iy, *heading = g->ih;
		return true;
	}
	double h = g->heading * 3.14159265358979323846 / 180.0;
	// The offset's +x is to the right of the camera's direction, +y along it.
	*x = g->x - (g->off_x * std::cos(h) + g->off_y * std::sin(h));
	*y = g->y - (-g->off_x * std::sin(h) + g->off_y * std::cos(h));
	*heading = g->heading;
	return true;
}

bool controller_ok(pros::controller_id_e_t id) {
	api_call();
	if (id != pros::E_CONTROLLER_MASTER && id != pros::E_CONTROLLER_PARTNER) {
		errno = EINVAL;
		return false;
	}
	return true;
}

void emit_lcd(int line) { host_emit("LCD " + std::to_string(line) + " " + D().lcd[line]); }

std::string vformat(const char* fmt, va_list args) {
	char buf[512];
	std::vsnprintf(buf, sizeof buf, fmt, args);
	return buf;
}

std::int32_t adi_index(std::uint8_t port) {
	if (port >= 'a' && port <= 'h') return port - 'a' + 1;
	if (port >= 'A' && port <= 'H') return port - 'A' + 1;
	return port;
}

bool adi_ok(std::uint8_t smart_port, std::int32_t& adi_port) {
	api_call();
	adi_port = adi_index(static_cast<std::uint8_t>(adi_port));
	if (smart_port < 1 || smart_port > 22 || adi_port < 1 || adi_port > 8) {
		errno = ENXIO;
		return false;
	}
	host_warn_once("adi",
	               "three-wire (ADI) devices are not simulated yet: outputs such as pneumatics remember "
	               "their value, inputs and encoders read 0");
	return true;
}

}  // namespace

// A library's pose accessor, registered by code vexsim build generates (LemLib).
int (*g_pose_source)(double*, double*, double*) = nullptr;
bool g_pose_reported = false;

void devices_poll_pose() {
	static double last[3];
	static bool have_last = false;
	double pose[3];
	if (!g_pose_source || g_pose_reported || !g_pose_source(&pose[0], &pose[1], &pose[2])) return;
	if (have_last && pose[0] == last[0] && pose[1] == last[1] && pose[2] == last[2]) return;
	have_last = true;
	last[0] = pose[0], last[1] = pose[1], last[2] = pose[2];
	host_emit("P " + fmt(pose[0]) + " " + fmt(pose[1]) + " " + fmt(pose[2]));
}

void devices_register(int port, const std::string& kind, const std::string& detail) {
	if (port < 1 || port > 21) return;
	Kind k = kind == "motor" ? Kind::motor
	         : kind == "imu" ? Kind::imu
	         : kind == "rotation" ? Kind::rotation
	         : kind == "distance" ? Kind::distance
	         : kind == "gps"      ? Kind::gps
	                              : Kind::none;
	D().kind[port] = k;
	if (k == Kind::motor) D().motor[port].cartridge = detail == "red" ? 36 : detail == "blue" ? 6 : 18;
}

void devices_ready() {
	D().ready = true;
	// Settings made by global constructors before the config arrived take effect now.
	for (int p = 1; p <= 21; p++) {
		MotorPort& m = D().motor[p];
		if (D().kind[p] != Kind::motor) continue;
		if (m.brake != pros::E_MOTOR_BRAKE_COAST) m.pending_brake = std::to_string(m.brake);
		if (m.current_limit != 2500) m.pending_limit = std::to_string(m.current_limit);
		if (m.gearset >= 0 && ratio_of(m.gearset) != m.cartridge) {
			host_warn_once("gearing" + std::to_string(p),
			               "port " + std::to_string(p) + ": the code declares the " +
			                   cartridge_name(ratio_of(m.gearset)) + " cartridge, but the robot config has " +
			                   cartridge_name(m.cartridge) + "; as on a real motor, speeds and positions are scaled");
		}
	}
}

void devices_set_competition(std::uint8_t status) { D().competition = status; }

bool devices_reading(const char* line) {
	int port = 0;
	switch (line[0]) {
		case 'm': {
			double deg, rpm, temp, torque, power;
			int ma, mv, flags;
			if (std::sscanf(line + 1, "%d %lf %lf %d %d %lf %lf %lf %d", &port, &deg, &rpm, &ma, &mv, &temp, &torque,
			                &power, &flags) != 9 ||
			    port < 1 || port > 21)
				return true;
			MotorPort& m = D().motor[port];
			m.raw_deg = deg, m.raw_rpm = rpm, m.cur_ma = ma, m.volt_mv = mv;
			m.temp = temp, m.torque = torque, m.power = power;
			m.over_temp = flags & 1, m.over_current = flags & 2;
			m.read_us = sched_now_us();
			return true;
		}
		case 'i': {
			double rot, gyro;
			char word[8];
			if (std::sscanf(line + 1, "%d %lf %lf", &port, &rot, &gyro) == 3 && port >= 1 && port <= 21) {
				ImuPort& i = D().imu[port];
				i.calibrating = false, i.rot = rot, i.gyro = gyro;
			} else if (std::sscanf(line + 1, "%d %7s", &port, word) == 2 && port >= 1 && port <= 21) {
				D().imu[port].calibrating = true;
			}
			return true;
		}
		case 'r': {
			long long cdeg;
			double vel;
			if (std::sscanf(line + 1, "%d %lld %lf", &port, &cdeg, &vel) == 3 && port >= 1 && port <= 21) {
				D().rotation[port].raw = cdeg;
				D().rotation[port].vel = static_cast<std::int32_t>(std::lround(vel));
			}
			return true;
		}
		case 'd': {
			int mm, confidence = 63;
			if (std::sscanf(line + 1, "%d %d %d", &port, &mm, &confidence) >= 2 && port >= 1 && port <= 21) {
				D().distance[port].mm = mm;
				D().distance[port].confidence = confidence;
			}
			return true;
		}
		case 'g': {
			double x, y, heading, rotation, error, gyro;
			if (std::sscanf(line + 1, "%d %lf %lf %lf %lf %lf %lf", &port, &x, &y, &heading, &rotation, &error, &gyro) ==
			        7 &&
			    port >= 1 && port <= 21) {
				GpsPort& g = D().gps[port];
				g.have = true, g.x = x, g.y = y, g.heading = heading, g.rotation = rotation;
				g.error = error, g.gyro = gyro;
			}
			return true;
		}
		case 'c': {
			Controller& c = D().controller;
			unsigned buttons;
			std::sscanf(line + 1, "%d %d %d %d %u", &c.analog[0], &c.analog[1], &c.analog[2], &c.analog[3], &buttons);
			c.buttons = buttons;
			return true;
		}
		case 'b': {
			double pct;
			std::sscanf(line + 1, "%d %d %lf", &D().battery_mv, &D().battery_ma, &pct);
			D().battery_pct = pct;
			return true;
		}
		default:
			return false;
	}
}

void devices_flush_commands() {
	bool disabled = D().competition & COMPETITION_DISABLED;
	for (int p = 1; p <= 21; p++) {
		MotorPort& m = D().motor[p];
		if (!m.pending_brake.empty()) {
			static const char* names[] = {"coast", "brake", "hold"};
			host_emit("B " + std::to_string(p) + " " + names[std::atoi(m.pending_brake.c_str())]);
			m.pending_brake.clear();
		}
		if (!m.pending_limit.empty()) {
			host_emit("L " + std::to_string(p) + " " + m.pending_limit);
			m.pending_limit.clear();
		}
		if (!m.pending.empty()) {
			// A disabled robot's motors ignore commands (field control), but the code keeps running.
			if (!disabled) host_emit("M " + std::to_string(p) + " " + m.pending);
			m.pending.clear();
		}
	}
}

}  // namespace vexsim

using namespace vexsim;

extern "C" {

int32_t vexsim_unsupported(const char* what) {
	api_call();
	host_warn_once(std::string("unsupported:") + what,
	               std::string(what) + " is not simulated yet: its calls fail with errno ENODEV");
	errno = ENODEV;
	return PROS_ERR;
}

void vexsim_report_pose(double x_in, double y_in, double theta_deg) {
	api_call();
	g_pose_reported = true;  // the code reports its own pose: don't poll LemLib's
	host_emit("P " + fmt(x_in) + " " + fmt(y_in) + " " + fmt(theta_deg));
}

// vexsim::draw_* (sim.hpp): a drawing command, one line, for the simulator's drawing layers.
// Not a PROS call: drawing never costs the robot code simulated time.
void vexsim_draw(const char* command) {
	std::string line(command ? command : "");
	for (char& c : line)
		if (c == '\n' || c == '\r') c = ' ';
	host_emit("D " + line);
}

void vexsim_set_pose_source(int (*source)(double*, double*, double*)) { g_pose_source = source; }

namespace pros {
namespace c {

v5_device_e_t get_plugged_type(uint8_t port) {
	api_call();
	if (port < 1 || port > 21) {
		errno = ENXIO;
		return E_DEVICE_UNDEFINED;
	}
	switch (D().kind[port]) {
		case Kind::motor:
			return E_DEVICE_MOTOR;
		case Kind::imu:
			return E_DEVICE_IMU;
		case Kind::rotation:
			return E_DEVICE_ROTATION;
		case Kind::distance:
			return E_DEVICE_DISTANCE;
		case Kind::gps:
			return E_DEVICE_GPS;
		default:
			return E_DEVICE_NONE;
	}
}

// ---- motors ----------------------------------------------------------------------------

int32_t motor_move(int8_t port, int32_t voltage) {
	voltage = std::clamp(voltage, -127, 127);
	if (port < 0) voltage = -voltage;
	int8_t abs_port = static_cast<int8_t>(std::abs(port));
	int32_t command = ((voltage + 127) * 12000) / 127 - 12000;  // PROS's integer mapping
	return motor_move_voltage(abs_port, command);
}

int32_t motor_brake(int8_t port) { return motor_move_velocity(port, 0); }

int32_t motor_move_absolute(int8_t port, double position, const int32_t velocity) {
	MotorPort* m = motor(port);
	if (!m) return PROS_ERR;
	command_position(*m, sign(port) * position, velocity);
	return PROS_SUCCESS;
}

int32_t motor_move_relative(int8_t port, double position, const int32_t velocity) {
	MotorPort* m = motor(port);
	if (!m) return PROS_ERR;
	command_position(*m, device_position(*m) + sign(port) * position, velocity);
	return PROS_SUCCESS;
}

int32_t motor_move_velocity(int8_t port, const int32_t velocity) {
	MotorPort* m = motor(port);
	if (!m) return PROS_ERR;
	int32_t limit = 3600 / declared_ratio(*m);
	int32_t v = std::clamp(sign(port) * velocity, -limit, limit);
	m->mode = Mode::velocity;
	m->target_vel = v;
	m->pending = "s " + fmt(v / scale(*m));
	return PROS_SUCCESS;
}

int32_t motor_move_voltage(int8_t port, const int32_t voltage) {
	MotorPort* m = motor(port);
	if (!m) return PROS_ERR;
	int32_t v = std::clamp(sign(port) * voltage, -12000, 12000);
	if (m->voltage_limit > 0) v = std::clamp(v, -m->voltage_limit, m->voltage_limit);
	m->mode = Mode::voltage;
	m->target_vel = 0;
	m->pending = "v " + std::to_string(v);
	return PROS_SUCCESS;
}

int32_t motor_modify_profiled_velocity(int8_t port, const int32_t velocity) {
	MotorPort* m = motor(port);
	if (!m) return PROS_ERR;
	if (m->mode == Mode::position) command_position(*m, m->target_pos, velocity);
	return PROS_SUCCESS;
}

double motor_get_target_position(int8_t port) {
	MotorPort* m = motor(port);
	return m ? sign(port) * m->target_pos : PROS_ERR_F;
}

int32_t motor_get_target_velocity(int8_t port) {
	MotorPort* m = motor(port);
	return m ? sign(port) * m->target_vel : PROS_ERR;
}

double motor_get_actual_velocity(int8_t port) {
	MotorPort* m = motor(port);
	return m ? sign(port) * reported_rpm(*m) : PROS_ERR_F;
}

int32_t motor_get_current_draw(int8_t port) {
	MotorPort* m = motor(port);
	return m ? m->cur_ma : PROS_ERR;
}

int32_t motor_get_direction(int8_t port) {
	MotorPort* m = motor(port);
	return m ? sign(port) * (reported_rpm(*m) < 0 ? -1 : 1) : PROS_ERR;
}

double motor_get_efficiency(int8_t port) {
	MotorPort* m = motor(port);
	if (!m) return PROS_ERR_F;
	double power_in = std::abs(double(m->volt_mv) * m->cur_ma) / 1e6;
	return power_in > 0.01 ? std::clamp(100.0 * m->power / power_in, 0.0, 100.0) : 0.0;
}

int32_t motor_is_over_current(int8_t port) {
	MotorPort* m = motor(port);
	return m ? m->over_current : PROS_ERR;
}

int32_t motor_is_over_temp(int8_t port) {
	MotorPort* m = motor(port);
	return m ? m->over_temp : PROS_ERR;
}

uint32_t motor_get_faults(int8_t port) {
	MotorPort* m = motor(port);
	if (!m) return PROS_ERR;
	return (m->over_temp ? E_MOTOR_FAULT_MOTOR_OVER_TEMP : 0) | (m->over_current ? E_MOTOR_FAULT_OVER_CURRENT : 0);
}

uint32_t motor_get_flags(int8_t port) {
	MotorPort* m = motor(port);
	if (!m) return PROS_ERR;
	uint32_t flags = 0;
	if (std::abs(reported_rpm(*m)) < 0.5) flags |= E_MOTOR_FLAGS_ZERO_VELOCITY;
	if (std::abs(reported_deg(*m) - m->zero_deg) < 0.5) flags |= E_MOTOR_FLAGS_ZERO_POSITION;
	return flags;
}

int32_t motor_get_raw_position(int8_t port, uint32_t* const timestamp) {
	MotorPort* m = motor(port);
	if (!m) return PROS_ERR;
	if (timestamp) *timestamp = static_cast<uint32_t>(m->read_us / 1000);
	double counts = reported_deg(*m) * 50.0 * declared_ratio(*m) / 360.0;
	return static_cast<int32_t>(sign(port) * std::lround(counts));
}

double motor_get_position(int8_t port) {
	MotorPort* m = motor(port);
	return m ? sign(port) * device_position(*m) : PROS_ERR_F;
}

double motor_get_power(int8_t port) {
	MotorPort* m = motor(port);
	return m ? m->power : PROS_ERR_F;
}

double motor_get_temperature(int8_t port) {
	MotorPort* m = motor(port);
	return m ? m->temp : PROS_ERR_F;
}

double motor_get_torque(int8_t port) {
	MotorPort* m = motor(port);
	return m ? m->torque : PROS_ERR_F;
}

int32_t motor_get_voltage(int8_t port) {
	MotorPort* m = motor(port);
	return m ? sign(port) * m->volt_mv : PROS_ERR;
}

int32_t motor_set_zero_position(int8_t port, const double position) {
	MotorPort* m = motor(port);
	if (!m) return PROS_ERR;
	m->zero_deg = reported_deg(*m) - from_units(*m, position);
	return PROS_SUCCESS;
}

int32_t motor_tare_position(int8_t port) {
	MotorPort* m = motor(port);
	if (!m) return PROS_ERR;
	m->zero_deg = reported_deg(*m);
	return PROS_SUCCESS;
}

int32_t motor_set_brake_mode(int8_t port, const motor_brake_mode_e_t mode) {
	MotorPort* m = motor(port);
	if (!m) return PROS_ERR;
	if (mode < E_MOTOR_BRAKE_COAST || mode > E_MOTOR_BRAKE_HOLD) {
		errno = EINVAL;
		return PROS_ERR;
	}
	if (m->brake != mode || !D().ready) {
		m->brake = mode;
		if (D().ready) m->pending_brake = std::to_string(mode);
	}
	return PROS_SUCCESS;
}

int32_t motor_set_current_limit(int8_t port, const int32_t limit) {
	MotorPort* m = motor(port);
	if (!m) return PROS_ERR;
	int32_t value = std::clamp(limit, 0, 2500);
	if (m->current_limit != value) {
		m->current_limit = value;
		if (D().ready) m->pending_limit = std::to_string(value);
	}
	return PROS_SUCCESS;
}

int32_t motor_set_encoder_units(int8_t port, const motor_encoder_units_e_t units) {
	MotorPort* m = motor(port);
	if (!m) return PROS_ERR;
	if (units < E_MOTOR_ENCODER_DEGREES || units > E_MOTOR_ENCODER_COUNTS) {
		errno = EINVAL;
		return PROS_ERR;
	}
	m->units = units;
	return PROS_SUCCESS;
}

int32_t motor_set_gearing(int8_t port, const motor_gearset_e_t gearset) {
	MotorPort* m = motor(port);
	if (!m) return PROS_ERR;
	if (gearset < E_MOTOR_GEARSET_36 || gearset > E_MOTOR_GEARSET_06) {
		errno = EINVAL;
		return PROS_ERR;
	}
	m->gearset = gearset;
	int p = std::abs(port);
	if (D().ready && ratio_of(gearset) != m->cartridge) {
		host_warn_once("gearing" + std::to_string(p),
		               "port " + std::to_string(p) + ": the code declares the " + cartridge_name(ratio_of(gearset)) +
		                   " cartridge, but the robot config has " + cartridge_name(m->cartridge) +
		                   "; as on a real motor, speeds and positions are scaled");
	}
	return PROS_SUCCESS;
}

int32_t motor_set_voltage_limit(int8_t port, const int32_t limit) {
	MotorPort* m = motor(port);
	if (!m) return PROS_ERR;
	m->voltage_limit = std::clamp(limit, 0, 12000);
	return PROS_SUCCESS;
}

motor_brake_mode_e_t motor_get_brake_mode(int8_t port) {
	MotorPort* m = motor(port);
	return m ? static_cast<motor_brake_mode_e_t>(m->brake) : E_MOTOR_BRAKE_INVALID;
}

int32_t motor_get_current_limit(int8_t port) {
	MotorPort* m = motor(port);
	return m ? m->current_limit : PROS_ERR;
}

motor_encoder_units_e_t motor_get_encoder_units(int8_t port) {
	MotorPort* m = motor(port);
	return m ? static_cast<motor_encoder_units_e_t>(m->units) : E_MOTOR_ENCODER_INVALID;
}

motor_gearset_e_t motor_get_gearing(int8_t port) {
	MotorPort* m = motor(port);
	if (!m) return E_MOTOR_GEARSET_INVALID;
	int ratio = declared_ratio(*m);
	return ratio == 36 ? E_MOTOR_GEARSET_36 : ratio == 6 ? E_MOTOR_GEARSET_06 : E_MOTOR_GEARSET_18;
}

int32_t motor_get_voltage_limit(int8_t port) {
	MotorPort* m = motor(port);
	return m ? m->voltage_limit : PROS_ERR;
}

motor_type_e_t motor_get_type(int8_t port) {
	return motor(port) ? E_MOTOR_TYPE_V5 : E_MOTOR_TYPE_INVALID;
}

// ---- inertial sensor -------------------------------------------------------------------

int32_t imu_reset(uint8_t port) {
	ImuPort* i = imu(port);
	if (!i) return PROS_ERR;
	if (i->calibrating) {
		errno = EAGAIN;
		return PROS_ERR;
	}
	host_emit("I " + std::to_string(port));
	i->calibrating = true;
	task_delay(5);  // PROS waits for the calibrating flag to appear
	return PROS_SUCCESS;
}

int32_t imu_reset_blocking(uint8_t port) {
	if (imu_reset(port) == PROS_ERR) return PROS_ERR;
	ImuPort* i = &D().imu[port];
	for (uint32_t waited = 5; i->calibrating; waited += 5) {
		if (waited >= 3000) {
			errno = EAGAIN;
			return PROS_ERR;
		}
		task_delay(5);
	}
	return PROS_SUCCESS;
}

int32_t imu_set_data_rate(uint8_t port, uint32_t rate) {
	(void)rate;
	return imu(port) ? PROS_SUCCESS : PROS_ERR;
}

double imu_get_rotation(uint8_t port) {
	ImuPort* i = imu(port);
	return imu_ready(i) ? i->rot + i->rot_off : PROS_ERR_F;
}

double imu_get_heading(uint8_t port) {
	ImuPort* i = imu(port);
	return imu_ready(i) ? wrap360(wrap360(i->rot) + i->head_off) : PROS_ERR_F;
}

euler_s_t imu_get_euler(uint8_t port) {
	ImuPort* i = imu(port);
	if (!imu_ready(i)) return {PROS_ERR_F, PROS_ERR_F, PROS_ERR_F};
	return {i->pitch_off, i->roll_off, raw_yaw(*i) + i->yaw_off};
}

quaternion_s_t imu_get_quaternion(uint8_t port) {
	ImuPort* i = imu(port);
	if (!imu_ready(i)) return {PROS_ERR_F, PROS_ERR_F, PROS_ERR_F, PROS_ERR_F};
	const double d2r = 3.14159265358979323846 / 180.0;
	double roll = std::fmod(i->roll_off, 360.0) * d2r, pitch = std::fmod(i->pitch_off, 360.0) * d2r;
	double yaw = std::fmod(raw_yaw(*i) + i->yaw_off, 360.0) * d2r;
	double cy = std::cos(yaw / 2), sy = std::sin(yaw / 2), cp = std::cos(pitch / 2), sp = std::sin(pitch / 2);
	double cr = std::cos(roll / 2), sr = std::sin(roll / 2);
	return {sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy,
	        cr * cp * cy + sr * sp * sy};
}

double imu_get_pitch(uint8_t port) {
	ImuPort* i = imu(port);
	return imu_ready(i) ? std::fmod(i->pitch_off, 360.0) : PROS_ERR_F;
}

double imu_get_roll(uint8_t port) {
	ImuPort* i = imu(port);
	return imu_ready(i) ? std::fmod(i->roll_off, 360.0) : PROS_ERR_F;
}

double imu_get_yaw(uint8_t port) {
	ImuPort* i = imu(port);
	return imu_ready(i) ? std::fmod(raw_yaw(*i) + i->yaw_off, 360.0) : PROS_ERR_F;
}

imu_gyro_s_t imu_get_gyro_rate(uint8_t port) {
	ImuPort* i = imu(port);
	if (!imu_ready(i)) return {PROS_ERR_F, PROS_ERR_F, PROS_ERR_F};
	return {0.0, 0.0, i->gyro};
}

imu_accel_s_t imu_get_accel(uint8_t port) {
	ImuPort* i = imu(port);
	if (!imu_ready(i)) return {PROS_ERR_F, PROS_ERR_F, PROS_ERR_F};
	return {0.0, 0.0, 0.0};  // acceleration is not simulated
}

imu_status_e_t imu_get_status(uint8_t port) {
	ImuPort* i = imu(port);
	if (!i) return E_IMU_STATUS_ERROR;
	return i->calibrating ? E_IMU_STATUS_CALIBRATING : E_IMU_STATUS_READY;
}

imu_orientation_e_t imu_get_physical_orientation(uint8_t port) {
	return imu(port) ? E_IMU_Z_UP : E_IMU_ORIENTATION_ERROR;
}

int32_t imu_tare_rotation(uint8_t port) { return imu_set_rotation(port, 0); }
int32_t imu_tare_heading(uint8_t port) { return imu_set_heading(port, 0); }
int32_t imu_tare_pitch(uint8_t port) { return imu_set_pitch(port, 0); }
int32_t imu_tare_roll(uint8_t port) { return imu_set_roll(port, 0); }
int32_t imu_tare_yaw(uint8_t port) { return imu_set_yaw(port, 0); }

int32_t imu_tare_euler(uint8_t port) { return imu_set_euler(port, {0, 0, 0}); }

int32_t imu_tare(uint8_t port) {
	ImuPort* i = imu(port);
	if (!imu_ready(i)) return PROS_ERR;
	i->rot_off = -i->rot;
	i->head_off = -wrap360(i->rot);
	i->pitch_off = i->roll_off = 0;
	i->yaw_off = -raw_yaw(*i);
	return PROS_SUCCESS;
}

int32_t imu_set_euler(uint8_t port, euler_s_t target) {
	ImuPort* i = imu(port);
	if (!imu_ready(i)) return PROS_ERR;
	i->pitch_off = target.pitch;
	i->roll_off = target.roll;
	i->yaw_off = target.yaw - raw_yaw(*i);
	return PROS_SUCCESS;
}

int32_t imu_set_rotation(uint8_t port, double target) {
	ImuPort* i = imu(port);
	if (!imu_ready(i)) return PROS_ERR;
	i->rot_off = target - i->rot;
	return PROS_SUCCESS;
}

int32_t imu_set_heading(uint8_t port, double target) {
	ImuPort* i = imu(port);
	if (!imu_ready(i)) return PROS_ERR;
	target = std::clamp(target, 0.0, 360.0);
	i->head_off = target - wrap360(i->rot);
	return PROS_SUCCESS;
}

int32_t imu_set_pitch(uint8_t port, double target) {
	ImuPort* i = imu(port);
	if (!imu_ready(i)) return PROS_ERR;
	i->pitch_off = target;
	return PROS_SUCCESS;
}

int32_t imu_set_roll(uint8_t port, double target) {
	ImuPort* i = imu(port);
	if (!imu_ready(i)) return PROS_ERR;
	i->roll_off = target;
	return PROS_SUCCESS;
}

int32_t imu_set_yaw(uint8_t port, double target) {
	ImuPort* i = imu(port);
	if (!imu_ready(i)) return PROS_ERR;
	i->yaw_off = target - raw_yaw(*i);
	return PROS_SUCCESS;
}

// ---- rotation sensor -------------------------------------------------------------------

int32_t rotation_reset(uint8_t port) {
	RotationPort* r = rotation(port);
	if (!r) return PROS_ERR;
	int32_t angle = rotation_get_angle(port);
	r->offset = rotation_sign(*r) * angle - r->raw;
	return PROS_SUCCESS;
}

int32_t rotation_set_data_rate(uint8_t port, uint32_t rate) {
	(void)rate;
	return rotation(port) ? PROS_SUCCESS : PROS_ERR;
}

int32_t rotation_set_position(uint8_t port, int32_t position) {
	RotationPort* r = rotation(port);
	if (!r) return PROS_ERR;
	r->offset = rotation_sign(*r) * position - r->raw;
	return PROS_SUCCESS;
}

int32_t rotation_reset_position(uint8_t port) { return rotation_set_position(port, 0); }

int32_t rotation_get_position(uint8_t port) {
	RotationPort* r = rotation(port);
	return r ? static_cast<int32_t>(rotation_sign(*r) * (r->raw + r->offset)) : PROS_ERR;
}

int32_t rotation_get_velocity(uint8_t port) {
	RotationPort* r = rotation(port);
	return r ? static_cast<int32_t>(rotation_sign(*r) * r->vel) : PROS_ERR;
}

int32_t rotation_get_angle(uint8_t port) {
	RotationPort* r = rotation(port);
	if (!r) return PROS_ERR;
	std::int64_t angle = (rotation_sign(*r) * r->raw) % 36000;
	return static_cast<int32_t>(angle < 0 ? angle + 36000 : angle);
}

int32_t rotation_set_reversed(uint8_t port, bool value) {
	RotationPort* r = rotation(port);
	if (!r) return PROS_ERR;
	r->reversed = value;
	return PROS_SUCCESS;
}

int32_t rotation_reverse(uint8_t port) {
	RotationPort* r = rotation(port);
	if (!r) return PROS_ERR;
	r->reversed = !r->reversed;
	return PROS_SUCCESS;
}

int32_t rotation_init_reverse(uint8_t port, bool reverse_flag) { return rotation_set_reversed(port, reverse_flag); }

int32_t rotation_get_reversed(uint8_t port) {
	RotationPort* r = rotation(port);
	return r ? r->reversed : PROS_ERR;
}

// ---- distance sensor -------------------------------------------------------------------

int32_t distance_get(uint8_t port) {
	if (!check_port(port, Kind::distance)) return PROS_ERR;
	int32_t mm = D().distance[port].mm;
	return mm < 0 ? 9999 : mm;
}

int32_t distance_get_confidence(uint8_t port) {
	if (!check_port(port, Kind::distance)) return PROS_ERR;
	return D().distance[port].mm < 0 ? 0 : D().distance[port].confidence;
}

int32_t distance_get_object_size(uint8_t port) {
	if (!check_port(port, Kind::distance)) return PROS_ERR;
	return D().distance[port].mm < 0 ? 0 : 400;  // the field walls are large objects
}

double distance_get_object_velocity(uint8_t port) {
	if (!check_port(port, Kind::distance)) return PROS_ERR_F;
	return 0.0;
}

// ---- GPS -------------------------------------------------------------------------------

int32_t gps_set_offset(uint8_t port, double xOffset, double yOffset) {
	GpsPort* g = gps(port);
	if (!g) return PROS_ERR;
	g->off_x = xOffset, g->off_y = yOffset;
	return 1;
}

int32_t gps_set_position(uint8_t port, double xInitial, double yInitial, double headingInitial) {
	GpsPort* g = gps(port);
	if (!g) return PROS_ERR;
	g->initial = true, g->ix = xInitial, g->iy = yInitial, g->ih = headingInitial;
	return 1;
}

int32_t gps_initialize_full(uint8_t port, double xInitial, double yInitial, double headingInitial, double xOffset,
                            double yOffset) {
	if (gps_set_offset(port, xOffset, yOffset) == PROS_ERR) return PROS_ERR;
	return gps_set_position(port, xInitial, yInitial, headingInitial);
}

gps_position_s_t gps_get_offset(uint8_t port) {
	GpsPort* g = gps(port);
	if (!g) return {PROS_ERR_F, PROS_ERR_F};
	return {g->off_x, g->off_y};
}

int32_t gps_set_data_rate(uint8_t port, uint32_t rate) {
	(void)rate;  // the simulated GPS keeps its configured rate
	return gps(port) ? 1 : PROS_ERR;
}

double gps_get_error(uint8_t port) {
	GpsPort* g = gps(port);
	if (!g) return PROS_ERR_F;
	if (!g->have) {
		errno = EAGAIN;
		return PROS_ERR_F;
	}
	return g->error;
}

gps_position_s_t gps_get_position(uint8_t port) {
	double x, y, h;
	if (!gps_state(port, &x, &y, &h)) return {PROS_ERR_F, PROS_ERR_F};
	return {x, y};
}

double gps_get_position_x(uint8_t port) { return gps_get_position(port).x; }

double gps_get_position_y(uint8_t port) { return gps_get_position(port).y; }

double gps_get_heading(uint8_t port) {
	double x, y, h;
	if (!gps_state(port, &x, &y, &h)) return PROS_ERR_F;
	return std::fmod(std::fmod(h, 360.0) + 360.0, 360.0);
}

double gps_get_heading_raw(uint8_t port) {
	GpsPort* g = gps(port);
	if (!g) return PROS_ERR_F;
	if (!g->have) return g->initial ? g->ih : (errno = EAGAIN, PROS_ERR_F);
	return g->rotation;
}

double gps_get_yaw(uint8_t port) {
	double heading = gps_get_heading(port);
	if (heading == PROS_ERR_F) return PROS_ERR_F;
	return heading > 180.0 ? heading - 360.0 : heading;
}

double gps_get_pitch(uint8_t port) {
	double x, y, h;
	return gps_state(port, &x, &y, &h) ? 0.0 : PROS_ERR_F;  // the field is flat
}

double gps_get_roll(uint8_t port) { return gps_get_pitch(port); }

gps_orientation_s_t gps_get_orientation(uint8_t port) {
	return {gps_get_pitch(port), gps_get_roll(port), gps_get_yaw(port)};
}

gps_status_s_t gps_get_position_and_orientation(uint8_t port) {
	gps_position_s_t p = gps_get_position(port);
	return {p.x, p.y, gps_get_pitch(port), gps_get_roll(port), gps_get_yaw(port)};
}

gps_status_s_t gps_get_status(uint8_t port) { return gps_get_position_and_orientation(port); }

gps_gyro_s_t gps_get_gyro_rate(uint8_t port) {
	GpsPort* g = gps(port);
	if (!g || !g->have) return {PROS_ERR_F, PROS_ERR_F, PROS_ERR_F};
	return {0.0, 0.0, g->gyro};
}

double gps_get_gyro_rate_x(uint8_t port) { return gps_get_gyro_rate(port).x; }

double gps_get_gyro_rate_y(uint8_t port) { return gps_get_gyro_rate(port).y; }

double gps_get_gyro_rate_z(uint8_t port) { return gps_get_gyro_rate(port).z; }

gps_accel_s_t gps_get_accel(uint8_t port) {
	GpsPort* g = gps(port);
	if (!g || !g->have) return {PROS_ERR_F, PROS_ERR_F, PROS_ERR_F};
	return {0.0, 0.0, 0.0};  // not modeled
}

double gps_get_accel_x(uint8_t port) { return gps_get_accel(port).x; }

double gps_get_accel_y(uint8_t port) { return gps_get_accel(port).y; }

double gps_get_accel_z(uint8_t port) { return gps_get_accel(port).z; }

// ---- controller ------------------------------------------------------------------------

int32_t controller_is_connected(controller_id_e_t id) {
	if (!controller_ok(id)) return PROS_ERR;
	return id == E_CONTROLLER_MASTER;
}

int32_t controller_get_analog(controller_id_e_t id, controller_analog_e_t channel) {
	if (!controller_ok(id)) return PROS_ERR;
	if (channel < E_CONTROLLER_ANALOG_LEFT_X || channel > E_CONTROLLER_ANALOG_RIGHT_Y) {
		errno = EINVAL;
		return PROS_ERR;
	}
	return id == E_CONTROLLER_MASTER ? D().controller.analog[channel] : 0;
}

int32_t controller_get_battery_capacity(controller_id_e_t id) {
	if (!controller_ok(id)) return PROS_ERR;
	return id == E_CONTROLLER_MASTER ? 100 : 0;
}

int32_t controller_get_battery_level(controller_id_e_t id) {
	if (!controller_ok(id)) return PROS_ERR;
	return id == E_CONTROLLER_MASTER ? 100 : 0;
}

int32_t controller_get_digital(controller_id_e_t id, controller_digital_e_t button) {
	if (!controller_ok(id)) return PROS_ERR;
	if (button < E_CONTROLLER_DIGITAL_L1 || button > E_CONTROLLER_DIGITAL_A) {
		errno = EINVAL;
		return PROS_ERR;
	}
	if (id != E_CONTROLLER_MASTER) return 0;
	return (D().controller.buttons >> (button - E_CONTROLLER_DIGITAL_L1)) & 1u;
}

int32_t controller_get_digital_new_press(controller_id_e_t id, controller_digital_e_t button) {
	int32_t pressed = controller_get_digital(id, button);
	if (pressed == PROS_ERR) return PROS_ERR;
	bool& seen = D().controller.pressed[button - E_CONTROLLER_DIGITAL_L1];
	if (!pressed) seen = false;
	if (pressed && !seen) {
		seen = true;
		return 1;
	}
	return 0;
}

int32_t controller_get_digital_new_release(controller_id_e_t id, controller_digital_e_t button) {
	int32_t pressed = controller_get_digital(id, button);
	if (pressed == PROS_ERR) return PROS_ERR;
	bool& seen = D().controller.released[button - E_CONTROLLER_DIGITAL_L1];
	if (pressed) seen = false;
	if (!pressed && !seen) {
		seen = true;
		return 1;
	}
	return 0;
}

int32_t controller_set_text(controller_id_e_t id, uint8_t line, uint8_t col, const char* str) {
	if (!controller_ok(id)) return PROS_ERR;
	if (id != E_CONTROLLER_MASTER || line > 2 || col > 18) return PROS_SUCCESS;
	std::string& row = D().controller.screen[line];
	std::string before = row;
	for (std::size_t k = 0; str[k] && col + k < row.size(); k++) row[col + k] = str[k];
	if (row != before) host_emit("CTRL " + std::to_string(line) + " " + row);
	return PROS_SUCCESS;
}

int32_t controller_print(controller_id_e_t id, uint8_t line, uint8_t col, const char* fmt, ...) {
	va_list args;
	va_start(args, fmt);
	std::string text = vformat(fmt, args);
	va_end(args);
	return controller_set_text(id, line, col, text.c_str());
}

int32_t controller_clear_line(controller_id_e_t id, uint8_t line) {
	if (!controller_ok(id)) return PROS_ERR;
	if (id == E_CONTROLLER_MASTER && line <= 2) {
		D().controller.screen[line] = std::string(19, ' ');
		host_emit("CTRL " + std::to_string(line) + " ");
	}
	return PROS_SUCCESS;
}

int32_t controller_clear(controller_id_e_t id) {
	for (uint8_t line = 0; line < 3; line++) controller_clear_line(id, line);
	return PROS_SUCCESS;
}

int32_t controller_rumble(controller_id_e_t id, const char* rumble_pattern) {
	(void)rumble_pattern;
	return controller_ok(id) ? PROS_SUCCESS : PROS_ERR;
}

// ---- competition, battery, SD card -----------------------------------------------------

uint8_t competition_get_status(void) {
	api_call();
	return D().competition;
}
uint8_t competition_is_disabled(void) { return (competition_get_status() & COMPETITION_DISABLED) != 0; }
uint8_t competition_is_connected(void) { return (competition_get_status() & COMPETITION_CONNECTED) != 0; }
uint8_t competition_is_autonomous(void) { return (competition_get_status() & COMPETITION_AUTONOMOUS) != 0; }
uint8_t competition_is_field(void) { return (competition_get_status() & COMPETITION_SYSTEM) != 0; }
uint8_t competition_is_switch(void) {
	uint8_t s = competition_get_status();
	return (s & COMPETITION_CONNECTED) && !(s & COMPETITION_SYSTEM);
}

int32_t battery_get_voltage(void) {
	api_call();
	return D().battery_mv;
}
int32_t battery_get_current(void) {
	api_call();
	return D().battery_ma;
}
double battery_get_temperature(void) {
	api_call();
	return 25.0;
}
double battery_get_capacity(void) {
	api_call();
	return D().battery_pct;
}

int32_t usd_is_installed(void) { return usd_folder() != nullptr ? 1 : 0; }  // vexsim run --sd
int32_t usd_list_files(const char* path, char* buffer, int32_t len) {
	(void)path;
	if (buffer && len > 0) buffer[0] = 0;
	errno = ENXIO;
	return PROS_ERR;
}

// ---- LLEMU and brain screen ------------------------------------------------------------

bool lcd_is_initialized(void) { return D().lcd_on; }

bool lcd_initialize(void) {
	D().lcd_on = true;
	return true;
}

bool lcd_shutdown(void) {
	D().lcd_on = false;
	return true;
}

bool lcd_set_text(int16_t line, const char* text) {
	api_call();
	if (!D().lcd_on) {
		errno = ENXIO;
		return false;
	}
	if (line < 0 || line > 7) {
		errno = EINVAL;
		return false;
	}
	if (D().lcd[line] != text) {
		D().lcd[line] = text;
		emit_lcd(line);
	}
	return true;
}

bool lcd_print(int16_t line, const char* fmt, ...) {
	va_list args;
	va_start(args, fmt);
	std::string text = vformat(fmt, args);
	va_end(args);
	return lcd_set_text(line, text.c_str());
}

bool lcd_clear_line(int16_t line) { return lcd_set_text(line, ""); }

bool lcd_clear(void) {
	for (int16_t line = 0; line < 8; line++) lcd_set_text(line, "");
	return D().lcd_on;
}

void lcd_register_btn0_cb(lcd_btn_cb_fn_t cb) { (void)cb; }
void lcd_register_btn1_cb(lcd_btn_cb_fn_t cb) { (void)cb; }
void lcd_register_btn2_cb(lcd_btn_cb_fn_t cb) { (void)cb; }
uint8_t lcd_read_buttons(void) { return 0; }

uint32_t screen_set_pen(uint32_t color) { return (void)color, 1; }
uint32_t screen_set_eraser(uint32_t color) { return (void)color, 1; }
uint32_t screen_get_pen(void) { return 0x00FFFFFF; }
uint32_t screen_get_eraser(void) { return 0; }
uint32_t screen_erase(void) { return 1; }
uint32_t screen_scroll(int16_t, int16_t) { return 1; }
uint32_t screen_scroll_area(int16_t, int16_t, int16_t, int16_t, int16_t) { return 1; }
uint32_t screen_copy_area(int16_t, int16_t, int16_t, int16_t, uint32_t*, int32_t) { return 1; }
uint32_t screen_draw_pixel(int16_t, int16_t) { return 1; }
uint32_t screen_erase_pixel(int16_t, int16_t) { return 1; }
uint32_t screen_draw_line(int16_t, int16_t, int16_t, int16_t) { return 1; }
uint32_t screen_erase_line(int16_t, int16_t, int16_t, int16_t) { return 1; }
uint32_t screen_draw_rect(int16_t, int16_t, int16_t, int16_t) { return 1; }
uint32_t screen_erase_rect(int16_t, int16_t, int16_t, int16_t) { return 1; }
uint32_t screen_fill_rect(int16_t, int16_t, int16_t, int16_t) { return 1; }
uint32_t screen_draw_circle(int16_t, int16_t, int16_t) { return 1; }
uint32_t screen_erase_circle(int16_t, int16_t, int16_t) { return 1; }
uint32_t screen_fill_circle(int16_t, int16_t, int16_t) { return 1; }

uint32_t screen_print(text_format_e_t txt_fmt, const int16_t line, const char* text, ...) {
	(void)txt_fmt;
	va_list args;
	va_start(args, text);
	std::string s = vformat(text, args);
	va_end(args);
	if (line >= 0 && line <= 7 && D().lcd[line] != s) {
		D().lcd[line] = s;
		emit_lcd(line);
	}
	return 1;
}

uint32_t screen_print_at(text_format_e_t txt_fmt, const int16_t x, const int16_t y, const char* text, ...) {
	(void)txt_fmt, (void)x, (void)y, (void)text;
	return 1;
}

screen_touch_status_s_t screen_touch_status(void) { return {E_TOUCH_RELEASED, 0, 0, 0, 0}; }
uint32_t screen_touch_callback(touch_event_cb_fn_t cb, last_touch_e_t event_type) {
	(void)cb, (void)event_type;
	return 1;
}

// ---- three-wire ports ------------------------------------------------------------------

adi_port_config_e_t ext_adi_port_get_config(uint8_t smart_port, uint8_t adi_port) {
	int32_t a = adi_port;
	if (!adi_ok(smart_port, a)) return E_ADI_ERR;
	return static_cast<adi_port_config_e_t>(D().adi_config[smart_port][a]);
}

int32_t ext_adi_port_get_value(uint8_t smart_port, uint8_t adi_port) {
	int32_t a = adi_port;
	if (!adi_ok(smart_port, a)) return PROS_ERR;
	int32_t config = D().adi_config[smart_port][a];
	bool output = config == E_ADI_DIGITAL_OUT || config == E_ADI_ANALOG_OUT || config == E_ADI_LEGACY_PWM ||
	              config == E_ADI_LEGACY_SERVO;
	return output ? D().adi_value[smart_port][a] : 0;
}

int32_t ext_adi_port_set_config(uint8_t smart_port, uint8_t adi_port, adi_port_config_e_t type) {
	int32_t a = adi_port;
	if (!adi_ok(smart_port, a)) return PROS_ERR;
	D().adi_config[smart_port][a] = type;
	D().adi_value[smart_port][a] = 0;
	return PROS_SUCCESS;
}

int32_t ext_adi_port_set_value(uint8_t smart_port, uint8_t adi_port, int32_t value) {
	int32_t a = adi_port;
	if (!adi_ok(smart_port, a)) return PROS_ERR;
	D().adi_value[smart_port][a] = value;
	return PROS_SUCCESS;
}

adi_port_config_e_t adi_port_get_config(uint8_t port) { return ext_adi_port_get_config(INTERNAL_ADI_PORT, port); }
int32_t adi_port_get_value(uint8_t port) { return ext_adi_port_get_value(INTERNAL_ADI_PORT, port); }
int32_t adi_port_set_config(uint8_t port, adi_port_config_e_t type) {
	return ext_adi_port_set_config(INTERNAL_ADI_PORT, port, type);
}
int32_t adi_port_set_value(uint8_t port, int32_t value) { return ext_adi_port_set_value(INTERNAL_ADI_PORT, port, value); }
int32_t adi_analog_calibrate(uint8_t port) { return adi_port_get_value(port); }
int32_t adi_analog_read(uint8_t port) { return adi_port_get_value(port); }
int32_t adi_analog_read_calibrated(uint8_t port) { return adi_port_get_value(port); }
int32_t adi_analog_read_calibrated_HR(uint8_t port) { return adi_port_get_value(port); }
int32_t adi_digital_read(uint8_t port) { return adi_port_get_value(port); }
int32_t adi_digital_get_new_press(uint8_t port) { return adi_port_get_value(port) == PROS_ERR ? PROS_ERR : 0; }
int32_t adi_digital_write(uint8_t port, bool value) { return adi_port_set_value(port, value); }
int32_t adi_pin_mode(uint8_t port, uint8_t mode) {
	adi_port_config_e_t config = mode == OUTPUT          ? E_ADI_DIGITAL_OUT
	                             : mode == INPUT_ANALOG  ? E_ADI_ANALOG_IN
	                             : mode == OUTPUT_ANALOG ? E_ADI_ANALOG_OUT
	                                                     : E_ADI_DIGITAL_IN;
	return adi_port_set_config(port, config);
}
int32_t adi_motor_set(uint8_t port, int8_t speed) { return adi_port_set_value(port, speed); }
int32_t adi_motor_get(uint8_t port) { return adi_port_get_value(port); }
int32_t adi_motor_stop(uint8_t port) { return adi_port_set_value(port, 0); }
adi_encoder_t adi_encoder_init(uint8_t port_top, uint8_t port_bottom, bool reverse) {
	(void)port_bottom, (void)reverse;
	return adi_port_set_config(port_top, E_ADI_LEGACY_ENCODER) == PROS_ERR ? PROS_ERR : adi_index(port_top);
}
int32_t adi_encoder_get(adi_encoder_t enc) { return adi_port_get_value(static_cast<uint8_t>(enc)); }
int32_t adi_encoder_reset(adi_encoder_t enc) { return adi_port_set_value(static_cast<uint8_t>(enc), 0); }
int32_t adi_encoder_shutdown(adi_encoder_t enc) { return (void)enc, PROS_SUCCESS; }
adi_ultrasonic_t adi_ultrasonic_init(uint8_t port_ping, uint8_t port_echo) {
	(void)port_echo;
	return adi_port_set_config(port_ping, E_ADI_LEGACY_ULTRASONIC) == PROS_ERR ? PROS_ERR : adi_index(port_ping);
}
int32_t adi_ultrasonic_get(adi_ultrasonic_t ult) { return adi_port_get_value(static_cast<uint8_t>(ult)); }
int32_t adi_ultrasonic_shutdown(adi_ultrasonic_t ult) { return (void)ult, PROS_SUCCESS; }
adi_gyro_t adi_gyro_init(uint8_t port, double multiplier) {
	(void)multiplier;
	return adi_port_set_config(port, E_ADI_LEGACY_GYRO) == PROS_ERR ? PROS_ERR : adi_index(port);
}
double adi_gyro_get(adi_gyro_t gyro) { return adi_port_get_value(static_cast<uint8_t>(gyro)); }
int32_t adi_gyro_reset(adi_gyro_t gyro) { return adi_port_set_value(static_cast<uint8_t>(gyro), 0); }
int32_t adi_gyro_shutdown(adi_gyro_t gyro) { return (void)gyro, PROS_SUCCESS; }
adi_potentiometer_t adi_potentiometer_init(uint8_t port) {
	return adi_port_set_config(port, E_ADI_ANALOG_IN) == PROS_ERR ? PROS_ERR : adi_index(port);
}
adi_potentiometer_t adi_potentiometer_type_init(uint8_t port, adi_potentiometer_type_e_t potentiometer_type) {
	(void)potentiometer_type;
	return adi_potentiometer_init(port);
}
double adi_potentiometer_get_angle(adi_potentiometer_t potentiometer) {
	return adi_port_get_value(static_cast<uint8_t>(potentiometer)) == PROS_ERR ? PROS_ERR_F : 0.0;
}

}  // namespace c
}  // namespace pros
}
