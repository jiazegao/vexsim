// vexsim robot host: the LVGL stand-in (include/liblvgl/lvgl.h). Objects keep
// their place in the tree, text, flags and callbacks; nothing is drawn and no
// event ever fires, because the simulated brain has no screen to touch.
#include <cstdarg>
#include <cstdio>
#include <string>
#include <vector>

#include "liblvgl/lvgl.h"

struct _lv_event_dsc_t {
	lv_event_cb_t cb;
	lv_event_code_t filter;
	void* user_data;
};

struct _lv_obj_t {
	lv_obj_t* parent = nullptr;
	std::vector<lv_obj_t*> children;
	std::vector<_lv_event_dsc_t*> events;
	std::string text;
	const void* image = nullptr;
	int32_t x = 0, y = 0, w = 0, h = 0;
	lv_obj_flag_t flags = 0;
	lv_state_t state = LV_STATE_DEFAULT;
	void* user_data = nullptr;
};

struct _lv_event_t {
	lv_obj_t* target;
	lv_obj_t* current_target;
	lv_event_code_t code;
	void* user_data;
	void* param;
};

struct _lv_timer_t {
	lv_timer_cb_t cb;
	uint32_t period;
	void* user_data;
	bool paused;
};

namespace {

lv_obj_t* screen() {
	static lv_obj_t* active = new lv_obj_t{.w = 480, .h = 240};
	return active;
}

lv_obj_t*& active_screen() {
	static lv_obj_t* active = screen();
	return active;
}

lv_obj_t* create(lv_obj_t* parent, lv_obj_flag_t flags = 0) {
	auto* obj = new lv_obj_t;
	obj->parent = parent;
	obj->flags = flags;
	if (parent) parent->children.push_back(obj);
	return obj;
}

void destroy(lv_obj_t* obj) {
	for (lv_obj_t* child : obj->children) {
		child->parent = nullptr;
		destroy(child);
	}
	for (auto* dsc : obj->events) delete dsc;
	delete obj;
}

}  // namespace

