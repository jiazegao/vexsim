// vexsim's calibration program: a calibration session's tests, one at a time from a menu on
// the brain's screen and the controller, each logged with vexsim's logger (vexsim_log.hpp).
//
// `vexsim calibration program ROBOT.yaml FIELD.yaml FOLDER` writes it into a PROS project
// with include/vexsim_calibration_tests.hpp: the robot's devices and the plan's tests (where
// each starts, its steps, how far it may go). This file is the same for every robot. It uses
// only the PROS 4 C API and the logger, so it builds with PROS for the robot (in a spare
// slot: pros upload --slot 8) and runs unchanged in vexsim.
//
// Safety: a test that turns the wheels starts once the robot is still, after a 3 s countdown
// with a rumble. Any button, or a stick past 20%, stops every motor at once; so does a driving
// test going further than the plan's simulations did (its envelope: by the IMU and the motor
// encoders). A stopped run's log is kept, marked as stopped.
//
// At each step it also prints a "#vexsim-cal" line to the terminal, saying what it does or
// waits for: for vexsim's simulated student (vexsim/calibration/student.py) and the laptop.
#include "main.h"

#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>

#include "vexsim_calibration_tests.hpp"
#include "vexsim_log.hpp"

namespace {

using namespace cal;
using Button = pros::controller_digital_e_t;

constexpr auto MASTER = pros::E_CONTROLLER_MASTER;
constexpr Button A = pros::E_CONTROLLER_DIGITAL_A;
constexpr Button B = pros::E_CONTROLLER_DIGITAL_B;
constexpr Button X = pros::E_CONTROLLER_DIGITAL_X;
constexpr Button UP = pros::E_CONTROLLER_DIGITAL_UP;
constexpr Button DOWN = pros::E_CONTROLLER_DIGITAL_DOWN;
constexpr Button BUTTONS[] = {
    pros::E_CONTROLLER_DIGITAL_L1,   pros::E_CONTROLLER_DIGITAL_L2,    pros::E_CONTROLLER_DIGITAL_R1,
    pros::E_CONTROLLER_DIGITAL_R2,   UP,                               DOWN,
    pros::E_CONTROLLER_DIGITAL_LEFT, pros::E_CONTROLLER_DIGITAL_RIGHT, X,
    B,                               pros::E_CONTROLLER_DIGITAL_Y,     A};
constexpr pros::controller_analog_e_t STICKS[] = {
    pros::E_CONTROLLER_ANALOG_LEFT_X, pros::E_CONTROLLER_ANALOG_LEFT_Y,
    pros::E_CONTROLLER_ANALOG_RIGHT_X, pros::E_CONTROLLER_ANALOG_RIGHT_Y};
constexpr int STICK_STOP = 25;      // of 127: past 20% stops a run
constexpr int WIDTH = 48;           // characters on a line of the brain's screen
constexpr int PAD_WIDTH = 19;       // and of the controller's
constexpr int BATTERY_MIN = 80;     // %: below, a test asks first
constexpr double HOT_C = 45;        // a drive motor this hot waits to cool
constexpr double WARM_C = 50;       // and after a run, gets a warning
constexpr int SAG_MV = 10800;       // a battery below this during a run gets a warning
constexpr double SUDDEN_IN_S = 20;  // the wheels losing this much speed in 100 ms: a crash?
constexpr double BRAKE_DEG_S2 = 4000;  // braking slows a drive motor at least this fast
constexpr int CHECK_MV = 3000;      // the device check spins the wheels this gently
constexpr int CLOSE_MM = 100;       // a hand over a distance sensor reads closer than this
constexpr int CLEAR_MM = 200;       // and an uncovered one further

// ---- screens and the terminal -------------------------------------------------------------

char g_pad[3][PAD_WIDTH + 1];        // what the controller should show
char g_pad_shown[3][PAD_WIDTH + 1];  // and does
std::uint32_t g_pad_next = 0;

// printf into one of 8 rotating buffers: for a page's lines.
const char* f(const char* format, ...) {
	static char buffers[8][128];
	static int next = 0;
	char* out = buffers[next++ % 8];
	va_list args;
	va_start(args, format);
	std::vsnprintf(out, sizeof buffers[0], format, args);
	va_end(args);
	return out;
}

void brain(int line, const char* text) {
	pros::c::screen_print(pros::E_TEXT_MEDIUM, line, "%-*.*s", WIDTH, WIDTH, text);
}

void pad(int line, const char* text) {
	std::snprintf(g_pad[line], sizeof g_pad[line], "%-*.*s", PAD_WIDTH, PAD_WIDTH, text);
}

// The controller takes a line every 50 ms or so: one changed line at a time.
void pad_flush() {
	std::uint32_t now = pros::c::millis();
	if (now < g_pad_next) return;
	for (int line = 0; line < 3; line++) {
		if (std::strcmp(g_pad[line], g_pad_shown[line]) != 0) {
			pros::c::controller_set_text(MASTER, line, 0, g_pad[line]);
			std::strcpy(g_pad_shown[line], g_pad[line]);
			g_pad_next = now + 60;
			return;
		}
	}
}

// A "#vexsim-cal" line on the terminal.
void say(const char* format, ...) {
	char text[160];
	va_list args;
	va_start(args, format);
	std::vsnprintf(text, sizeof text, format, args);
	va_end(args);
	std::printf("#vexsim-cal %s\n", text);
	std::fflush(stdout);
}

// The page under the status lines: a title, up to 4 lines, what the buttons do; and the
// controller's two lines.
void page(const char* title, std::initializer_list<const char*> lines, const char* buttons,
          const char* pad_title, const char* pad_buttons) {
	brain(2, title);
	int line = 3;
	for (const char* text : lines) {
		if (line < 7) brain(line++, text);
	}
	while (line < 7) brain(line++, "");
	brain(7, buttons);
	pad(1, pad_title);
	pad(2, pad_buttons);
}

// ---- the robot ---------------------------------------------------------------------------------

char g_problems[12][160];  // what the device check found wrong
int g_problem_count = 0;
int g_saved = 0;           // logs saved this session
bool g_imu_moved = false;  // the wheels turned while the IMU calibrated
int g_sample_ms = 0;       // while waiting on the student: a log row this often (0: none)
std::uint32_t g_next_sample = 0;

double position(int i) { return pros::c::motor_get_position(MOTORS[i].port); }

// A drive motor's speed (rpm), + the way the config says is forward.
double speed(int i) { return pros::c::motor_get_actual_velocity(MOTORS[i].port) * MOTORS[i].direction; }

double rotation() { return IMU_PORT ? pros::c::imu_get_rotation(IMU_PORT) : 0.0; }

int battery_pct() { return static_cast<int>(std::lround(pros::c::battery_get_capacity())); }

void command(int i, int mv) {
	pros::c::motor_move_voltage(MOTORS[i].port, mv);
	vexsim_log::command(MOTORS[i].port, mv);
}

// Every drive motor stopped: braking, or coasting.
void stop_motors(bool brake) {
	for (int i = 0; i < MOTOR_COUNT; i++) {
		int port = MOTORS[i].port;
		pros::c::motor_set_brake_mode(port, brake ? pros::E_MOTOR_BRAKE_BRAKE : pros::E_MOTOR_BRAKE_COAST);
		pros::c::motor_brake(port);
		vexsim_log::command(port, 0);
	}
}

// The hottest drive motor's temperature (C), and its port.
double hottest(int* port) {
	double hot = 0;
	for (int i = 0; i < MOTOR_COUNT; i++) {
		double c = pros::c::motor_get_temperature(MOTORS[i].port);
		if (std::isfinite(c) && c > hot) {
			hot = c;
			*port = MOTORS[i].port;
		}
	}
	return hot;
}

void status() {
	int port = 0;
	double hot = hottest(&port);
	bool card = pros::c::usd_is_installed();
	brain(0, f("%s: calibration", ROBOT));
	brain(1, f("Battery %d%%  motors %.0f C  %s  %d saved", battery_pct(), hot, card ? "SD card" : "no card",
	           g_saved));
	pad(0, f("%d%% %.0fC %s %d", battery_pct(), hot, card ? "SD" : "noSD", g_saved));
}

void problem(const char* text) {
	if (g_problem_count < 12) std::snprintf(g_problems[g_problem_count++], sizeof g_problems[0], "%s", text);
}

// ---- the controller ----------------------------------------------------------------------------

// Any button held, or a stick past 20%.
bool any_input() {
	for (Button b : BUTTONS) {
		if (pros::c::controller_get_digital(MASTER, b) == 1) return true;
	}
	for (auto s : STICKS) {
		if (std::abs(pros::c::controller_get_analog(MASTER, s)) > STICK_STOP) return true;
	}
	return false;
}

// 10 ms, keeping the screens fresh (and logging, if a test waiting on the student does).
void tick() {
	static std::uint32_t next_status = 0;
	std::uint32_t now = pros::c::millis();
	if (now >= next_status) {
		status();
		next_status = now + 1000;
	}
	if (g_sample_ms && now >= g_next_sample) {
		vexsim_log::sample();
		g_next_sample = now + g_sample_ms;
	}
	pad_flush();
	pros::c::delay(10);
}

// Waits for one of the buttons to be pressed.
Button wait_for(std::initializer_list<Button> buttons) {
	for (Button b : buttons) pros::c::controller_get_digital_new_press(MASTER, b);  // not an old one
	while (true) {
		for (Button b : buttons) {
			if (pros::c::controller_get_digital_new_press(MASTER, b) == 1) return b;
		}
		tick();
	}
}

// ---- logs --------------------------------------------------------------------------------------

void log_start(const char* log_name, const char* test, int run) {
	char name[64];
	std::snprintf(name, sizeof name, "%s", log_name);
	vexsim_log::info("robot", ROBOT);
	vexsim_log::info("field", FIELD);
	vexsim_log::info("program", "vexsim calibration");
	vexsim_log::info("test", test);
	vexsim_log::info("run", f("%d", run));
	if (g_imu_moved) vexsim_log::info("warning", "the robot moved while the IMU calibrated");
	vexsim_log::start(name, vexsim_log::Sampling::manual);
	vexsim_log::sample();
	say("log %s %s %d", name, test, run);
}

void log_spot(const cal::Spot& spot) {
	vexsim_log::info("spot", f("%.2f %.2f %.1f", spot.x, spot.y, spot.heading));
}

// Saves the log, with how the run ended ("finished", or why it stopped).
void log_stop(const char* ended) {
	vexsim_log::info("ended", ended);
	if (vexsim_log::stop() > 0) g_saved++;
	say("saved %s", ended);
}

// ---- before a test -----------------------------------------------------------------------------

const char* type_name(int type) {
	switch (type) {
		case 0: return "nothing";
		case 2: return "a motor";
		case 4: return "a rotation sensor";
		case 6: return "an IMU";
		case 7: return "a distance sensor";
		case 11: return "a vision sensor";
		case 16: return "an optical sensor";
		case 20: return "a GPS sensor";
		default: return "another device";
	}
}

// Every device the tests use answers on its port, as its type; if one doesn't, says which.
bool devices_answer() {
	for (const auto& d : DEVICES) {
		int found = static_cast<int>(pros::c::get_plugged_type(d.port));
		if (found == d.type) continue;
		page(f("Port %d: %s missing", d.port, d.what),
		     {f("The config has the %s on port %d,", d.what, d.port), f("but %s answers there.", type_name(found)),
		      "Plug it in, or fix the robot config."},
		     "B: back", f("Port %d missing", d.port), "B:back");
		say("ask device %d", d.port);
		wait_for({B});
		return false;
	}
	return true;
}

// Before a test: every device answers, the battery is charged (or the student goes on
// anyway), no drive motor is hot. False to go back to the menu.
bool ready() {
	if (!devices_answer()) return false;
	int pct = battery_pct();
	if (pct < BATTERY_MIN) {
		page(f("The battery is at %d%%", pct),
		     {"Charge it to 80% or more: tests on a low", "battery fit the model less well."},
		     "A: run anyway  B: back", f("Battery %d%%", pct), "A:run B:back");
		say("ask battery %d", pct);
		if (wait_for({A, B}) == B) return false;
	}
	while (true) {
		int port = 0;
		double hot = hottest(&port);
		if (hot <= HOT_C) return true;
		page(f("Motor %d is %.0f C", port, hot),
		     {"Let it cool below 45 C: a hot motor is", "weaker, and the fit would learn that."},
		     "A: check again  B: back", f("Motor %d %.0fC", port, hot), "A:again B:back");
		say("ask hot %d", port);
		if (wait_for({A, B}) == B) return false;
	}
}

// Until the robot is still: no wheel turning and the IMU steady, for half a second.
void wait_still() {
	page("Waiting for the robot to be still", {"Hands off."}, "", "Hands off", "");
	double last[MOTOR_COUNT];
	for (int i = 0; i < MOTOR_COUNT; i++) last[i] = position(i);
	double turn = rotation();
	std::uint32_t began = pros::c::millis();
	int still_ms = 0;
	while (still_ms < 500 && pros::c::millis() - began < 5000) {
		tick();
		bool moving = std::fabs(rotation() - turn) > 0.2;
		turn = rotation();
		for (int i = 0; i < MOTOR_COUNT; i++) {
			if (std::fabs(position(i) - last[i]) > 0.5) moving = true;
			last[i] = position(i);
		}
		still_ms = moving ? 0 : still_ms + 10;
	}
}

// Hands off the controller, then 3, 2, 1 with a rumble each second. False if a button or
// a stick moved during the countdown.
bool go() {
	while (any_input()) {
		brain(5, "Let go of the controller");
		tick();
	}
	say("countdown");
	for (int s = 3; s > 0; s--) {
		brain(5, f("Starting in %d: stand clear!", s));
		pad(1, f("Starting in %d", s));
		pros::c::controller_rumble(MASTER, ".");
		g_pad_next = pros::c::millis() + 60;  // the controller takes one thing at a time
		for (int t = 0; t < 1000; t += 10) {
			if (any_input()) {
				stop_motors(true);
				brain(5, "Cancelled.");
				say("cancelled");
				return false;
			}
			tick();
		}
	}
	pros::c::controller_rumble(MASTER, "-");
	g_pad_next = pros::c::millis() + 60;
	return true;
}

// Calibrates the IMU (about 2 s), noting whether the wheels turned meanwhile: an IMU that
// calibrates while the robot moves reads a drifting heading.
void calibrate_imu() {
	if (!IMU_PORT) return;
	page("Calibrating the IMU", {"Keep the robot still."}, "", "IMU: keep still", "");
	say("imu calibrating");
	double start[MOTOR_COUNT];
	for (int i = 0; i < MOTOR_COUNT; i++) start[i] = position(i);
	pros::c::imu_reset(IMU_PORT);
	std::uint32_t began = pros::c::millis();
	bool moved = false;
	while ((pros::c::imu_get_status(IMU_PORT) & pros::E_IMU_STATUS_CALIBRATING) &&
	       pros::c::millis() - began < 5000) {
		for (int i = 0; i < MOTOR_COUNT; i++) {
			if (std::fabs(position(i) - start[i]) > 10) moved = true;
		}
		tick();
	}
	g_imu_moved = moved;
	say("imu ready%s", moved ? " moved" : "");
}

// ---- running steps -----------------------------------------------------------------------------

struct Outcome {
	const char* stopped = nullptr;  // why it stopped early, if it did
	double seconds = 0;
	double top_in_s = 0;  // the wheels' fastest
	double turn_deg = 0;
	bool sudden = false;  // the wheels slowed suddenly: did it hit something?
	int low_mv = 100000;  // the battery's lowest
};

// What stops a run: a button or stick, or going further than the plan's envelope, braking
// included: a motor's distance from where it started, plus how far it turns braking from its
// speed if it's moving away.
const char* stop_reason(const double start[], double start_turn, double max_motor_deg, double max_turn_deg) {
	if (any_input()) return "a button or stick";
	for (int i = 0; i < MOTOR_COUNT; i++) {
		double from = position(i) - start[i];
		double v = pros::c::motor_get_actual_velocity(MOTORS[i].port) * 6;  // deg/s
		double braking = from * v > 0 ? v * v / (2 * BRAKE_DEG_S2) : 0;
		if (std::fabs(from) + braking > max_motor_deg) return "went further than planned";
	}
	if (IMU_PORT && max_turn_deg > 0 && std::fabs(rotation() - start_turn) > max_turn_deg) {
		return "turned further than planned";
	}
	return nullptr;
}

// The wheels' surface speed (in/s), averaged over the drive motors.
double wheel_speed() {
	double sum = 0;
	for (int i = 0; i < MOTOR_COUNT; i++) sum += std::fabs(speed(i)) * MOTORS[i].in_per_rev / 60;
	return sum / MOTOR_COUNT;
}

void apply(const cal::Step& step) {
	for (int i = 0; i < MOTOR_COUNT; i++) {
		int port = MOTORS[i].port;
		pros::c::motor_set_brake_mode(port, step.brake ? pros::E_MOTOR_BRAKE_BRAKE : pros::E_MOTOR_BRAKE_COAST);
		if (step.mv[i] != 0) {
			pros::c::motor_move_voltage(port, step.mv[i]);
		} else {
			pros::c::motor_brake(port);
		}
		vexsim_log::command(port, step.mv[i]);
	}
}

// After a run: half a second more of the log, the robot settling.
void settle(std::uint32_t* now) {
	for (int t = 0; t < 500; t += 10) {
		vexsim_log::sample();
		pros::c::task_delay_until(now, 10);
	}
}

// Runs open-loop steps, a log row every 10 ms; stops at once on a button or stick, or on
// leaving the envelope.
Outcome run_steps(const cal::Step* steps, int count, double max_motor_deg, double max_turn_deg) {
	Outcome out;
	double start[MOTOR_COUNT];
	for (int i = 0; i < MOTOR_COUNT; i++) start[i] = position(i);
	double start_turn = rotation();
	double recent[10] = {};  // the wheels' speed over the last 100 ms
	int n = 0;
	std::uint32_t began = pros::c::millis(), now = began;
	for (int k = 0; k < count && !out.stopped; k++) {
		const cal::Step& step = steps[k];
		vexsim_log::mark(step.name);
		apply(step);
		for (int t = 0; t < step.ms; t += 10) {
			vexsim_log::sample();
			pros::c::task_delay_until(&now, 10);
			if ((out.stopped = stop_reason(start, start_turn, max_motor_deg, max_turn_deg))) break;
			double v = wheel_speed();
			out.top_in_s = std::fmax(out.top_in_s, v);
			int mv = pros::c::battery_get_voltage();
			if (mv > 0 && mv < out.low_mv) out.low_mv = mv;
			// Coasting, or driven the way the wheels turn, and losing 20 in/s in 100 ms (coasting
			// loses about 4): did it hit something?
			bool along = !step.brake && t >= 100 && n >= 10;
			for (int i = 0; i < MOTOR_COUNT; i++) {
				if (pros::c::motor_get_actual_velocity(MOTORS[i].port) * step.mv[i] < 0) along = false;
			}
			if (along && recent[n % 10] - v > SUDDEN_IN_S && !out.sudden) {
				out.sudden = true;
				vexsim_log::mark("slowed suddenly");
			}
			recent[n++ % 10] = v;
		}
	}
	stop_motors(true);
	if (out.stopped) {
		vexsim_log::mark(f("stopped: %s", out.stopped));
		say("stopped %s", out.stopped);
		settle(&now);
	}
	out.seconds = (pros::c::millis() - began) / 1000.0;
	out.turn_deg = std::fabs(rotation() - start_turn);
	return out;
}

// Turns in place counter-clockwise by `degrees`, at about deg_per_s, guided by the IMU.
Outcome turn_in_place(double degrees, double deg_per_s) {
	Outcome out;
	double start[MOTOR_COUNT];
	for (int i = 0; i < MOTOR_COUNT; i++) start[i] = position(i);
	double r0 = rotation();
	double max_motor = MOTOR_DEG_PER_TURN_DEG * (degrees + 30) * 1.3 + 90;
	double limit_s = degrees / deg_per_s * 2 + 5;
	double fraction = deg_per_s * TURN_PER_DEG_S;  // a first guess, from the plan's simulations
	double history[11] = {};
	int k = 0;
	std::uint32_t began = pros::c::millis(), now = began;
	vexsim_log::mark("turn");
	for (int i = 0; i < MOTOR_COUNT; i++) {
		pros::c::motor_set_brake_mode(MOTORS[i].port, pros::E_MOTOR_BRAKE_BRAKE);
	}
	while (r0 - rotation() < degrees) {  // counter-clockwise: PROS's rotation goes down
		history[k % 11] = rotation();
		if (k >= 10) {
			double rate = (history[(k - 10) % 11] - history[k % 11]) / 0.1;
			fraction += 0.00004 * (deg_per_s - rate);  // toward the rate, slowly
			fraction = std::fmin(std::fmax(fraction, 0.03), 1.0);
		}
		k++;
		for (int i = 0; i < MOTOR_COUNT; i++) command(i, static_cast<int>(std::lround(MIX[i][2] * fraction)));
		vexsim_log::sample();
		pros::c::task_delay_until(&now, 10);
		out.top_in_s = std::fmax(out.top_in_s, wheel_speed());
		if (any_input()) {
			out.stopped = "a button or stick";
		} else if ((pros::c::millis() - began) / 1000.0 > limit_s) {
			out.stopped = "too slow: is it stuck?";
		} else {
			for (int i = 0; i < MOTOR_COUNT; i++) {
				if (std::fabs(position(i) - start[i]) > max_motor) out.stopped = "the wheels turned more than the robot";
			}
		}
		if (out.stopped) break;
	}
	stop_motors(true);
	vexsim_log::mark(out.stopped ? f("stopped: %s", out.stopped) : "brake");
	if (out.stopped) say("stopped %s", out.stopped);
	settle(&now);
	out.seconds = (pros::c::millis() - began) / 1000.0;
	out.turn_deg = std::fabs(r0 - rotation());
	return out;
}

// What a run did, and its warnings: up to 4 lines.
void show_outcome(const char* title, const Outcome& out) {
	const char* lines[4] = {"", "", "", ""};
	int n = 0;
	if (out.stopped) {
		lines[n++] = f("Stopped: %s.", out.stopped);
	} else {
		lines[n++] = f("%.1f s, wheels up to %.0f in/s, turned %.0f deg", out.seconds, out.top_in_s, out.turn_deg);
	}
	if (out.sudden && n < 4) lines[n++] = "It slowed suddenly: did it hit something?";
	int port = 0;
	if (hottest(&port) > WARM_C && n < 4) lines[n++] = f("Motor %d is hot: let it cool.", port);
	if (out.low_mv < SAG_MV && n < 4) lines[n++] = f("The battery sagged to %.1f V: charge it.", out.low_mv / 1000.0);
	if (g_imu_moved && n < 4) lines[n++] = "It moved while the IMU calibrated: redo IMU.";
	page(title, {lines[0], lines[1], lines[2], lines[3]}, "A: next  B: menu", out.stopped ? "Stopped" : "Saved",
	     "A:next B:menu");
}

// ---- the tests ---------------------------------------------------------------------------------

struct Item {
	const char* key;
	const char* title;
	int number;
	int runs;  // runs it takes (0: Drive mode)
	int done;
};

// The device check, on its side: spins a group's motors (or one of them: only >= 0) forward
// at 3 V, as the config says, for 1.5 s; each motor's speed over the last half second.
bool spin_check(int g, int only, double speeds[]) {
	page(only < 0 ? f("Watch the %s wheels", GROUPS[g].name) : f("Watch the wheels: motor %d alone", MOTORS[only].port),
	     {"They spin slowly for 1.5 s. Hands off."}, "", "Watch the wheels", "");
	if (!go()) return false;
	if (only < 0) {
		say("spin group %s", GROUPS[g].name);
		vexsim_log::mark(f("spin %s", GROUPS[g].name));
	} else {
		say("spin motor %d", MOTORS[only].port);
		vexsim_log::mark(f("spin motor %d", MOTORS[only].port));
	}
	for (int i = 0; i < MOTOR_COUNT; i++) {
		speeds[i] = 0;
		bool on = MOTORS[i].group == g && (only < 0 || only == i);
		pros::c::motor_set_brake_mode(MOTORS[i].port, pros::E_MOTOR_BRAKE_COAST);
		if (on) {
			command(i, CHECK_MV * MOTORS[i].direction);
		} else {
			pros::c::motor_brake(MOTORS[i].port);
			vexsim_log::command(MOTORS[i].port, 0);
		}
	}
	std::uint32_t now = pros::c::millis();
	int n = 0;
	bool stopped = false;
	for (int t = 0; t < 1500 && !stopped; t += 10) {
		vexsim_log::sample();
		pros::c::task_delay_until(&now, 10);
		if (any_input()) stopped = true;
		if (t >= 1000) {
			for (int i = 0; i < MOTOR_COUNT; i++) speeds[i] += speed(i);
			n++;
		}
	}
	stop_motors(false);  // coasting to a stop
	for (int t = 0; t < 800; t += 10) {
		vexsim_log::sample();
		pros::c::task_delay_until(&now, 10);
	}
	for (int i = 0; i < MOTOR_COUNT; i++) speeds[i] /= n > 0 ? n : 1;
	return !stopped;
}

// Did the wheels spin forward? The student watched: 'f' yes, 'b' backward, 'x' they didn't.
char ask_forward(const char* what, int g) {
	page(f("Did the %s spin forward?", what),
	     {"Forward: the top of each wheel moves toward", f("the robot's %s.", GROUPS[g].toward)},
	     "A: yes  B: no, backward  X: they didn't", "Forward?", "A:yes B:no X:still");
	say("ask forward");
	Button b = wait_for({A, B, X});
	vexsim_log::mark(b == A ? "answer: forward" : b == B ? "answer: backward" : "answer: didn't turn");
	return b == A ? 'f' : b == B ? 'b' : 'x';
}

// The config's motor port, signed as the config has it.
int signed_port(int i) { return MOTORS[i].port * MOTORS[i].direction; }

// Checks one group of drive motors, the robot on its side: they turn together, and forward.
// False if cancelled.
bool check_group(int g) {
	double speeds[MOTOR_COUNT];
	if (!spin_check(g, -1, speeds)) return false;
	int members = 0, forward = 0;
	for (int i = 0; i < MOTOR_COUNT; i++) {
		if (MOTORS[i].group != g) continue;
		members++;
		if (speeds[i] > 0.05 * MOTORS[i].rpm) forward++;
	}
	int before = g_problem_count;
	if (forward == members) {  // they turn together
		char answer = ask_forward(f("%s wheels", GROUPS[g].name), g);
		if (answer == 'x') problem(f("%s: the motors turn, but not the wheels", GROUPS[g].name));
		if (answer == 'b') problem(f("%s: all backward: flip each motor's sign", GROUPS[g].name));
	} else {  // they fight, or some don't turn: one at a time
		for (int i = 0; i < MOTOR_COUNT; i++) {
			if (MOTORS[i].group != g) continue;
			if (!spin_check(g, i, speeds)) return false;
			char answer = ask_forward(f("wheels (motor %d)", MOTORS[i].port), g);
			if (answer == 'b') problem(f("motor %d runs backward: make it %d", MOTORS[i].port, -signed_port(i)));
			if (answer == 'x') problem(f("motor %d doesn't turn the wheels", MOTORS[i].port));
		}
		if (g_problem_count == before) problem(f("%s: the motors fight each other", GROUPS[g].name));
	}
	vexsim_log::info(f("check_%s", GROUPS[g].name), g_problem_count > before ? g_problems[before] : "ok");
	return true;
}

// Checks the IMU counts a turn to the left the right way.
void check_imu() {
	page("IMU: turn the robot", {"Turn the robot by hand about a quarter turn", "to the left (counter-clockwise, seen from", "above), then press A."},
	     "A: done", "Turn 1/4 left", "A:done");
	double r0 = rotation();
	say("ask turn left 90");
	vexsim_log::mark("turn left by hand");
	wait_for({A});
	double turned = r0 - rotation();  // counter-clockwise
	vexsim_log::mark(f("the IMU turned %.1f deg", turned));
	int before = g_problem_count;
	if (turned < -45) {
		problem("IMU: it reads turns backward");
	} else if (turned < 45) {
		problem(f("IMU: it saw only %.0f deg: is it on port %d?", turned, IMU_PORT));
	}
	vexsim_log::info("check_imu", g_problem_count > before ? g_problems[before] : "ok");
}

// Checks each tracking wheel counts the right way: the robot pushed forward, then left.
void check_tracking() {
	int before = g_problem_count;
	bool bad[TRACKING_COUNT + 1] = {};
	for (int push = 0; push < 2; push++) {
		const char* way = push == 0 ? "forward" : "to its left";
		page(f("Tracking wheels: push it %s", way), {f("Push the robot straight %s about", way), "12 in (30 cm), then press A."},
		     "A: done", push == 0 ? "Push it forward" : "Push it left", "A:done");
		int start[TRACKING_COUNT + 1];
		for (int k = 0; k < TRACKING_COUNT; k++) start[k] = pros::c::rotation_get_position(TRACKING[k].port);
		say("ask push %s 12", push == 0 ? "forward" : "left");
		vexsim_log::mark(push == 0 ? "push forward by hand" : "push left by hand");
		wait_for({A});
		for (int k = 0; k < TRACKING_COUNT; k++) {
			int expected = push == 0 ? TRACKING[k].forward : TRACKING[k].left;
			if (expected == 0 || bad[k]) continue;
			int change = (pros::c::rotation_get_position(TRACKING[k].port) - start[k]) * expected;
			if (change > 3600) continue;  // over 36 degrees, the right way
			bad[k] = true;
			if (change < -3600) {
				problem(f("tracking wheel %d counts backward: flip reversed", TRACKING[k].port));
			} else {
				problem(f("tracking wheel %d didn't turn: on the floor?", TRACKING[k].port));
			}
		}
	}
	vexsim_log::info("check_tracking", g_problem_count > before ? g_problems[before] : "ok");
}

// A distance sensor's reading, averaged over 0.3 s (9999: nothing in range).
void read_distances(int out[]) {
	long sums[DISTANCE_COUNT + 1] = {};
	for (int n = 0; n < 10; n++) {
		for (int k = 0; k < DISTANCE_COUNT; k++) sums[k] += pros::c::distance_get(DISTANCES[k].port);
		tick();
		pros::c::delay(20);
	}
	for (int k = 0; k < DISTANCE_COUNT; k++) out[k] = static_cast<int>(sums[k] / 10);
}

// Checks each distance sensor is the one the config says: a hand over each in turn.
void check_distances() {
	int before = g_problem_count;
	page("Distance sensors", {"Turn the robot so nothing is within a foot", "of any of its distance sensors, then", "press A."},
	     "A: done", "Clear the sensors", "A:done");
	say("ask open");
	wait_for({A});
	int base[DISTANCE_COUNT + 1], now[DISTANCE_COUNT + 1];
	int found[DISTANCE_COUNT + 1];  // which sensor read close, each sensor covered (-1: none, -2: more)
	read_distances(base);
	for (int k = 0; k < DISTANCE_COUNT; k++) {
		page(f("Cover the sensor at the %s", DISTANCES[k].where),
		     {f("(port %d) with your hand, close to it,", DISTANCES[k].port), "then press A."}, "A: done",
		     f("Cover port %d", DISTANCES[k].port), "A:done");
		say("ask cover %d", DISTANCES[k].port);
		wait_for({A});
		read_distances(now);
		int covered = -1, many = 0;
		for (int j = 0; j < DISTANCE_COUNT; j++) {
			if (now[j] < CLOSE_MM && base[j] >= CLEAR_MM) {
				covered = j;
				many++;
			}
		}
		found[k] = many == 1 ? covered : many == 0 ? -1 : -2;
		vexsim_log::mark(f("covered at the %s: port %d", DISTANCES[k].where, covered < 0 ? 0 : DISTANCES[covered].port));
	}
	for (int k = 0; k < DISTANCE_COUNT; k++) {
		int j = found[k];
		if (j == k) continue;
		if (j >= 0 && found[j] == k) {  // a pair swapped: said once
			if (j > k) problem(f("ports %d and %d are swapped", DISTANCES[k].port, DISTANCES[j].port));
		} else if (j >= 0) {
			problem(f("the sensor at the %s is on port %d, not %d", DISTANCES[k].where, DISTANCES[j].port,
			          DISTANCES[k].port));
		} else if (j == -1) {
			problem(f("port %d: nothing read close: plugged in?", DISTANCES[k].port));
		} else {
			problem(f("port %d: more than one read close", DISTANCES[k].port));
		}
	}
	vexsim_log::info("check_distance", g_problem_count > before ? g_problems[before] : "ok");
	page("Distance sensors: done", {"Take your hand away."}, "A: next", "Hand away", "A:next");
	say("ask uncover");
	wait_for({A});
}

void device_check(Item& item) {
	if (!devices_answer()) return;
	page("Device check, on its side",
	     {"Lay the robot on its side, its wheels off the", "ground and nothing touching them. Each side's",
	      "wheels spin slowly; say which way they went."},
	     "A: ready  B: back", "Lay it on its side", "A:ready B:back");
	say("ask side");
	if (wait_for({A, B}) == B) return;
	vexsim_log::set_limit_s(900);
	log_start("device_check", "device_check", 1);
	g_problem_count = 0;
	for (int g = 0; g < GROUP_COUNT; g++) {
		if (!check_group(g)) {
			stop_motors(true);
			log_stop("stopped: cancelled");
			vexsim_log::set_limit_s(180);
			return;
		}
	}
	page("Stand the robot on its wheels", {"Put it down flat, then press A."}, "A: done", "Stand it up", "A:done");
	say("ask flat");
	wait_for({A});
	g_sample_ms = 50;
	if (IMU_PORT) {
		calibrate_imu();
		check_imu();
	}
	if (TRACKING_COUNT) check_tracking();
	if (DISTANCE_COUNT) check_distances();
	g_sample_ms = 0;
	int count = g_problem_count;
	for (int k = 0; k < count; k++) vexsim_log::mark(f("to fix: %s", g_problems[k]));
	vexsim_log::info("check", count ? "failed" : "passed");
	log_stop("finished");
	vexsim_log::set_limit_s(180);
	if (count == 0) {
		page("Device check: passed", {"Every device answers, turns and counts", "the way the config says."}, "A: next",
		     "Check: passed", "A:next");
	} else {
		page(f("Device check: %d to fix", count),
		     {g_problems[0], count > 1 ? g_problems[1] : "", count > 2 ? g_problems[2] : "",
		      count > 3 ? f("...and %d more (see the log)", count - 3) : "Fix the config, then check again."},
		     "A: next", "Check: fix it", "A:next");
	}
	for (int k = 0; k < count; k++) say("problem %s", g_problems[k]);
	say("ask done %s", count ? "failed" : "passed");
	wait_for({A});
	item.done = 1;
}

void free_spin(Item& item) {
	if (!ready()) return;
	page("Free spin, on its side",
	     {"Lay the robot on its side, its wheels off the", "ground and nothing touching them. The",
	      "wheels spin up to full speed, about 12 s."},
	     "A: start  B: back", "Lay it on its side", "A:start B:back");
	say("ask side");
	if (wait_for({A, B}) == B) return;
	if (!go()) return;
	log_start("free_spin", "free_spin", 1);
	const char* stopped = nullptr;
	std::uint32_t now = pros::c::millis();
	auto hold = [&](int ms) {
		for (int t = 0; t < ms && !stopped; t += 10) {
			vexsim_log::sample();
			pros::c::task_delay_until(&now, 10);
			if (any_input()) stopped = "a button or stick";
		}
	};
	stop_motors(false);
	for (int mv : FREE_SPIN_MV) {
		if (stopped) break;
		vexsim_log::mark(f("%d V", mv / 1000));
		for (int i = 0; i < MOTOR_COUNT; i++) command(i, mv * MOTORS[i].direction);
		hold(1500);
	}
	if (!stopped) {
		vexsim_log::mark("brake");
		stop_motors(true);
		hold(1000);
	}
	for (int pct : {50, 100}) {
		if (stopped) break;
		vexsim_log::mark(f("velocity %d%%", pct));
		for (int i = 0; i < MOTOR_COUNT; i++) {
			int rpm = MOTORS[i].rpm * pct / 100 * MOTORS[i].direction;
			pros::c::motor_move_velocity(MOTORS[i].port, rpm);
			vexsim_log::command_velocity(MOTORS[i].port, rpm);
		}
		hold(1500);
	}
	stop_motors(true);
	vexsim_log::mark(stopped ? f("stopped: %s", stopped) : "brake");
	if (stopped) say("stopped %s", stopped);
	for (int t = 0; t < 1000; t += 10) {
		vexsim_log::sample();
		pros::c::task_delay_until(&now, 10);
	}
	log_stop(stopped ? f("stopped: %s", stopped) : "finished");
	page(stopped ? "Free spin: stopped" : "Free spin: saved", {"Stand the robot back on its wheels, then", "press A."},
	     "A: done", "Stand it up", "A:done");
	say("ask flat");
	wait_for({A});
	if (!stopped) item.done = 1;
}

void imu_still(Item& item) {
	if (!ready()) return;
	page(f("IMU, still for %d s", IMU_STILL_S),
	     {"Put the robot down flat where nobody will", "bump it. It calibrates the IMU, then",
	      f("must stay still for %d s: hands off.", IMU_STILL_S)},
	     "A: start  B: back", "Put it down still", "A:start B:back");
	say("ask still");
	if (wait_for({A, B}) == B) return;
	while (any_input()) tick();
	calibrate_imu();
	page(f("IMU, still for %d s: hands off", IMU_STILL_S), {"", "Any button stops it."}, "", "Hands off", "");
	log_start("imu_still", "imu_still", 1);
	double r0 = rotation();
	const char* stopped = nullptr;
	std::uint32_t now = pros::c::millis();
	for (int t = 0; t < IMU_STILL_S * 1000 && !stopped; t += 10) {
		vexsim_log::sample();
		if (t % 1000 == 0) {
			brain(3, f("%d s to go.", IMU_STILL_S - t / 1000));
			pad(1, f("Still: %d s", IMU_STILL_S - t / 1000));
			pad_flush();
		}
		pros::c::task_delay_until(&now, 10);
		if (any_input()) stopped = "a button or stick";
	}
	double drift = rotation() - r0;
	log_stop(stopped ? f("stopped: %s", stopped) : "finished");
	page(stopped ? "IMU still: stopped" : "IMU still: saved", {f("It drifted %.2f deg in %d s.", drift, IMU_STILL_S)},
	     "A: next", "Saved", "A:next");
	say("ask next");
	wait_for({A});
	if (!stopped) item.done = 1;
}

void imu_turns(Item& item) {
	while (item.done < 2) {
		const char* way = item.done == 0 ? "left" : "right";
		if (!ready()) return;
		page(f("IMU: %d turns to the %s", IMU_TURNS, way),
		     {"Line the robot up along a tape line, one", "side against it, then press A. Then turn",
		      f("it %d full turns to the %s by hand, and", IMU_TURNS, way), "line it up on the tape again."},
		     "A: ready  B: back", f("%d turns %s", IMU_TURNS, way), "A:ready B:back");
		say("ask line");
		if (wait_for({A, B}) == B) return;
		log_start(f("imu_turns_%s", way), "imu_turns", item.done + 1);
		vexsim_log::info("direction", way);
		vexsim_log::info("turns", f("%d", IMU_TURNS));
		double r0 = rotation();
		page(f("Turn it %d times to the %s", IMU_TURNS, way),
		     {"Slowly and smoothly, by hand. Then line it", "up on the tape again and press A."},
		     "A: done  B: cancel", f("Turn %d %s, then A", IMU_TURNS, way), "A:done B:cancel");
		say("ask turn %s %d", way, IMU_TURNS * 360);
		g_sample_ms = 20;
		Button b = wait_for({A, B});
		g_sample_ms = 0;
		vexsim_log::sample();
		double turned = r0 - rotation();  // counter-clockwise
		log_stop(b == A ? "finished" : "stopped: cancelled");
		if (b == B) return;
		double real = IMU_TURNS * 360.0 * (item.done == 0 ? 1 : -1);
		double off = (turned - real) / real * 100;
		const char* note = std::fabs(off) > 5 ? "That's not 10 turns: count, and run it again." : "";
		page("Saved", {f("The IMU read %.1f deg for %.0f.", std::fabs(turned), std::fabs(real)),
		               f("It reads %.2f%% %s than it turns.", std::fabs(off), off > 0 ? "more" : "less"), note},
		     "A: next", "Saved", "A:next");
		say("ask next");
		wait_for({A});
		if (std::fabs(off) <= 5) item.done++;
	}
}

void push(Item& item) {
	while (item.done < 2) {
		bool back = item.done == 1;
		if (!ready()) return;
		if (!back) {
			page(f("Push lane (map %d)", item.number),
			     {PUSH_SPOT.place[0], PUSH_SPOT.place[1], PUSH_SPOT.place[2], "Then press A."}, "A: ready  B: back",
			     "Put it on the lane", "A:ready B:back");
			say("ask place push");
		} else {
			page("Push it back", {"Now the other way: from the end line back", "to the start line."},
			     "A: ready  B: back", "Push it back", "A:ready B:back");
			say("ask ready");
		}
		if (wait_for({A, B}) == B) return;
		stop_motors(false);  // coasting: the wheels roll freely
		double start[MOTOR_COUNT];
		for (int i = 0; i < MOTOR_COUNT; i++) start[i] = position(i);
		log_start(back ? "push_back" : "push_forward", "push", item.done + 1);
		log_spot(PUSH_SPOT);
		vexsim_log::info("length_in", f("%.1f", PUSH_IN));
		vexsim_log::info("direction", back ? "back" : "forward");
		page(back ? "Push it back to the start line" : "Push it to the end line",
		     {f("Slowly and straight, %.0f in, until its", PUSH_IN),
		      back ? "front edge is on the start line again." : "front edge is on the end line.", "Then press A."},
		     "A: done  B: cancel", "Push, then A", "A:done B:cancel");
		say("ask lane %s %.1f", back ? "back" : "forward", PUSH_IN);
		g_sample_ms = 10;
		Button b = wait_for({A, B});
		g_sample_ms = 0;
		vexsim_log::sample();
		log_stop(b == A ? "finished" : "stopped: cancelled");
		if (b == B) return;
		double travel = 0;
		int n = 0;
		for (int i = 0; i < MOTOR_COUNT; i++) {
			if (MOTORS[i].in_per_deg <= 0) continue;
			travel += std::fabs(position(i) - start[i]) * MOTORS[i].in_per_deg;
			n++;
		}
		travel /= n > 0 ? n : 1;
		double off = (travel - PUSH_IN) / PUSH_IN * 100;
		page("Saved", {f("The wheels say %.1f in for %.0f in:", travel, PUSH_IN),
		               f("%.1f%% %s.", std::fabs(off), off > 0 ? "more" : "less")},
		     "A: next", "Saved", "A:next");
		say("ask next");
		wait_for({A});
		item.done++;
	}
}

void drive_test(Item& item, const cal::DriveTest& test) {
	while (item.done < item.runs) {
		int run = item.done + 1;
		if (!ready()) return;
		page(f("%s, run %d of %d (map %d)", test.title, run, item.runs, item.number),
		     {"Put the robot on its spot:", test.spot.place[0], test.spot.place[1], test.spot.place[2]},
		     "A: start  B: back", f("%s %d/%d", test.key, run, item.runs), "A:start B:back");
		say("ask place %s", test.key);
		if (wait_for({A, B}) == B) return;
		wait_still();
		if (!go()) continue;
		log_start(test.key, test.key, run);
		log_spot(test.spot);
		vexsim_log::info("scale", f("%.2f", test.scale));
		Outcome out = run_steps(test.steps, test.step_count, test.max_motor_deg, test.max_turn_deg);
		log_stop(out.stopped ? f("stopped: %s", out.stopped) : "finished");
		if (!out.stopped) item.done++;
		show_outcome(f("%s, run %d: %s", test.title, run, out.stopped ? "stopped" : "saved"), out);
		say("ask next");
		if (wait_for({A, B}) == B) return;
	}
}

void spin_test(Item& item, const cal::Spin& spin) {
	if (!ready()) return;
	page(f("%s (map %d)", spin.title, item.number),
	     {"Put the robot on its spot:", spin.spot.place[0], spin.spot.place[1], spin.spot.place[2]},
	     "A: start  B: back", f("%s", spin.key), "A:start B:back");
	say("ask place %s", spin.key);
	if (wait_for({A, B}) == B) return;
	wait_still();
	if (!go()) return;
	log_start(spin.key, spin.key, 1);
	log_spot(spin.spot);
	vexsim_log::info("turns", f("%g", spin.turns));
	Outcome out = turn_in_place(spin.turns * 360, spin.deg_per_s);
	log_stop(out.stopped ? f("stopped: %s", out.stopped) : "finished");
	if (!out.stopped) item.done = 1;
	show_outcome(f("%s: %s", spin.title, out.stopped ? "stopped" : "saved"), out);
	say("ask next");
	wait_for({A, B});
}

// Drives the robot between spots: tank, half speed, without logging.
void drive_mode() {
	page("Drive mode: tank, half speed", {"Left stick: left side; right stick: right", "side (left and right on the sticks: sideways,",
	                                     "if the drive can)."},
	     "B: back to the menu", "Drive: half speed", "B:menu");
	say("drive");
	pros::c::controller_get_digital_new_press(MASTER, B);
	while (pros::c::controller_get_digital_new_press(MASTER, B) != 1) {
		double left_y = pros::c::controller_get_analog(MASTER, pros::E_CONTROLLER_ANALOG_LEFT_Y) / 127.0;
		double right_y = pros::c::controller_get_analog(MASTER, pros::E_CONTROLLER_ANALOG_RIGHT_Y) / 127.0;
		double side = (pros::c::controller_get_analog(MASTER, pros::E_CONTROLLER_ANALOG_LEFT_X) +
		               pros::c::controller_get_analog(MASTER, pros::E_CONTROLLER_ANALOG_RIGHT_X)) /
		              254.0;
		double forward = (left_y + right_y) / 2, turn = (right_y - left_y) / 2;
		for (int i = 0; i < MOTOR_COUNT; i++) {
			double mv = 0.5 * (MIX[i][0] * forward - MIX[i][1] * side + MIX[i][2] * turn);
			pros::c::motor_move_voltage(MOTORS[i].port, static_cast<int>(std::lround(std::fmax(-6000, std::fmin(6000, mv)))));
		}
		tick();
	}
	stop_motors(true);
}

Item g_items[MENU_COUNT + 1];
int g_count = 0;

void run_item(Item& item) {
	const char* key = item.key;
	if (!std::strcmp(key, "device_check")) return device_check(item);
	if (!std::strcmp(key, "free_spin")) return free_spin(item);
	if (!std::strcmp(key, "imu_still")) return imu_still(item);
	if (!std::strcmp(key, "imu_turns")) return imu_turns(item);
	if (!std::strcmp(key, "push")) return push(item);
	if (!std::strcmp(key, "drive")) return drive_mode();
	for (int k = 0; k < DRIVE_TEST_COUNT; k++) {
		if (!std::strcmp(key, DRIVE_TESTS[k].key)) return drive_test(item, DRIVE_TESTS[k]);
	}
	for (int k = 0; k < SPIN_COUNT; k++) {
		if (!std::strcmp(key, SPINS[k].key)) return spin_test(item, SPINS[k]);
	}
}

void show_menu(int cursor) {
	int first = cursor - 1;
	if (first > g_count - 5) first = g_count - 5;
	if (first < 0) first = 0;
	brain(2, "Tests, in order:");
	for (int line = 3; line < 7; line++) {
		int k = first + line - 3;
		if (k >= g_count) {
			brain(line, "");
			continue;
		}
		const Item& item = g_items[k];
		const char* state = item.runs == 0 ? "" : item.done >= item.runs ? "done" : item.done ? f("%d/%d", item.done, item.runs) : "";
		brain(line, f("%c%2d %-38.38s %s", k == cursor ? '>' : ' ', item.number, item.title, state));
	}
	brain(7, "UP/DOWN: choose  A: start");
	const Item& item = g_items[cursor];
	pad(1, f(">%d %s", item.number, item.title));
	pad(2, "A:start ^v:choose");
	say("menu %s", item.key);
}

}  // namespace

