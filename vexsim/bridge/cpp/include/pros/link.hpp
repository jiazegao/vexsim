/* vexsim PROS 4 shim: pros::Link (VEXlink radios are not simulated: calls fail with ENODEV). */
#ifndef _PROS_LINK_HPP_
#define _PROS_LINK_HPP_

#include <cstdint>
#include <string>

#include "pros/device.hpp"
#include "pros/unsupported.h"

namespace pros {
inline namespace v5 {

typedef enum link_type_e { E_LINK_RECIEVER = 0, E_LINK_TRANSMITTER, E_LINK_RX = E_LINK_RECIEVER, E_LINK_TX = E_LINK_TRANSMITTER } link_type_e_t;

class Link : public Device {
	public:
	Link(const std::uint8_t port, const std::string link_id, link_type_e_t type, bool ov = false)
	    : Device(port, DeviceType::radio) {
		(void)link_id, (void)type, (void)ov;
	}
	std::uint32_t connected() { return 0; }
	std::uint32_t raw_receivable_size() { return 0; }
	std::uint32_t raw_transmittable_size() { return 0; }
	std::uint32_t transmit_raw(void*, std::uint16_t) { return vexsim_unsupported("pros::Link"); }
	std::uint32_t receive_raw(void*, std::uint16_t) { return vexsim_unsupported("pros::Link"); }
	std::uint32_t transmit(void*, std::uint16_t) { return vexsim_unsupported("pros::Link"); }
	std::uint32_t receive(void*, std::uint16_t) { return vexsim_unsupported("pros::Link"); }
	std::uint32_t clear_receive_buf() { return vexsim_unsupported("pros::Link"); }
};

}  // namespace v5
}  // namespace pros

#endif