extern "C" {

lv_obj_t* lv_screen_active(void) { return active_screen(); }
lv_obj_t* lv_layer_top(void) {
	static lv_obj_t* layer = create(nullptr);
	return layer;
}
void lv_screen_load(lv_obj_t* screen) {
	if (screen) active_screen() = screen;
}
lv_obj_t* lv_obj_create(lv_obj_t* parent) {
	return create(parent, LV_OBJ_FLAG_CLICKABLE | LV_OBJ_FLAG_SCROLLABLE);
}
void lv_obj_delete(lv_obj_t* obj) {
	if (!obj || obj == screen()) return;
	if (obj->parent) {
		auto& siblings = obj->parent->children;
		for (auto it = siblings.begin(); it != siblings.end(); ++it) {
			if (*it == obj) {
				siblings.erase(it);
				break;
			}
		}
	}
	destroy(obj);
}
void lv_obj_clean(lv_obj_t* obj) {
	if (!obj) return;
	for (lv_obj_t* child : obj->children) {
		child->parent = nullptr;
		destroy(child);
	}
	obj->children.clear();
}
lv_obj_t* lv_obj_get_parent(const lv_obj_t* obj) { return obj ? obj->parent : nullptr; }
lv_obj_t* lv_obj_get_child(const lv_obj_t* obj, int32_t index) {
	if (!obj) return nullptr;
	int32_t n = static_cast<int32_t>(obj->children.size());
	if (index < 0) index += n;
	return index >= 0 && index < n ? obj->children[index] : nullptr;
}
uint32_t lv_obj_get_child_count(const lv_obj_t* obj) {
	return obj ? static_cast<uint32_t>(obj->children.size()) : 0;
}
void lv_obj_set_pos(lv_obj_t* obj, int32_t x, int32_t y) {
	if (obj) obj->x = x, obj->y = y;
}
void lv_obj_set_x(lv_obj_t* obj, int32_t x) {
	if (obj) obj->x = x;
}
void lv_obj_set_y(lv_obj_t* obj, int32_t y) {
	if (obj) obj->y = y;
}
void lv_obj_set_size(lv_obj_t* obj, int32_t w, int32_t h) {
	if (obj) obj->w = w, obj->h = h;
}
void lv_obj_set_width(lv_obj_t* obj, int32_t w) {
	if (obj) obj->w = w;
}
void lv_obj_set_height(lv_obj_t* obj, int32_t h) {
	if (obj) obj->h = h;
}
int32_t lv_obj_get_x(const lv_obj_t* obj) { return obj ? obj->x : 0; }
int32_t lv_obj_get_y(const lv_obj_t* obj) { return obj ? obj->y : 0; }
int32_t lv_obj_get_width(const lv_obj_t* obj) { return obj ? obj->w : 0; }
int32_t lv_obj_get_height(const lv_obj_t* obj) { return obj ? obj->h : 0; }
void lv_obj_set_align(lv_obj_t*, lv_align_t) {}
void lv_obj_align(lv_obj_t* obj, lv_align_t, int32_t x_ofs, int32_t y_ofs) {
	lv_obj_set_pos(obj, x_ofs, y_ofs);
}
void lv_obj_align_to(lv_obj_t* obj, const lv_obj_t*, lv_align_t, int32_t x_ofs, int32_t y_ofs) {
	lv_obj_set_pos(obj, x_ofs, y_ofs);
}
void lv_obj_center(lv_obj_t* obj) { lv_obj_set_pos(obj, 0, 0); }
void lv_obj_add_flag(lv_obj_t* obj, lv_obj_flag_t f) {
	if (obj) obj->flags |= f;
}
void lv_obj_remove_flag(lv_obj_t* obj, lv_obj_flag_t f) {
	if (obj) obj->flags &= ~f;
}
bool lv_obj_has_flag(const lv_obj_t* obj, lv_obj_flag_t f) { return obj && (obj->flags & f) == f; }
void lv_obj_add_state(lv_obj_t* obj, lv_state_t state) {
	if (obj) obj->state |= state;
}
void lv_obj_remove_state(lv_obj_t* obj, lv_state_t state) {
	if (obj) obj->state &= ~state;
}
bool lv_obj_has_state(const lv_obj_t* obj, lv_state_t state) {
	return obj && (obj->state & state) == state;
}
void lv_obj_set_user_data(lv_obj_t* obj, void* user_data) {
	if (obj) obj->user_data = user_data;
}
void* lv_obj_get_user_data(lv_obj_t* obj) { return obj ? obj->user_data : nullptr; }
void lv_obj_invalidate(const lv_obj_t*) {}

void lv_obj_set_style_bg_color(lv_obj_t*, lv_color_t, lv_style_selector_t) {}
void lv_obj_set_style_bg_opa(lv_obj_t*, lv_opa_t, lv_style_selector_t) {}
void lv_obj_set_style_text_color(lv_obj_t*, lv_color_t, lv_style_selector_t) {}
void lv_obj_set_style_text_opa(lv_obj_t*, lv_opa_t, lv_style_selector_t) {}
void lv_obj_set_style_text_font(lv_obj_t*, const lv_font_t*, lv_style_selector_t) {}
void lv_obj_set_style_text_align(lv_obj_t*, lv_text_align_t, lv_style_selector_t) {}
void lv_obj_set_style_border_color(lv_obj_t*, lv_color_t, lv_style_selector_t) {}
void lv_obj_set_style_border_width(lv_obj_t*, int32_t, lv_style_selector_t) {}
void lv_obj_set_style_border_opa(lv_obj_t*, lv_opa_t, lv_style_selector_t) {}
void lv_obj_set_style_radius(lv_obj_t*, int32_t, lv_style_selector_t) {}
void lv_obj_set_style_pad_all(lv_obj_t*, int32_t, lv_style_selector_t) {}
void lv_obj_set_style_shadow_width(lv_obj_t*, int32_t, lv_style_selector_t) {}
void lv_obj_set_style_opa(lv_obj_t*, lv_opa_t, lv_style_selector_t) {}

lv_event_dsc_t* lv_obj_add_event_cb(lv_obj_t* obj, lv_event_cb_t event_cb, lv_event_code_t filter,
                                    void* user_data) {
	if (!obj) return nullptr;
	auto* dsc = new _lv_event_dsc_t{event_cb, filter, user_data};
	obj->events.push_back(dsc);
	return dsc;
}
lv_event_code_t lv_event_get_code(lv_event_t* e) { return e ? e->code : LV_EVENT_ALL; }
void* lv_event_get_target(lv_event_t* e) { return e ? e->target : nullptr; }
void* lv_event_get_current_target(lv_event_t* e) { return e ? e->current_target : nullptr; }
lv_obj_t* lv_event_get_target_obj(lv_event_t* e) { return e ? e->target : nullptr; }
void* lv_event_get_user_data(lv_event_t* e) { return e ? e->user_data : nullptr; }
void* lv_event_get_param(lv_event_t* e) { return e ? e->param : nullptr; }

lv_obj_t* lv_label_create(lv_obj_t* parent) {
	lv_obj_t* obj = create(parent);
	obj->text = "Text";
	return obj;
}
void lv_label_set_text(lv_obj_t* obj, const char* text) {
	if (obj) obj->text = text ? text : "";
}
void lv_label_set_text_fmt(lv_obj_t* obj, const char* fmt, ...) {
	if (!obj || !fmt) return;
	va_list args;
	va_start(args, fmt);
	va_list copy;
	va_copy(copy, args);
	int n = std::vsnprintf(nullptr, 0, fmt, copy);
	va_end(copy);
	std::string text(n > 0 ? n : 0, '\0');
	if (n > 0) std::vsnprintf(text.data(), text.size() + 1, fmt, args);
	va_end(args);
	obj->text = text;
}
void lv_label_set_text_static(lv_obj_t* obj, const char* text) { lv_label_set_text(obj, text); }
char* lv_label_get_text(const lv_obj_t* obj) {
	return obj ? const_cast<char*>(obj->text.c_str()) : nullptr;
}
lv_obj_t* lv_button_create(lv_obj_t* parent) { return create(parent, LV_OBJ_FLAG_CLICKABLE); }
lv_obj_t* lv_image_create(lv_obj_t* parent) { return create(parent); }
void lv_image_set_src(lv_obj_t* obj, const void* src) {
	if (obj) obj->image = src;
}

lv_timer_t* lv_timer_create(lv_timer_cb_t timer_xcb, uint32_t period, void* user_data) {
	return new lv_timer_t{timer_xcb, period, user_data, false};
}
void lv_timer_delete(lv_timer_t* timer) { delete timer; }
void lv_timer_pause(lv_timer_t* timer) {
	if (timer) timer->paused = true;
}
void lv_timer_resume(lv_timer_t* timer) {
	if (timer) timer->paused = false;
}
void lv_timer_set_period(lv_timer_t* timer, uint32_t period) {
	if (timer) timer->period = period;
}
void* lv_timer_get_user_data(lv_timer_t* timer) { return timer ? timer->user_data : nullptr; }
uint32_t lv_timer_handler(void) { return 5; }

}  // extern "C"
