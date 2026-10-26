// vexsim robot host: process setup and the protocol loop.
//
// The simulator starts this program with pipes on stdin/stdout. Before any
// robot code runs (even global constructors), the host moves the protocol to
// private file descriptors and points stdout/stderr at an internal pipe, so
// printf and std::cout from robot code become console lines and can't corrupt
// the protocol.
//
// Protocol (text lines): the simulator sends
//   INIT <spin_calls_per_ms> <busy_timeout_ms>, DEV <port> <kind> [cartridge] ..., GO
// and the host answers READY. Then, repeatedly:
//   [MODE <serial> <phase> <status bits>] [readings: m/i/r/d/c/b lines] RUN <time_us>
// and the host runs every due task until all are blocked, then answers with
// commands (M, B, L, I), console text (T), screens (LCD, CTRL), poses (P),
// warnings (E), finished competition functions (F <serial>) and finally
// W <next wake time in us, or -1>. STOP ends the process.
// Fatal problems end the process after a BUSY or CRASH line.

#include <atomic>
#include <cerrno>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <mutex>
#include <set>
#include <string>

#include <fcntl.h>

#include "internal.hpp"

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <io.h>
#include <windows.h>
#else
#include <unistd.h>
#endif

extern "C" {
void initialize(void);
void autonomous(void);
void opcontrol(void);
void disabled(void);
void competition_initialize(void);
}

