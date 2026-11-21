// Runs the loop guard (runtime/spirv_loop_guard.c) over every *.spv of a shader cache directory and writes each rewrite
// to an output directory under the same name, for spirv-val (tests/loop_guard_check.py drives it). The cache holds
// translated game shaders: keep both directories outside the repository.
//   loop_guard_check <cache dir> <out dir> [cap]
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../runtime/spirv_loop_guard.h"

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: %s <cache dir> <out dir> [cap]\n", argv[0]); return 2; }
    uint32_t cap = argc > 3 ? (uint32_t)strtoul(argv[3], NULL, 0) : 4096;
    DIR *d = opendir(argv[1]);
    if (!d) { perror(argv[1]); return 2; }
    unsigned files = 0, rewritten = 0, reports = 0, loops = 0, unguarded = 0, returns = 0, failed = 0;
    struct dirent *e;
    char path[4096];
    while ((e = readdir(d))) {
        size_t l = strlen(e->d_name);
        if (l < 5 || strcmp(e->d_name + l - 4, ".spv")) continue;
        snprintf(path, sizeof path, "%s/%s", argv[1], e->d_name);
        FILE *f = fopen(path, "rb");
        if (!f) continue;
        fseek(f, 0, SEEK_END);
        long sz = ftell(f);
        fseek(f, 0, SEEK_SET);
        uint32_t *w = sz > 20 && sz % 4 == 0 ? malloc((size_t)sz) : NULL;
        if (!w || fread(w, 1, (size_t)sz, f) != (size_t)sz) { free(w), fclose(f); continue; }
        fclose(f);
        files++;
        uint32_t id = (uint32_t)strtoul((char[9]){e->d_name[0], e->d_name[1], e->d_name[2], e->d_name[3], e->d_name[4],
                                                   e->d_name[5], e->d_name[6], e->d_name[7], 0}, NULL, 16);
        uint64_t on = 0;
        SpirvLoopGuardStats st;
        uint32_t *o = spirv_loop_guard(w, (uint64_t)sz / 4, cap, 1, id, &on, &st);
        loops += st.loops, unguarded += st.unguarded, returns += st.returns;
        if (o) {
            rewritten++, reports += st.reports;
            snprintf(path, sizeof path, "%s/%s", argv[2], e->d_name);
            FILE *g = fopen(path, "wb");
            if (!g || fwrite(o, 4, on, g) != on) failed++;
            if (g) fclose(g);
            free(o);
        } else if (st.loops) {
            failed++;
        }
        free(w);
    }
    closedir(d);
    printf("loop guard: %u modules, %u rewritten (%u report), %u loops guarded, %u unguarded, %u reporting returns, "
           "%u failed\n", files, rewritten, reports, loops, unguarded, returns, failed);
    return failed ? 1 : 0;
}
