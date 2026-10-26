/*
 * Stand-in for the PROS SDK's api.h, which `pros conductor` copies into every
 * project. `vexsim build` must use its own PROS shim instead, so including
 * this file is an error.
 */
#error "vexsim build used the project's include/api.h instead of the vexsim PROS shim"
