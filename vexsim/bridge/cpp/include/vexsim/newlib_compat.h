/*
 * vexsim: functions the V5's C library (newlib) provides that PC C libraries
 * don't. `vexsim build` includes this before every source file.
 */
#ifndef _VEXSIM_NEWLIB_COMPAT_H_
#define _VEXSIM_NEWLIB_COMPAT_H_

#include <math.h>

#ifdef __cplusplus
extern "C++" {
inline double infinity(void) { return HUGE_VAL; }
inline float infinityf(void) { return HUGE_VALF; }
}
#else
static inline double infinity(void) { return HUGE_VAL; }
static inline float infinityf(void) { return HUGE_VALF; }
#endif

#endif
