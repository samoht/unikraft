/* SPDX-License-Identifier: BSD-3-Clause */
/* Copyright (c) 2023, Unikraft GmbH and The Unikraft Authors.
 * Licensed under the BSD-3-Clause License (the "License").
 * You may not use this file except in compliance with the License.
 */
#ifndef __UK_SCHEDCOOP_SCHEDCOOP_H__
#define __UK_SCHEDCOOP_SCHEDCOOP_H__

#include <uk/schedcoop.h>
#include <uk/arch/spinlock.h>

struct schedcoop {
	struct uk_sched sched;
	struct uk_thread_list run_queue;
	struct uk_thread_list sleep_queue;

	struct uk_thread idle;
	__nsec idle_return_time;
	__nsec ts_prev_switch;

	/* SMP worker cores (see uk_schedcoop_set_busy_poll): when set, the
	 * run/sleep queues are guarded by [lock] so a cross-core uk_thread_wake
	 * (a futex wake from another CPU inserting into this core's run queue)
	 * cannot race this core's own schedule, and the idle thread spins on the
	 * run queue instead of halting -- Unikraft has no cross-core IPI to break
	 * a halt, and a dedicated worker core wants to stay hot anyway. The boot
	 * scheduler leaves this clear and keeps its exact single-core path. */
	__spinlock lock;
	int busy_poll;
};

static inline struct schedcoop *uksched2schedcoop(struct uk_sched *s)
{
	UK_ASSERT(s);

	return __containerof(s, struct schedcoop, sched);
}

void schedcoop_thread_woken_isr(struct uk_sched *s, struct uk_thread *t);

#endif /* __UK_SCHEDCOOP_SCHEDCOOP_H__ */
