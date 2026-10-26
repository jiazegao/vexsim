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

/* The C++ standard puts the float and long double math functions (std::sqrtf,
 * std::sinl, ...) in <cmath>. newlib's libstdc++ has them; libstdc++ before
 * g++ 14 doesn't. */
#if defined(__cplusplus) && defined(_GLIBCXX_RELEASE) && _GLIBCXX_RELEASE < 14
#define VEXSIM_MATH_FUNCTIONS(X)                                                         \
	X(acos) X(asin) X(atan) X(atan2) X(ceil) X(cos) X(cosh) X(exp) X(fabs) X(floor)       \
	X(fmod) X(frexp) X(ldexp) X(log) X(log10) X(modf) X(pow) X(sin) X(sinh) X(sqrt)       \
	X(tan) X(tanh) X(acosh) X(asinh) X(atanh) X(cbrt) X(copysign) X(erf) X(erfc) X(exp2) \
	X(expm1) X(fdim) X(fma) X(fmax) X(fmin) X(hypot) X(ilogb) X(lgamma) X(llrint)       \
	X(llround) X(log1p) X(log2) X(logb) X(lrint) X(lround) X(nan) X(nearbyint)          \
	X(nextafter) X(nexttoward) X(remainder) X(remquo) X(rint) X(round) X(scalbln)        \
	X(scalbn) X(tgamma) X(trunc)
#define VEXSIM_USING_FL(name) using ::name##f; using ::name##l;
namespace std {
VEXSIM_MATH_FUNCTIONS(VEXSIM_USING_FL)
}
#undef VEXSIM_USING_FL
#undef VEXSIM_MATH_FUNCTIONS
#endif

#endif