namespace vexsim {
namespace {

int g_proto_in = -1;
int g_proto_out = -1;
int g_console_read = -1;
// The reply being built and the console pipe are shared by the task holding the baton
// (host_emit) and the host thread (draining the pipe while a task runs).
std::mutex g_out_mutex;
std::string g_reply;           // messages for the current reply
std::string g_console_partial;  // console text after the last newline
std::set<std::string>* g_warned;

#ifdef _WIN32
int sys_read(int fd, void* buf, unsigned n) { return _read(fd, buf, n); }
int sys_write(int fd, const void* buf, unsigned n) { return _write(fd, buf, n); }
#else
int sys_read(int fd, void* buf, unsigned n) { return static_cast<int>(read(fd, buf, n)); }
int sys_write(int fd, const void* buf, unsigned n) { return static_cast<int>(write(fd, buf, n)); }
#endif

void write_all(int fd, const char* data, std::size_t n) {
	while (n > 0) {
		int done = sys_write(fd, data, static_cast<unsigned>(n));
		if (done <= 0) {
			if (errno == EINTR) continue;
			std::_Exit(2);  // the simulator is gone
		}
		data += done;
		n -= static_cast<std::size_t>(done);
	}
}

void send(const std::string& text) { write_all(g_proto_out, text.data(), text.size()); }

// Bytes waiting in the console pipe, without blocking.
std::size_t console_available() {
#ifdef _WIN32
	DWORD avail = 0;
	HANDLE h = reinterpret_cast<HANDLE>(_get_osfhandle(g_console_read));
	if (!PeekNamedPipe(h, nullptr, 0, nullptr, &avail, nullptr)) return 0;
	return avail;
#else
	return 65536;  // the read end is non-blocking
#endif
}

void console_text(const char* data, std::size_t n) {
	for (std::size_t k = 0; k < n; k++) {
		char ch = data[k];
		if (ch == '\n') {
			g_reply += "T " + g_console_partial + "\n";
			g_console_partial.clear();
		} else if (ch != '\r') {
			g_console_partial += ch;
		}
	}
	if (g_console_partial.size() > 4000) {  // never hold an endless line back
		g_reply += "T " + g_console_partial + "\n";
		g_console_partial.clear();
	}
}

// Move console pipe contents into the reply. Call with g_out_mutex held.
void drain_locked() {
	if (g_console_read < 0) return;
	int saved_errno = errno;  // robot code may be about to read errno from the call that got here
	char buf[8192];
	for (;;) {
		std::size_t avail = console_available();
		if (avail == 0) break;
		int n = sys_read(g_console_read, buf, static_cast<unsigned>(avail < sizeof buf ? avail : sizeof buf));
		if (n <= 0) break;
		console_text(buf, static_cast<std::size_t>(n));
	}
	errno = saved_errno;
}

void setup_io() {
#ifdef _WIN32
	// No Windows Error Reporting dialogs: crashes are reported through the protocol (and
	// abort() through the SIGABRT handler, which exits before the C runtime says anything).
	SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
	g_proto_in = _dup(0);
	g_proto_out = _dup(1);
	_setmode(g_proto_in, _O_BINARY);
	_setmode(g_proto_out, _O_BINARY);
	int fds[2];
	if (_pipe(fds, 1 << 20, _O_BINARY) != 0) std::_Exit(2);
	_dup2(fds[1], 1);
	_dup2(fds[1], 2);
	g_console_read = fds[0];
	int null_fd = _open("NUL", _O_RDONLY);
	if (null_fd >= 0) _dup2(null_fd, 0);
#else
	g_proto_in = dup(0);
	g_proto_out = dup(1);
	int fds[2];
	if (pipe(fds) != 0) std::_Exit(2);
#ifdef F_SETPIPE_SZ
	fcntl(fds[1], F_SETPIPE_SZ, 1 << 20);
#endif
	fcntl(fds[0], F_SETFL, fcntl(fds[0], F_GETFL) | O_NONBLOCK);
	dup2(fds[1], 1);
	dup2(fds[1], 2);
	g_console_read = fds[0];
	int null_fd = open("/dev/null", O_RDONLY);
	if (null_fd >= 0) dup2(null_fd, 0);
#endif
	std::setvbuf(stdout, nullptr, _IONBF, 0);
	std::setvbuf(stderr, nullptr, _IONBF, 0);
}

const char* signal_name(int sig) {
	switch (sig) {
		case SIGSEGV:
			return "segmentation fault (invalid memory access)";
		case SIGFPE:
			return "arithmetic error (integer division by zero?)";
		case SIGILL:
			return "illegal instruction";
		case SIGABRT:
			return "abort (an uncaught exception or a failed assert?)";
		default:
			return "fatal signal";
	}
}

std::atomic<bool> g_crashing{false};

[[noreturn]] void crash(const char* what) {
	if (g_crashing.exchange(true)) std::_Exit(70);
	bool locked = g_out_mutex.try_lock();  // a crash inside host_emit already holds it
	drain_locked();
	if (!g_console_partial.empty()) g_reply += "T " + g_console_partial + "\n";
	const Tcb* t = current_task();
	g_reply += std::string("CRASH ") + (t ? t->name : std::string("(startup)")) + "\t" + what + "\n";
	send(g_reply);
	if (locked) g_out_mutex.unlock();
	std::_Exit(70);
}

void on_signal(int sig) { crash(signal_name(sig)); }

#ifdef _WIN32
LONG WINAPI on_exception(EXCEPTION_POINTERS* info) {
	switch (info->ExceptionRecord->ExceptionCode) {
		case EXCEPTION_ACCESS_VIOLATION:
			crash("segmentation fault (invalid memory access)");
		case EXCEPTION_INT_DIVIDE_BY_ZERO:
			crash("arithmetic error (integer division by zero?)");
		case EXCEPTION_STACK_OVERFLOW:
			crash("stack overflow (infinite recursion?)");
		case EXCEPTION_ILLEGAL_INSTRUCTION:
			crash("illegal instruction");
		default:
			crash("unhandled exception");
	}
}
#endif

// Runs before robot code's global constructors (default priority 65535).
__attribute__((constructor(101))) void early_init() {
	setup_io();
	g_warned = new std::set<std::string>();
	std::signal(SIGSEGV, on_signal);
	std::signal(SIGFPE, on_signal);
	std::signal(SIGILL, on_signal);
	std::signal(SIGABRT, on_signal);
#ifdef _WIN32
	SetUnhandledExceptionFilter(on_exception);
#endif
}

bool read_line(std::string& line) {
	static char buf[65536];
	static std::size_t start = 0, end = 0;
	line.clear();
	for (;;) {
		for (std::size_t k = start; k < end; k++) {
			if (buf[k] == '\n') {
				line.append(buf + start, k - start);
				start = k + 1;
				if (!line.empty() && line.back() == '\r') line.pop_back();
				return true;
			}
		}
		line.append(buf + start, end - start);
		start = end = 0;
		int n = sys_read(g_proto_in, buf, sizeof buf);
		if (n <= 0) {
			if (n < 0 && errno == EINTR) continue;
			return false;
		}
		end = static_cast<std::size_t>(n);
	}
}

struct Phase {
	const char* name;
	void (*fn)();
	const char* task_name;
};

const Phase kPhases[] = {
    {"initialize", initialize, "User Initialization (PROS)"},
    {"competition_initialize", competition_initialize, "User Comp. Init. (PROS)"},
    {"autonomous", autonomous, "User Autonomous (PROS)"},
    {"opcontrol", opcontrol, "User Operator Control (PROS)"},
    {"disabled", disabled, "User Disabled (PROS)"},
};

}  // namespace

namespace {
// Everything for the current reply, with the console drained first; clears it.
std::string take_reply() {
	std::lock_guard<std::mutex> lock(g_out_mutex);
	drain_locked();
	std::string out;
	out.swap(g_reply);
	return out;
}
}  // namespace

void host_emit(const std::string& line) {
	std::lock_guard<std::mutex> lock(g_out_mutex);
	drain_locked();  // console text printed before this message comes first
	g_reply += line;
	g_reply += '\n';
}

void host_warn_once(const std::string& key, const std::string& message) {
	if (!g_warned) g_warned = new std::set<std::string>();
	if (g_warned->insert(key).second) host_emit("E " + message);
}

void host_drain_console() {
	std::lock_guard<std::mutex> lock(g_out_mutex);
	drain_locked();
}

void host_busy(const Tcb* task, double seconds) {
	std::string reply = take_reply();
	if (!g_console_partial.empty()) reply += "T " + g_console_partial + "\n";
	char text[64];
	std::snprintf(text, sizeof text, "%.1f", seconds);
	reply += "BUSY " + (task ? task->name : std::string("?")) + "\t" + text + "\n";
	send(reply);
	std::_Exit(3);
}

}  // namespace vexsim

