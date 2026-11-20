"""Bring a title up automatically: run it headless, read why it stopped, apply what the tool knows or can learn, repeat.

    python tools\\bringup.py --folder <dump>            (the folder `universal_ns2_to_pc.py build --folder` used)
    python tools\\bringup.py --exe <build>\\<short>.exe [--rounds 8] [--seconds 20] [--timeout 120] [--no-learn] [--no-shot]

Each round runs the game with no GPU (TOTK_GPU=null --seconds S, inside an outer time limit) and classifies the log:

  passed    the boot presented frames and reached S seconds: done. A Vulkan run then saves a screenshot.
  fault     an access violation inside an exported SDK function (`in lifted function f_X = sdk+0x.. (_ZN2nn...+0)`): the
            function's system service is missing on a PC. The tool tries generic answers for it (runtime
            learned_overrides.c: ret0, ret1, noop), keeps the first that gets the game further (it presents frames, or
            stops somewhere else), and records it.
  poll      a thread sleeps from the same frame 500 times (runtime kernel.c poll detector): the guest call chain is
            recorded; a frame with an SDK symbol in it is tried as a fault is, answering "ready".
  stalled   no frames before the time limit, no poll and no fault: recorded for a person.
  fatal     a named runtime fatal: recorded for a person.

What it learns goes to <exe dir>/learned_overrides.txt (this title) and to knowledge/learned_overrides.txt (every
title; it is copied beside each build as learned_overrides.shared.txt), so the next title starts with it. Every round
is written to <exe dir>/bringup_report.md and bringup_report.json.

A learned answer gets a game past a missing service; it is not that service. The report lists each one so a real
implementation can replace it (as the Switch 2 font service did: runtime/ov_system.c "nn::pl built-in fonts").
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE = ROOT / 'knowledge' / 'learned_overrides.txt'

FAULT_RE = re.compile(r'in lifted function f_[0-9a-f]+ = (\w+)\+0x([0-9a-f]+) \((_ZN[^)+ ]+)\+0x?([0-9a-f]*)\)')
POLL_RE = re.compile(r'poll: thread (0x[0-9a-f]+) sleeps')
POLL_FRAME_RE = re.compile(r'poll frame +\d+: (.+)$')
BOOT_RE = re.compile(r'boot: frames (\d+) presented \(nvn calls (\d+), distinct (\d+), unimplemented (\d+), '
                     r'validation errors (\d+), shader failures (\d+)')
PASSED_RE = re.compile(r'boot: passed')
NVN_MISSING_RE = re.compile(r'nvn: no such proc "(\w+)"')
FATAL_RE = re.compile(r'(FATAL[^\n]*|rt_fatal[^\n]*)')


def demangle_hint(sym):
    """nn::pl::GetBuiltInFontData from _ZN2nn2pl18GetBuiltInFontDataE..., enough for a report and a guess."""
    m = re.match(r'_ZN((?:\d+\w+?)+?)E', sym)
    if not m:
        return sym
    parts, s = [], m.group(1)
    while s:
        n = re.match(r'(\d+)', s)
        if not n:
            break
        k = int(n.group(1))
        s = s[len(n.group(1)):]
        parts.append(s[:k])
        s = s[k:]
    return '::'.join(parts) or sym


def trial_order(sym, polled):
    """The answers to try for a function, likeliest first: a query polled until it is true wants 1; Get/Is/Has/Try/Check
    names are often bool; anything else is most often a Result (0 = success) or void."""
    name = demangle_hint(sym).split('::')[-1]
    if polled or re.match(r'(Is|Has|Try|Check|Can|Get)[A-Z]', name):
        return ['ret1', 'ret0', 'noop']
    return ['ret0', 'noop', 'ret1']


def read_overrides(path):
    out = {}
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            body = line.split('#', 1)[0].split()
            if len(body) == 2:
                out[body[0]] = body[1]
    return out


def write_override(path, sym, action, note):
    lines = path.read_text(encoding='utf-8').splitlines() if path.is_file() else [
        '# Learned overrides (tools/bringup.py): <mangled symbol> <ret0|ret1|retm1|noop>  # how it was learned',
        '# A learned answer gets past a missing service; replace it with a real implementation when one exists.']
    lines = [l for l in lines if l.split('#', 1)[0].split()[:1] != [sym]]
    lines.append(f'{sym} {action}  # {note}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def drop_override(path, sym):
    if path.is_file():
        keep = [l for l in path.read_text(encoding='utf-8').splitlines() if l.split('#', 1)[0].split()[:1] != [sym]]
        path.write_text('\n'.join(keep) + '\n', encoding='utf-8')


def run(exe, seconds, timeout, gpu='null', shot=None):
    env = dict(os.environ)
    env['TOTK_GPU'] = gpu
    args = [str(exe), '--seconds', str(seconds)] + (['--shot', shot] if shot else [])
    t0 = time.monotonic()
    with open(exe.parent / 'bringup_last.log', 'w', encoding='utf-8', errors='replace') as err:
        p = subprocess.Popen(args, cwd=str(exe.parent), env=env, stdout=subprocess.DEVNULL, stderr=err)
        try:
            p.wait(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            timed_out = True
    text = (exe.parent / 'bringup_last.log').read_text(encoding='utf-8', errors='replace')
    return text, timed_out, time.monotonic() - t0


def classify(text, timed_out):
    r = {'nvn_missing': sorted(set(NVN_MISSING_RE.findall(text)))}
    b = BOOT_RE.search(text)
    if b:
        r['frames'], r['nvn_calls'], _, r['nvn_unimplemented'], r['validation_errors'], r['shader_failures'] = map(int, b.groups())
    else:
        r['frames'] = 0
    f = FAULT_RE.search(text)
    if f:
        r.update(kind='fault', module=f.group(1), offset=int(f.group(2), 16), symbol=f.group(3),
                 at_entry=f.group(4) in ('', '0'), name=demangle_hint(f.group(3)))
        return r
    if PASSED_RE.search(text) and r['frames'] > 0:
        r['kind'] = 'passed'
        return r
    fatal = FATAL_RE.search(text)
    if fatal:
        r.update(kind='fatal', message=fatal.group(1)[:300])
        return r
    if POLL_RE.search(text):
        lines = text.splitlines()
        i = next(i for i, l in enumerate(lines) if POLL_RE.search(l))
        chain = [m.group(1) for l in lines[i + 1:i + 18] if (m := POLL_FRAME_RE.search(l))]
        sym = next((re.search(r'\((_ZN\w+)', c).group(1) for c in chain if '(_ZN' in c), None)
        r.update(kind='poll', chain=chain, symbol=sym, name=demangle_hint(sym) if sym else None)
        return r
    r['kind'] = 'stalled' if timed_out else 'exited'
    r['tail'] = text.splitlines()[-8:]
    return r


def learnable(r):
    """A stop the tool can try to answer: a fault at an SDK function's entry, or a poll whose chain names one."""
    sym = r.get('symbol') or ''
    return sym.startswith('_ZN2nn') and (r['kind'] == 'poll' or (r['kind'] == 'fault' and r.get('at_entry')))


