/* vexsim PROS 4 shim: pros::Vision (not simulated yet: no objects, calls fail with ENODEV). */
#ifndef _PROS_VISION_HPP_
#define _PROS_VISION_HPP_

#include <cstdint>

#include "pros/device.hpp"
#include "pros/error.h"
#include "pros/unsupported.h"
#include "pros/vision.h"

namespace pros {
inline namespace v5 {

class Vision : public Device {
	public:
	explicit Vision(std::uint8_t port, vision_zero_e_t zero_point = E_VISION_ZERO_TOPLEFT)
	    : Device(port, DeviceType::vision) {
		(void)zero_point;
	}
	std::int32_t clear_led(void) const { return _fail(); }
	static vision_signature_s_t signature_from_utility(const std::int32_t id, const std::int32_t u_min,
	                                                   const std::int32_t u_max, const std::int32_t u_mean,
	                                                   const std::int32_t v_min, const std::int32_t v_max,
	                                                   const std::int32_t v_mean, const float range,
	                                                   const std::int32_t type) {
		vision_signature_s_t sig{};
		sig.id = static_cast<std::uint8_t>(id);
		sig.range = range;
		sig.u_min = u_min, sig.u_max = u_max, sig.u_mean = u_mean;
		sig.v_min = v_min, sig.v_max = v_max, sig.v_mean = v_mean;
		sig.type = static_cast<std::uint32_t>(type);
		return sig;
	}
	vision_color_code_t create_color_code(const std::uint32_t, const std::uint32_t, const std::uint32_t = 0,
	                                      const std::uint32_t = 0, const std::uint32_t = 0) const {
		return 0;
	}
	vision_object_s_t get_by_size(const std::uint32_t) const { return _none(); }
	vision_object_s_t get_by_sig(const std::uint32_t, const std::uint32_t) const { return _none(); }
	vision_object_s_t get_by_code(const std::uint32_t, const vision_color_code_t) const { return _none(); }
	std::int32_t get_exposure(void) const { return _fail(); }
	std::int32_t get_object_count(void) const { return _fail(); }
	vision_signature_s_t get_signature(const std::uint8_t signature_id) const {
		vision_signature_s_t sig{};
		sig.id = signature_id;
		return sig;
	}
	std::int32_t get_white_balance(void) const { return _fail(); }
	std::int32_t read_by_size(const std::uint32_t, const std::uint32_t, vision_object_s_t* const) const {
		return _fail();
	}
	std::int32_t read_by_sig(const std::uint32_t, const std::uint32_t, const std::uint32_t,
	                         vision_object_s_t* const) const {
		return _fail();
	}
	std::int32_t read_by_code(const std::uint32_t, const vision_color_code_t, const std::uint32_t,
	                          vision_object_s_t* const) const {
		return _fail();
	}
	std::int32_t print_signature(const vision_signature_s_t) { return _fail(); }
	std::int32_t set_auto_white_balance(const std::uint8_t) const { return _fail(); }
	std::int32_t set_exposure(const std::uint8_t) const { return _fail(); }
	std::int32_t set_led(const std::int32_t) const { return _fail(); }
	std::int32_t set_signature(const std::uint8_t, vision_signature_s_t* const) const { return _fail(); }
	std::int32_t set_white_balance(const std::int32_t) const { return _fail(); }
	std::int32_t set_zero_point(vision_zero_e_t) const { return _fail(); }
	std::int32_t set_wifi_mode(const std::uint8_t) const { return _fail(); }

	private:
	static std::int32_t _fail() { return vexsim_unsupported("pros::Vision"); }
	static vision_object_s_t _none() {
		vexsim_unsupported("pros::Vision");
		vision_object_s_t obj{};
		obj.signature = VISION_OBJECT_ERR_SIG;
		return obj;
	}
};

}  // namespace v5
}  // namespace pros

#endif
