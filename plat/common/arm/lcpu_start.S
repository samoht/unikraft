/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Authors: Răzvan Vîrtan <virtanrazvan@gmail.com>
 *          Justin He     <justin.he@arm.com>
 *
 * Copyright (c) 2021, Arm Ltd. All rights reserved.
 * Copyright (c) 2021, University Politehnica of Bucharest. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 * 3. Neither the name of the copyright holder nor the names of its
 *    contributors may be used to endorse or promote products derived from
 *    this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
 * LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
 * CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 */

 #include <uk/asm.h>
 #include <uk/plat/common/lcpu.h>
 #include <uk/reloc.h>

.text
/* void _lcpu_start(lcpu *cpu) */
ENTRY(lcpu_start)
	/* save x0 */
	mov	x9, x0

	/* Enable FP/SIMD (CPACR_EL1.FPEN=0b11) FIRST -- before start_mmu and any C.
	 * start_mmu and libc memset/memcpy use NEON, and a bare secondary comes up
	 * with Advanced SIMD/FP trapped, so the first SIMD instruction would fault
	 * (Undefined Instruction, ESR EC 0x7). A system-register write works with
	 * the MMU still off. */
	mrs	x28, cpacr_el1
	orr	x28, x28, #(3 << 20)
	msr	cpacr_el1, x28
	isb

	/* Disable interrupts */
	msr	daifset, #2

	/* Set the context id */
	msr	contextidr_el1, xzr

	/* Setup exception vector table address before enable MMU */
	ur_ldr  x29, vector_table
	msr     VBAR_EL1, x29

	/* Enable the mmu */
	bl	start_mmu

	/* Switch to the boot core's runtime page tables. start_mmu loaded the
	 * early boot tables (arm64_bpt_l3_pt0), but ukvmem has since remapped
	 * the heap, stacks and app memory into a runtime table; without this a
	 * secondary faults on its stack right after this routine. A zero value
	 * means "keep the boot tables". */
	ur_ldr	x27, secondary_runtime_ttbr0
	ldr	x27, [x27]
	cbz	x27, 1f
	msr	ttbr0_el1, x27
	dsb	sy
	isb
	tlbi	vmalle1
	dsb	nsh
	isb
1:

	/* restore x0 */
	mov	x0, x9

	/* Load the stack pointer */
	ldr	x9, [x0, #LCPU_STACKP_OFFSET]
	mov	sp, x9


	/* Load the entry address and jump to it */
	ldr	x9, [x0, #LCPU_ENTRY_OFFSET]
	br	x9
END(lcpu_start)
