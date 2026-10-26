/*
 * vexsim: a stand-in for LVGL 9 (liblvgl), the graphics library behind the
 * V5 brain's touch screen.
 *
 * The simulator has no brain screen, so nothing is drawn and nobody touches
 * it: objects exist and keep their text and flags, event callbacks are stored
 * but never fire, and timers never run. That is enough for the usual screen
 * code (auton selectors, logos, status labels) to compile and run alongside
 * the robot code. Covered: objects, screens, labels, buttons, images, events,
 * timers and the common style setters. Code that calls anything else fails to
 * compile; add the function here (and in runtime/lvgl.cpp).
 */
#ifndef _VEXSIM_LIBLVGL_LVGL_H_
#define _VEXSIM_LIBLVGL_LVGL_H_

#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define LVGL_VERSION_MAJOR 9
#define LVGL_VERSION_MINOR 2
#define LVGL_VERSION_PATCH 0

#ifndef LV_ATTRIBUTE_LARGE_CONST
#define LV_ATTRIBUTE_LARGE_CONST
#endif
#ifndef LV_ATTRIBUTE_MEM_ALIGN
#define LV_ATTRIBUTE_MEM_ALIGN
#endif

typedef struct _lv_obj_t lv_obj_t;
typedef struct _lv_event_t lv_event_t;
typedef struct _lv_event_dsc_t lv_event_dsc_t;
typedef struct _lv_timer_t lv_timer_t;
typedef struct _lv_font_t lv_font_t;

typedef int32_t lv_coord_t;
typedef uint8_t lv_opa_t;
typedef uint32_t lv_part_t;
typedef uint32_t lv_state_t;
typedef uint32_t lv_style_selector_t;
typedef uint32_t lv_obj_flag_t;

typedef struct {
	uint8_t blue;
	uint8_t green;
	uint8_t red;
} lv_color_t;

static inline lv_color_t lv_color_make(uint8_t r, uint8_t g, uint8_t b) {
	lv_color_t c;
	c.blue = b;
	c.green = g;
	c.red = r;
	return c;
}
static inline lv_color_t lv_color_hex(uint32_t c) {
	return lv_color_make((uint8_t)(c >> 16), (uint8_t)(c >> 8), (uint8_t)c);
}
static inline lv_color_t lv_color_hex3(uint32_t c) {
	return lv_color_make((uint8_t)(((c >> 8) & 0xF) * 17), (uint8_t)(((c >> 4) & 0xF) * 17),
	                     (uint8_t)((c & 0xF) * 17));
}
static inline lv_color_t lv_color_white(void) { return lv_color_make(255, 255, 255); }
static inline lv_color_t lv_color_black(void) { return lv_color_make(0, 0, 0); }

enum {
	LV_OPA_TRANSP = 0,
	LV_OPA_0 = 0,
	LV_OPA_10 = 25,
	LV_OPA_20 = 51,
	LV_OPA_30 = 76,
	LV_OPA_40 = 102,
	LV_OPA_50 = 127,
	LV_OPA_60 = 153,
	LV_OPA_70 = 178,
	LV_OPA_80 = 204,
	LV_OPA_90 = 229,
	LV_OPA_100 = 255,
	LV_OPA_COVER = 255,
};

enum {
	LV_PART_MAIN = 0x000000,
	LV_PART_SCROLLBAR = 0x010000,
	LV_PART_INDICATOR = 0x020000,
	LV_PART_KNOB = 0x030000,
	LV_PART_SELECTED = 0x040000,
	LV_PART_ITEMS = 0x050000,
	LV_PART_CURSOR = 0x060000,
	LV_PART_ANY = 0x0F0000,
};

enum {
	LV_STATE_DEFAULT = 0x0000,
	LV_STATE_CHECKED = 0x0001,
	LV_STATE_FOCUSED = 0x0002,
	LV_STATE_FOCUS_KEY = 0x0004,
	LV_STATE_EDITED = 0x0008,
	LV_STATE_HOVERED = 0x0010,
	LV_STATE_PRESSED = 0x0020,
	LV_STATE_SCROLLED = 0x0040,
	LV_STATE_DISABLED = 0x0080,
	LV_STATE_ANY = 0xFFFF,
};

enum {
	LV_OBJ_FLAG_HIDDEN = 1u << 0,
	LV_OBJ_FLAG_CLICKABLE = 1u << 1,
	LV_OBJ_FLAG_CLICK_FOCUSABLE = 1u << 2,
	LV_OBJ_FLAG_CHECKABLE = 1u << 3,
	LV_OBJ_FLAG_SCROLLABLE = 1u << 4,
};

