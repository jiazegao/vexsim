// vexsim robot host: shared declarations between the scheduler, the device
// layer and the protocol loop. Not visible to robot code.
#pragma once

#include <condition_variable>
#include <cstdint>
#include <string>
#include <vector>

namespace vexsim {

constexpr std::uint64_t NEVER = UINT64_MAX;

enum class TaskState { ready, running, blocked, suspended, deleted };
enum class Wait { none, delay, mutex, notify, join };

struct SimMutex;

// One PROS task. Never freed, so task handles stay valid forever (as in PROS,
// where a deleted task's handle reads as E_TASK_STATE_DELETED).
struct Tcb {
	std::uint32_t id = 0;
	std::string name;
	std::uint32_t priority = 8;
	TaskState state = TaskState::ready;
	Wait wait = Wait::none;
	std::uint64_t wake_us = NEVER;  // when a delay or a timed wait ends
	std::uint64_t seq = 0;          // ready-queue order within a priority
	SimMutex* waiting_on = nullptr;
	Tcb* joining = nullptr;
	bool timed_out = false;
	std::uint32_t notify_value = 0;
	bool notify_pending = false;
	std::uint32_t spin = 0;  // PROS calls since the task last blocked
	std::condition_variable cv;
	void (*fn)(void*) = nullptr;
	void* arg = nullptr;
	// a task the route runner follows (vexsim_follow_tasks): LemLib's async motions
	bool followed = false;
	bool follow_ended = false;  // its end was reported
	std::uint32_t follow_serial = 0;
};

struct SimMutex {
	Tcb* owner = nullptr;
	std::uint32_t count = 0;
	bool recursive = false;
	std::vector<Tcb*> waiters;  // highest priority first, then FIFO
};

// --- scheduler (scheduler.cpp) ---------------------------------------------------------
void sched_configure(std::uint32_t spin_calls_per_ms, std::uint32_t busy_timeout_ms);
std::uint64_t sched_now_us();
// Advance to `now_us` and make every task due by then ready.
void sched_wake(std::uint64_t now_us);
// Run ready tasks until all are blocked. Returns the next time a task needs to run, or NEVER.
std::uint64_t sched_run();
// Start a competition function as the competition task, deleting the previous one.
void sched_start_competition_task(void (*fn)(), const char* task_name, std::uint32_t serial);
Tcb* current_task();
// Every PROS API call: a task that makes many calls without blocking is charged
// simulated time (one tick per `spin_calls_per_ms` calls), as a busy loop would be.
void api_call();

// --- host (host.cpp) -------------------------------------------------------------------
// Queue a protocol message for the current reply. Only the baton holder calls it.
void host_emit(const std::string& line);
void host_warn_once(const std::string& key, const std::string& message);
void host_drain_console();
[[noreturn]] void host_busy(const Tcb* task, double seconds);
// An exception escaped a task: report it as a crash (on the V5 it would end the program).
[[noreturn]] void host_uncaught_exception(const char* what);

// --- devices (devices.cpp) -------------------------------------------------------------
void devices_register(int port, const std::string& kind, const std::string& detail);
void devices_ready();
bool devices_reading(const char* line);  // false if not a reading line
void devices_set_competition(std::uint8_t status);
void devices_flush_commands();  // emit pending motor commands into the reply
void devices_poll_pose();       // report a library's odometry pose (LemLib), if it has one

}  // namespace vexsim
