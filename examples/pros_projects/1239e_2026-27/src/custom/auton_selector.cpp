
#include "custom/auton_selector.hpp"
#include <cstdio>  // vexsim
#include <cstdlib>  // vexsim
#include <string>  // vexsim
#include "liblvgl/widgets/image/lv_image.h"
#include "custom/auton.hpp"
#include "vexsim_log.hpp"

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

// vexsim's logger (vexsim_log.hpp): the routine's log, by its name, to the SD card (without
// a card nothing is logged, and initialize() rumbles the controller to say so).
static void startRoutineLog(std::string_view name) {
    if (pros::c::usd_is_installed()) vexsim_log::start(std::string(name).c_str());
}

// Call the according autonomous
void runAuton() {
#ifdef VEXSIM
    // vexsim: nobody taps the simulated brain screen, so the routine comes from the
    // VEXSIM_AUTON environment variable (vexsim run --env VEXSIM_AUTON="Left 40").
    if (const char* name = std::getenv("VEXSIM_AUTON")) {
        // "startMcl" only starts MCL, with no resets, where the run put the robot
        // (VEXSIM_START), for following a log (vexsim run --follow).
        float x, y, theta;
        const char* start = std::getenv("VEXSIM_START");
        if (std::string(name) == "startMcl" && start && std::sscanf(start, "%f,%f,%f", &x, &y, &theta) == 3) {
            startMcl(x, y, theta, false, false, false, false);
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
		startRoutineLog("Skills");
		skills();
		return;
	}
    if (autonCount >= 0 && autonCount < (int)AutonCollection.size()) {
        startRoutineLog(AutonCollection[autonCount].Name);
        AutonCollection[autonCount].AutonFunc();
    }
}
