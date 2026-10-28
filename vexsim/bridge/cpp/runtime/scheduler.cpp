// vexsim robot host: lockstep task scheduler behind the PROS rtos API.
//
// Every PROS task is a host thread, but exactly one thread runs at a time: a
// task runs until it blocks (delay, mutex, notification), then hands the
// baton back to the host thread, which picks the next ready task by priority
// and then by the order tasks became ready, as FreeRTOS does on the V5. Time
// stands still while tasks run and only moves when the host is told to
// (RUN <time>), so a run is deterministic at any wall-clock speed.

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <exception>
#include <mutex>
#include <thread>

#include "internal.hpp"
#include "pros/rtos.h"

namespace vexsim {
namespace {

struct Sched {
	std::mutex m;
	std::condition_variable host_cv;
	Tcb* running = nullptr;  // the baton; nullptr while the host thread holds it
	std::vector<Tcb*> tasks;
	std::uint64_t now_us = 0;
	std::uint64_t seq = 0;
	std::uint32_t next_id = 1;
	std::uint32_t spin_limit = 1000;
	std::uint32_t busy_timeout_ms = 5000;
	Tcb* competition = nullptr;
};

Sched& S() {
	static Sched* s = new Sched();  // never destroyed: detached threads may outlive main
	return *s;
}

thread_local Tcb* t_current = nullptr;

// The tasks the route runner follows: those a task creates while it holds `mutex` (LemLib
// starts each async motion's task holding its chassis' motion mutex). Its callbacks run in
// the task that creates one, and in the one that ends (or the task deleting it).
struct Follow {
	SimMutex* mutex = nullptr;
	void (*started)(std::uint32_t) = nullptr;
	void (*ended)(std::uint32_t) = nullptr;
	std::uint32_t count = 0;
};

Follow& F() {
	static Follow f;
	return f;
}

// Owner of a mutex taken outside any task (from a global constructor).
Tcb g_no_task;

using Lock = std::unique_lock<std::mutex>;

void make_ready(Tcb* t) {
	t->state = TaskState::ready;
	t->wait = Wait::none;
	t->wake_us = NEVER;
	t->seq = ++S().seq;
}

Tcb* pick_ready() {
	Tcb* best = nullptr;
	for (Tcb* t : S().tasks) {
		if (t->state != TaskState::ready) continue;
		if (!best || t->priority > best->priority || (t->priority == best->priority && t->seq < best->seq)) best = t;
	}
	return best;
}

// Hand the baton back to the host and sleep until it is handed to us again.
// A task deleted while parked is never handed the baton again.
void park(Lock& lk) {
	Tcb* self = t_current;
	S().running = nullptr;
	S().host_cv.notify_one();
	self->cv.wait(lk, [self] { return S().running == self; });
	self->spin = 0;
}

void block(Tcb* self, Wait wait, std::uint64_t wake_us) {
	self->state = TaskState::blocked;
	self->wait = wait;
	self->wake_us = wake_us;
	self->timed_out = false;
}

std::uint64_t timeout_to_wake(std::uint32_t timeout_ms) {
	return timeout_ms == TIMEOUT_MAX ? NEVER : S().now_us + std::uint64_t(timeout_ms) * 1000;
}

void remove_waiter(Tcb* t) {
	if (t->waiting_on) {
		auto& w = t->waiting_on->waiters;
		w.erase(std::remove(w.begin(), w.end(), t), w.end());
		t->waiting_on = nullptr;
	}
}

// FreeRTOS switches as soon as a higher-priority task becomes ready.
void maybe_preempt(Lock& lk) {
	Tcb* self = t_current;
	if (!self) return;
	Tcb* best = pick_ready();
	if (best && best->priority > self->priority) {
		make_ready(self);
		park(lk);
	}
}

void wake_joiners(Tcb* t) {
	for (Tcb* other : S().tasks) {
		if (other->state == TaskState::blocked && other->wait == Wait::join && other->joining == t) {
			other->joining = nullptr;
			make_ready(other);
		}
	}
}

void mark_deleted(Tcb* t) {
	remove_waiter(t);
	t->state = TaskState::deleted;
	t->wait = Wait::none;
	wake_joiners(t);
}

// A followed task's end, said once; called without the scheduler's lock (the callback prints).
void report_end(Tcb* t) {
	if (!t->followed || t->follow_ended) return;
	t->follow_ended = true;
	if (F().ended) F().ended(t->follow_serial);
}

void thread_main(Tcb* t) {
	{
		Lock lk(S().m);
		t->cv.wait(lk, [t] { return S().running == t; });
	}
	t_current = t;
	// Caught here, not left to std::terminate: on Windows an exception that leaves the
	// thread reaches the OS crash filter first, without its message.
	try {
		t->fn(t->arg);
		report_end(t);
	} catch (const std::exception& e) {
		host_uncaught_exception(e.what());
	} catch (...) {
		host_uncaught_exception(nullptr);
	}
	Lock lk(S().m);
	mark_deleted(t);
	S().running = nullptr;
	S().host_cv.notify_one();
}

Tcb* spawn(void (*fn)(void*), void* arg, std::uint32_t prio, const char* name) {
	Tcb* t = new Tcb();
	t->id = S().next_id++;
	t->priority = std::clamp<std::uint32_t>(prio, TASK_PRIORITY_MIN, TASK_PRIORITY_MAX);
	t->name = name ? std::string(name).substr(0, TASK_NAME_MAX_LEN) : "";
	t->fn = fn;
	t->arg = arg;
	if (F().mutex && t_current && F().mutex->owner == t_current) {
		t->followed = true;
		t->follow_serial = F().count++;
	}
	make_ready(t);
	S().tasks.push_back(t);
	std::thread(thread_main, t).detach();
	return t;
}

Tcb* resolve(pros::task_t task) {
	return task ? static_cast<Tcb*>(task) : t_current;
}

void delay_until_us(std::uint64_t wake_us) {
	Tcb* self = t_current;
	if (!self) {
		host_warn_once("delay-outside-task",
		               "pros::delay was called outside a PROS task (from a global constructor or a "
		               "std::thread); it returns immediately in the simulator");
		return;
	}
	Lock lk(S().m);
	if (wake_us <= S().now_us) {
		make_ready(self);  // delay(0): let other ready tasks of this priority run first
	} else {
		block(self, Wait::delay, wake_us);
	}
	park(lk);
}

struct CompetitionArg {
	void (*fn)();
	std::uint32_t serial;
};

void competition_entry(void* p) {
	auto* arg = static_cast<CompetitionArg*>(p);
	arg->fn();
	host_emit("F " + std::to_string(arg->serial));
	delete arg;
}

}  // namespace

void sched_configure(std::uint32_t spin_calls_per_ms, std::uint32_t busy_timeout_ms) {
	S().spin_limit = spin_calls_per_ms;
	S().busy_timeout_ms = busy_timeout_ms;
}

std::uint64_t sched_now_us() { return S().now_us; }

Tcb* current_task() { return t_current; }

void sched_wake(std::uint64_t now_us) {
	Lock lk(S().m);
	S().now_us = std::max(S().now_us, now_us);

	// Wake due tasks in the order their wake times came up.
	std::vector<Tcb*> due;
	for (Tcb* t : S().tasks) {
		if (t->state == TaskState::blocked && t->wake_us <= S().now_us) due.push_back(t);
	}
	std::stable_sort(due.begin(), due.end(), [](Tcb* a, Tcb* b) { return a->wake_us < b->wake_us; });
	for (Tcb* t : due) {
		if (t->wait != Wait::delay) t->timed_out = true;
		remove_waiter(t);
		make_ready(t);
	}
}

std::uint64_t sched_run() {
	Lock lk(S().m);
	while (Tcb* t = pick_ready()) {
		t->state = TaskState::running;
		S().running = t;
		t->cv.notify_one();
		auto start = std::chrono::steady_clock::now();
		while (S().running != nullptr) {
			S().host_cv.wait_for(lk, std::chrono::milliseconds(20));
			if (S().running == nullptr) break;
			host_drain_console();  // a chatty task can fill the console pipe
			double seconds =
			    std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
			if (S().busy_timeout_ms && seconds * 1000.0 > S().busy_timeout_ms) host_busy(S().running, seconds);
		}
		host_drain_console();
	}

	std::uint64_t next = NEVER;
	for (Tcb* t : S().tasks) {
		if (t->state == TaskState::blocked) next = std::min(next, t->wake_us);
	}
	return next;
}

void sched_start_competition_task(void (*fn)(), const char* task_name, std::uint32_t serial) {
	Lock lk(S().m);
	if (S().competition && S().competition->state != TaskState::deleted) mark_deleted(S().competition);
	S().competition = spawn(competition_entry, new CompetitionArg{fn, serial}, TASK_PRIORITY_DEFAULT, task_name);
}

void api_call() {
	Tcb* self = t_current;
	if (!self || S().spin_limit == 0) return;
	if (++self->spin < S().spin_limit) return;
	// Busy for a simulated millisecond without blocking: charge it a tick.
	delay_until_us(S().now_us + 1000);
}

}  // namespace vexsim

