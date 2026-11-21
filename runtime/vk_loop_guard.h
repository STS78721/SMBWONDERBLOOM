// Loop guard, host side (vk_loop_guard.c; the SPIR-V rewrite is spirv_loop_guard.c, the reasons in its header).
//   NS2_LOOP_GUARD unset: on, a loop ends after 4096 loop-header passes per shader invocation
//   NS2_LOOP_GUARD=0: off (modules are created as translated)
//   NS2_LOOP_GUARD=<n>: on with a cap of n passes (at least 2)
#pragma once
#include <stdint.h>

#include "gfx.h"
#include "spirv_loop_guard.h"   // LOOP_GUARD_SUPPORT_OFFSET

// make_module_linked (vk_pipeline.c): a malloc'd guarded rewrite of the final SPIR-V of src's module, or NULL to keep
// it. Compute modules are never rewritten.
uint32_t *vk_loop_guard_module(const GfxShader *src, const uint32_t *w, uint64_t words, uint64_t *out_words);
// support_fill (vk_exec_draw.c): the report buffer's device address for the support buffer, 0 when reports are off.
uint64_t vk_loop_guard_address(void);
// Once per present (vk_backend.c): logs shaders that ended a loop at the cap since the last call. vk_device_fault_report
// calls it with final 1 after a device loss.
void vk_loop_guard_poll(uint64_t frame, int final);
