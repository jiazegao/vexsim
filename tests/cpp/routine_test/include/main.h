/**
 * \file main.h
 *
 * Contains common definitions and header files used throughout your PROS
 * project.
 */

#ifndef _PROS_MAIN_H_
#define _PROS_MAIN_H_

/**
 * If defined, some commonly used enums will have preprocessor macros which give
 * a shorter, more convenient naming pattern (e.g. DIGITAL_A instead of
 * pros::E_CONTROLLER_DIGITAL_A).
 */
#define PROS_USE_SIMPLE_NAMES

/**
 * If defined, C++ literals will be available for use (e.g. 1_mtr).
 */
#define PROS_USE_LITERALS

#include "api.h"

/**
 * Prototypes for the competition control tasks are redefined here to ensure
 * that they can be called from user code (i.e. calling autonomous from a
 * button press in opcontrol() for testing purposes).
 */
#ifdef __cplusplus
extern "C" {
#endif
void autonomous(void);
void initialize(void);
void disabled(void);
void competition_initialize(void);
void opcontrol(void);
#ifdef __cplusplus
}
#endif

#endif  // _PROS_MAIN_H_
