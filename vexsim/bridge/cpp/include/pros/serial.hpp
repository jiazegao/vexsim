/* vexsim PROS 4 shim: pros::Serial (generic serial ports are not simulated: calls fail with ENODEV). */
#ifndef _PROS_SERIAL_HPP_
#define _PROS_SERIAL_HPP_

#include <cstdint>

#include "pros/device.hpp"
#include "pros/unsupported.h"

namespace pros {
inline namespace v5 {

class Serial : public Device {
	public:
	explicit Serial(std::uint8_t port, std::int32_t baudrate) : Device(port, DeviceType::serial) { (void)baudrate; }
	explicit Serial(std::uint8_t port) : Device(port, DeviceType::serial) {}
	virtual std::int32_t set_baudrate(std::int32_t) const { return vexsim_unsupported("pros::Serial"); }
	virtual std::int32_t flush() const { return vexsim_unsupported("pros::Serial"); }
	virtual std::int32_t get_read_avail() const { return 0; }
	virtual std::int32_t get_write_free() const { return 0; }
	virtual std::int32_t peek_byte() const { return vexsim_unsupported("pros::Serial"); }
	virtual std::int32_t read_byte() const { return vexsim_unsupported("pros::Serial"); }
	virtual std::int32_t read(std::uint8_t*, std::int32_t) const { return vexsim_unsupported("pros::Serial"); }
	virtual std::int32_t write_byte(std::uint8_t) const { return vexsim_unsupported("pros::Serial"); }
	virtual std::int32_t write(std::uint8_t*, std::int32_t) const { return vexsim_unsupported("pros::Serial"); }
};

namespace literals {
inline const pros::Serial operator""_ser(const unsigned long long int m) {
	return pros::Serial(static_cast<std::uint8_t>(m));
}
}  // namespace literals

}  // namespace v5
}  // namespace pros

#endif
