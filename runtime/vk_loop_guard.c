// Loop guard, host side: the cap setting, the report buffer, the shader registry and the log lines. Why the guard
// exists and what the rewrite does: spirv_loop_guard.h and spirv_loop_guard.c.
//
// The report buffer is LOOP_GUARD_WORDS words of host-coherent memory with a buffer device address; every support
// buffer carries that address at LOOP_GUARD_SUPPORT_OFFSET (support_fill, vk_exec_draw.c). A guarded shader that
// reached the cap adds to word 0 and to its slot on return. The address lives in the support buffer, not in the SPIR-V,
// so a module's code is the same in every run and the driver's pipeline cache keeps serving it.
//
// Shader ids are the first four bytes of the translated shader's cache key (gfx_shader_key, the shader-cache file
// name), so the log names the file; the registry maps an id back to the whole key and the NVN 2 origin.
#include "vk_loop_guard.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cfg.h"
#include "host.h"
#include "platform/platform.h"
#include "spirv_loop_guard.h"
#include "vk.h"

enum { REG_SLOTS = 8192 };   // open addressing by id; a full table names later shaders by id alone
typedef struct { uint32_t id; uint8_t stage, used; uint8_t key[32]; uint64_t origin; } RegEnt;

static struct {
    PlatMutex lock;
    volatile int32_t cap_read, init_done;
    uint32_t cap;                  // 0: off
    int report_fs, report_vtg;     // stores and atomics allowed in fragment / vertex, tessellation, geometry stages
    VkBuffer buf;
    VmaAllocation alloc;
    volatile uint32_t *map;
    uint64_t address;
    RegEnt reg[REG_SLOTS];
    uint32_t seen_total, seen[LOOP_GUARD_SLOTS];
    uint64_t modules, loops, unguarded, returns, reporting;   // since the start, under lock
    uint64_t summary_frame;
} G = {.lock = PLAT_MUTEX_INIT};

static uint32_t cap_of(void) {
    if (__atomic_load_n(&G.cap_read, __ATOMIC_ACQUIRE)) return G.cap;
    plat_mutex_lock(&G.lock);
    if (!G.cap_read) {
        const char *e = cfg_get("NS2_LOOP_GUARD");
        unsigned long v = e && *e ? strtoul(e, NULL, 0) : 4096;
        G.cap = v == 0 ? 0 : v < 2 ? 2 : v > 0x40000000ul ? 0x40000000u : (uint32_t)v;
        __atomic_store_n(&G.cap_read, 1, __ATOMIC_RELEASE);
    }
    plat_mutex_unlock(&G.lock);
    return G.cap;
}

// Caller holds G.lock. Allocates the report buffer once; reports stay off without buffer device addresses.
static void init_locked(void) {
    if (G.init_done) return;
    G.init_done = 1;
    VkCtx *c = vk_ctx();
    if (!c || !G.cap) return;
    VkPhysicalDeviceFeatures f;
    vkGetPhysicalDeviceFeatures(c->phys, &f);
    PFN_vkGetBufferDeviceAddress bda =
        c->has_buffer_device_address ? (PFN_vkGetBufferDeviceAddress)vkGetDeviceProcAddr(c->device, "vkGetBufferDeviceAddress")
                                     : NULL;
    if (bda && f.shaderInt64) {
        VkBufferCreateInfo bi = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = LOOP_GUARD_WORDS * 4,
                                 .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT};
        VmaAllocationCreateInfo ai = {.usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
                                      .flags = VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT | VMA_ALLOCATION_CREATE_MAPPED_BIT,
                                      .requiredFlags = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT};
        VmaAllocationInfo info;
        if (vmaCreateBuffer(c->vma, &bi, &ai, &G.buf, &G.alloc, &info) == VK_SUCCESS) {
            G.map = info.pMappedData;
            memset((void *)G.map, 0, LOOP_GUARD_WORDS * 4);
            VkBufferDeviceAddressInfo di = {.sType = VK_STRUCTURE_TYPE_BUFFER_DEVICE_ADDRESS_INFO, .buffer = G.buf};
            G.address = bda(c->device, &di);
            G.report_fs = f.fragmentStoresAndAtomics, G.report_vtg = f.vertexPipelineStoresAndAtomics;
        }
    }
    rt_log("vk: loop guard on: a graphics shader invocation leaves its loops after %u loop passes instead of running "
           "until Windows resets the GPU; %s (NS2_LOOP_GUARD=0 turns it off, NS2_LOOP_GUARD=<passes> sets the cap)",
           G.cap, G.address ? "a shader that reaches the cap is named in this log" : "reports unavailable on this device");
}

uint64_t vk_loop_guard_address(void) {
    if (!cap_of()) return 0;
    if (!__atomic_load_n(&G.init_done, __ATOMIC_ACQUIRE)) {
        plat_mutex_lock(&G.lock);
        init_locked();
        plat_mutex_unlock(&G.lock);
    }
    return G.address;
}

