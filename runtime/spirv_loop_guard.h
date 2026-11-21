// Loop guard for translated graphics shaders (spirv_loop_guard.c, host side vk_loop_guard.c). A Switch 2 shader whose
// loop count comes from game data (a per-tile light count read from a constant bank, for one) runs for seconds when
// that word is wrong, Windows resets the GPU after its TDR delay and the run ends in VK_ERROR_DEVICE_LOST. The rewrite
// gives every function with a loop a per-invocation counter of loop-header passes; at the cap the loop leaves through
// its merge block, and the function's return reports the shader through a buffer device address the support buffer
// carries, so the log names it (vk: loop guard ...).
#pragma once
#include <stdint.h>

// Words of the report buffer: [0] trips in all, [1] spare, then LOOP_GUARD_SLOTS pairs {shader id, trips}; a shader
// with id d writes pair d % LOOP_GUARD_SLOTS.
#define LOOP_GUARD_SLOTS 256u
#define LOOP_GUARD_WORDS (2u + 2u * LOOP_GUARD_SLOTS)
// Byte offset of the report address (a 64-bit member appended to Ryujinx's support buffer, which ends at 1396).
#define LOOP_GUARD_SUPPORT_OFFSET 1408u

typedef struct {
    unsigned loops;        // loop headers given the counter
    unsigned unguarded;    // headers whose branch cannot take an exit (both targets inside the loop): left as they were
    unsigned returns;      // returns that report a trip
    int reports;           // 1 when the module reports (support buffer found and report asked for)
} SpirvLoopGuardStats;

// Returns a malloc'd rewrite of the module w[0..n) (words in *out_n), or NULL when it has no loop or cannot be
// rewritten. cap: loop-header passes per invocation before the loops are left. report: also write trips to the report
// buffer (needs the Int64 and buffer device address features and stores and atomics in the stage). id: the shader id
// written to the report buffer.
uint32_t *spirv_loop_guard(const uint32_t *w, uint64_t n, uint32_t cap, int report, uint32_t id, uint64_t *out_n,
                           SpirvLoopGuardStats *st);