using namespace vexsim;

int main() {
	std::set_terminate([] {
		// Let the C++ runtime print the exception, then report it as a crash.
		if (auto e = std::current_exception()) {
			try {
				std::rethrow_exception(e);
			} catch (const std::exception& ex) {
				std::fprintf(stderr, "terminate called after throwing: %s\n", ex.what());
			} catch (...) {
				std::fprintf(stderr, "terminate called after throwing a non-standard exception\n");
			}
		}
		crash("uncaught C++ exception");
	});

	const Phase* pending_phase = nullptr;
	std::uint8_t pending_status = 0;
	std::uint32_t pending_serial = 0;
	std::string line;
	while (read_line(line)) {
		if (line.empty()) continue;
		if (devices_reading(line.c_str())) continue;
		char word[32] = {0};
		std::sscanf(line.c_str(), "%31s", word);
		std::string cmd = word;
		if (cmd == "RUN") {
			unsigned long long now = 0;
			std::sscanf(line.c_str() + 3, "%llu", &now);
			// Tasks due now become ready before a competition task started now, as when the
			// PROS daemon notices a mode change after the tick that woke them.
			sched_wake(now);
			if (pending_phase) {
				devices_set_competition(pending_status);
				sched_start_competition_task(pending_phase->fn, pending_phase->task_name, pending_serial);
				pending_phase = nullptr;
			}
			std::uint64_t next = sched_run();
			devices_flush_commands();
			std::string reply = take_reply();
			reply += next == NEVER ? std::string("W -1\n") : "W " + std::to_string(next) + "\n";
			send(reply);
		} else if (cmd == "MODE") {
			unsigned serial = 0, status = 0;
			char phase[40] = {0};
			std::sscanf(line.c_str() + 4, "%u %39s %u", &serial, phase, &status);
			pending_status = static_cast<std::uint8_t>(status);
			pending_serial = serial;
			for (const Phase& p : kPhases) {
				if (std::strcmp(p.name, phase) == 0) pending_phase = &p;
			}
		} else if (cmd == "DEV") {
			int port = 0;
			char kind[32] = {0}, detail[32] = {0};
			std::sscanf(line.c_str() + 3, "%d %31s %31s", &port, kind, detail);
			devices_register(port, kind, detail);
		} else if (cmd == "INIT") {
			unsigned spin = 1000, busy = 5000;
			std::sscanf(line.c_str() + 4, "%u %u", &spin, &busy);
			sched_configure(spin, busy);
		} else if (cmd == "GO") {
			devices_ready();
			send(take_reply() + "READY\n");  // with output from global constructors
		} else if (cmd == "STOP") {
			break;
		}
	}
	std::string rest = take_reply();
	if (!g_console_partial.empty()) rest += "T " + g_console_partial + "\n";
	send(rest);
	std::_Exit(0);  // tasks may still be parked; don't run destructors under them
}
