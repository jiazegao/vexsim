/* vexsim PROS 4 shim: pros::screen. */
#ifndef _PROS_SCREEN_HPP_
#define _PROS_SCREEN_HPP_

#include <cstdint>
#include <string>

#include "pros/colors.hpp"
#include "pros/screen.h"

namespace pros {
namespace screen {

namespace {
template <typename T>
T convert_args(T arg) {
	return arg;
}
[[maybe_unused]] const char* convert_args(const std::string& arg) { return arg.c_str(); }
}  // namespace

inline std::uint32_t set_pen(pros::Color color) { return pros::c::screen_set_pen(static_cast<std::uint32_t>(color)); }
inline std::uint32_t set_pen(std::uint32_t color) { return pros::c::screen_set_pen(color); }
inline std::uint32_t set_eraser(pros::Color color) {
	return pros::c::screen_set_eraser(static_cast<std::uint32_t>(color));
}
inline std::uint32_t set_eraser(std::uint32_t color) { return pros::c::screen_set_eraser(color); }
inline std::uint32_t get_pen() { return pros::c::screen_get_pen(); }
inline std::uint32_t get_eraser() { return pros::c::screen_get_eraser(); }
inline std::uint32_t erase() { return pros::c::screen_erase(); }
inline std::uint32_t scroll(const std::int16_t start_line, const std::int16_t lines) {
	return pros::c::screen_scroll(start_line, lines);
}
inline std::uint32_t scroll_area(const std::int16_t x0, const std::int16_t y0, const std::int16_t x1,
                                 const std::int16_t y1, std::int16_t lines) {
	return pros::c::screen_scroll_area(x0, y0, x1, y1, lines);
}
inline std::uint32_t copy_area(const std::int16_t x0, const std::int16_t y0, const std::int16_t x1,
                               const std::int16_t y1, uint32_t* buf, const std::int32_t stride) {
	return pros::c::screen_copy_area(x0, y0, x1, y1, buf, stride);
}
inline std::uint32_t draw_pixel(const std::int16_t x, const std::int16_t y) { return pros::c::screen_draw_pixel(x, y); }
inline std::uint32_t erase_pixel(const std::int16_t x, const std::int16_t y) {
	return pros::c::screen_erase_pixel(x, y);
}
inline std::uint32_t draw_line(const std::int16_t x0, const std::int16_t y0, const std::int16_t x1,
                               const std::int16_t y1) {
	return pros::c::screen_draw_line(x0, y0, x1, y1);
}
inline std::uint32_t erase_line(const std::int16_t x0, const std::int16_t y0, const std::int16_t x1,
                                const std::int16_t y1) {
	return pros::c::screen_erase_line(x0, y0, x1, y1);
}
inline std::uint32_t draw_rect(const std::int16_t x0, const std::int16_t y0, const std::int16_t x1,
                               const std::int16_t y1) {
	return pros::c::screen_draw_rect(x0, y0, x1, y1);
}
inline std::uint32_t erase_rect(const std::int16_t x0, const std::int16_t y0, const std::int16_t x1,
                                const std::int16_t y1) {
	return pros::c::screen_erase_rect(x0, y0, x1, y1);
}
inline std::uint32_t fill_rect(const std::int16_t x0, const std::int16_t y0, const std::int16_t x1,
                               const std::int16_t y1) {
	return pros::c::screen_fill_rect(x0, y0, x1, y1);
}
inline std::uint32_t draw_circle(const std::int16_t x, const std::int16_t y, const std::int16_t radius) {
	return pros::c::screen_draw_circle(x, y, radius);
}
inline std::uint32_t erase_circle(const std::int16_t x, const std::int16_t y, const std::int16_t radius) {
	return pros::c::screen_erase_circle(x, y, radius);
}
inline std::uint32_t fill_circle(const std::int16_t x, const std::int16_t y, const std::int16_t radius) {
	return pros::c::screen_fill_circle(x, y, radius);
}
template <typename... Params>
void print(pros::text_format_e_t txt_fmt, const std::int16_t line, const char* text, Params... args) {
	pros::c::screen_print(txt_fmt, line, text, convert_args(args)...);
}
template <typename... Params>
void print(pros::text_format_e_t txt_fmt, const std::int16_t x, const std::int16_t y, const char* text,
           Params... args) {
	pros::c::screen_print_at(txt_fmt, x, y, text, convert_args(args)...);
}
inline screen_touch_status_s_t touch_status() { return pros::c::screen_touch_status(); }
inline std::uint32_t touch_callback(touch_event_cb_fn_t cb, last_touch_e_t event_type) {
	return pros::c::screen_touch_callback(cb, event_type);
}

}  // namespace screen
}  // namespace pros

#endif
