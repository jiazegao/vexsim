// Test scenarios for the vexsim C++ bridge, selected by $VEXSIM_TEST.
// tests/test_bridge.py runs each one and checks what it prints.

#include "main.h"

#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <stdexcept>

#if __has_include("vexsim/sim.hpp")
#include "vexsim/sim.hpp"
#endif

static bool is(const char* name) {
	const char* s = std::getenv("VEXSIM_TEST");
	return s && std::strcmp(s, name) == 0;
}

static unsigned now() { return static_cast<unsigned>(pros::millis()); }

struct Announce {
	Announce() {
		if (is("console")) printf("from a global constructor\n");
	}
} announce;

// Constructed before main(), as robot code usually does.
pros::MotorGroup left_drive({1, 2, 3}, pros::MotorGearset::blue);
pros::MotorGroup right_drive({-4, -5, -6}, pros::MotorGearset::blue);

static void scheduler_scenarios() {
	if (is("delay")) {
		for (int i = 0; i < 4; i++) {
			printf("tick %u\n", now());
			pros::delay(7);
		}
	} else if (is("delay_until")) {
		uint32_t start = pros::millis();
		for (int i = 0; i < 4; i++) {
			printf("loop %u\n", now());
			pros::delay(i * 3);  // work that takes time; delay_until absorbs it
			pros::Task::delay_until(&start, 10);
		}
	} else if (is("priority")) {
		pros::Task low([] { pros::delay(10); printf("low %u\n", now()); }, TASK_PRIORITY_DEFAULT - 1,
		               TASK_STACK_DEPTH_DEFAULT, "low");
		pros::Task high([] { pros::delay(10); printf("high %u\n", now()); }, TASK_PRIORITY_DEFAULT + 1,
		                TASK_STACK_DEPTH_DEFAULT, "high");
		pros::delay(20);
	} else if (is("preempt")) {
		pros::Task child([] { printf("child runs\n"); }, TASK_PRIORITY_DEFAULT + 2, TASK_STACK_DEPTH_DEFAULT, "child");
		printf("parent continues\n");
		pros::Task same([] { printf("same priority runs\n"); }, "same");
		printf("parent before delay\n");
		pros::delay(1);
	} else if (is("mutex")) {
		static pros::Mutex m;
		pros::Task holder(
		    [] {
			    m.take();
			    printf("holder took %u\n", now());
			    pros::delay(50);
			    m.give();
		    },
		    "holder");
		pros::delay(10);
		bool got = m.take(20);
		printf("try for 20 ms: %d at %u\n", got, now());
		got = m.take();
		printf("wait: %d at %u\n", got, now());
		printf("take while held: %d\n", m.take(0));
		m.give();
		static pros::RecursiveMutex r;
		bool first = r.take(), second = r.take(), give1 = r.give(), give2 = r.give(), give3 = r.give();
		printf("recursive: %d %d %d %d %d\n", first, second, give1, give2, give3);
	} else if (is("notify")) {
		pros::Task waiter(
		    [] {
			    uint32_t v = pros::Task::notify_take(true, TIMEOUT_MAX);
			    printf("woken %u value %u\n", now(), v);
			    uint32_t w = pros::Task::notify_take(true, 15);
			    printf("timed out %u value %u\n", now(), w);
		    },
		    "waiter");
		pros::delay(30);
		waiter.notify();
		pros::delay(30);
	} else if (is("join")) {
		pros::Task worker([] { pros::delay(40); }, "worker");
		worker.join();
		printf("joined %u state %u\n", now(), worker.get_state());
	} else if (is("suspend")) {
		pros::Task counter(
		    [] {
			    while (true) {
				    printf("count %u\n", now());
				    pros::delay(10);
			    }
		    },
		    "counter");
		pros::delay(25);
		counter.suspend();
		pros::delay(30);
		counter.resume();
		pros::delay(5);
		counter.remove();
		printf("removed %u state %u\n", now(), counter.get_state());
		pros::delay(30);
	} else if (is("spin")) {
		while (pros::millis() < 25) {
		}
		printf("spun until %u\n", now());
	} else if (is("busy")) {
		volatile unsigned long x = 0;
		while (true) x = x + 1;
	} else if (is("crash")) {
		pros::Task crasher(
		    [] {
			    pros::delay(5);
			    printf("about to crash\n");
			    volatile int* p = nullptr;
			    *p = 1;
		    },
		    "crasher");
		pros::delay(100);
	} else if (is("throw")) {
		pros::delay(5);
		throw std::runtime_error("boom");
	} else if (is("console")) {
		printf("no newline yet...");
		pros::delay(5);
		printf(" done\n");
		std::cout << "cout line" << std::endl;
		fprintf(stderr, "stderr line\n");
	} else if (is("competition")) {
		pros::Task background(
		    [] {
			    while (true) {
				    printf("background %u\n", now());
				    pros::delay(100);
			    }
		    },
		    "background");
	}
}

