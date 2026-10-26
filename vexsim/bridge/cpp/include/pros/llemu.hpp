/* vexsim PROS 4 shim: pros::lcd. */
#ifndef _PROS_LLEMU_HPP_
#define _PROS_LLEMU_HPP_

#include <cstdint>
#include <string>

#include "pros/llemu.h"

namespace pros {
namespace lcd {

namespace {
template <typename T>
T convert_args(T arg) {
	return arg;
}
[[maybe_unused]] const char* convert_args(const std::string& arg) { return arg.c_str(); }
}  // namespace

using lcd_btn_cb_fn_t = void (*)(void);

inline bool is_initialized(void) { return pros::c::lcd_is_initialized(); }
inline bool initialize(void) { return pros::c::lcd_initialize(); }
inline bool shutdown(void) { return pros::c::lcd_shutdown(); }
template <typename... Params>
bool print(std::int16_t line, const char* fmt, Params... args) {
	return pros::c::lcd_print(line, fmt, convert_args(args)...);
}
inline bool set_text(std::int16_t line, std::string text) { return pros::c::lcd_set_text(line, text.c_str()); }
inline bool clear(void) { return pros::c::lcd_clear(); }
inline bool clear_line(std::int16_t line) { return pros::c::lcd_clear_line(line); }
inline void register_btn0_cb(lcd_btn_cb_fn_t cb) { pros::c::lcd_register_btn0_cb(cb); }
inline void register_btn1_cb(lcd_btn_cb_fn_t cb) { pros::c::lcd_register_btn1_cb(cb); }
inline void register_btn2_cb(lcd_btn_cb_fn_t cb) { pros::c::lcd_register_btn2_cb(cb); }
inline std::uint8_t read_buttons(void) { return pros::c::lcd_read_buttons(); }

}  // namespace lcd
}  // namespace pros

#endif
