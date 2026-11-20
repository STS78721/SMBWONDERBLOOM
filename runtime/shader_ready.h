// Local proof of warmup, never copied from a build or a release. A new executable,
// moved install, or regenerated shader list must warm its own cache again.
#pragma once
#include <stdio.h>
#include <string.h>
#include "cfg.h"
#include "platform/platform.h"

#define SHADER_WARM_RECEIPT "ns2-shaders-ready.bin"

typedef struct {
    char magic[8];
    uint64_t location;
    PlatFileId binary, variants;
} ShaderWarmReceipt;

static inline int shader_warm_receipt_path(const char *dir, char *out, size_t cap) {
    const char *cache = cfg_get("NS2_SHADER_CACHE");
    int n = cache && *cache && strlen(cache) < 1024
          ? snprintf(out, cap, "%s/" SHADER_WARM_RECEIPT, cache)
          : snprintf(out, cap, "%s/shader-cache/" SHADER_WARM_RECEIPT, dir);
    return n >= 0 && (size_t)n < cap;
}

static inline int shader_warm_identity(const char *dir, ShaderWarmReceipt *out) {
    char exe[PLAT_PATH_MAX * 2], list[PLAT_PATH_MAX * 2 + 32];
    size_t len = plat_exe_path(exe, sizeof exe);
    int n = snprintf(list, sizeof list, "%s/shader-prepared.bin", dir);
    if (!len || len >= sizeof exe || n < 0 || (size_t)n >= sizeof list) return 0;
    memset(out, 0, sizeof *out);
    memcpy(out->magic, "NS2WARM1", sizeof out->magic);
    out->location = UINT64_C(0xcbf29ce484222325);
    for (const unsigned char *p = (const unsigned char *)exe; *p; p++) {
        out->location ^= *p;
        out->location *= UINT64_C(0x100000001b3);
    }
    PlatFile *binary = plat_file_open(exe), *variants = plat_file_open(list);
    int ok = binary && variants && plat_file_id(binary, &out->binary) &&
             plat_file_id(variants, &out->variants) && out->variants.size > 16;
    if (binary) plat_file_close(binary);
    if (variants) plat_file_close(variants);
    return ok;
}

static inline int shader_warm_ready(const char *dir) {
    char path[PLAT_PATH_MAX * 2 + 64];
    ShaderWarmReceipt identity, saved;
    if (!dir || !*dir || !shader_warm_receipt_path(dir, path, sizeof path) ||
        plat_file_size(path) != (int64_t)sizeof saved || !shader_warm_identity(dir, &identity)) return 0;
    PlatFile *file = plat_file_open(path);
    if (!file) return 0;
    int ok = plat_file_pread(file, &saved, sizeof saved, 0) == (int64_t)sizeof saved &&
             !memcmp(&identity, &saved, sizeof saved);
    plat_file_close(file);
    return ok;
}
