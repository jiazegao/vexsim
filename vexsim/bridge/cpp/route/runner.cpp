// vexsim's route runner (vexsim/bridge/runner.py): the steps of the route VEXSIM_ROUTE names,
// made as an export of the route makes them. A route build appends this to a file it
// generates, which includes the project's headers, and then defines chassis(), call() and
// the tables of the team's functions after it.
//
// The route is a text file, a line for each thing:
//   vexsim-route 1
//   start X Y THETA                          chassis.setPose(X, Y, THETA)
//   drive KS KV KA KT KP MAXV MAXA MAXLAT    the vexsim::Drive vexsim's own motions drive with
//   N move_to_point X Y TIMEOUT [KEY=VALUE]  a motion: its target (a swing's locked side
//   N turn_to_heading THETA TIMEOUT ...      after it), timeout, options and async
//   N move_arc RADIUS DEGREES TIMEOUT ...    vexsim's own motions (vexsim/motions.hpp)
//   N ramsete X1 Y1 X2 Y2... TIMEOUT ...
//   N call NAME [ARGUMENT]...                one of the team's functions
//   N wait MS | N wait_until DISTANCE | N wait_until_done
//
// It says what it does on the console, for vexsim (bridge/program.py):
//   vexsim: route starts
//   vexsim: route step N starts M            M: how many motions had started
//   vexsim: route step N called M X Y THETA  the step's call returned; LemLib's pose
//   vexsim: route motion K starts            LemLib started a motion's task (K from 0)
//   vexsim: route motion K ends X Y THETA    and it ended
//   vexsim: route ends
//   vexsim: route can't run: WHY
// LemLib starts each async motion's task while it holds its chassis' motion mutex, so the
// tasks created then are the motions (vexsim_follow_tasks, in the runtime's scheduler).

#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

#include "vexsim/motions.hpp"

extern "C" {
void vexsim_set_route(void (*run)(void));
void vexsim_follow_tasks(void* mutex, void (*started)(std::uint32_t), void (*ended)(std::uint32_t));
std::uint32_t vexsim_followed_count(void);
}

namespace vexsim_route {

lemlib::Chassis& chassis();  // the project's own, defined after this

// LemLib keeps the mutex its motions queue on private, as the shim's pros::Mutex keeps its
// handle; an explicit instantiation may name them.
pros::Mutex& motion_mutex(lemlib::Chassis& c);
pros::mutex_t handle_of(pros::Mutex& m);

template <pros::Mutex lemlib::Chassis::*Member>
struct MotionMutex {
	friend pros::Mutex& motion_mutex(lemlib::Chassis& c) { return c.*Member; }
};
template struct MotionMutex<&lemlib::Chassis::mutex>;

template <std::atomic<pros::mutex_t> pros::Mutex::*Member>
struct MutexHandle {
	friend pros::mutex_t handle_of(pros::Mutex& m) { return (m.*Member).load(); }
};
template struct MutexHandle<&pros::Mutex::mutex>;

void note(const char* format, ...) {
	std::va_list args;
	va_start(args, format);
	std::fputs("vexsim: route ", stdout);
	std::vprintf(format, args);
	std::fputc('\n', stdout);
	std::fflush(stdout);
	va_end(args);
}

// A step: its number, kind, words in order, and key=value options
struct Step {
	int number = 0;
	std::string kind;
	std::vector<std::string> words;
	std::vector<std::pair<std::string, std::string>> options;

	const std::string* option(const char* key) const {
		for (const auto& [k, v] : options)
			if (k == key) return &v;
		return nullptr;
	}
	double number_at(std::size_t i) const { return i < words.size() ? std::strtod(words[i].c_str(), nullptr) : 0.0; }
	int whole_at(std::size_t i) const { return static_cast<int>(number_at(i)); }
};

template <typename E>
struct Named {
	const char* name;
	E value;
};

// A call's arguments, each read as its parameter's type
class Args {
	const std::vector<std::string>& words;
	std::size_t first;
	mutable std::string problem;

	public:
	Args(const std::vector<std::string>& words, std::size_t first) : words(words), first(first) {}
	std::size_t size() const { return words.size() - first; }
	const char* why() const { return problem.c_str(); }

	// false if argument i doesn't read as a T; one that isn't given leaves ``out`` as it was
	template <typename T>
	bool get(std::size_t i, T& out) const {
		if (i >= size()) return true;
		const std::string& text = words[first + i];
		char* end = nullptr;
		if constexpr (std::is_same_v<T, bool>) {
			if (text != "true" && text != "false") return fail(i, "true or false");
			out = text == "true";
		} else if constexpr (std::is_integral_v<T>) {
			long long value = std::strtoll(text.c_str(), &end, 10);
			if (end == text.c_str() || *end) return fail(i, "a whole number");
			out = static_cast<T>(value);
		} else {
			double value = std::strtod(text.c_str(), &end);
			if (end == text.c_str() || *end) return fail(i, "a number");
			out = static_cast<T>(value);
		}
		return true;
	}

