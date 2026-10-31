// vexsim's logger (vexsim_log.hpp): every device on every port, every 10 ms, in vexsim's
// robot-log format (version 2), kept in memory while the robot drives and saved at the end.
//
// A log is CSV: "# key: value" lines first (what it is, what was plugged in where), then a
// header, then a row every 10 ms. Readings are as PROS reports them for a positive port, so
// a motor on a reversed port reads backwards; a reversed rotation sensor is read as if it
// weren't. Marks are "#mark,<ms>,<text>" lines among the rows. vexsim/calibration/log.py
// reads it.
#include "vexsim_log.hpp"

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "api.h"

namespace vexsim_log {
namespace {

constexpr std::uint32_t PERIOD_MS = 10;
constexpr std::size_t BLOCK_ROWS = 500;  // rows are kept in blocks, so a long log never moves
constexpr int PORTS = 21;
const char* const BEGIN = "#vexsim-log begin";
const char* const END = "#vexsim-log end";

enum class Kind { motor, rotation, imu, distance, gps };
enum class Mode { disabled, autonomous, driver };

struct Device {
	Kind kind;
	std::uint8_t port;
};

struct Source {
	std::string name;
	std::function<Pose()> pose;  // a pose, or else
	std::function<double()> value;
};

struct Column {
	std::string name;
	int digits;  // decimals written; -1: %g
};

struct Mark {
	std::uint32_t ms;
	std::string text;
};

// A log: what start() found and set up, then what was recorded. Only the logger's lock
// guards times, blocks and marks; the rest doesn't change once the log starts.
struct Log {
	std::string name;
	Sampling sampling = Sampling::task;
	std::uint32_t start_ms = 0;
	Mode started_in = Mode::driver;
	Mode mode = Mode::driver;  // as last seen
	bool autonomous = false;   // started in autonomous: saves itself when it ends
	std::string devices_found;
	double battery_pct = NAN;
	std::vector<Device> devices;  // motors, then the rest, each by port
	std::vector<Source> sources;
	std::vector<Column> columns;  // after time_ms
	std::vector<std::pair<std::string, std::string>> info;
	std::vector<std::uint32_t> times;
	std::vector<std::vector<float>> blocks;
	std::vector<Mark> marks;
};

pros::mutex_t g_lock = pros::c::mutex_create();
std::shared_ptr<Log> g_log;  // the log being recorded, if any
std::vector<Source> g_sources;
std::vector<std::pair<std::string, std::string>> g_info;  // for the next log
double g_cmd_mv[PORTS + 1];
double g_cmd_rpm[PORTS + 1];
int g_limit_s = 180;
pros::task_t g_task = nullptr;   // samples every 10 ms, above the code's own tasks
pros::task_t g_saver = nullptr;  // saves finished logs, below them
std::deque<std::shared_ptr<Log>> g_unsaved;  // finished logs, oldest first
std::uint32_t g_finished = 0;                // logs finished so far
std::uint32_t g_saved = 0;                   // and saved

struct Locked {
	Locked() { pros::c::mutex_take(g_lock, TIMEOUT_MAX); }
	~Locked() { pros::c::mutex_give(g_lock); }
	Locked(const Locked&) = delete;
	Locked& operator=(const Locked&) = delete;
};

// "Left 40" -> "left_40": lower case letters and digits, words joined by underscores.
std::string slug(const char* text, std::size_t most = 32) {
	std::string out;
	bool gap = false;
	for (const char* p = text ? text : ""; *p != '\0' && out.size() < most; p++) {
		char c = *p;
		if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
		if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9'))) {
			gap = !out.empty();
			continue;
		}
		if (gap) out += '_';
		gap = false;
		out += c;
	}
	return out;
}

std::string one_line(const char* text) {
	std::string out(text ? text : "");
	for (char& c : out)
		if (c == '\n' || c == '\r') c = ' ';
	return out;
}

Mode mode_now() {
	if (pros::c::competition_is_disabled()) return Mode::disabled;
	return pros::c::competition_is_autonomous() ? Mode::autonomous : Mode::driver;
}

const char* mode_name(Mode mode) {
	return mode == Mode::disabled ? "disabled" : mode == Mode::autonomous ? "autonomous" : "driver";
}

// What is plugged into each port. Type numbers are VEX's (PROS's v5_device_e_t).
std::vector<Device> find_devices(std::string& found) {
	std::vector<Device> motors, others;
	for (int port = 1; port <= PORTS; port++) {
		auto p = static_cast<std::uint8_t>(port);
		const char* what;
		switch (static_cast<int>(pros::c::get_plugged_type(p))) {
			case 0:    // nothing
			case 255:  // couldn't tell
				continue;
			case 2:
				motors.push_back({Kind::motor, p}), what = "motor";
				break;
			case 4:
				others.push_back({Kind::rotation, p}), what = "rotation";
				break;
			case 6:
				others.push_back({Kind::imu, p}), what = "imu";
				break;
			case 7:
				others.push_back({Kind::distance, p}), what = "distance";
				break;
			case 20:
				others.push_back({Kind::gps, p}), what = "gps";
				break;
			case 8:
				what = "radio";
				break;
			case 11:
				what = "vision";
				break;
			case 12:
				what = "adi";
				break;
			case 16:
				what = "optical";
				break;
			case 29:
				what = "ai vision";
				break;
			case 129:
				what = "serial";
				break;
			default:
				what = "other";
				break;
		}
		if (!found.empty()) found += ", ";
		found += std::to_string(port) + " " + what;
	}
	motors.insert(motors.end(), others.begin(), others.end());
	return motors;
}

std::vector<Column> columns_of(const Log& log) {
	std::vector<Column> out = {{"battery_mv", 0}, {"battery_ma", 0}};
	for (const Device& d : log.devices) {
		std::string p = std::to_string(d.port);
		switch (d.kind) {
			case Kind::motor:
				out.insert(out.end(), {{"m" + p + "_cmd_mv", 0},
				                       {"m" + p + "_cmd_rpm", 2},
				                       {"m" + p + "_brake", 0},
				                       {"m" + p + "_deg", 2},
				                       {"m" + p + "_rpm", 2},
				                       {"m" + p + "_ma", 0},
				                       {"m" + p + "_mv", 0},
				                       {"m" + p + "_temp", 1}});
				break;
			case Kind::rotation:
				out.push_back({"r" + p + "_cdeg", 0});
				break;
			case Kind::imu:
				out.push_back({"imu" + p + "_deg", 4});
				break;
			case Kind::distance:
				out.insert(out.end(), {{"d" + p + "_mm", 0}, {"d" + p + "_conf", 0}, {"d" + p + "_size", 0}});
				break;
			case Kind::gps:
				out.insert(out.end(), {{"gps" + p + "_x_m", 4},
				                       {"gps" + p + "_y_m", 4},
				                       {"gps" + p + "_heading_deg", 3},
				                       {"gps" + p + "_error_m", 4}});
				break;
		}
	}
	for (const Source& s : log.sources) {
		if (s.pose) {
			out.insert(out.end(), {{"pose_" + s.name + "_x_in", 3},
			                       {"pose_" + s.name + "_y_in", 3},
			                       {"pose_" + s.name + "_theta_deg", 3}});
		} else {
			out.push_back({"val_" + s.name, -1});
		}
	}
	return out;
}

// A row of readings, now. Reads the devices and calls the code's sources without the lock,
// so a source may mark or log as it likes.
void take_row(const std::shared_ptr<Log>& log) {
	double cmd_mv[PORTS + 1], cmd_rpm[PORTS + 1];
	{
		Locked lock;
		if (g_log != log) return;
		for (int p = 0; p <= PORTS; p++) cmd_mv[p] = g_cmd_mv[p], cmd_rpm[p] = g_cmd_rpm[p];
	}
	std::uint32_t now = pros::c::millis();
	std::vector<float> row;
	row.reserve(log->columns.size());
	auto put = [&row](double v, bool ok = true) { row.push_back(ok && std::isfinite(v) ? static_cast<float>(v) : NAN); };
	std::int32_t battery_mv = pros::c::battery_get_voltage();
	std::int32_t battery_ma = pros::c::battery_get_current();
	put(battery_mv, battery_mv != PROS_ERR);
	put(battery_ma, battery_ma != PROS_ERR);
	for (const Device& d : log->devices) {
		std::uint8_t p = d.port;
		switch (d.kind) {
			case Kind::motor: {
				auto port = static_cast<std::int8_t>(p);
				put(cmd_mv[p]);
				put(cmd_rpm[p]);
				auto brake = static_cast<std::int32_t>(pros::c::motor_get_brake_mode(port));
				put(brake, brake >= 0 && brake <= 2);
				put(pros::c::motor_get_position(port));
				put(pros::c::motor_get_actual_velocity(port));
				std::int32_t ma = pros::c::motor_get_current_draw(port);
				put(ma, ma != PROS_ERR);
				std::int32_t mv = pros::c::motor_get_voltage(port);
				put(mv, mv != PROS_ERR);
				put(pros::c::motor_get_temperature(port));
				break;
			}
			case Kind::rotation: {
				std::int32_t cdeg = pros::c::rotation_get_position(p);
				if (cdeg != PROS_ERR && pros::c::rotation_get_reversed(p) == 1) cdeg = -cdeg;
				put(cdeg, cdeg != PROS_ERR);
				break;
			}
			case Kind::imu:
				put(pros::c::imu_get_rotation(p));  // PROS_ERR_F (infinite) while it calibrates
				break;
			case Kind::distance: {
				std::int32_t mm = pros::c::distance_get(p);
				put(mm, mm != PROS_ERR && mm != 9999);  // 9999: nothing in range
				std::int32_t confidence = pros::c::distance_get_confidence(p);
				put(confidence, confidence != PROS_ERR);
				std::int32_t size = pros::c::distance_get_object_size(p);
				put(size, size != PROS_ERR);
				break;
			}
			case Kind::gps: {
				auto at = pros::c::gps_get_position(p);
				put(at.x);
				put(at.y);
				put(pros::c::gps_get_heading(p));
				put(pros::c::gps_get_error(p));
				break;
			}
		}
	}
	for (const Source& s : log->sources) {
		if (s.pose) {
			Pose pose = s.pose();
			put(pose.x);
			put(pose.y);
			put(pose.theta);
		} else {
			put(s.value());
		}
	}
	Locked lock;
	if (g_log != log) return;  // it stopped meanwhile
	std::size_t n = log->columns.size();
	if (log->times.size() % BLOCK_ROWS == 0) log->blocks.emplace_back(BLOCK_ROWS * n);
	float* to = log->blocks.back().data() + (log->times.size() % BLOCK_ROWS) * n;
	for (std::size_t i = 0; i < n; i++) to[i] = row[i];
	log->times.push_back(now - log->start_ms);
}

// The next numbered file on the card for a log of this name ("" if none would open).
std::string card_file(const std::string& name) {
	const char* const COUNT = "/usd/vexsim_count.txt";  // the last number used
	int count = 0;
	if (std::FILE* file = std::fopen(COUNT, "r")) {
		if (std::fscanf(file, "%d", &count) != 1) count = 0;
		std::fclose(file);
	}
	for (int n = count + 1; n <= count + 1000; n++) {
		char path[96];
		std::snprintf(path, sizeof path, "/usd/vexsim_%04d_%s.csv", n, name.c_str());
		if (std::FILE* taken = std::fopen(path, "r")) {
			std::fclose(taken);
			continue;
		}
		if (std::FILE* file = std::fopen(COUNT, "w")) {
			std::fprintf(file, "%d\n", n);
			std::fclose(file);
		}
		return path;
	}
	return "";
}

void write_log(std::FILE* out, const Log& log, bool paced) {
	auto line = [out](const std::string& text) {
		std::fputs(text.c_str(), out);
		std::fputc('\n', out);
	};
	line("# vexsim-log: 2");
	line("# name: " + log.name);
	line("# started_ms: " + std::to_string(log.start_ms));
	line(std::string("# mode: ") + mode_name(log.started_in));
	if (std::isfinite(log.battery_pct)) line("# battery_pct: " + std::to_string(std::lround(log.battery_pct)));
	line("# devices: " + log.devices_found);
	for (const auto& [key, value] : log.info) line("# " + key + ": " + value);
	std::string header = "time_ms";
	for (const Column& c : log.columns) header += "," + c.name;
	line(header);
	std::size_t n = log.columns.size(), m = 0;
	char cell[48];
	for (std::size_t r = 0; r < log.times.size(); r++) {
		std::uint32_t t = log.times[r];
		for (; m < log.marks.size() && log.marks[m].ms <= t; m++)
			line("#mark," + std::to_string(log.marks[m].ms) + "," + log.marks[m].text);
		std::string row = std::to_string(t);
		const float* v = log.blocks[r / BLOCK_ROWS].data() + (r % BLOCK_ROWS) * n;
		for (std::size_t i = 0; i < n; i++) {
			row += ',';
			if (std::isnan(v[i])) continue;
			if (log.columns[i].digits < 0) {
				std::snprintf(cell, sizeof cell, "%.6g", v[i]);
			} else {
				std::snprintf(cell, sizeof cell, "%.*f", log.columns[i].digits, v[i]);
			}
			row += cell;
		}
		line(row);
		if (paced && r % 20 == 19) {  // let the terminal keep up
			std::fflush(out);
			pros::c::delay(2);
		}
	}
	for (; m < log.marks.size(); m++) line("#mark," + std::to_string(log.marks[m].ms) + "," + log.marks[m].text);
}

int save(const Log& log) {
	int rows = static_cast<int>(log.times.size());
	if (pros::c::usd_is_installed()) {
		std::string name = slug(log.name.c_str());
		std::string path = card_file(name.empty() ? "log" : name);
		std::FILE* file = path.empty() ? nullptr : std::fopen(path.c_str(), "w");
		if (file != nullptr) {
			write_log(file, log, false);
			std::fclose(file);
			std::printf("vexsim_log: saved %d rows to %s\n", rows, path.c_str());
			return rows;
		}
	}
	std::printf("%s\n", BEGIN);
	write_log(stdout, log, true);
	std::printf("%s\n", END);
	std::fflush(stdout);
	return rows;
}

struct Finished {
	std::uint32_t ticket;  // the saver says it saved this one when g_saved reaches it; 0: none
	int rows;
};

// Stops the log (``only``: if it's that one) and hands it to the saver.
Finished finish(const std::shared_ptr<Log>& only = nullptr) {
	Finished done{0, 0};
	{
		Locked lock;
		if (!g_log || (only && g_log != only)) return done;
		done = {++g_finished, static_cast<int>(g_log->times.size())};
		g_unsaved.push_back(std::move(g_log));
		g_log = nullptr;
	}
	pros::c::task_notify(g_saver);
	return done;
}

// Saves finished logs, one after another, in a task of its own: the field ends the
// autonomous task when autonomous ends, which would cut a save in it short, and this one
// runs below the code's own tasks, so a long save doesn't hold up driver control.
void save_loop(void*) {
	while (true) {
		pros::c::task_notify_take(true, TIMEOUT_MAX);
		while (true) {
			std::shared_ptr<Log> log;
			{
				Locked lock;
				if (g_unsaved.empty()) break;
				log = g_unsaved.front();
			}
			save(*log);
			Locked lock;
			g_unsaved.pop_front();
			g_saved++;
		}
	}
}

// Every 10 ms of a log: a row (unless the code samples), a mark when the competition mode
// changes, and the save when autonomous ends or the log is full. False once it's over.
bool tick(const std::shared_ptr<Log>& log) {
	if (log->sampling == Sampling::task) take_row(log);
	Mode mode = mode_now();
	bool over = false;
	{
		Locked lock;
		if (g_log != log) return false;
		if (mode != log->mode) {
			log->marks.push_back({pros::c::millis() - log->start_ms, std::string("mode: ") + mode_name(mode)});
			log->mode = mode;
			over = log->autonomous && mode != Mode::autonomous;
		}
		over = over || log->times.size() >= static_cast<std::size_t>(g_limit_s) * 1000 / PERIOD_MS;
	}
	if (over) finish(log);
	return !over;
}

void loop(void*) {
	while (true) {
		pros::c::task_notify_take(true, TIMEOUT_MAX);  // start() says a log began
		std::shared_ptr<Log> log;
		{
			Locked lock;
			log = g_log;
		}
		if (!log) continue;
		std::uint32_t at = log->start_ms;
		do pros::c::task_delay_until(&at, PERIOD_MS);
		while (tick(log));
	}
}

void add_source(Source source) {
	Locked lock;
	for (Source& s : g_sources) {
		if (s.name == source.name) {
			s = std::move(source);
			return;
		}
	}
	g_sources.push_back(std::move(source));
}

}  // namespace

