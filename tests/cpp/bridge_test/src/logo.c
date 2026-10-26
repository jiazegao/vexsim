/* An image as LVGL 9's converter writes it (C, designated initializers). */
#include "liblvgl/lvgl.h"

static const LV_ATTRIBUTE_MEM_ALIGN LV_ATTRIBUTE_LARGE_CONST uint8_t test_logo_map[] = {
    0xc3, 0x18, 0xc3, 0x18,
};

const lv_image_dsc_t test_logo = {
    .header.cf = LV_COLOR_FORMAT_RGB565,
    .header.magic = LV_IMAGE_HEADER_MAGIC,
    .header.w = 2,
    .header.h = 1,
    .data_size = 2 * 2,
    .data = test_logo_map,
};
