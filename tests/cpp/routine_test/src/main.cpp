#include "main.h"
#include "custom/auton.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>

void run_selected();

void delta() { std::printf("delta runs\n"); }

void initialize() {}
void disabled() {}
void competition_initialize() {}

void autonomous() {
	std::printf("autonomous setup\n");  // the project's own setup, which a picked routine keeps
	const char* calls = std::getenv("TEST_CALLS");
	if (calls && std::strcmp(calls, "delta") == 0)
		delta();  // a routine of this file, called directly: the switch never sees it
	else
		run_selected();
	std::printf("autonomous done\n");
}

void opcontrol() {
	while (true) pros::delay(20);
}
