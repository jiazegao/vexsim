/*
 * vexsim: replaces LemLib's asset.hpp. On the V5, objcopy turns static/<file>
 * into symbols including _binary_static_<name>_size, whose *address* is the
 * size; that trick doesn't survive a PC's relocatable executables. `vexsim
 * build` generates the data and a size variable instead. ASSET(name) is used
 * exactly as with LemLib.
 */
#pragma once

#include <cstddef>
#include <cstdint>

#ifndef _ASSET_H_
#define _ASSET_H_

extern "C" {
typedef struct __attribute__((__packed__)) _asset {
	uint8_t* buf;
	size_t size;
} asset;
}

#define ASSET(x)                                                                                                       \
	extern "C" {                                                                                                       \
	extern uint8_t _binary_static_##x##_start[];                                                                       \
	extern const size_t _vexsim_asset_size_static_##x;                                                                 \
	static asset x = {_binary_static_##x##_start, _vexsim_asset_size_static_##x};                                      \
	}

#define ASSET_LIB(x)                                                                                                   \
	extern "C" {                                                                                                       \
	extern uint8_t _binary_static_lib_##x##_start[];                                                                   \
	extern const size_t _vexsim_asset_size_static_lib_##x;                                                             \
	static asset x = {_binary_static_lib_##x##_start, _vexsim_asset_size_static_lib_##x};                              \
	}

#endif  // _ASSET_H_
