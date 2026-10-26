/*
 * vexsim extras for robot code. On the robot this header doesn't exist, so
 * guard its use:
 *
 *   #if __has_include("vexsim/sim.hpp")
 *   #include "vexsim/sim.hpp"
 *   #endif
 *   ...
 *   #ifdef VEXSIM
 *   vexsim::report_pose(x, y, theta);
 *   #endif
 *
 * `vexsim build` defines VEXSIM=1.
 */
#ifndef _VEXSIM_SIM_HPP_
#define _VEXSIM_SIM_HPP_

#include <cstdlib>
#include <map>
#include <sstream>
#include <string>

extern "C" void vexsim_report_pose(double x_in, double y_in, double theta_deg);

namespace vexsim {

/*
 * The task `vexsim bench` asks this program to do, for scenarios whose
 * controller is a PROS project (kind: pros). Poses use the LemLib convention:
 * inches, theta in degrees clockwise from +y.
 */
struct Task {
	std::string type;  // move_to_point, move_to_pose, turn_to_heading, drive or follow; "" outside a benchmark
	double start_x = 0, start_y = 0, start_theta = 0;  // where odometry should start
	double x = 0, y = 0, theta = 0;                    // the target
	bool forwards = true;                              // move_to_point
	double distance = 0;                               // drive: inches along the current heading
	int timeout_ms = 0;                                // the scenario's time limit
	std::string path;  // follow: the reference path as a LemLib path file ("x, y, speed" lines, endData)
	std::map<std::string, std::string> options;  // the scenario's controller options

	explicit operator bool() const { return !type.empty(); }
	double option(const std::string& key, double fallback) const {
		auto it = options.find(key);
		return it == options.end() ? fallback : std::strtod(it->second.c_str(), nullptr);
	}
};

namespace detail {
inline void parse_numbers(const std::string& text, double* out, int n) {
	std::stringstream in(text);
	std::string item;
	for (int i = 0; i < n && std::getline(in, item, ','); i++) out[i] = std::strtod(item.c_str(), nullptr);
}

// VEXSIM_TASK: key=value pairs separated by ';' (see vexsim/bench/trial.py).
inline Task parse_task(const char* text) {
	Task task;
	if (!text) return task;
	std::stringstream in(text);
	std::string field;
	while (std::getline(in, field, ';')) {
		auto eq = field.find('=');
		if (eq == std::string::npos) continue;
		std::string key = field.substr(0, eq), value = field.substr(eq + 1);
		double v[3] = {0, 0, 0};
		if (key == "type") {
			task.type = value;
		} else if (key == "start") {
			parse_numbers(value, v, 3);
			task.start_x = v[0], task.start_y = v[1], task.start_theta = v[2];
		} else if (key == "target") {
			parse_numbers(value, v, 3);
			task.x = v[0], task.y = v[1], task.theta = v[2];
		} else if (key == "forwards") {
			task.forwards = value != "0";
		} else if (key == "distance") {
			task.distance = std::strtod(value.c_str(), nullptr);
		} else if (key == "timeout_ms") {
			task.timeout_ms = std::atoi(value.c_str());
		} else if (key == "path") {
			std::stringstream points(value);
			std::string point;
			while (std::getline(points, point, ' ')) {
				parse_numbers(point, v, 3);
				std::ostringstream line;
				line << v[0] << ", " << v[1] << ", " << v[2] << "\n";
				task.path += line.str();
			}
			task.path += "endData\n";
		} else if (key.rfind("opt.", 0) == 0) {
			task.options[key.substr(4)] = value;
		}
	}
	return task;
}
}  // namespace detail

/* The benchmark task, from $VEXSIM_TASK; converts to false outside `vexsim bench`. */
inline Task& benchmark_task() {
	static Task task = detail::parse_task(std::getenv("VEXSIM_TASK"));
	return task;
}

/*
 * Show your odometry's pose estimate in the viewer and telemetry (the
 * "estimated pose" trail). LemLib convention: inches, theta in degrees
 * clockwise from +y, so (0, 0, 90) faces +x.
 */
inline void report_pose(double x_in, double y_in, double theta_deg) { vexsim_report_pose(x_in, y_in, theta_deg); }

}  // namespace vexsim

#endif
