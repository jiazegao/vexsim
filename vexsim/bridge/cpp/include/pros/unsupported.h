/*
 * vexsim: devices the simulator doesn't model yet. Their calls fail the way
 * PROS does when nothing is plugged in (PROS_ERR, errno = ENODEV) and the
 * first call of each kind logs a note in the console.
 */
#ifndef _VEXSIM_UNSUPPORTED_H_
#define _VEXSIM_UNSUPPORTED_H_

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Logs "<what> is not simulated" once per name, sets errno = ENODEV, returns PROS_ERR. */
int32_t vexsim_unsupported(const char* what);

#ifdef __cplusplus
}
#endif

#endif
