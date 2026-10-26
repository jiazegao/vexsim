/*
 * vexsim extras for robot code. On the robot this header doesn't exist, so
 * guard its use:
 *
 *   #if __has_include("vexsim/sim.hpp")
 *   #include "vexsim/sim.hpp"
 *   #endif
 *   ...
 *   #ifdef VEXSIM
 *   vexsim::report_pose(x, y, theta);
 *   #endif
 *
 * `vexsim build` defines VEXSIM=1.
 */
#ifndef _VEXSIM_SIM_HPP_
#define _VEXSIM_SIM_HPP_

extern "C" void vexsim_report_pose(double x_in, double y_in, double theta_deg);

namespace vexsim {

/*
 * Show your odometry's pose estimate in the viewer and telemetry (the
 * "estimated pose" trail). LemLib convention: inches, theta in degrees
 * clockwise from +y, so (0, 0, 90) faces +x.
 */
inline void report_pose(double x_in, double y_in, double theta_deg) { vexsim_report_pose(x_in, y_in, theta_deg); }

}  // namespace vexsim

#endif