static void device_scenarios() {
	if (is("drive")) {
		left_drive.move_velocity(300);
		right_drive.move_velocity(300);
		pros::delay(1000);
		printf("left %.0f right %.0f\n", left_drive.get_position(), right_drive.get_position());
		printf("rotation %d\n", pros::Rotation(11).get_position());
		printf("reversed rotation %d\n", pros::Rotation(-11).get_position());
		left_drive.brake();
		right_drive.brake();
	} else if (is("zero")) {
		pros::Motor m(1);
		m.move_absolute(100, 300);
		pros::delay(1000);
		printf("at %.0f\n", m.get_position());
		m.set_zero_position(80);
		printf("after set_zero_position(80): %.0f\n", m.get_position());
		m.move_absolute(100, 300);
		pros::delay(1000);
		printf("moved to %.0f target %.0f\n", m.get_position(), m.get_target_position());
		m.tare_position();
		printf("after tare: %.0f reversed object: %.0f\n", m.get_position(), pros::Motor(-1).get_position());
		m.set_encoder_units(pros::MotorUnits::rotations);
		m.move_relative(1, 300);
		pros::delay(1000);
		printf("rotations %.2f\n", m.get_position());
	} else if (is("gearing")) {
		pros::Motor m(1, pros::MotorGears::green);  // every cartridge is blue
		left_drive.set_gearing_all(pros::MotorGears::green);
		right_drive.set_gearing_all(pros::MotorGears::green);
		left_drive.move_velocity(100);
		right_drive.move_velocity(100);
		pros::delay(1000);
		printf("reported %.1f rpm\n", m.get_actual_velocity());
	} else if (is("group_brake")) {
		left_drive.set_brake_mode(pros::MotorBrake::hold);  // PROS 4: only the first motor
		right_drive.set_brake_mode_all(pros::E_MOTOR_BRAKE_BRAKE);
		printf("left modes %d %d %d\n", (int)left_drive.get_brake_mode(0), (int)left_drive.get_brake_mode(1),
		       (int)left_drive.get_brake_mode(2));
		pros::delay(10);
	} else if (is("imu")) {
		pros::Imu imu(10);
		printf("calibrating %d rotation %.1f\n", imu.is_calibrating(), imu.get_rotation());
		imu.set_heading(90);
		printf("heading %.1f rotation %.1f\n", imu.get_heading(), imu.get_rotation());
		uint32_t start = pros::millis();
		imu.reset(true);
		printf("reset took %u ms, heading %.1f\n", now() - start, imu.get_heading());
		imu.reset(false);
		errno = 0;
		double r = imu.get_rotation();
		printf("during calibration: %s errno %s\n", r == PROS_ERR_F ? "PROS_ERR_F" : "value",
		       errno == EAGAIN ? "EAGAIN" : "other");
	} else if (is("missing")) {
		errno = 0;
		int32_t result = pros::Motor(7).move(50);
		printf("move on empty port: %s errno %s\n", result == PROS_ERR ? "PROS_ERR" : "ok",
		       errno == ENODEV ? "ENODEV" : "other");
		errno = 0;
		double d = pros::Imu(1).get_heading();
		printf("imu on motor port: %s errno %s\n", d == PROS_ERR_F ? "PROS_ERR_F" : "value",
		       errno == ENODEV ? "ENODEV" : "other");
		pros::adi::Pneumatics piston('A', false);
		piston.extend();
		printf("piston extended %d\n", piston.is_extended());
		pros::delay(10);
	} else if (is("controller")) {
		pros::Controller master(pros::E_CONTROLLER_MASTER);
		for (int i = 0; i < 6; i++) {
			printf("t %u LY %d A %d new %d\n", now(), master.get_analog(ANALOG_LEFT_Y), master.get_digital(DIGITAL_A),
			       master.get_digital_new_press(DIGITAL_A));
			pros::delay(20);
		}
		master.print(0, 0, "hello %d", 7);
		pros::lcd::initialize();
		pros::lcd::print(3, "lcd %d", 3);
		pros::delay(10);
	} else if (is("disabled")) {
		left_drive.move(127);
		right_drive.move(127);
		pros::delay(500);
		printf("moved %.0f\n", left_drive.get_position());
	} else if (is("kitchen_sink")) {
		void kitchen_sink();
		kitchen_sink();
	} else if (is("lvgl")) {
		void lvgl_screen();
		lvgl_screen();
	} else if (is("seed")) {
		printf("seed %s\n", std::getenv("VEXSIM_SEED"));
	} else if (is("report_pose")) {
		vexsim::report_pose(12, 24, 90);
		pros::delay(10);
	}
}

void initialize() {
	scheduler_scenarios();
	device_scenarios();
}

void competition_initialize() {}

void disabled() {
	if (is("competition")) printf("disabled %u status %d\n", now(), pros::competition::get_status());
}

void autonomous() {
	if (is("competition")) {
		while (true) {
			printf("autonomous %u status %d\n", now(), pros::competition::get_status());
			pros::delay(100);
		}
	}
}

void opcontrol() {
	if (is("competition")) printf("opcontrol %u status %d\n", now(), pros::competition::get_status());
}