using namespace vexsim;

extern "C" {
namespace pros {
namespace c {

uint32_t millis(void) {
	api_call();
	return static_cast<uint32_t>(S().now_us / 1000);
}

uint64_t micros(void) {
	api_call();
	return S().now_us;
}

task_t task_create(task_fn_t function, void* const parameters, uint32_t prio, const uint16_t stack_depth,
                   const char* const name) {
	(void)stack_depth;
	Lock lk(S().m);
	Tcb* t = spawn(function, parameters, prio, name);
	if (t->followed && F().started) {
		lk.unlock();
		F().started(t->follow_serial);
		lk.lock();
	}
	maybe_preempt(lk);
	return t;
}

void task_delete(task_t task) {
	Tcb* t = resolve(task);
	if (!t) return;
	if (t_current && t->state != TaskState::deleted) report_end(t);
	Lock lk(S().m);
	if (t->state == TaskState::deleted) return;
	mark_deleted(t);
	if (t == t_current) {
		S().running = nullptr;
		S().host_cv.notify_one();
		t->cv.wait(lk, [] { return false; });  // a deleted task never runs again
	}
}

void task_delay(const uint32_t milliseconds) {
	delay_until_us(S().now_us + std::uint64_t(milliseconds) * 1000);
}

void delay(const uint32_t milliseconds) { task_delay(milliseconds); }

void task_delay_until(uint32_t* const prev_time, const uint32_t delta) {
	uint32_t wake_ms = *prev_time + delta;
	*prev_time = wake_ms;
	if (std::uint64_t(wake_ms) * 1000 <= S().now_us) {
		api_call();  // already late: FreeRTOS returns without blocking
		return;
	}
	delay_until_us(std::uint64_t(wake_ms) * 1000);
}

uint32_t task_get_priority(task_t task) {
	Tcb* t = resolve(task);
	return t ? t->priority : 0;
}

void task_set_priority(task_t task, uint32_t prio) {
	Tcb* t = resolve(task);
	if (!t) return;
	Lock lk(S().m);
	t->priority = std::clamp<std::uint32_t>(prio, TASK_PRIORITY_MIN, TASK_PRIORITY_MAX);
	maybe_preempt(lk);
}

task_state_e_t task_get_state(task_t task) {
	Tcb* t = resolve(task);
	if (!t) return E_TASK_STATE_INVALID;
	if (t == t_current) return E_TASK_STATE_RUNNING;
	switch (t->state) {
		case TaskState::ready:
		case TaskState::running:
			return E_TASK_STATE_READY;
		case TaskState::blocked:
			return E_TASK_STATE_BLOCKED;
		case TaskState::suspended:
			return E_TASK_STATE_SUSPENDED;
		case TaskState::deleted:
			return E_TASK_STATE_DELETED;
	}
	return E_TASK_STATE_INVALID;
}

void task_suspend(task_t task) {
	Tcb* t = resolve(task);
	if (!t) return;
	Lock lk(S().m);
	if (t->state == TaskState::deleted) return;
	remove_waiter(t);
	t->state = TaskState::suspended;
	if (t == t_current) park(lk);
}

void task_resume(task_t task) {
	Tcb* t = resolve(task);
	if (!t) return;
	Lock lk(S().m);
	if (t->state != TaskState::suspended) return;
	if (t->wait != Wait::none && t->wait != Wait::delay) t->timed_out = true;
	make_ready(t);
	maybe_preempt(lk);
}

uint32_t task_get_count(void) {
	Lock lk(S().m);
	return static_cast<uint32_t>(std::count_if(S().tasks.begin(), S().tasks.end(),
	                                           [](Tcb* t) { return t->state != TaskState::deleted; }));
}

char* task_get_name(task_t task) {
	Tcb* t = resolve(task);
	return t ? const_cast<char*>(t->name.c_str()) : nullptr;
}

task_t task_get_by_name(const char* name) {
	Lock lk(S().m);
	for (Tcb* t : S().tasks) {
		if (t->state != TaskState::deleted && t->name == name) return t;
	}
	return nullptr;
}

task_t task_get_current() { return t_current; }

uint32_t task_notify_ext(task_t task, uint32_t value, notify_action_e_t action, uint32_t* prev_value) {
	Tcb* t = resolve(task);
	if (!t) return 0;
	Lock lk(S().m);
	if (prev_value) *prev_value = t->notify_value;
	switch (action) {
		case E_NOTIFY_ACTION_NONE:
			break;
		case E_NOTIFY_ACTION_BITS:
			t->notify_value |= value;
			break;
		case E_NOTIFY_ACTION_INCR:
			t->notify_value++;
			break;
		case E_NOTIFY_ACTION_OWRITE:
			t->notify_value = value;
			break;
		case E_NOTIFY_ACTION_NO_OWRITE:
			if (t->notify_pending) return 0;
			t->notify_value = value;
			break;
	}
	t->notify_pending = true;
	if (t->state == TaskState::blocked && t->wait == Wait::notify) {
		make_ready(t);
		maybe_preempt(lk);
	}
	return 1;
}

uint32_t task_notify(task_t task) { return task_notify_ext(task, 0, E_NOTIFY_ACTION_INCR, nullptr); }

uint32_t task_notify_take(bool clear_on_exit, uint32_t timeout) {
	Tcb* self = t_current;
	if (!self) return 0;
	Lock lk(S().m);
	if (self->notify_value == 0 && timeout > 0) {
		block(self, Wait::notify, timeout_to_wake(timeout));
		park(lk);
	}
	uint32_t value = self->notify_value;
	if (value) self->notify_value = clear_on_exit ? 0 : value - 1;
	self->notify_pending = false;
	return value;
}

bool task_notify_clear(task_t task) {
	Tcb* t = resolve(task);
	if (!t) return false;
	Lock lk(S().m);
	bool was = t->notify_pending;
	t->notify_pending = false;
	return was;
}

void task_join(task_t task) {
	Tcb* t = static_cast<Tcb*>(task);
	Tcb* self = t_current;
	if (!t || !self || t == self) return;
	Lock lk(S().m);
	if (t->state == TaskState::deleted) return;
	block(self, Wait::join, NEVER);
	self->joining = t;
	park(lk);
}

mutex_t mutex_create(void) {
	return new SimMutex();
}

mutex_t mutex_recursive_create(void) {
	auto* m = new SimMutex();
	m->recursive = true;
	return m;
}

void mutex_delete(mutex_t mutex) {
	(void)mutex;  // tasks may still be waiting on it; leak it like a deleted task
}

bool mutex_take(mutex_t mutex, uint32_t timeout) {
	auto* m = static_cast<SimMutex*>(mutex);
	if (!m) {
		errno = EINVAL;
		return false;
	}
	Tcb* self = t_current ? t_current : &g_no_task;
	Lock lk(S().m);
	if (!m->owner) {
		m->owner = self;
		m->count = 1;
		return true;
	}
	if (m->recursive && m->owner == self) {
		m->count++;
		return true;
	}
	if (timeout == 0 || !t_current) {
		lk.unlock();
		api_call();
		return false;
	}
	block(self, Wait::mutex, timeout_to_wake(timeout));
	self->waiting_on = m;
	auto pos = std::find_if(m->waiters.begin(), m->waiters.end(),
	                        [self](Tcb* w) { return w->priority < self->priority; });
	m->waiters.insert(pos, self);
	park(lk);
	if (self->timed_out) {
		self->timed_out = false;
		return false;
	}
	return true;  // the giver handed us ownership
}

bool mutex_give(mutex_t mutex) {
	auto* m = static_cast<SimMutex*>(mutex);
	if (!m) {
		errno = EINVAL;
		return false;
	}
	Tcb* self = t_current ? t_current : &g_no_task;
	Lock lk(S().m);
	if (m->owner != self && m->owner != &g_no_task) return false;
	if (m->recursive && --m->count > 0) return true;
	if (m->waiters.empty()) {
		m->owner = nullptr;
		m->count = 0;
		return true;
	}
	Tcb* next = m->waiters.front();
	m->waiters.erase(m->waiters.begin());
	next->waiting_on = nullptr;
	m->owner = next;
	m->count = 1;
	make_ready(next);
	maybe_preempt(lk);
	return true;
}

bool mutex_recursive_take(mutex_t mutex, uint32_t timeout) { return mutex_take(mutex, timeout); }

bool mutex_recursive_give(mutex_t mutex) { return mutex_give(mutex); }

}  // namespace c
}  // namespace pros

// vexsim's own, for the route runner (vexsim/bridge/cpp/route/runner.cpp)
void vexsim_follow_tasks(void* mutex, void (*started)(std::uint32_t), void (*ended)(std::uint32_t)) {
	Lock lk(S().m);
	F().mutex = static_cast<SimMutex*>(mutex);
	F().started = started;
	F().ended = ended;
}

std::uint32_t vexsim_followed_count(void) {
	Lock lk(S().m);
	return F().count;
}
}
