// The LVGL stand-in: screen code (an auton selector, a logo) compiles and runs; nothing is drawn.
#include <cmath>

#include "liblvgl/lvgl.h"
#include "liblvgl/widgets/image/lv_image.h"
#include "main.h"

LV_IMAGE_DECLARE(test_logo);  // defined in logo.c, as LVGL's image converter writes it

static int clicks = 0;
static void on_click(lv_event_t*) { clicks++; }

void lvgl_screen() {
	lv_obj_t* button = lv_button_create(lv_screen_active());
	lv_obj_set_pos(button, 10, 20);
	lv_obj_set_size(button, 110, 200);
	lv_obj_add_event_cb(button, on_click, LV_EVENT_CLICKED, nullptr);
	lv_obj_set_style_bg_color(button, lv_color_hex(0xFF0000), LV_PART_MAIN);
	lv_obj_t* label = lv_label_create(button);
	lv_label_set_text_fmt(label, "auton %d", 3);
	lv_obj_t* image = lv_image_create(lv_screen_active());
	lv_obj_align(image, LV_ALIGN_CENTER, 0, 0);
	lv_image_set_src(image, &test_logo);
	printf("label \"%s\" on screen %u size %d x %d clicks %d\n", lv_label_get_text(label),
	       (unsigned)lv_obj_get_child_count(lv_screen_active()), (int)lv_obj_get_width(button),
	       (int)lv_obj_get_height(button), clicks);
	printf("logo %ux%u format 0x%x\n", (unsigned)test_logo.header.w, (unsigned)test_logo.header.h,
	       (unsigned)test_logo.header.cf);
	lv_obj_delete(button);
	printf("after delete %u\n", (unsigned)lv_obj_get_child_count(lv_screen_active()));
	printf("sqrtf %.1f sinf %.1f\n", std::sqrtf(16.0f), std::sinf(0.0f));  // newlib's <cmath>
}
