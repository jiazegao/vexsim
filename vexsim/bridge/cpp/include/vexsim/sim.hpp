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

#include <cstdio>
#include <cstdlib>
#include <map>
#include <sstream>
#include <string>

extern "C" void vexsim_report_pose(double x_in, double y_in, double theta_deg);
extern "C" void vexsim_draw(const char* command);

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

/*
 * Drawing on the field, to debug with: the browser app (vexsim ui) shows what robot code
 * draws over the field, live and in recorded runs. Shapes go into named layers, which can be
 * shown and hidden one by one. A layer keeps what was drawn into it until it's cleared, so
 * clear it, then draw it again, whenever it changes:
 *
 *   vexsim::draw_clear("mcl");
 *   for (auto& p : particles) vexsim::draw_point("mcl", p.x, p.y);
 *   vexsim::draw_ellipse("mcl", x, y, 2 * std_x, 2 * std_y, 0, vexsim::Color::blue);
 *   vexsim::draw_pose("mcl", x, y, theta, vexsim::Color::blue);
 *
 * Inches in the field's frame (LemLib's x and y), angles as LemLib's: degrees clockwise
 * from +y. Colors are the field's palette, so drawings show in light and dark themes.
 */
enum class Color { violet, blue, orange, aqua, yellow, magenta, green, red, ink, muted };

namespace detail {
inline const char* color_name(Color color) {
	static const char* const names[] = {"violet", "blue",  "orange", "aqua", "yellow",
	                                    "magenta", "green", "red",    "ink",  "muted"};
	int i = static_cast<int>(color);
	return i >= 0 && i < 10 ? names[i] : "violet";
}

// A layer's name as the protocol takes it: one word.
inline std::string layer_name(const std::string& layer) {
	std::string name = layer.empty() ? std::string("debug") : layer.substr(0, 40);
	for (char& c : name)
		if (static_cast<unsigned char>(c) <= ' ') c = '_';
	return name;
}

// "<shape> <layer> <numbers...> <color>"
inline void draw(const char* shape, const std::string& layer, const double* numbers, int n, Color color) {
	std::string command = std::string(shape) + " " + layer_name(layer);
	char buf[32];
	for (int i = 0; i < n; i++) {
		std::snprintf(buf, sizeof buf, " %.6g", numbers[i]);
		command += buf;
	}
	command += " ";
	command += color_name(color);
	vexsim_draw(command.c_str());
}
}  // namespace detail

/* Empty a layer, to draw it afresh. */
inline void draw_clear(const std::string& layer) { vexsim_draw(("clear " + detail::layer_name(layer)).c_str()); }

/* A dot `size_px` pixels across (it stays that size when the view zooms). */
inline void draw_point(const std::string& layer, double x, double y, Color color = Color::violet, double size_px = 3) {
	const double v[] = {x, y, size_px};
	detail::draw("point", layer, v, 3, color);
}

inline void draw_line(const std::string& layer, double x1, double y1, double x2, double y2, Color color = Color::violet) {
	const double v[] = {x1, y1, x2, y2};
	detail::draw("line", layer, v, 4, color);
}

inline void draw_circle(const std::string& layer, double x, double y, double radius, Color color = Color::violet) {
	const double v[] = {x, y, radius};
	detail::draw("circle", layer, v, 3, color);
}

/* Half-widths `rx` along x and `ry` along y, then turned clockwise by `theta_deg`. */
inline void draw_ellipse(const std::string& layer, double x, double y, double rx, double ry, double theta_deg = 0,
                         Color color = Color::violet) {
	const double v[] = {x, y, rx, ry, -theta_deg};
	detail::draw("ellipse", layer, v, 5, color);
}

/* A pose, as LemLib's (theta in degrees clockwise from +y): a dot with a heading tick. */
inline void draw_pose(const std::string& layer, double x, double y, double theta_deg, Color color = Color::violet) {
	const double v[] = {x, y, 90.0 - theta_deg};
	detail::draw("pose", layer, v, 3, color);
}

inline void draw_text(const std::string& layer, double x, double y, const std::string& text, Color color = Color::ink) {
	char buf[80];
	std::snprintf(buf, sizeof buf, " %.6g %.6g %s ", x, y, detail::color_name(color));
	std::string line = text.substr(0, 120);
	for (char& c : line)
		if (c == '\n' || c == '\r') c = ' ';
	vexsim_draw(("text " + detail::layer_name(layer) + buf + line).c_str());
}

}  // namespace vexsim

#endif
