// vexsim robot host: a folder that stands in for the brain's SD card (vexsim run --sd FOLDER,
// which names it in VEXSIM_SD_DIR). With one, usd_is_installed() says a card is in, and a
// file the robot code opens under /usd/ (fopen, C++ file streams) opens in the folder.
//
// On Linux the robot host defines fopen and fopen64 itself, so every caller (libstdc++ too)
// comes here; on Windows the link wraps them (-Wl,--wrap=fopen,--wrap=fopen64), which
// reaches libstdc++ as well, since it's linked in statically there.

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <string>
#include <system_error>

#include "internal.hpp"

#if !defined(_WIN32)
#include <dlfcn.h>
#endif

namespace vexsim {

const char* usd_folder() {
	static const char* const folder = [] {
		const char* dir = std::getenv("VEXSIM_SD_DIR");
		if (dir == nullptr || *dir == '\0') return static_cast<const char*>(nullptr);
		std::error_code ignored;  // made if it isn't there; if that fails, files won't open
		std::filesystem::create_directories(dir, ignored);
		return dir;
	}();
	return folder;
}

std::string usd_path(const char* path) {
	const char* folder = usd_folder();
	if (path == nullptr) return "";
	if (folder == nullptr || std::strncmp(path, "/usd/", 5) != 0) return path;
	return std::string(folder) + "/" + (path + 5);
}

}  // namespace vexsim

#if defined(_WIN32)

extern "C" std::FILE* __real_fopen(const char* path, const char* mode);
extern "C" std::FILE* __real_fopen64(const char* path, const char* mode);

extern "C" std::FILE* __wrap_fopen(const char* path, const char* mode) {
	return __real_fopen(vexsim::usd_path(path).c_str(), mode);
}

extern "C" std::FILE* __wrap_fopen64(const char* path, const char* mode) {
	return __real_fopen64(vexsim::usd_path(path).c_str(), mode);
}

#else

using Open = std::FILE* (*)(const char*, const char*);

extern "C" std::FILE* fopen(const char* path, const char* mode) {
	static const Open real = reinterpret_cast<Open>(dlsym(RTLD_NEXT, "fopen"));
	return real(vexsim::usd_path(path).c_str(), mode);
}

#if defined(__GLIBC__)
extern "C" std::FILE* fopen64(const char* path, const char* mode) {
	static const Open real = reinterpret_cast<Open>(dlsym(RTLD_NEXT, "fopen64"));
	return real(vexsim::usd_path(path).c_str(), mode);
}
#endif

#endif
