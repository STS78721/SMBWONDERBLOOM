// Learned overrides: SDK functions the tool has learned to answer by itself, read from data instead of code.
//
// tools/bringup.py runs a new title headless, reads its log, and when the game faults inside an SDK function whose
// system service the runtime does not provide (or polls one forever), it tries a generic answer for that function and
// keeps the one that lets the game go further. What it keeps lands in two files, one line per function:
//   knowledge/learned_overrides.txt   shared by every title (copied beside each build by tools/build_game.py)
//   <exe dir>/learned_overrides.txt   this title's own
// Each line:  <mangled symbol> <action>   # optional note
// Actions: ret0 (x0 = 0: Result success, false, null), ret1 (x0 = 1: true, "ready"), retm1 (x0 = -1), noop (x0 kept).
// A function with a real implementation (HOST_OVERRIDE) is never replaced: the linked table wins, and the line is
// reported as superseded. Every override taken is logged, so a learned answer never hides in a run.
// NS2_LEARNED=0 turns the files off (to see the unanswered fault again).
#include "cfg.h"
#include "host.h"
#include "platform/platform.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void lo_ret0(Cpu *c) { ret_x(c, 0); }
static void lo_ret1(Cpu *c) { ret_x(c, 1); }
static void lo_retm1(Cpu *c) { ret_x(c, (uint64_t)-1); }
static void lo_noop(Cpu *c) { (void)c; }

static GuestFn action_fn(const char *a) {
    if (!strcmp(a, "ret0")) return lo_ret0;
    if (!strcmp(a, "ret1")) return lo_ret1;
    if (!strcmp(a, "retm1")) return lo_retm1;
    if (!strcmp(a, "noop")) return lo_noop;
    return NULL;
}

static int load_file(const char *path, const char *what) {
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    char line[1024];
    int taken = 0, n = 0;
    while (fgets(line, sizeof line, f)) {
        n++;
        char *hash = strchr(line, '#');
        if (hash) *hash = 0;
        char sym[768], act[32];
        if (sscanf(line, "%767s %31s", sym, act) != 2) continue;
        GuestFn fn = action_fn(act);
        if (!fn) { rt_log("learned: %s line %d: unknown action '%s' (ret0, ret1, retm1, noop)", what, n, act); continue; }
        if (hostfn_override(sym)) { rt_log("learned: %s: %s has a real implementation; '%s' superseded", what, sym, act); continue; }
        hostfn_add_override(strdup(sym), fn);
        rt_log("learned: %s: %s -> %s", what, sym, act);
        taken++;
    }
    fclose(f);
    return taken;
}

// Called by ldr_load before the modules are bound (hostfn_add_override must come first).
void learned_overrides_load(void) {
    const char *e = cfg_get("NS2_LEARNED");
    if (e && *e == '0') return;
    char exe[PLAT_PATH_MAX], path[PLAT_PATH_MAX + 64];
    int len = plat_exe_path(exe, sizeof exe);
    char *cut = len && (size_t)len < sizeof exe ? plat_last_sep(exe) : NULL;
    if (!cut) return;
    *cut = 0;
    int n = 0;
    snprintf(path, sizeof path, "%s/learned_overrides.shared.txt", exe);
    n += load_file(path, "shared");
    snprintf(path, sizeof path, "%s/learned_overrides.txt", exe);
    n += load_file(path, "title");
    if (n) rt_log("learned: %d override(s) from data (NS2_LEARNED=0 turns them off)", n);
}
