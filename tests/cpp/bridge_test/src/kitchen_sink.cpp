// Compile coverage for the shim: one use of most of the PROS 4 API surface.
#include <mutex>
#include <vector>

#include "liblvgl/llemu.hpp"
#include "main.h"
#include "pros/apix.h"

using namespace pros::literals;

extern "C" int c_side_check(void);

void kitchen_sink() {
	auto m = 1_mtr;
	auto rm = 2_rmtr;
	auto imu = 10_imu;
	auto rot = 11_rot;
	auto dist = 13_dist;
	pros::Motor counts(3, pros::v5::MotorGears::blue, pros::v5::MotorUnits::counts);
	pros::MotorGroup group(std::vector<std::int8_t>{1, -2});
	group += counts;
	group.append(rm);
	group.erase_port(3);
	pros::AbstractMotor& abstract = group;
	abstract.move(0);
	group.set_reversed_all(false);
	std::cout << m << " " << imu << " " << rot << " " << dist << std::endl;
	printf("group ports %d %d %d\n", group.get_port(0), group.get_port(1), group.size());
	printf("counts per rev %.0f\n", counts.get_position() + 300.0 * (counts.get_gearing() == pros::MotorGears::blue));

	pros::Task lambda_task([] {}, "lambda");
	pros::Task c_task(+[](void*) {}, nullptr, "c-style");
	pros::Task::create([] {}, "created");
	pros::Mutex mutex;
	{ std::lock_guard<pros::Mutex> lock(mutex); }
	pros::MutexVar<int> shared(5);
	*shared.lock() += 1;
	(void)pros::Clock::now();
	pros::c::task_delay(0);
	pros::rtos::Task::delay(0);
	pros::delay(0);
	(void)pros::micros();

	pros::Controller partner(CONTROLLER_PARTNER);
	partner.print(0, 0, "%s", std::string("x"));
	partner.set_text(1, 0, std::string("y"));
	partner.rumble("-.");
	printf("partner connected %d\n", partner.is_connected());

	pros::screen::set_pen(pros::Color::red);
	pros::screen::set_pen(pros::c::COLOR_BLUE);
	pros::screen::print(TEXT_MEDIUM, 1, "screen %d", 1);
	pros::screen::fill_rect(0, 0, 10, 10);
	pros::lcd::initialize();
	pros::lcd::print(0, "%s", std::string("lcd"));

	pros::adi::DigitalOut out('B');
	out.set_value(true);
	pros::adi::Encoder encoder('C', 'D');
	pros::ADIDigitalIn button('E');
	pros::adi::Led led('F', 10);
	led.set_all(0xFF0000);
	led.update();
	pros::adi::Potentiometer pot('G');
	pros::adi::AnalogIn expander({2, 'A'});
	printf("adi %d %d %.0f %d\n", encoder.get_value(), button.get_value(), pot.get_angle(), expander.get_value());

	pros::Optical optical(5);
	pros::Gps gps(6);
	pros::Vision vision(8);
	pros::Link link(9, "id", pros::E_LINK_TX);
	pros::Serial serial(7, 115200);
	printf("unsupported %d %d %d %d\n", optical.get_proximity(), gps.get_position().x == PROS_ERR_F,
	       vision.get_object_count(), serial.flush());

	printf("battery %.0f%% comp %d usd %d\n", pros::battery::get_capacity(), pros::competition::is_connected(),
	       pros::usd::is_installed());
	pros::quaternion_s_t q = pros::Imu(10).get_quaternion();
	printf("imu q.w %.2f\n", q.w);
	printf("devices %zu motors %zu imus %zu\n", pros::Device::get_all_devices().size(),
	       pros::Motor::get_all_devices().size(), pros::Imu::get_all_devices().size());
	printf("c api %d\n", c_side_check());
}