void pose(const char* name, std::function<Pose()> read) {
	std::string key = slug(name);
	add_source({key.empty() ? "pose" : key, std::move(read), nullptr});
}

void value(const char* name, std::function<double()> read) {
	std::string key = slug(name);
	add_source({key.empty() ? "value" : key, nullptr, std::move(read)});
}

bool start(const char* name, Sampling sampling) {
	auto log = std::make_shared<Log>();
	log->name = one_line(name);
	log->sampling = sampling;
	log->devices = find_devices(log->devices_found);
	log->mode = log->started_in = mode_now();
	log->autonomous = log->mode == Mode::autonomous;
	log->battery_pct = pros::c::battery_get_capacity();
	{
		Locked lock;
		if (g_log) return false;
		log->sources = g_sources;
		log->columns = columns_of(*log);
		log->info = std::move(g_info);
		g_info.clear();
		for (int p = 0; p <= PORTS; p++) g_cmd_mv[p] = g_cmd_rpm[p] = NAN;
		log->start_ms = pros::c::millis();
		g_log = log;
	}
	if (sampling == Sampling::task) take_row(log);  // the first row, at 0 ms
	if (g_task == nullptr) {
		g_task = pros::c::task_create(loop, nullptr, TASK_PRIORITY_DEFAULT + 1, TASK_STACK_DEPTH_DEFAULT,
		                              "vexsim_log");
		g_saver = pros::c::task_create(save_loop, nullptr, TASK_PRIORITY_DEFAULT - 1, TASK_STACK_DEPTH_DEFAULT,
		                               "vexsim_log save");
	}
	pros::c::task_notify(g_task);
	return true;
}