typedef enum {
	LV_ALIGN_DEFAULT = 0,
	LV_ALIGN_TOP_LEFT,
	LV_ALIGN_TOP_MID,
	LV_ALIGN_TOP_RIGHT,
	LV_ALIGN_BOTTOM_LEFT,
	LV_ALIGN_BOTTOM_MID,
	LV_ALIGN_BOTTOM_RIGHT,
	LV_ALIGN_LEFT_MID,
	LV_ALIGN_RIGHT_MID,
	LV_ALIGN_CENTER,
	LV_ALIGN_OUT_TOP_LEFT,
	LV_ALIGN_OUT_TOP_MID,
	LV_ALIGN_OUT_TOP_RIGHT,
	LV_ALIGN_OUT_BOTTOM_LEFT,
	LV_ALIGN_OUT_BOTTOM_MID,
	LV_ALIGN_OUT_BOTTOM_RIGHT,
	LV_ALIGN_OUT_LEFT_TOP,
	LV_ALIGN_OUT_LEFT_MID,
	LV_ALIGN_OUT_LEFT_BOTTOM,
	LV_ALIGN_OUT_RIGHT_TOP,
	LV_ALIGN_OUT_RIGHT_MID,
	LV_ALIGN_OUT_RIGHT_BOTTOM,
} lv_align_t;

typedef enum {
	LV_TEXT_ALIGN_AUTO = 0,
	LV_TEXT_ALIGN_LEFT,
	LV_TEXT_ALIGN_CENTER,
	LV_TEXT_ALIGN_RIGHT,
} lv_text_align_t;

typedef enum {
	LV_EVENT_ALL = 0,
	LV_EVENT_PRESSED,
	LV_EVENT_PRESSING,
	LV_EVENT_PRESS_LOST,
	LV_EVENT_SHORT_CLICKED,
	LV_EVENT_SINGLE_CLICKED,
	LV_EVENT_DOUBLE_CLICKED,
	LV_EVENT_TRIPLE_CLICKED,
	LV_EVENT_LONG_PRESSED,
	LV_EVENT_LONG_PRESSED_REPEAT,
	LV_EVENT_CLICKED,
	LV_EVENT_RELEASED,
	LV_EVENT_SCROLL_BEGIN,
	LV_EVENT_SCROLL_END,
	LV_EVENT_SCROLL,
	LV_EVENT_GESTURE,
	LV_EVENT_KEY,
	LV_EVENT_FOCUSED,
	LV_EVENT_DEFOCUSED,
	LV_EVENT_LEAVE,
	LV_EVENT_VALUE_CHANGED = 0x20,
	LV_EVENT_INSERT,
	LV_EVENT_REFRESH,
	LV_EVENT_READY,
	LV_EVENT_CANCEL,
	LV_EVENT_CREATE,
	LV_EVENT_DELETE,
	LV_EVENT_SIZE_CHANGED = 0x2A,
	LV_EVENT_SCREEN_LOADED = 0x33,
} lv_event_code_t;

typedef void (*lv_event_cb_t)(lv_event_t* e);
typedef void (*lv_timer_cb_t)(lv_timer_t* timer);

/* Images. LVGL's image converter writes lv_image_dsc_t definitions like this. */
typedef enum {
	LV_COLOR_FORMAT_UNKNOWN = 0x00,
	LV_COLOR_FORMAT_RAW = 0x01,
	LV_COLOR_FORMAT_RAW_ALPHA = 0x02,
	LV_COLOR_FORMAT_L8 = 0x06,
	LV_COLOR_FORMAT_I1 = 0x07,
	LV_COLOR_FORMAT_I2 = 0x08,
	LV_COLOR_FORMAT_I4 = 0x09,
	LV_COLOR_FORMAT_I8 = 0x0A,
	LV_COLOR_FORMAT_A8 = 0x0E,
	LV_COLOR_FORMAT_RGB888 = 0x0F,
	LV_COLOR_FORMAT_ARGB8888 = 0x10,
	LV_COLOR_FORMAT_XRGB8888 = 0x11,
	LV_COLOR_FORMAT_RGB565 = 0x12,
	LV_COLOR_FORMAT_ARGB8565 = 0x13,
	LV_COLOR_FORMAT_RGB565A8 = 0x14,
} lv_color_format_t;

#define LV_IMAGE_HEADER_MAGIC (0x19)

typedef struct {
	uint32_t magic : 8;
	uint32_t cf : 8;
	uint32_t flags : 16;
	uint32_t w : 16;
	uint32_t h : 16;
	uint32_t stride : 16;
	uint32_t reserved_2 : 16;
} lv_image_header_t;

typedef struct {
	lv_image_header_t header;
	uint32_t data_size;
	const uint8_t* data;
	const void* reserved;
} lv_image_dsc_t;

#define LV_IMAGE_DECLARE(var_name) extern const lv_image_dsc_t var_name

