// vexsim's logger: what a robot's devices read every 10 ms, with the code's own poses,
// numbers and notes, saved to the SD card (or sent over USB) for vexsim to read.
//
// The same two files (include/vexsim_log.hpp, src/vexsim_log.cpp) work in every PROS 4
// project, whatever is plugged in: `vexsim logger add PROJECT` copies them in. They use only
// the PROS 4 C API, so they build with PROS for the robot and run unchanged in vexsim.
//
//   void initialize() {
//       vexsim_log::pose("lemlib", [] {
//           lemlib::Pose p = chassis.getPose();
//           return vexsim_log::Pose{p.x, p.y, p.theta};
//       });
//   }
//   void autonomous() {
//       vexsim_log::start("Left 40");
//       left40();
//       vexsim_log::stop();  // or it saves itself when autonomous ends
//   }
#pragma once

#include <functional>

namespace vexsim_log {

// A pose as LemLib has them: inches, and degrees clockwise from +y.
struct Pose {
	double x;
	double y;
	double theta;
};

// Something only the code knows, read every 10 ms in every log started after this: a pose
// (columns pose_<name>_x_in, _y_in and _theta_deg) or a number (val_<name>).
void pose(const char* name, std::function<Pose()> read);
void value(const char* name, std::function<double()> read);

enum class Sampling {
	task,    // every 10 ms, in a task of the logger's own
	manual,  // each time the code calls sample()
};

// Starts a log: finds what is plugged into each port, then samples it all every 10 ms.
// A log started in autonomous saves itself when autonomous ends, and any log saves itself
// after 3 minutes (set_limit_s). False if a log is already running.
bool start(const char* name = "", Sampling sampling = Sampling::task);
void sample();  // Sampling::manual: a row, now
bool running();

// Notes: a mark at this moment, or a "# key: value" line at the top of the log.
void mark(const char* text);
void info(const char* key, const char* value);

// What the code told a motor (its port, without the sign), for logs vexsim replays: a
// voltage (0: stopped with its brake mode) or a velocity. Without these, vexsim replays
// the voltage each motor measured.
void command(int port, int millivolts);
void command_velocity(int port, double rpm);

// Saves the log to the next numbered file on the SD card (/usd/vexsim_0001_<name>.csv) or,
// without a card, prints it to the terminal between "#vexsim-log begin" and
// "#vexsim-log end" lines. The number of rows it saved (0 if no log was running).
int stop();
void set_limit_s(int seconds);  // how long a log runs before it saves itself (180)

}  // namespace vexsim_log