	template <typename E, std::size_t N>
	bool get(std::size_t i, E& out, const Named<E> (&values)[N]) const {
		if (i >= size()) return true;
		for (const Named<E>& v : values) {
			if (words[first + i] == v.name) {
				out = v.value;
				return true;
			}
		}
		return fail(i, "one of its enum's values");
	}

	private:
	bool fail(std::size_t i, const char* wanted) const {
		problem = "argument " + std::to_string(i + 1) + " (" + words[first + i] + ") isn't " + wanted;
		return false;
	}
};

// The team's function ``name`` with ``args``: nullptr once called, else why it wasn't
const char* call(const std::string& name, const Args& args);

template <typename T>
void set(const Step& s, const char* key, T& field) {
	const std::string* value = s.option(key);
	if (!value) return;
	if constexpr (std::is_same_v<T, bool>) {
		field = *value == "true";
	} else if constexpr (std::is_same_v<T, lemlib::AngularDirection>) {
		field = *value == "cw"    ? lemlib::AngularDirection::CW_CLOCKWISE
		        : *value == "ccw" ? lemlib::AngularDirection::CCW_COUNTERCLOCKWISE
		                          : lemlib::AngularDirection::AUTO;
	} else {
		field = static_cast<T>(std::strtod(value->c_str(), nullptr));
	}
}

template <typename Params>
void speeds(const Step& s, Params& p) {
	set(s, "max_speed", p.maxSpeed);
	set(s, "min_speed", p.minSpeed);
	set(s, "early_exit", p.earlyExitRange);
}

lemlib::DriveSide side(const std::string& word) {
	return word == "right" ? lemlib::DriveSide::RIGHT : lemlib::DriveSide::LEFT;
}

// One step, made as an export makes it: nullptr once done, else why it couldn't be
const char* run_step(const Step& s, lemlib::Chassis& c, vexsim::Motions& motions) {
	const std::string* async = s.option("async");
	bool go_on = async ? *async == "true" : true;  // LemLib's default
	if (s.kind == "wait") {
		pros::delay(static_cast<std::uint32_t>(s.whole_at(0)));
	} else if (s.kind == "wait_until") {
		c.waitUntil(static_cast<float>(s.number_at(0)));
	} else if (s.kind == "wait_until_done") {
		c.waitUntilDone();
	} else if (s.kind == "call") {
		if (s.words.empty()) return "no function named";
		return call(s.words[0], Args(s.words, 1));
	} else if (s.kind == "move_to_point") {
		lemlib::MoveToPointParams p;
		set(s, "forwards", p.forwards);
		speeds(s, p);
		c.moveToPoint(s.number_at(0), s.number_at(1), s.whole_at(2), p, go_on);
	} else if (s.kind == "move_to_pose") {
		lemlib::MoveToPoseParams p;
		set(s, "forwards", p.forwards);
		set(s, "horizontal_drift", p.horizontalDrift);
		set(s, "lead", p.lead);
		speeds(s, p);
		c.moveToPose(s.number_at(0), s.number_at(1), s.number_at(2), s.whole_at(3), p, go_on);
	} else if (s.kind == "turn_to_heading") {
		lemlib::TurnToHeadingParams p;
		set(s, "direction", p.direction);
		speeds(s, p);
		c.turnToHeading(s.number_at(0), s.whole_at(1), p, go_on);
	} else if (s.kind == "turn_to_point") {
		lemlib::TurnToPointParams p;
		set(s, "forwards", p.forwards);
		set(s, "direction", p.direction);
		speeds(s, p);
		c.turnToPoint(s.number_at(0), s.number_at(1), s.whole_at(2), p, go_on);
	} else if (s.kind == "swing_to_heading") {
		lemlib::SwingToHeadingParams p;
		set(s, "direction", p.direction);
		speeds(s, p);
		c.swingToHeading(s.number_at(0), side(s.words.size() > 1 ? s.words[1] : ""), s.whole_at(2), p, go_on);
	} else if (s.kind == "swing_to_point") {
		lemlib::SwingToPointParams p;
		set(s, "forwards", p.forwards);
		set(s, "direction", p.direction);
		speeds(s, p);
		c.swingToPoint(s.number_at(0), s.number_at(1), side(s.words.size() > 2 ? s.words[2] : ""), s.whole_at(3),
		               p, go_on);
	} else if (s.kind == "move_arc") {
		vexsim::ArcParams p;
		set(s, "forwards", p.forwards);
		set(s, "max_velocity", p.maxVelocity);
		set(s, "max_accel", p.maxAccel);
		motions.moveArc(s.number_at(0), s.number_at(1), s.whole_at(2), p, go_on);
	} else if (s.kind == "ramsete") {
		vexsim::PathParams p;
		set(s, "forwards", p.forwards);
		set(s, "max_velocity", p.maxVelocity);
		set(s, "max_accel", p.maxAccel);
		set(s, "end_heading", p.endHeading);
		if (s.words.size() < 3) return "no points to go through";
		std::vector<vexsim::Waypoint> points;
		for (std::size_t k = 0; k + 2 < s.words.size(); k += 2) points.push_back({s.number_at(k), s.number_at(k + 1)});
		motions.ramsete(points, s.whole_at(s.words.size() - 1), p, go_on);
	} else {
		return "this runner doesn't know that kind of step";
	}
	return nullptr;
}

std::vector<std::string> split(const char* line) {
	std::vector<std::string> words;
	std::string word;
	for (const char* c = line; *c; c++) {
		if (*c == ' ' || *c == '\t' || *c == '\n' || *c == '\r') {
			if (!word.empty()) words.push_back(word);
			word.clear();
		} else {
			word += *c;
		}
	}
	if (!word.empty()) words.push_back(word);
	return words;
}

bool read(const char* path, std::vector<Step>& steps, double start[3], vexsim::Drive& drive, std::string& why) {
	std::FILE* file = path ? std::fopen(path, "r") : nullptr;
	if (!file) {
		why = std::string("can't open ") + (path ? path : "the route");
		return false;
	}
	char line[4096];
	bool header = false;
	while (std::fgets(line, sizeof line, file)) {
		std::vector<std::string> words = split(line);
		if (words.empty()) continue;
		if (!header) {
			header = words.size() == 2 && words[0] == "vexsim-route" && words[1] == "1";
			if (!header) break;
		} else if (words[0] == "start" && words.size() == 4) {
			for (int k = 0; k < 3; k++) start[k] = std::strtod(words[k + 1].c_str(), nullptr);
		} else if (words[0] == "drive" && words.size() == 9) {
			float* fields[] = {&drive.kS, &drive.kV,          &drive.kA,       &drive.kT,
			                   &drive.kP, &drive.maxVelocity, &drive.maxAccel, &drive.maxLateralAccel};
			for (int k = 0; k < 8; k++) *fields[k] = std::strtof(words[k + 1].c_str(), nullptr);
		} else if (words.size() >= 2) {
			Step step;
			step.number = std::atoi(words[0].c_str());
			step.kind = words[1];
			for (std::size_t k = 2; k < words.size(); k++) {
				std::size_t eq = words[k].find('=');
				if (eq == std::string::npos) {
					step.words.push_back(words[k]);
				} else {
					step.options.emplace_back(words[k].substr(0, eq), words[k].substr(eq + 1));
				}
			}
			steps.push_back(step);
		}
	}
	std::fclose(file);
	if (!header) why = std::string(path) + " isn't a route this runner reads";
	return header;
}

void motion_started(std::uint32_t k) { note("motion %u starts", static_cast<unsigned>(k)); }

void motion_ended(std::uint32_t k) {
	lemlib::Pose p = chassis().getPose();
	note("motion %u ends %.4f %.4f %.4f", static_cast<unsigned>(k), p.x, p.y, p.theta);
}

void run() {
	std::vector<Step> steps;
	double start[3] = {0, 0, 0};
	vexsim::Drive drive;
	std::string why;
	if (!read(std::getenv("VEXSIM_ROUTE"), steps, start, drive, why)) {
		note("can't run: %s", why.c_str());
		return;
	}
	lemlib::Chassis& c = chassis();
	vexsim::Motions motions(c, drive);
	vexsim_follow_tasks(handle_of(motion_mutex(c)), motion_started, motion_ended);
	c.setPose(start[0], start[1], start[2]);
	note("starts");
	for (const Step& s : steps) {
		note("step %d starts %u", s.number, static_cast<unsigned>(vexsim_followed_count()));
		if (const char* failed = run_step(s, c, motions)) {
			note("can't run: step %d (%s): %s", s.number, s.kind.c_str(), failed);
			return;
		}
		lemlib::Pose p = c.getPose();
		note("step %d called %u %.4f %.4f %.4f", s.number, static_cast<unsigned>(vexsim_followed_count()), p.x,
		     p.y, p.theta);
	}
	note("ends");
}

struct Register {
	Register() {
		const char* path = std::getenv("VEXSIM_ROUTE");
		if (path && *path) vexsim_set_route(run);
	}
} register_route;

}  // namespace vexsim_route