void initialize() {
	for (int line = 0; line < 3; line++) {
		std::memset(g_pad[line], ' ', PAD_WIDTH);
		g_pad[line][PAD_WIDTH] = g_pad_shown[line][0] = '\0';
	}
	for (int i = 0; i < MOTOR_COUNT; i++) {
		pros::c::motor_set_encoder_units(MOTORS[i].port, pros::E_MOTOR_ENCODER_DEGREES);
		pros::c::motor_set_brake_mode(MOTORS[i].port, pros::E_MOTOR_BRAKE_COAST);
		pros::c::motor_brake(MOTORS[i].port);
	}
	for (int k = 0; k < TRACKING_COUNT; k++) pros::c::rotation_set_reversed(TRACKING[k].port, false);  // raw counts
	for (int k = 0; k < MENU_COUNT; k++) g_items[g_count++] = {MENU[k].key, MENU[k].title, k + 1, MENU[k].runs, 0};
	g_items[g_count] = {"drive", "Drive mode (move it between spots)", g_count + 1, 0, 0};
	g_count++;
	status();
	calibrate_imu();
}

void disabled() {}

void competition_initialize() {}

// Nothing: the tests run from the menu (opcontrol), with no competition switch.
void autonomous() {}

void opcontrol() {
	int cursor = 0;
	while (true) {
		show_menu(cursor);
		Button b = wait_for({UP, DOWN, A});
		if (b == UP) {
			cursor = (cursor + g_count - 1) % g_count;
		} else if (b == DOWN) {
			cursor = (cursor + 1) % g_count;
		} else {
			Item& item = g_items[cursor];
			run_item(item);
			stop_motors(true);
			g_sample_ms = 0;
			if (item.runs && item.done >= item.runs && cursor < g_count - 1) cursor++;
		}
	}
}
