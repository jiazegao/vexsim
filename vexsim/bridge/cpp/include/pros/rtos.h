/*
 * vexsim PROS 4 shim: tasks, delays and mutexes.
 *
 * In the simulator every task is a host thread, but only one runs at a time
 * and simulated time stands still while it runs (lockstep scheduling).
 * A task advances time only by blocking: delay, delay_until, waiting on a
 * mutex or a notification.
 */
#ifndef _PROS_RTOS_H_
#define _PROS_RTOS_H_

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
namespace pros {
#endif

#define TASK_PRIORITY_MAX 16
#define TASK_PRIORITY_MIN 1
#define TASK_PRIORITY_DEFAULT 8
#define TASK_STACK_DEPTH_DEFAULT 0x2000
#define TASK_STACK_DEPTH_MIN 0x200
#define TASK_NAME_MAX_LEN 32
#define TIMEOUT_MAX ((uint32_t)0xffffffffUL)

typedef void* task_t;
typedef void (*task_fn_t)(void*);

typedef enum {
	E_TASK_STATE_RUNNING = 0,
	E_TASK_STATE_READY,
	E_TASK_STATE_BLOCKED,
	E_TASK_STATE_SUSPENDED,
	E_TASK_STATE_DELETED,
	E_TASK_STATE_INVALID
} task_state_e_t;

typedef enum {
	E_NOTIFY_ACTION_NONE,
	E_NOTIFY_ACTION_BITS,
	E_NOTIFY_ACTION_INCR,
	E_NOTIFY_ACTION_OWRITE,
	E_NOTIFY_ACTION_NO_OWRITE
} notify_action_e_t;

#ifdef PROS_USE_SIMPLE_NAMES
#ifndef VEXSIM_PROS_NS
#ifdef __cplusplus
#define VEXSIM_PROS_NS pros::
#else
#define VEXSIM_PROS_NS
#endif
#endif
#define TASK_STATE_RUNNING VEXSIM_PROS_NS E_TASK_STATE_RUNNING
#define TASK_STATE_READY VEXSIM_PROS_NS E_TASK_STATE_READY
#define TASK_STATE_BLOCKED VEXSIM_PROS_NS E_TASK_STATE_BLOCKED
#define TASK_STATE_SUSPENDED VEXSIM_PROS_NS E_TASK_STATE_SUSPENDED
#define TASK_STATE_DELETED VEXSIM_PROS_NS E_TASK_STATE_DELETED
#define TASK_STATE_INVALID VEXSIM_PROS_NS E_TASK_STATE_INVALID
#define NOTIFY_ACTION_NONE VEXSIM_PROS_NS E_NOTIFY_ACTION_NONE
#define NOTIFY_ACTION_BITS VEXSIM_PROS_NS E_NOTIFY_ACTION_BITS
#define NOTIFY_ACTION_INCR VEXSIM_PROS_NS E_NOTIFY_ACTION_INCR
#define NOTIFY_ACTION_OWRITE VEXSIM_PROS_NS E_NOTIFY_ACTION_OWRITE
#define NOTIFY_ACTION_NO_OWRITE VEXSIM_PROS_NS E_NOTIFY_ACTION_NO_OWRITE
#endif

typedef void* mutex_t;

#ifdef __cplusplus
#define CURRENT_TASK ((pros::task_t)NULL)
#else
#define CURRENT_TASK ((task_t)NULL)
#endif

#ifdef __cplusplus
namespace c {
#endif

uint32_t millis(void);
uint64_t micros(void);
task_t task_create(task_fn_t function, void* const parameters, uint32_t prio, const uint16_t stack_depth,
                   const char* const name);
void task_delete(task_t task);
void task_delay(const uint32_t milliseconds);
void delay(const uint32_t milliseconds);
void task_delay_until(uint32_t* const prev_time, const uint32_t delta);
uint32_t task_get_priority(task_t task);
void task_set_priority(task_t task, uint32_t prio);
task_state_e_t task_get_state(task_t task);
void task_suspend(task_t task);
void task_resume(task_t task);
uint32_t task_get_count(void);
char* task_get_name(task_t task);
task_t task_get_by_name(const char* name);
task_t task_get_current();
uint32_t task_notify(task_t task);
void task_join(task_t task);
uint32_t task_notify_ext(task_t task, uint32_t value, notify_action_e_t action, uint32_t* prev_value);
uint32_t task_notify_take(bool clear_on_exit, uint32_t timeout);
bool task_notify_clear(task_t task);
mutex_t mutex_create(void);
bool mutex_take(mutex_t mutex, uint32_t timeout);
bool mutex_give(mutex_t mutex);
mutex_t mutex_recursive_create(void);
bool mutex_recursive_take(mutex_t mutex, uint32_t timeout);
bool mutex_recursive_give(mutex_t mutex);
void mutex_delete(mutex_t mutex);

#ifdef __cplusplus
}  // namespace c
}  // namespace pros
}
#endif

#endif  // _PROS_RTOS_H_
