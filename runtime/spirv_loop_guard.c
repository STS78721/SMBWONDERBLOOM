// Loop guard: the SPIR-V rewrite (see spirv_loop_guard.h for why). Pure code, no Vulkan, so a check can run it over a
// shader cache (tests/loop_guard_check.c).
//
// For every function that holds a loop:
//   - its first block gets a Function variable cnt, set to 0;
//   - every loop header (the block of an OpLoopMerge) adds 1 to cnt before its merge instruction, and its branch leaves
//     for the merge block once cnt reaches the cap:
//       OpBranch B                      -> OpBranchConditional (cnt < cap) B M
//       OpBranchConditional c B M       -> OpBranchConditional (c && cnt < cap) B M
//       OpBranchConditional c M B       -> OpBranchConditional (c || cnt >= cap) M B
//     A header whose branch has both targets inside the loop is left alone (counted as unguarded). The new edge from a
//     header to its merge block gets OpUndef entries in that block's OpPhi instructions: after a trip the loop's
//     results are undefined, which is the price of not hanging.
//   - with reports on, each return first checks cnt >= cap and, if so, adds 1 to word 0 of the report buffer, writes
//     the shader id to its slot and adds 1 to the slot's trips. The buffer's address is a 64-bit member appended to
//     the support buffer (binding 0, Ryujinx's SupportBuffer, last member at 1392) at LOOP_GUARD_SUPPORT_OFFSET, read
//     with OpConvertUToPtr (PhysicalStorageBuffer64 addressing, SPV_KHR_physical_storage_buffer, Int64).
// Since the header counts every pass, nested and later loops share one budget per invocation: once it is spent, every
// loop the invocation reaches afterwards exits on its first pass.
#include "spirv_loop_guard.h"

#include <stdlib.h>
#include <string.h>

enum {
    OP_UNDEF = 1, OP_LINE = 8, OP_EXTENSION = 10, OP_MEMORY_MODEL = 14, OP_ENTRY_POINT = 15, OP_CAPABILITY = 17,
    OP_TYPE_BOOL = 20, OP_TYPE_INT = 21, OP_TYPE_RUNTIME_ARRAY = 29, OP_TYPE_STRUCT = 30, OP_TYPE_POINTER = 32,
    OP_CONSTANT = 43, OP_FUNCTION = 54, OP_VARIABLE = 59, OP_LOAD = 61, OP_STORE = 62, OP_ACCESS_CHAIN = 65,
    OP_DECORATE = 71, OP_MEMBER_DECORATE = 72, OP_CONVERT_U_TO_PTR = 120, OP_IADD = 128, OP_LOGICAL_OR = 166,
    OP_LOGICAL_AND = 167, OP_UGREATER_THAN_EQUAL = 174, OP_ULESS_THAN = 176, OP_ATOMIC_EXCHANGE = 229,
    OP_ATOMIC_IADD = 234, OP_PHI = 245, OP_LOOP_MERGE = 246, OP_SELECTION_MERGE = 247, OP_LABEL = 248,
    OP_BRANCH = 249, OP_BRANCH_CONDITIONAL = 250, OP_RETURN = 253, OP_RETURN_VALUE = 254, OP_NO_LINE = 317,
};
enum { CAP_INT64 = 11, CAP_PSB = 5347, ADDR_PSB64 = 5348, SC_UNIFORM = 2, SC_FUNCTION = 7, SC_PSB = 5349,
       DEC_BLOCK = 2, DEC_ARRAY_STRIDE = 6, DEC_BINDING = 33, DEC_OFFSET = 35, MODEL_GLCOMPUTE = 5 };

static const char kExt[] = "SPV_KHR_physical_storage_buffer";

typedef struct { uint32_t *p; size_t n, cap; int bad; } Out;