void sample() {
	std::shared_ptr<Log> log;
	{
		Locked lock;
		log = g_log;
	}
	if (log && log->sampling == Sampling::manual) take_row(log);
}

bool running() {
	Locked lock;
	return g_log != nullptr;
}

void mark(const char* text) {
	Locked lock;
	if (g_log) g_log->marks.push_back({pros::c::millis() - g_log->start_ms, one_line(text)});
}

void info(const char* key, const char* value) {
	std::string k = slug(key);
	if (k.empty()) return;
	Locked lock;
	(g_log ? g_log->info : g_info).emplace_back(k, one_line(value));
}

void command(int port, int millivolts) {
	if (port < 1 || port > PORTS) return;
	Locked lock;
	g_cmd_mv[port] = millivolts;
	g_cmd_rpm[port] = NAN;
}

void command_velocity(int port, double rpm) {
	if (port < 1 || port > PORTS) return;
	Locked lock;
	g_cmd_rpm[port] = rpm;
	g_cmd_mv[port] = NAN;
}

int stop() {
	Finished done = finish();
	if (done.ticket == 0) return 0;
	while (true) {  // until the saver has saved it (if this task is ended meanwhile, it still does)
		{
			Locked lock;
			if (g_saved >= done.ticket) break;
		}
		pros::c::delay(1);
	}
	return done.rows;
}

void set_limit_s(int seconds) {
	Locked lock;
	g_limit_s = seconds < 1 ? 1 : seconds;
}

}  // namespace vexsim_log
