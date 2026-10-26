/* vexsim PROS 4 shim: pros::Task, pros::Mutex and friends. */
#ifndef _PROS_RTOS_HPP_
#define _PROS_RTOS_HPP_

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <type_traits>

#include "pros/rtos.h"
#undef delay

namespace pros {
inline namespace rtos {

class Task {
	public:
	Task(task_fn_t function, void* parameters = nullptr, std::uint32_t prio = TASK_PRIORITY_DEFAULT,
	     std::uint16_t stack_depth = TASK_STACK_DEPTH_DEFAULT, const char* name = "")
	    : task(pros::c::task_create(function, parameters, prio, stack_depth, name)) {}
	Task(task_fn_t function, void* parameters, const char* name)
	    : Task(function, parameters, TASK_PRIORITY_DEFAULT, TASK_STACK_DEPTH_DEFAULT, name) {}

	template <class F>
	static task_t create(F&& function, std::uint32_t prio = TASK_PRIORITY_DEFAULT,
	                     std::uint16_t stack_depth = TASK_STACK_DEPTH_DEFAULT, const char* name = "") {
		static_assert(std::is_invocable_r_v<void, F>);
		return pros::c::task_create(
		    [](void* parameters) {
			    std::unique_ptr<std::function<void()>> ptr{static_cast<std::function<void()>*>(parameters)};
			    (*ptr)();
		    },
		    new std::function<void()>(std::forward<F>(function)), prio, stack_depth, name);
	}
	template <class F>
	static task_t create(F&& function, const char* name) {
		return Task::create(std::forward<F>(function), TASK_PRIORITY_DEFAULT, TASK_STACK_DEPTH_DEFAULT, name);
	}

	template <class F>
	explicit Task(F&& function, std::uint32_t prio = TASK_PRIORITY_DEFAULT,
	              std::uint16_t stack_depth = TASK_STACK_DEPTH_DEFAULT, const char* name = "")
	    : Task(
	          [](void* parameters) {
		          std::unique_ptr<std::function<void()>> ptr{static_cast<std::function<void()>*>(parameters)};
		          (*ptr)();
	          },
	          new std::function<void()>(std::forward<F>(function)), prio, stack_depth, name) {
		static_assert(std::is_invocable_r_v<void, F>);
	}
	template <class F>
	Task(F&& function, const char* name)
	    : Task(std::forward<F>(function), TASK_PRIORITY_DEFAULT, TASK_STACK_DEPTH_DEFAULT, name) {}

	explicit Task(task_t task) : task(task) {}
	static Task current() { return Task(pros::c::task_get_current()); }
	Task& operator=(task_t in) {
		task = in;
		return *this;
	}

	void remove() { pros::c::task_delete(task); }
	std::uint32_t get_priority() { return pros::c::task_get_priority(task); }
	void set_priority(std::uint32_t prio) { pros::c::task_set_priority(task, prio); }
	std::uint32_t get_state() { return pros::c::task_get_state(task); }
	void suspend() { pros::c::task_suspend(task); }
	void resume() { pros::c::task_resume(task); }
	const char* get_name() { return pros::c::task_get_name(task); }
	explicit operator task_t() { return task; }
	std::uint32_t notify() { return pros::c::task_notify(task); }
	void join() { pros::c::task_join(task); }
	std::uint32_t notify_ext(std::uint32_t value, notify_action_e_t action, std::uint32_t* prev_value) {
		return pros::c::task_notify_ext(task, value, action, prev_value);
	}
	static std::uint32_t notify_take(bool clear_on_exit, std::uint32_t timeout) {
		return pros::c::task_notify_take(clear_on_exit, timeout);
	}
	bool notify_clear() { return pros::c::task_notify_clear(task); }
	static void delay(const std::uint32_t milliseconds) { pros::c::task_delay(milliseconds); }
	static void delay_until(std::uint32_t* const prev_time, const std::uint32_t delta) {
		pros::c::task_delay_until(prev_time, delta);
	}
	static std::uint32_t get_count() { return pros::c::task_get_count(); }

	private:
	task_t task{};
};

struct Clock {
	using rep = std::uint32_t;
	using period = std::milli;
	using duration = std::chrono::duration<rep, period>;
	using time_point = std::chrono::time_point<Clock>;
	const bool is_steady = true;
	static time_point now() { return time_point{duration{pros::c::millis()}}; }
};

class Mutex {
	std::atomic<mutex_t> mutex{nullptr};
	mutex_t lazy_init() {
		mutex_t current = mutex.load();
		if (current) return current;
		mutex_t created = pros::c::mutex_create();
		if (mutex.compare_exchange_strong(current, created)) return created;
		pros::c::mutex_delete(created);
		return current;
	}

	public:
	constexpr Mutex() {
		if (!std::is_constant_evaluated()) lazy_init();
	}
	Mutex(const Mutex&) = delete;
	Mutex(Mutex&&) = delete;
	Mutex& operator=(const Mutex&) = delete;
	Mutex& operator=(Mutex&&) = delete;

	bool take() { return take(TIMEOUT_MAX); }
	bool take(std::uint32_t timeout) { return pros::c::mutex_take(lazy_init(), timeout); }
	bool give() { return pros::c::mutex_give(lazy_init()); }
	void lock() {
		while (!take(TIMEOUT_MAX)) {
		}
	}
	void unlock() { give(); }
	[[nodiscard]] bool try_lock() { return take(0); }
	template <typename Rep, typename Period>
	[[nodiscard]] bool try_lock_for(const std::chrono::duration<Rep, Period>& rel_time) {
		return take(std::chrono::duration_cast<Clock::duration>(rel_time).count());
	}
	template <typename Duration>
	bool try_lock_until(const std::chrono::time_point<Clock, Duration>& abs_time) {
		return take(std::max(static_cast<uint32_t>(0), (abs_time - Clock::now()).count()));
	}
	~Mutex() {
		// Like the PROS kernel's own globals, never freed: a task may still hold it.
	}
};

class RecursiveMutex {
	std::atomic<mutex_t> mutex{nullptr};
	mutex_t lazy_init() {
		mutex_t current = mutex.load();
		if (current) return current;
		mutex_t created = pros::c::mutex_recursive_create();
		if (mutex.compare_exchange_strong(current, created)) return created;
		pros::c::mutex_delete(created);
		return current;
	}

	public:
	constexpr RecursiveMutex() {
		if (!std::is_constant_evaluated()) lazy_init();
	}
	RecursiveMutex(const RecursiveMutex&) = delete;
	RecursiveMutex(RecursiveMutex&&) = delete;
	RecursiveMutex& operator=(const RecursiveMutex&) = delete;
	RecursiveMutex& operator=(RecursiveMutex&&) = delete;

	bool take() { return take(TIMEOUT_MAX); }
	bool take(std::uint32_t timeout) { return pros::c::mutex_recursive_take(lazy_init(), timeout); }
	bool give() { return pros::c::mutex_recursive_give(lazy_init()); }
	void lock() {
		while (!take(TIMEOUT_MAX)) {
		}
	}
	void unlock() { give(); }
	[[nodiscard]] bool try_lock() { return take(0); }
	template <typename Rep, typename Period>
	[[nodiscard]] bool try_lock_for(const std::chrono::duration<Rep, Period>& rel_time) {
		return take(std::chrono::duration_cast<Clock::duration>(rel_time).count());
	}
	template <typename Duration>
	bool try_lock_until(const std::chrono::time_point<Clock, Duration>& abs_time) {
		return take(std::max(static_cast<uint32_t>(0), (abs_time - Clock::now()).count()));
	}
	~RecursiveMutex() {}
};

template <typename Var>
class MutexVar;

template <typename Var>
class MutexVarLock {
	Mutex& mutex;
	Var& var;
	friend class MutexVar<Var>;
	constexpr MutexVarLock(Mutex& mutex, Var& var) : mutex(mutex), var(var) {}

	public:
	constexpr Var& operator*() const { return var; }
	constexpr Var* operator->() const { return &var; }
	~MutexVarLock() { mutex.unlock(); }
};

template <typename Var>
class MutexVar {
	Mutex mutex;
	Var var;

	public:
	template <typename... Args>
	MutexVar(Args&&... args) : mutex(), var(std::forward<Args>(args)...) {}
	std::optional<MutexVarLock<Var>> try_lock(std::uint32_t timeout) {
		if (mutex.take(timeout)) return {{mutex, var}};
		return {};
	}
	template <typename Rep, typename Period>
	std::optional<MutexVarLock<Var>> try_lock(const std::chrono::duration<Rep, Period>& rel_time) {
		return try_lock(std::chrono::duration_cast<Clock::duration>(rel_time).count());
	}
	MutexVarLock<Var> lock() {
		while (!mutex.take(TIMEOUT_MAX)) {
		}
		return {mutex, var};
	}
};

using pros::c::delay;
using pros::c::micros;
using pros::c::millis;

}  // namespace rtos
}  // namespace pros

#endif  // _PROS_RTOS_HPP_
