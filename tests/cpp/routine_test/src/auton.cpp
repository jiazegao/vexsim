#include "main.h"
#include "custom/auton.hpp"

#include <cstdio>

// LemLib's chassis, as far as setPose goes
struct Chassis {
	void setPose(float x, float y, float theta, bool radians = false) {
		std::printf("setPose %g %g %g%s\n", x, y, theta, radians ? " rad" : "");
	}
} chassis;

void drive_for(int ms) { pros::delay(ms); }

void alpha() {
	chassis.setPose(-60, 24.5, 90);
	std::printf("alpha runs\n");
	drive_for(10);
}

void beta() {
	chassis.setPose(12, -36, 180);
	std::printf("beta runs\n");
	alpha();  // a routine calling another in its own file: as written
}

namespace extra {
void gamma() noexcept { std::printf("gamma runs\n"); }
}  // namespace extra
