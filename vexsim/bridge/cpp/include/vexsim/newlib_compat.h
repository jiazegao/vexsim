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

/* glibc declares these too; MinGW's headers don't (older g++ knew them as builtins). */
#ifdef __MINGW32__
#ifndef isnanf
#define isnanf(x) __builtin_isnan((float)(x))
#endif
#ifndef isinff
#define isinff(x) __builtin_isinf((float)(x))
#endif
#ifndef finitef
#define finitef(x) __builtin_isfinite((float)(x))
#endif
#endif

#endif