static const char *stage_name(int st) {
    return st == GFX_STAGE_VS ? "vertex" : st == GFX_STAGE_TCS ? "tessellation control" : st == GFX_STAGE_TES ?
           "tessellation evaluation" : st == GFX_STAGE_GS ? "geometry" : st == GFX_STAGE_FS ? "fragment" : "graphics";
}

uint32_t *vk_loop_guard_module(const GfxShader *src, const uint32_t *w, uint64_t words, uint64_t *out_words) {
    uint32_t cap = cap_of();
    if (!cap || !w) return NULL;
    int st = src ? gfx_shader_stage(src) : -1;
    if (st == GFX_STAGE_CS) return NULL;
    uint64_t addr = vk_loop_guard_address();
    const uint8_t *key = src ? gfx_shader_key(src) : NULL;
    uint32_t id = 0;
    if (key) id = (uint32_t)key[0] << 24 | (uint32_t)key[1] << 16 | (uint32_t)key[2] << 8 | key[3];
    int report = addr && key && (st == GFX_STAGE_FS ? G.report_fs : st >= 0 ? G.report_vtg : 0);
    SpirvLoopGuardStats s;
    uint32_t *o = spirv_loop_guard(w, words, cap, report, id, out_words, &s);
    if (!o) return NULL;
    plat_mutex_lock(&G.lock);
    G.modules++, G.loops += s.loops, G.unguarded += s.unguarded, G.returns += s.returns, G.reporting += s.reports;
    if (s.reports) {
        uint32_t h = (id * 0x9E3779B1u) >> 19;   // 13 bits
        for (uint32_t k = 0; k < 64; k++, h = (h + 1) & (REG_SLOTS - 1)) {
            RegEnt *e = &G.reg[h];
            if (e->used && e->id != id) continue;
            if (!e->used) {
                e->used = 1, e->id = id, e->stage = (uint8_t)st;
                memcpy(e->key, key, 32);
                e->origin = gfx_shader_origin(src);
            }
            break;
        }
    }
    plat_mutex_unlock(&G.lock);
    return o;
}

// Caller holds G.lock.
static const RegEnt *reg_find(uint32_t id) {
    uint32_t h = (id * 0x9E3779B1u) >> 19;
    for (uint32_t k = 0; k < 64; k++, h = (h + 1) & (REG_SLOTS - 1))
        if (!G.reg[h].used) return NULL;
        else if (G.reg[h].id == id) return &G.reg[h];
    return NULL;
}

void vk_loop_guard_poll(uint64_t frame, int final) {
    if (!G.map) return;
    uint32_t total = __atomic_load_n(&G.map[0], __ATOMIC_ACQUIRE);
    if (frame >= G.summary_frame + 36000 || (final && G.modules)) {   // a census every 10 minutes at 60 fps
        plat_mutex_lock(&G.lock);
        G.summary_frame = frame;
        rt_log("vk: loop guard%s: %llu modules guarded (%llu reporting), %llu loops, %llu loops left as they were; "
               "%u invocations reached the cap", final ? " at the end" : "", (unsigned long long)G.modules,
               (unsigned long long)G.reporting, (unsigned long long)G.loops, (unsigned long long)G.unguarded, total);
        plat_mutex_unlock(&G.lock);
    }
    if (total == G.seen_total) return;
    G.seen_total = total;
    plat_mutex_lock(&G.lock);
    for (uint32_t k = 0; k < LOOP_GUARD_SLOTS; k++) {
        uint32_t n = __atomic_load_n(&G.map[3 + 2 * k], __ATOMIC_ACQUIRE);
        if (n == G.seen[k]) continue;
        uint32_t id = __atomic_load_n(&G.map[2 + 2 * k], __ATOMIC_ACQUIRE), before = G.seen[k];
        G.seen[k] = n;
        // Every trip of a new shader is logged, then each doubling: a scene that keeps tripping stays readable.
        if (before && (n >> 1) < before && !final) continue;
        const RegEnt *e = reg_find(id);
        char name[80];
        if (e) {
            for (int i = 0; i < 32; i++) snprintf(name + 2 * i, 3, "%02x", e->key[i]);
        } else {
            snprintf(name, sizeof name, "%08x (id only)", id);
        }
        char origin[48] = "";
        if (e && e->origin) snprintf(origin, sizeof origin, " (NVN 2 origin %016llx)", (unsigned long long)e->origin);
        rt_log("vk: loop guard: %s shader %s%s left its loops at the cap of %u passes: %u invocations so far "
               "(present %llu). A loop that long can keep the GPU busy until Windows resets it (device lost); its "
               "count comes from data the draw reads, so check that draw's constant and storage buffers",
               e ? stage_name(e->stage) : "a", name, origin, G.cap, n, (unsigned long long)frame);
    }
    plat_mutex_unlock(&G.lock);
}