/* Screens and objects */
lv_obj_t* lv_screen_active(void);
lv_obj_t* lv_layer_top(void);
void lv_screen_load(lv_obj_t* screen);
lv_obj_t* lv_obj_create(lv_obj_t* parent);
void lv_obj_delete(lv_obj_t* obj);
void lv_obj_clean(lv_obj_t* obj);
lv_obj_t* lv_obj_get_parent(const lv_obj_t* obj);
lv_obj_t* lv_obj_get_child(const lv_obj_t* obj, int32_t index);
uint32_t lv_obj_get_child_count(const lv_obj_t* obj);
void lv_obj_set_pos(lv_obj_t* obj, int32_t x, int32_t y);
void lv_obj_set_x(lv_obj_t* obj, int32_t x);
void lv_obj_set_y(lv_obj_t* obj, int32_t y);
void lv_obj_set_size(lv_obj_t* obj, int32_t w, int32_t h);
void lv_obj_set_width(lv_obj_t* obj, int32_t w);
void lv_obj_set_height(lv_obj_t* obj, int32_t h);
int32_t lv_obj_get_x(const lv_obj_t* obj);
int32_t lv_obj_get_y(const lv_obj_t* obj);
int32_t lv_obj_get_width(const lv_obj_t* obj);
int32_t lv_obj_get_height(const lv_obj_t* obj);
void lv_obj_set_align(lv_obj_t* obj, lv_align_t align);
void lv_obj_align(lv_obj_t* obj, lv_align_t align, int32_t x_ofs, int32_t y_ofs);
void lv_obj_align_to(lv_obj_t* obj, const lv_obj_t* base, lv_align_t align, int32_t x_ofs,
                     int32_t y_ofs);
void lv_obj_center(lv_obj_t* obj);
void lv_obj_add_flag(lv_obj_t* obj, lv_obj_flag_t f);
void lv_obj_remove_flag(lv_obj_t* obj, lv_obj_flag_t f);
bool lv_obj_has_flag(const lv_obj_t* obj, lv_obj_flag_t f);
void lv_obj_add_state(lv_obj_t* obj, lv_state_t state);
void lv_obj_remove_state(lv_obj_t* obj, lv_state_t state);
bool lv_obj_has_state(const lv_obj_t* obj, lv_state_t state);
void lv_obj_set_user_data(lv_obj_t* obj, void* user_data);
void* lv_obj_get_user_data(lv_obj_t* obj);
void lv_obj_invalidate(const lv_obj_t* obj);

/* Styles: accepted and ignored */
void lv_obj_set_style_bg_color(lv_obj_t* obj, lv_color_t value, lv_style_selector_t selector);
void lv_obj_set_style_bg_opa(lv_obj_t* obj, lv_opa_t value, lv_style_selector_t selector);
void lv_obj_set_style_text_color(lv_obj_t* obj, lv_color_t value, lv_style_selector_t selector);
void lv_obj_set_style_text_opa(lv_obj_t* obj, lv_opa_t value, lv_style_selector_t selector);
void lv_obj_set_style_text_font(lv_obj_t* obj, const lv_font_t* value,
                                lv_style_selector_t selector);
void lv_obj_set_style_text_align(lv_obj_t* obj, lv_text_align_t value,
                                 lv_style_selector_t selector);
void lv_obj_set_style_border_color(lv_obj_t* obj, lv_color_t value, lv_style_selector_t selector);
void lv_obj_set_style_border_width(lv_obj_t* obj, int32_t value, lv_style_selector_t selector);
void lv_obj_set_style_border_opa(lv_obj_t* obj, lv_opa_t value, lv_style_selector_t selector);
void lv_obj_set_style_radius(lv_obj_t* obj, int32_t value, lv_style_selector_t selector);
void lv_obj_set_style_pad_all(lv_obj_t* obj, int32_t value, lv_style_selector_t selector);
void lv_obj_set_style_shadow_width(lv_obj_t* obj, int32_t value, lv_style_selector_t selector);
void lv_obj_set_style_opa(lv_obj_t* obj, lv_opa_t value, lv_style_selector_t selector);

/* Events: callbacks are kept, but nothing presses the (missing) screen */
lv_event_dsc_t* lv_obj_add_event_cb(lv_obj_t* obj, lv_event_cb_t event_cb, lv_event_code_t filter,
                                    void* user_data);
lv_event_code_t lv_event_get_code(lv_event_t* e);
void* lv_event_get_target(lv_event_t* e);
void* lv_event_get_current_target(lv_event_t* e);
lv_obj_t* lv_event_get_target_obj(lv_event_t* e);
void* lv_event_get_user_data(lv_event_t* e);
void* lv_event_get_param(lv_event_t* e);

/* Widgets */
lv_obj_t* lv_label_create(lv_obj_t* parent);
void lv_label_set_text(lv_obj_t* obj, const char* text);
void lv_label_set_text_fmt(lv_obj_t* obj, const char* fmt, ...);
void lv_label_set_text_static(lv_obj_t* obj, const char* text);
char* lv_label_get_text(const lv_obj_t* obj);
lv_obj_t* lv_button_create(lv_obj_t* parent);
lv_obj_t* lv_image_create(lv_obj_t* parent);
void lv_image_set_src(lv_obj_t* obj, const void* src);

/* Timers: created, never run */
lv_timer_t* lv_timer_create(lv_timer_cb_t timer_xcb, uint32_t period, void* user_data);
void lv_timer_delete(lv_timer_t* timer);
void lv_timer_pause(lv_timer_t* timer);
void lv_timer_resume(lv_timer_t* timer);
void lv_timer_set_period(lv_timer_t* timer, uint32_t period);
void* lv_timer_get_user_data(lv_timer_t* timer);
uint32_t lv_timer_handler(void);

#ifdef __cplusplus
}
#endif

#endif
