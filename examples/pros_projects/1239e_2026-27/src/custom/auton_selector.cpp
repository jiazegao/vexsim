
#include "custom/auton_selector.hpp"
#include <cstdio>  // vexsim
#include <cstdlib>  // vexsim
#include "liblvgl/widgets/image/lv_image.h"
#include "custom/auton.hpp"

// Button event callback functions
void toggle_color(lv_event_t* e) {
    allianceColor = (allianceColor == alliance_color::RED) ? alliance_color::BLUE : alliance_color::RED;
    lv_label_set_text(label_color, (allianceColor == alliance_color::RED) ? "Red" : "Blue");
    lv_obj_set_style_bg_color(btn_color, (allianceColor == alliance_color::RED) ? lv_color_hex(0xFF0000) : lv_color_hex(0x0000FF), LV_PART_MAIN);
}

void toggle_type(lv_event_t* e) {
    autonCount = (autonCount+1)%AutonCollection.size();
    lv_label_set_text(label_type, AutonCollection[autonCount].Name.data());
}

void toggle_skills (lv_event_t* e) {
    runningSkills = (runningSkills == true) ? false : true;
    lv_label_set_text(label_skills, (runningSkills == true) ? "SKILLS/Y" : "SKILLS/N");
    lv_obj_set_style_bg_color(btn_skills, (runningSkills == true) ? lv_color_hex(0x00FF00) : lv_color_hex(0xFF0000), LV_PART_MAIN);
}

void recalibrate(lv_event_t* e) {
    chassis.calibrate();
}

// Initialize autonomous selector GUI
void init_auton_selector() {
    btn_color = lv_button_create(lv_screen_active());
    lv_obj_set_pos(btn_color, 10, 20);
    lv_obj_set_size(btn_color, 110, 200);
    lv_obj_add_event_cb(btn_color, toggle_color, LV_EVENT_CLICKED, NULL);
    lv_obj_set_style_bg_color(btn_color, lv_color_hex(0x808080), LV_PART_MAIN); // Default to gray
    label_color = lv_label_create(btn_color);
    lv_label_set_text(label_color, "Select Color");
    
    btn_type = lv_button_create(lv_screen_active());
    lv_obj_set_pos(btn_type, 130, 20);
    lv_obj_set_size(btn_type, 110, 200);
    lv_obj_add_event_cb(btn_type, toggle_type, LV_EVENT_CLICKED, NULL);
    label_type = lv_label_create(btn_type);
    lv_label_set_text(label_type, "Select Type");

    btn_skills = lv_button_create(lv_screen_active());
    lv_obj_set_pos(btn_skills, 250, 20);
    lv_obj_set_size(btn_skills, 110, 200);
    lv_obj_add_event_cb(btn_skills, toggle_skills, LV_EVENT_CLICKED, NULL);
    lv_obj_set_style_bg_color(btn_skills, lv_color_hex(0x808080), LV_PART_MAIN); // Default to gray
    label_skills = lv_label_create(btn_skills);
    lv_label_set_text(label_skills, "Skills?");

    btn_recalibrate = lv_button_create(lv_screen_active());
    lv_obj_set_pos(btn_recalibrate, 370, 20);
    lv_obj_set_size(btn_recalibrate, 90, 200);
    lv_obj_add_event_cb(btn_recalibrate, recalibrate, LV_EVENT_CLICKED, NULL);
    label_recalibrate = lv_label_create(btn_recalibrate);
    lv_label_set_text(label_recalibrate, "Recal");

    lv_label_set_text(label_color, (allianceColor == alliance_color::RED) ? "Red" : "Blue");
    lv_obj_set_style_bg_color(btn_color, (allianceColor == alliance_color::RED) ? lv_color_hex(0xFF0000) : lv_color_hex(0x0000FF), LV_PART_MAIN);
    lv_label_set_text(label_type, AutonCollection[autonCount].Name.data());
    lv_label_set_text(label_skills, (runningSkills) ? "SKILLS/Y" : "SKILLS/N");
    lv_obj_set_style_bg_color(btn_skills, (runningSkills == true) ? lv_color_hex(0x00FF00) : lv_color_hex(0xFF0000), LV_PART_MAIN);
}

// Call the according autonomous
void runAuton() {
#ifdef VEXSIM
    // vexsim: nobody taps the simulated brain screen, so the routine comes from the
    // VEXSIM_AUTON environment variable (vexsim run --env VEXSIM_AUTON="Left 40").
    if (const char* name = std::getenv("VEXSIM_AUTON")) {
        // "startMcl x,y,theta,front,left,back,right" only starts MCL, as a routine would,
        // for replaying a real MCL log (examples/scripts/replay_1239e_mcl_log.py).
        float x, y, theta;
        int f, l, b, r;
        if (std::sscanf(name, "startMcl %f,%f,%f,%d,%d,%d,%d", &x, &y, &theta, &f, &l, &b, &r) == 7) {
            startMcl(x, y, theta, f, l, b, r);
            return;
        }
        bool found = false;
        for (int i = 0; i < (int)AutonCollection.size(); i++) {
            if (AutonCollection[i].Name == name) autonCount = i, found = true;
        }
        if (!found) std::printf("VEXSIM_AUTON: no routine named \"%s\"\n", name);
    }
#endif
    // Auton Selection
	if (runningSkills) {
		skills();
		return;
	}
    if (autonCount >= 0 && autonCount < (int)AutonCollection.size()) {
        AutonCollection[autonCount].AutonFunc();
    }
}