static void put(Out *o, uint32_t v) {
    if (o->bad) return;
    if (o->n == o->cap) {
        size_t cap = o->cap ? o->cap * 2 : 4096;
        uint32_t *q = realloc(o->p, cap * 4);
        if (!q) { o->bad = 1; return; }
        o->p = q, o->cap = cap;
    }
    o->p[o->n++] = v;
}
static void ins(Out *o, uint32_t op, int nargs, const uint32_t *a) {
    put(o, (uint32_t)(nargs + 1) << 16 | op);
    for (int i = 0; i < nargs; i++) put(o, a[i]);
}
#define INS(o, op, ...) do { const uint32_t a_[] = {__VA_ARGS__}; ins(o, op, (int)(sizeof a_ / 4), a_); } while (0)

typedef struct { uint32_t merge, header; } Edge;

uint32_t *spirv_loop_guard(const uint32_t *w, uint64_t n, uint32_t cap, int report, uint32_t id, uint64_t *out_n,
                           SpirvLoopGuardStats *st) {
    SpirvLoopGuardStats local;
    if (!st) st = &local;
    memset(st, 0, sizeof *st);
    if (n < 5 || w[0] != 0x07230203u || cap < 2) return NULL;
    uint32_t bound = w[3];
    uint32_t *ptr_sc = calloc(bound, 4), *ptr_to = calloc(bound, 4), *var_ty = calloc(bound, 4), *var_sc = calloc(bound, 4);
    uint32_t *st_members = calloc(bound, 4), *st_maxoff = calloc(bound, 4), *phi_undef = calloc(bound, 4);
    uint8_t *bind0 = calloc(bound, 1), *is_struct = calloc(bound, 1), *merge_new = calloc(bound, 1);
    Edge *edges = NULL;
    size_t nedges = 0, cedges = 0;
    uint8_t *fn_loop = NULL;   // per function, in order: holds an OpLoopMerge
    size_t nfn = 0, cfn = 0;
    Out o = {0};
    uint32_t *res = NULL;
    if (!ptr_sc || !ptr_to || !var_ty || !var_sc || !st_members || !st_maxoff || !phi_undef || !bind0 || !is_struct ||
        !merge_new)
        goto done;

    // ---- pass 1: what the module has
    int has_int64 = 0, has_psb = 0, has_ext = 0, compute = 0, any_loop = 0;
    uint32_t t_u32 = 0, t_u64 = 0, t_bool = 0, cur = 0;
    uint64_t types_at = 0, fn_at = 0;
    for (uint64_t i = 5; i < n;) {
        uint32_t op = w[i] & 0xffff, len = w[i] >> 16;
        if (!len || i + len > n) goto done;
        const uint32_t *a = w + i + 1;
        switch (op) {
        case OP_CAPABILITY: if (len >= 2) has_int64 |= a[0] == CAP_INT64, has_psb |= a[0] == CAP_PSB; break;
        case OP_EXTENSION:
            if ((len - 1) * 4 >= sizeof kExt && !memcmp(a, kExt, sizeof kExt)) has_ext = 1;
            break;
        case OP_ENTRY_POINT: if (len >= 2 && a[0] == MODEL_GLCOMPUTE) compute = 1; break;
        case OP_DECORATE:
            if (len >= 4 && a[1] == DEC_BINDING && a[2] == 0 && a[0] < bound) bind0[a[0]] = 1;
            break;
        case OP_MEMBER_DECORATE:
            if (len >= 5 && a[2] == DEC_OFFSET && a[0] < bound && a[3] > st_maxoff[a[0]]) st_maxoff[a[0]] = a[3];
            break;
        case OP_TYPE_BOOL: if (!t_bool) t_bool = a[0]; break;
        case OP_TYPE_INT:
            if (len == 4 && a[2] == 0 && a[1] == 32 && !t_u32) t_u32 = a[0];
            if (len == 4 && a[2] == 0 && a[1] == 64 && !t_u64) t_u64 = a[0];
            break;
        case OP_TYPE_STRUCT: if (a[0] < bound) is_struct[a[0]] = 1, st_members[a[0]] = len - 2; break;
        case OP_TYPE_POINTER: if (len == 4 && a[0] < bound) ptr_sc[a[0]] = a[1], ptr_to[a[0]] = a[2]; break;
        case OP_VARIABLE: if (len >= 4 && a[1] < bound) var_ty[a[1]] = a[0], var_sc[a[1]] = a[2]; break;
        case OP_FUNCTION:
            if (!fn_at) fn_at = i;
            if (nfn == cfn) {
                size_t c = cfn ? cfn * 2 : 16;
                uint8_t *q = realloc(fn_loop, c);
                if (!q) goto done;
                fn_loop = q, cfn = c;
            }
            fn_loop[nfn++] = 0;
            break;
        case OP_LABEL: cur = a[0]; break;
        case OP_LOOP_MERGE:
            if (!nfn) goto done;
            fn_loop[nfn - 1] = 1, any_loop = 1;
            if (i + len + 1 < n && w[i + len] == (2u << 16 | OP_BRANCH) && w[i + len + 1] != a[0] && a[0] < bound) {
                // the guard adds an edge from this header to its merge block
                if (nedges == cedges) {
                    size_t c = cedges ? cedges * 2 : 16;
                    Edge *q = realloc(edges, c * sizeof *q);
                    if (!q) goto done;
                    edges = q, cedges = c;
                }
                edges[nedges++] = (Edge){a[0], cur};
                merge_new[a[0]] = 1;
            }
            break;
        default: break;
        }
        if (!types_at && op >= 19 && op <= 39) types_at = i;
        i += len;
    }
    if (compute || !any_loop || !types_at || !fn_at) goto done;

    // The support buffer: a Uniform variable at binding 0 whose block is Ryujinx's (its last member at 1392).
    uint32_t sup_var = 0, sup_struct = 0;
    for (uint32_t v = 1; v < bound && report; v++) {
        if (!bind0[v] || var_sc[v] != SC_UNIFORM || !var_ty[v] || ptr_sc[var_ty[v]] != SC_UNIFORM) continue;
        uint32_t s = ptr_to[var_ty[v]];
        if (s < bound && is_struct[s] && st_maxoff[s] >= 1392 && st_maxoff[s] < LOOP_GUARD_SUPPORT_OFFSET)
            sup_var = v, sup_struct = s;
        break;
    }
    report = report && sup_var;

    // ---- pass 2: the OpPhi types of merge blocks that gain an edge
    uint32_t nb = bound;
    cur = 0;
    for (uint64_t i = fn_at; i < n && nedges;) {
        uint32_t op = w[i] & 0xffff, len = w[i] >> 16;
        if (op == OP_LABEL) cur = w[i + 1];
        else if (op == OP_PHI && cur < bound && merge_new[cur] && w[i + 1] < bound && !phi_undef[w[i + 1]])
            phi_undef[w[i + 1]] = nb++;
        i += len;
    }

    // ids of what the rewrite adds
    int new_u32 = !t_u32, new_u64 = report && !t_u64, new_bool = !t_bool;
    if (new_u32) t_u32 = nb++;
    if (new_u64) t_u64 = nb++;
    if (new_bool) t_bool = nb++;
    uint32_t t_pfn = nb++, c0 = nb++, c1 = nb++, ccap = nb++;
    uint32_t t_rta = 0, t_ws = 0, t_pws = 0, t_pwu = 0, t_pu64 = 0, cm = 0, cslot_id = 0, cslot_n = 0, cid = 0;
    if (report) {
        t_rta = nb++, t_ws = nb++, t_pws = nb++, t_pwu = nb++, t_pu64 = nb++, cm = nb++, cslot_id = nb++, cslot_n = nb++;
        cid = nb++;
    }
    uint32_t slot = id % LOOP_GUARD_SLOTS;

    // ---- pass 3: the rewrite
    size_t fn = 0;
    int guard = 0, first_label = 0, need_init = 0, caps_done = 0;
    uint32_t cnt = 0;
    cur = 0;
    for (int k = 0; k < 5; k++) put(&o, w[k]);
    for (uint64_t i = 5; i < n;) {
        uint32_t op = w[i] & 0xffff, len = w[i] >> 16;
        const uint32_t *a = w + i + 1;
        if (!caps_done && op != OP_CAPABILITY) {
            caps_done = 1;
            if (report && !has_int64) INS(&o, OP_CAPABILITY, CAP_INT64);
            if (report && !has_psb) INS(&o, OP_CAPABILITY, CAP_PSB);
            if (report && !has_ext) {
                uint32_t s[sizeof kExt / 4 + 1] = {0};
                memcpy(s, kExt, sizeof kExt);
                ins(&o, OP_EXTENSION, (int)((sizeof kExt + 3) / 4), s);
            }
        }
        if (i == types_at) {
            if (report) {
                INS(&o, OP_DECORATE, t_rta, DEC_ARRAY_STRIDE, 4);
                INS(&o, OP_DECORATE, t_ws, DEC_BLOCK);
                INS(&o, OP_MEMBER_DECORATE, t_ws, 0, DEC_OFFSET, 0);
                INS(&o, OP_MEMBER_DECORATE, sup_struct, st_members[sup_struct], DEC_OFFSET, LOOP_GUARD_SUPPORT_OFFSET);
            }
            if (new_u32) INS(&o, OP_TYPE_INT, t_u32, 32, 0);
            if (new_u64) INS(&o, OP_TYPE_INT, t_u64, 64, 0);
            if (new_bool) INS(&o, OP_TYPE_BOOL, t_bool);
        }
        if (i == fn_at) {
            INS(&o, OP_TYPE_POINTER, t_pfn, SC_FUNCTION, t_u32);
            INS(&o, OP_CONSTANT, t_u32, c0, 0);
            INS(&o, OP_CONSTANT, t_u32, c1, 1);
            INS(&o, OP_CONSTANT, t_u32, ccap, cap);
            if (report) {
                INS(&o, OP_TYPE_RUNTIME_ARRAY, t_rta, t_u32);
                INS(&o, OP_TYPE_STRUCT, t_ws, t_rta);
                INS(&o, OP_TYPE_POINTER, t_pws, SC_PSB, t_ws);
                INS(&o, OP_TYPE_POINTER, t_pwu, SC_PSB, t_u32);
                INS(&o, OP_TYPE_POINTER, t_pu64, SC_UNIFORM, t_u64);
                INS(&o, OP_CONSTANT, t_u32, cm, st_members[sup_struct]);
                INS(&o, OP_CONSTANT, t_u32, cslot_id, 2 + 2 * slot);
                INS(&o, OP_CONSTANT, t_u32, cslot_n, 3 + 2 * slot);
                INS(&o, OP_CONSTANT, t_u32, cid, id);
            }
            for (uint32_t t = 1; t < bound; t++)
                if (phi_undef[t]) INS(&o, OP_UNDEF, t, phi_undef[t]);
        }
        if (need_init && op != OP_VARIABLE && op != OP_LINE && op != OP_NO_LINE) {
            INS(&o, OP_STORE, cnt, c0);
            need_init = 0;
        }
        switch (op) {
        case OP_MEMORY_MODEL:
            if (report) INS(&o, OP_MEMORY_MODEL, ADDR_PSB64, a[1]);
            else ins(&o, op, (int)len - 1, a);
            break;
        case OP_TYPE_STRUCT:
            ins(&o, op, (int)len - 1, a);
            if (report && a[0] == sup_struct && !o.bad) o.p[o.n - len] += 1u << 16, put(&o, t_u64);
            break;
        case OP_FUNCTION:
            guard = fn < nfn && fn_loop[fn];
            fn++, first_label = 1;
            ins(&o, op, (int)len - 1, a);
            break;
        case OP_LABEL:
            cur = a[0];
            ins(&o, op, (int)len - 1, a);
            if (guard && first_label) {
                cnt = nb++;
                INS(&o, OP_VARIABLE, t_pfn, cnt, SC_FUNCTION);
                need_init = 1;
            }
            first_label = 0;
            break;
        case OP_PHI: {
            size_t at = o.n;
            uint32_t extra = 0;
            ins(&o, op, (int)len - 1, a);
            if (cur < bound && merge_new[cur] && a[0] < bound)
                for (size_t e = 0; e < nedges; e++)
                    if (edges[e].merge == cur) put(&o, phi_undef[a[0]]), put(&o, edges[e].header), extra += 2;
            if (!o.bad) o.p[at] += extra << 16;
            break;
        }
        case OP_LOOP_MERGE: {
            uint64_t j = i + len;
            uint32_t top = j < n ? w[j] & 0xffff : 0, tlen = j < n ? w[j] >> 16 : 0, m = a[0];
            const uint32_t *b = w + j + 1;
            int kind = !guard ? 0 : top == OP_BRANCH && tlen == 2 && b[0] != m ? 1 :
                       top == OP_BRANCH_CONDITIONAL && tlen >= 4 && b[2] == m ? 2 :
                       top == OP_BRANCH_CONDITIONAL && tlen >= 4 && b[1] == m ? 3 : 0;
            if (!kind) {
                if (guard) st->unguarded++;
                ins(&o, op, (int)len - 1, a);
                break;
            }
            uint32_t ld = nb++, inc = nb++, cmp = nb++;
            INS(&o, OP_LOAD, t_u32, ld, cnt);
            INS(&o, OP_IADD, t_u32, inc, ld, c1);
            INS(&o, OP_STORE, cnt, inc);
            INS(&o, kind == 3 ? OP_UGREATER_THAN_EQUAL : OP_ULESS_THAN, t_bool, cmp, inc, ccap);
            uint32_t cond = cmp;
            if (kind != 1) {
                cond = nb++;
                INS(&o, kind == 2 ? OP_LOGICAL_AND : OP_LOGICAL_OR, t_bool, cond, b[0], cmp);
            }
            ins(&o, op, (int)len - 1, a);
            if (kind == 1) INS(&o, OP_BRANCH_CONDITIONAL, cmp, b[0], m);
            else INS(&o, OP_BRANCH_CONDITIONAL, cond, b[1], b[2]);
            st->loops++;
            i = j + tlen;   // the header's branch is replaced
            continue;
        }
        case OP_RETURN:
        case OP_RETURN_VALUE:
            if (guard && report) {
                uint32_t ld = nb++, hit = nb++, lr = nb++, l2 = nb++, pm = nb++, ad = nb++, p = nb++;
                uint32_t p0 = nb++, r0 = nb++, pi = nb++, r1 = nb++, pc = nb++, r2 = nb++;
                INS(&o, OP_LOAD, t_u32, ld, cnt);
                INS(&o, OP_UGREATER_THAN_EQUAL, t_bool, hit, ld, ccap);
                INS(&o, OP_SELECTION_MERGE, l2, 0);
                INS(&o, OP_BRANCH_CONDITIONAL, hit, lr, l2);
                INS(&o, OP_LABEL, lr);
                INS(&o, OP_ACCESS_CHAIN, t_pu64, pm, sup_var, cm);
                INS(&o, OP_LOAD, t_u64, ad, pm);
                INS(&o, OP_CONVERT_U_TO_PTR, t_pws, p, ad);
                INS(&o, OP_ACCESS_CHAIN, t_pwu, p0, p, c0, c0);
                INS(&o, OP_ATOMIC_IADD, t_u32, r0, p0, c1, c0, c1);    // scope Device (1), relaxed
                INS(&o, OP_ACCESS_CHAIN, t_pwu, pi, p, c0, cslot_id);
                INS(&o, OP_ATOMIC_EXCHANGE, t_u32, r1, pi, c1, c0, cid);
                INS(&o, OP_ACCESS_CHAIN, t_pwu, pc, p, c0, cslot_n);
                INS(&o, OP_ATOMIC_IADD, t_u32, r2, pc, c1, c0, c1);
                INS(&o, OP_BRANCH, l2);
                INS(&o, OP_LABEL, l2);
                cur = l2;
                st->returns++;
            }
            ins(&o, op, (int)len - 1, a);
            break;
        default:
            ins(&o, op, (int)len - 1, a);
            break;
        }
        i += len;
    }
    if (o.bad || !st->loops) goto done;   // nothing guarded: the caller keeps the original
    o.p[3] = nb;
    st->reports = report;
    *out_n = o.n;
    res = o.p, o.p = NULL;
done:
    free(o.p);
    free(ptr_sc), free(ptr_to), free(var_ty), free(var_sc), free(st_members), free(st_maxoff), free(phi_undef);
    free(bind0), free(is_struct), free(merge_new), free(edges), free(fn_loop);
    return res;
}