def progressed(before, after):
    """The answer helped: the game presents frames now, or it stops at another missing SDK service (this hole is filled,
    the next one shows). A crash in the game's own code or a fatal right after is not progress: a generic answer that
    hands back nothing usable (a font, a buffer) only moves the crash. Tested on Super Mario Bros. Wonder with the font
    service turned off (NS2_UNHOOK): "true" from GetBuiltInFontData let the game read a garbage font address."""
    if after['kind'] == 'passed' or after['frames'] > before.get('frames', 0):
        return True
    return learnable(after) and after.get('symbol') != before.get('symbol')


def find_exe(args):
    if args.exe:
        return args.exe.resolve()
    sys.path.insert(0, str(ROOT / 'tools'))
    import universal_ns2_to_pc as u
    disc = u.discover_game_folder(args.folder)
    exe = disc['folder'] / 'build' / disc['ver'] / (disc['short'] + ('.exe' if os.name == 'nt' else ''))
    if not exe.is_file():
        sys.exit(f'{exe} not found: build it first (universal_ns2_to_pc.py build --folder {args.folder})')
    return exe


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--folder', type=Path, help='the game folder `universal_ns2_to_pc.py build --folder` took')
    ap.add_argument('--exe', type=Path, help='the built game instead of --folder')
    ap.add_argument('--rounds', type=int, default=8)
    ap.add_argument('--seconds', type=float, default=20)
    ap.add_argument('--timeout', type=float, default=120)
    ap.add_argument('--no-learn', action='store_true', help='diagnose only: write no overrides')
    ap.add_argument('--no-shot', action='store_true', help='no Vulkan screenshot after a passed boot')
    args = ap.parse_args()
    if not args.exe and not args.folder:
        ap.error('give --folder or --exe')
    exe = find_exe(args)
    title_file = exe.parent / 'learned_overrides.txt'
    if KNOWLEDGE.is_file():
        shutil.copy2(KNOWLEDGE, exe.parent / 'learned_overrides.shared.txt')

    rounds, trying = [], None   # trying: (symbol, remaining actions, result before the trial, action)
    confirmed = []              # answers that helped this run; shared with every title once the game boots with them
    for n in range(1, args.rounds + 1):
        text, timed_out, took = run(exe, args.seconds, args.timeout)
        r = classify(text, timed_out)
        r.update(round=n, seconds=round(took, 1))
        if trying:
            sym, remaining, before, action = trying
            if progressed(before, r):
                r['learned'] = f'{sym} {action}'
                write_override(title_file, sym, action, f'helped: {before["kind"]} in {demangle_hint(sym)} (round {n - 1})')
                confirmed.append((sym, action, f'{exe.stem}: {before["kind"]} in {demangle_hint(sym)}'))
                trying = None
            elif remaining:
                action = remaining.pop(0)
                write_override(title_file, sym, action, f'trial after {action} did not help')
                trying = (sym, remaining, before, action)
                r['trial'] = f'{sym} {action}'
                rounds.append(r)
                print(f'round {n}: {r["kind"]}; trying {demangle_hint(sym)} -> {action}', flush=True)
                continue
            else:
                drop_override(title_file, sym)
                r['gave_up'] = sym
                trying = None
                rounds.append(r)
                print(f'round {n}: no generic answer for {demangle_hint(sym)} helps: it needs a real implementation')
                break
        rounds.append(r)
        print(f'round {n}: {r["kind"]}' + (f' in {r.get("name")}' if r.get('name') else '')
              + (f', {r["frames"]} frames' if r.get('frames') else '') + f' ({took:.0f} s)', flush=True)
        if r['kind'] == 'passed':
            for sym, action, note in confirmed:   # (the game boots with them: every later title starts with them)
                write_override(KNOWLEDGE, sym, action, note)
            if confirmed:
                r['shared'] = [f'{s} {a}' for s, a, _ in confirmed]
            if not args.no_shot:
                text, _, _ = run(exe, args.seconds, args.timeout, gpu='vulkan', shot='bringup_shot.png')
                r['shot'] = 'bringup_shot.png' if (exe.parent / 'bringup_shot.png').is_file() else None
                vk = classify(text, False)
                r['vulkan'] = {k: vk.get(k) for k in ('kind', 'frames', 'validation_errors', 'shader_failures')}
            break
        sym = r.get('symbol')
        if args.no_learn or not learnable(r) or read_overrides(title_file).get(sym) or read_overrides(KNOWLEDGE).get(sym):
            break   # (nothing generic to try, or a learned answer is already in place and this is what follows)
        order = trial_order(sym, r['kind'] == 'poll')
        action = order.pop(0)
        write_override(title_file, sym, action, f'trial: {r["kind"]} in {demangle_hint(sym)}')
        trying = (sym, order, r, action)
        r['trial'] = f'{sym} {action}'

    report = {'exe': str(exe), 'when': datetime.datetime.now().isoformat(timespec='seconds'), 'rounds': rounds}
    (exe.parent / 'bringup_report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    md = [f'# Bring-up report: {exe.name}', '', f'{report["when"]}, {len(rounds)} round(s).', '',
          '| Round | Result | Where | Frames | Action |', '|---|---|---|---|---|']
    for r in rounds:
        act = r.get('learned') and f'learned `{r["learned"]}`' or r.get('trial') and f'trying `{r["trial"]}`' or \
            r.get('gave_up') and f'gave up on `{r["gave_up"]}`' or ''
        md.append(f'| {r["round"]} | {r["kind"]} | {r.get("name") or ""} | {r.get("frames", 0)} | {act} |')
    last = rounds[-1] if rounds else {}
    if last.get('chain'):
        md += ['', 'Polling thread\'s guest call chain:', ''] + [f'- {c}' for c in last['chain']]
    if last.get('nvn_missing'):
        md += ['', 'NVN procs the game asked for that the runtime lacks:', ''] + [f'- `{p}`' for p in last['nvn_missing']]
    if last.get('vulkan'):
        md += ['', f'Vulkan run: {last["vulkan"]}; screenshot `{last.get("shot")}`.']
    (exe.parent / 'bringup_report.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print(f'report: {exe.parent / "bringup_report.md"}')
    return 0 if last.get('kind') == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
