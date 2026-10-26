/*
 * vexsim PROS 4 shim: brain screen drawing. Text printed with screen_print
 * goes to the console; drawing calls are accepted and ignored (headless).
 */
#ifndef _PROS_SCREEN_H_
#define _PROS_SCREEN_H_

#include <stdbool.h>
#include <stdint.h>

#include "pros/colors.h"

#ifdef __cplusplus
extern "C" {
namespace pros {
#endif

typedef enum {
	E_TEXT_SMALL = 0,
	E_TEXT_MEDIUM,
	E_TEXT_LARGE,
	E_TEXT_MEDIUM_CENTER,
	E_TEXT_LARGE_CENTER
} text_format_e_t;

typedef enum {
	E_TOUCH_RELEASED = 0,
	E_TOUCH_PRESSED,
	E_TOUCH_HELD,
	E_TOUCH_ERROR
} last_touch_e_t;

typedef struct screen_touch_status_s {
	last_touch_e_t touch_status;
	int16_t x;
	int16_t y;
	int32_t press_count;
	int32_t release_count;
} screen_touch_status_s_t;

#ifdef PROS_USE_SIMPLE_NAMES
#ifdef __cplusplus
#define TEXT_SMALL pros::E_TEXT_SMALL
#define TEXT_MEDIUM pros::E_TEXT_MEDIUM
#define TEXT_LARGE pros::E_TEXT_LARGE
#define TEXT_MEDIUM_CENTER pros::E_TEXT_MEDIUM_CENTER
#define TEXT_LARGE_CENTER pros::E_TEXT_LARGE_CENTER
#define TOUCH_RELEASED pros::E_TOUCH_RELEASED
#define TOUCH_PRESSED pros::E_TOUCH_PRESSED
#define TOUCH_HELD pros::E_TOUCH_HELD
#else
#define TEXT_SMALL E_TEXT_SMALL
#define TEXT_MEDIUM E_TEXT_MEDIUM
#define TEXT_LARGE E_TEXT_LARGE
#define TEXT_MEDIUM_CENTER E_TEXT_MEDIUM_CENTER
#define TEXT_LARGE_CENTER E_TEXT_LARGE_CENTER
#define TOUCH_RELEASED E_TOUCH_RELEASED
#define TOUCH_PRESSED E_TOUCH_PRESSED
#define TOUCH_HELD E_TOUCH_HELD
#endif
#endif

typedef void (*touch_event_cb_fn_t)();

#ifdef __cplusplus
namespace c {
#endif

uint32_t screen_set_pen(uint32_t color);
uint32_t screen_set_eraser(uint32_t color);
uint32_t screen_get_pen(void);
uint32_t screen_get_eraser(void);
uint32_t screen_erase(void);
uint32_t screen_scroll(int16_t start_line, int16_t lines);
uint32_t screen_scroll_area(int16_t x0, int16_t y0, int16_t x1, int16_t y1, int16_t lines);
uint32_t screen_copy_area(int16_t x0, int16_t y0, int16_t x1, int16_t y1, uint32_t* buf, int32_t stride);
uint32_t screen_draw_pixel(int16_t x, int16_t y);
uint32_t screen_erase_pixel(int16_t x, int16_t y);
uint32_t screen_draw_line(int16_t x0, int16_t y0, int16_t x1, int16_t y1);
uint32_t screen_erase_line(int16_t x0, int16_t y0, int16_t x1, int16_t y1);
uint32_t screen_draw_rect(int16_t x0, int16_t y0, int16_t x1, int16_t y1);
uint32_t screen_erase_rect(int16_t x0, int16_t y0, int16_t x1, int16_t y1);
uint32_t screen_fill_rect(int16_t x0, int16_t y0, int16_t x1, int16_t y1);
uint32_t screen_draw_circle(int16_t x, int16_t y, int16_t radius);
uint32_t screen_erase_circle(int16_t x, int16_t y, int16_t radius);
uint32_t screen_fill_circle(int16_t x, int16_t y, int16_t radius);
uint32_t screen_print(text_format_e_t txt_fmt, const int16_t line, const char* text, ...);
uint32_t screen_print_at(text_format_e_t txt_fmt, const int16_t x, const int16_t y, const char* text, ...);
screen_touch_status_s_t screen_touch_status(void);
uint32_t screen_touch_callback(touch_event_cb_fn_t cb, last_touch_e_t event_type);

#ifdef __cplusplus
}  // namespace c
}  // namespace pros
}
#endif

#endif
