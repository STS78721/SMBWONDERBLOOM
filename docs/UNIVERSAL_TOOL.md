# Universal NS2 Recompiler: purpose, how to use it, findings, next steps

*Started 2026-11-20 by Claude, from the first test of the tool on a game it had never seen (Super Mario Bros. Wonder –
Nintendo Switch 2 Edition). Living document: update it as each step lands. It is meant to move into the tool's own
repository.*

## Start here (for whoever picks this up)

**Where things are:**
- This is a local working checkout on branch `universal-core`, based on commit `ea85754`. No changes have been pushed.
- Local game dumps, compiled builds, runtime settings, saves, screenshots, caches, logs and cover art stay outside the
  repository. The test build is selected through a local folder path; no user's files are tracked.
- Wonder's verified game version is **1.0.0**. The current port build label is **Alpha 0.1.0a**. These are separate
  version numbers and must stay separate in the launcher, F1 menu, installer and release notes.

**Current Wonder state:** the user supplied a fully patched, working local build for installer input. The source tree
also builds successfully, launches the game, and has been used to capture the F1 menu at 1280x720 in all three themes.
The previous notes below about a crash after the title screen describe an earlier build and are not current status.

**Rebuild after a runtime change:** `python tools\universal_ns2_to_pc.py build --folder "<local-dump-folder>"`.
Keep all build output in that local folder, outside the repository.

### Start screen

The native SDL3 start screen runs before `rt_boot()` when `NS2_SHOW_LAUNCHER=1` (the default), unless the run uses
`--seconds` or `NS2_NO_LAUNCHER` is set. Play starts the guest; Quit exits. If SDL cannot make a window, startup continues
to the guest so its own error report remains visible. `NS2_FULLSCREEN` selects the initial display mode and F11 or the
Display row switches it. The Profile page saves `NS2_PLAYER_NAME` for the next game start. The main page's Theme row
cycles Dark, Light and the title's registered game theme. A title with a registered theme starts in that theme until the
player has set `NS2_MENU_THEME`; on Wonder this is WonderBloom. Dark and Light remain selectable, and the choice is shared
with the in-game menu.

The SDL renderer uses Dear ImGui's SDL3 and SDL_Renderer3 back ends. It reuses the menu's Roboto font. Each build
creates `launcher_icon.png` from the configured cover art in that build's output folder. At startup, the launcher loads
that PNG from beside the executable as a texture; it is not embedded in the executable. Keep the PNG beside the exe if
you move a build. The cover art source stays outside the repository. An optional `splash.png` beside the executable is
used as the backdrop. Without one, the screen draws palette colours and simple shapes.

The launcher's title and game version come from that build's expected metadata. For Wonder, that is `Super Mario Bros.
Wonder` and `1.0.0` (`tools/data/expected-smbw100.json`), shown as “Game version: 1.0.0”. The runtime's `rt_game_version`
remains `0` for this Switch 2 version family; that internal API/clock-family value is not the displayed game version.
The separate `Universal NS2 to PC · Port …` label uses the tool's root `VERSION` file (`Alpha 0.1.0a`), so the Alpha
label identifies the port, not the game.

### Release updates

On Windows the start screen checks published GitHub releases in the background. Wonder builds use
[STS78721/SMBWONDERBLOOM](https://github.com/STS78721/SMBWONDERBLOOM). The build takes `release_repo` from
the game metadata and writes `ns2-release-repo.txt` beside the executable. The installer carries this file
into the installed game. Only the owner's repository name is sent as part of the release query.

Tag port releases by version, for example `v0.1.0b` or `v0.1.1`, and put the highlights first in the release
notes. The launcher checks the port version, includes published prereleases, and ignores drafts. For a newer
release it shows the version and a short changelog. **Update now** opens that release on GitHub so players
can download its package. If the check fails or no newer release is available, the normal Play screen remains available.

For a screenshot with a test release card, set `NS2_LAUNCHER_SHOT_UPDATE=1` alongside the screenshot hook.
This uses sample notes and skips the live network check.

### Launcher screenshots

Launcher checks can be run without changing saved settings:

```
set NS2_LAUNCHER_SHOT=60
set NS2_LAUNCHER_SHOT_OUT=<local-build-output>\launcher-dark.png
set NS2_LAUNCHER_SIZE=1280x720
set NS2_MENU_THEME=dark
set NS2_FULLSCREEN=0
smbw.exe
```

`NS2_LAUNCHER_PAGE=profile` selects the Profile page; set `NS2_MENU_THEME` to `light` or `game` and repeat for those
palettes. `NS2_LAUNCHER_SIZE` accepts a test window size such as `1920x1080`. `NS2_LAUNCHER_PLAY=1` activates Play on
the first frame to check the normal boot path. These are environment hooks, not settings. The title's registered game
theme uses dark button text when its yellow accent is bright.

**Screenshot matrix:** capture both pages at both sizes in all three themes. On Wonder, `game` selects WonderBloom.
Keep the output under the local build folder, outside the repository.

| Theme (`NS2_MENU_THEME`) | Main, 1280x720 | Profile, 1280x720 | Main, 1920x1080 | Profile, 1920x1080 |
|---|---|---|---|---|
| Dark (`dark`) | `main-dark-1280x720.png` | `profile-dark-1280x720.png` | `main-dark-1920x1080.png` | `profile-dark-1920x1080.png` |
| Light (`light`) | `main-light-1280x720.png` | `profile-light-1280x720.png` | `main-light-1920x1080.png` | `profile-light-1920x1080.png` |
| WonderBloom (`game`) | `main-game-1280x720.png` | `profile-game-1280x720.png` | `main-game-1920x1080.png` | `profile-game-1920x1080.png` |

For each cell, set `NS2_MENU_THEME`, `NS2_LAUNCHER_SIZE`, and `NS2_LAUNCHER_SHOT_OUT` to the row, column, and filename;
leave `NS2_LAUNCHER_PAGE` unset for Main or set it to `profile` for Profile. Use `NS2_LAUNCHER_SHOT=60` and
`NS2_FULLSCREEN=0`, then launch `smbw.exe`. Check the log for `launcher: screenshot saved to ...` and inspect each PNG
for clipping, readable labels, yellow-button contrast, icon visibility, and layout at that size.

**Animation check:** screenshot mode intentionally freezes motion for repeatable stills, so the matrix cannot prove the
animation works. Start the executable interactively without `NS2_LAUNCHER_SHOT`, keep the launcher window focused, and
watch through the intro and several seconds afterward. Confirm the logo and left-side intro settle smoothly, the large
icon card bobs, WonderBloom petals turn slowly, and sparkles brighten and dim. The animation pauses when the window
loses focus. For a moving-decor capture, set `NS2_LAUNCHER_SHOT_MOTION=1` as well as the screenshot hook, keep the
window focused, and capture at different frame numbers (for example 60, 120, and 180). This animates the card and
backdrop; screenshot mode keeps the intro transition settled, so use the interactive run to check the intro itself.
For the in-game menu's WonderBloom motif, set `NS2_MENU_TEST_MOTION=1` with `NS2_MENU_TEST` and
`NS2_MENU_TEST_DIR` to let the test captures advance the animation. If recording evidence, use a live window recording;
separate still images only show samples of the motion.

**Current verification state (2026-11-20):** the launcher implementation exists in `runtime/ui/launcher/launcher.cpp`.
Its 12 static captures were generated successfully. Dark and WonderBloom layouts, the Profile page, readable yellow
button text, the right-side game icon and the Quit row were visually reviewed. The launcher’s live intro animation and
Profile save persistence still need an interactive check. The F1 menu now scales to the physical window height. At
1280x720 on the 216-DPI display, all six pages captured in Dark, Light and WonderBloom; visual review confirmed the full
Frame rate limit row, separate help panel, visible Continue/Quit controls, and distinct “Port Alpha 0.1.0a · game
1.0.0” labels. The game booted cleanly in each theme. The touchpad click-edge gate passed selftest; physical PS4/PS5
controller hardware was not available for verification.

The F1 menu uses this same palette and its animated flower and sparkle motif. On supported PS4 and PS5 controllers,
clicking the touchpad opens or closes the F1 menu; holding it does not repeat the toggle.

The Setup Wizard installer port should use the same WonderBloom colours and bloom/sparkle motifs as the start screen.

**Check it:**
- `python tools\universal_ns2_to_pc.py bringup --folder "<local-dump-folder>"`.
- For the menu: run with `NS2_MENU_TEST=600:20` and `NS2_MENU_TEST_DIR=<folder>`. It saves a shot of each tab (4h).
  Add `NS2_MENU_TEST_MOTION=1` when the captures should include the animated WonderBloom motif.

**The user's rules for this work:**
- Universal first: no game names in the engine.
- Fidelity first: measure before claiming. Check game progress and frame time, not only the runtime's speed figure.
- Hard limits: no game files or data derived from them leave the PC; the user's cover art stays outside the repository;
  personal settings do not go into releases; the user's email stays private.
- Keep themes and icons in the shared library, not in a title fork.
- When diagnosing generated C, back it up before editing, restore it afterward, and rebuild.
- Send a one-line progress note while working. Report what was measured and state plainly what is still unverified.
- Keep this handbook current after each step lands so someone else can continue.

### Remaining roadmap

These items came from the launcher handover and remain future work unless a later status note records completion:

1. **Remove TotK names from anything players can see.** Rename `totk.rc`, `totk.ico`, and `totk.manifest` with their
   references in `tools/build_game.py` and `tools/game_icon.py`; remove visible `totk+0x`, `TOTK_`, `libtotkrt`, and
   `totk.exe` strings; change runtime config reads from legacy `TOTK_` names to `NS2_` names while retaining the
   compatibility prefix where config supports it. Search with `-i totk`, rebuild, and run the probes afterward.
2. **Port the Setup Wizard installer** from the user's MKW-THWOMP reference. Keep it animated and use the WonderBloom
   palette and flower/sparkle motifs. It must consume a locally selected compiled build through a strict allowlist;
   never package the source build folder recursively. Produce tool-only installer releases with no game files,
   settings, saves, screenshots, caches, logs, or cover art.
3. **Measure PGO before keeping it.** Compare before/after frame-time numbers on the same workload; retain a PGO build
   only if it is measurably faster.
4. **Prepare the GitHub repository for launch.** Write the README, license notices, and release notes in the requested
   Pearl Abyss style, and require `tools/check_content.py` to pass cleanly. Before creating the repo, ask the user what
   to name it and whether Wonder should have a separate repository.
5. **Update this handbook as each step lands.** Delete `docs/HANDOVER_LAUNCHER.md` only after the launcher is committed
   and its instructions and status are covered here.

---

## 1. What the tool is for

**One tool that turns any Nintendo Switch 2 game the user owns into a native PC build**, from the user's own dump, on
the user's own PC. It is a static recompiler, not an emulator:
- the game's ARM64 code is translated ahead of time to C (`recomp/`), then compiled to x86-64;
- a host runtime stands in for the console's system (`runtime/`, Horizon OS services);
- the game's graphics calls (NVN 2) are replayed on Vulkan, and its SM86 (Ampere) shaders are translated to SPIR-V
  (`tools/xlate`, `runtime/third_party/eglantine`).

**"Universal" means: the user points it at a dump and it works out the rest.** Their own `.nup`, or `exefs` + `romfs`
folders, of any title. No per-game fork of the code, no branch per game, no game named in the engine. What one game
teaches the tool (a missing system call, an NVN procedure, a shader instruction, a quirk) lands as data that every
later game benefits from.

**What it is not:** a way to get games. No game files, keys or anything derived from them leave the user's PC or go into
the repository (`AGENTS.md`, "Game content boundary"; `tools/check_content.py`).

## 2. Why it is built this way

- **Static recompilation** gives native speed: no interpreter runs while the game plays. The cost is that every game
  has to be lifted and compiled once, on the user's PC, from their dump.
- **One engine, many games.** Every Switch 2 title shares the same system (Horizon), graphics API (NVN 2) and GPU
  (Ampere SM86). Only a thin layer is game-specific. Ports done game by game (Hookshot, DKB, MTF, MKW, Fast Fusion)
  each re-solved the same system and graphics problems. One engine solves them once.
- **Learning as data.** A fix found for one game should help the next one without anyone porting it by hand. That only
  works when the knowledge is something the tool reads, not something buried in code or on a branch.

## 3. How to use it (as of 2026-11-20)

Requirements: `docs/building.md` (MSYS2 UCRT64 clang/lld/ninja, .NET 10 SDK, Vulkan SDK, Python 3.10+ with `lz4`,
`zstandard`, `capstone`, `unicorn`). Keys are not needed for `.nup` containers. hactool and `prod.keys` are only needed
for encrypted NCA/NSP dumps.

```
# 1. Unpack the user's container (any .nup). By default (--package auto): the base with the newest update laid over it
#    when the container has one, and every add-on (DLC). Writes <dump>\exefs, <dump>\romfs, <dump>\aoc\<index>\romfs
#    and <dump>\title.json (name, title ID, version, whether an update was applied, the add-ons).
python tools\extract_nup.py "<game>.nup" --list
python tools\extract_nup.py "<game>.nup" --out "<dump>"

# 2. One command for the rest: scan, register, pack, lift, build, install the add-ons, then bring it up automatically
python tools\universal_ns2_to_pc.py port --folder "<dump>"

#    or step by step:
python tools\universal_ns2_to_pc.py scan --folder "<dump>" --json "<dump>\..\scan_report.json"
python tools\universal_ns2_to_pc.py init --folder "<dump>"
python tools\universal_ns2_to_pc.py build --folder "<dump>"     # -> <dump>\build\<ver>\<short>.exe (+ aoc-<index>\)
python tools\universal_ns2_to_pc.py bringup --folder "<dump>"   # run, diagnose, learn: section 5a
```

The game's name, short name and version key come from `title.json` (the container's own metadata), so the folder can
be called anything.

**Updates and DLC are automatic:**
- `extract_nup.py --package auto` (the default) takes the newest update in the container and lays it over the base
  (matched by title family), so the build is the updated game. `--package base` keeps the old behaviour.
- Each add-on package's RomFS goes to `<dump>\aoc\<index>\romfs`; the index is the low 12 bits of its title ID.
- `build` packs each add-on and installs it beside the exe as `aoc-<index>\romfs.bin` + `aoc-index.bin`, where the
  runtime mounts add-on content (`runtime/aoc_romfs.c`). The image is a hard link, so it isn't stored twice.
- An update or add-on bought later: put the newer `.nup` (or one holding just the update or add-on) through step 1
  again into the same `<dump>`. Unchanged files are skipped. Then run `build` again.

## 4. Findings

### 4a. The first unseen game: Super Mario Bros. Wonder – Nintendo Switch 2 Edition

| | |
|---|---|
| Container | `Wonder.nup`, 6.49 GB: base `040015100B514001` + add-on `010015100B515001` (Meetup in Bellabel Park content, 5.36 GB) |
| ExeFS | `main` (33 MB), `rtld`, `sdk`, `subsdk0`, `main.npdm` |
| RomFS | 36,842 files, 6.78 GB, packed to 6.32 GiB in 91 s |
| Imports | 1,372 SDK symbols, 345 already hooked by the runtime; the rest run as lifted SDK code |
| Lifter | 13.58 M `.text` words; 193,569 distinct sampled, **0 unhandled** |
| NVN 2 | 770 procs used, **41 not in the runtime's tables** (mostly exotic: CUDA interop, ray-tracing helpers, copy engine) |
| Shaders | 27,920 unique: 18,996 SM86 (Ampere) + **8,924 NVN 1 Maxwell** (left over from the Switch 1 version); 112 distinct SM86 opcodes, **100 % covered** |
| Textures | ASTC 4x4 sRGB |
| Media | 67 videos, up to 13.6 MiB |
| Build | **succeeded, no game-specific code**: 230 MB `smbw.exe` (4c) |

### 4b. Tool problems found and fixed on this run (branch `universal-core`)

1. **`scan` reported a broken run as a clean one.** Without the `lz4` module it could not decompress the NSO segments,
   returned an empty image, and printed 0 relocs, 0 imports, 0 NVN procs and 0 unhandled instructions, which reads as
   "this game needs nothing". Now it stops and says `lz4` is missing (`decode_nso_sections`).
2. **The game was named after its folder.** An extracted folder called `dump` became the game "dump", version
   `dump100`. `extract_nup.py` now writes `title.json` (title ID, program ID, name, version, packages) beside `exefs/`
   and `romfs/`, and `discover_game_folder` names the game from it: "Super Mario Bros Wonder", short name `smbw`,
   version key `smbw100`.
3. **NUP metadata records were read by number, and the numbers differ between containers.** In Wonder's container the
   NPDM is record 0 and the title name is record 4, which the extractor took for the display version (it expected the
   NPDM at 1 and the name at 5). Text records are now read by content: a version string looks like `1.2.0`, a name has
   letters and spaces.

### 4c. First bring-up results (historical, 2026-11-20)

This was an early test build, before the user supplied the fully patched working build. Its failure notes below are
historical and must not be presented as the current Wonder status.

**Build: succeeded with no game-specific code.**

| Step | Result |
|---|---|
| Lift | 305,746 functions (main 258,829, sdk 45,382, subsdk0 1,535), 932 MB of C, **0 unsupported instructions**, 17 s |
| Compile | 434 objects, 69 s (12 jobs, 3.6 GB peak) |
| Link | 0.7 s → `smbw.exe`, 230 MB |

**Boot, step by step:**
1. **Start-up works:** modules load and relocate (498,911 relocations in `main`), `nn::init`, 8,377 `main` init entries, the
   RomFS mounts (36,842 files), the controller initialises, NVN initialises, and Vulkan comes up (pipeline library,
   ASTC compute decoder, replay thread).
2. **First blocker, fixed:** a crash in `nn::pl::GetBuiltInFontData`. The Switch 2 SDK gets the system fonts from a
   font service the runtime did not have; its service object is null on a PC, and the game read through it. Fixed by the
   **Switch 2 font service** (4e).
3. **Second blocker, fixed:** after the fonts loaded, the main thread polled forever (1 ms sleeps, no frame). The new
   poll detector (`runtime/kernel.c`, 5a) named the loop at once: the font loader (main+0x881d90) calls
   `GetBuiltInFontData` until it returns **true**. The call returns the service's "found" flag, a bool, not a Result
   (the SDK returns the flag byte after the service call). The font service now returns true.
4. **Reaches the title screen.** At 20 s:
   - **Headless:** 1,201 frames, 2.1 M NVN calls, **0 unimplemented**, 0 validation errors, 0 shader failures, 0
     skipped draws, 69 threads; the save mounts and commits.
   - **Vulkan at 4K:** the full title screen ("Super Mario Bros. Wonder – Nintendo Switch 2 Edition + Meetup in
     Bellabel Park", "Press L + R to Start" drawn with the font service's fonts and button glyphs).
   - **DLC:** with the add-on installed, the game reports `aoc: 1 add-on content` and still boots clean.
5. At this early bring-up stage, play past the title screen, audio, movies and Bellabel Park content had not yet been
   tested. The user later confirmed their fully patched local Wonder build works; this early report does not describe it.

**NVN procs the game asked for that the runtime lacks** (all return NULL, which the game tolerates so far):
`nvnProgramBuilderGetRayTracingModuleCount`, `nvnProgramBuilderGetRayTracingModuleData`,
`nvnCommandBufferConvertCooperativeVectorMatrix`, `nvnDeviceGetCooperativeVectorMatrixSize`,
`nvnDeviceConvertCooperativeVectorMatrix`, `nvnCommandBufferGetAccelerationStructureVisualizationData`.

### 4e. The Switch 2 font service (`runtime/ov_system.c`, "nn::pl built-in fonts")

Built from the SDK's own code: the four Switch 2 font calls, each in its Nx and Ounce form. They are hooked by name,
so they work for every game built with this SDK, not just Wonder:

| Call | What it returns |
|---|---|
| `GetBuiltInFontData(out, type, bool)` | one font record |
| `GetBuiltInFontDataSet(count, out, types, n, language, bool)` | up to 7 (Nx) or 6 (Ounce) records, in the order the types are given |

Each record is 24 bytes: `+0` present (non-zero = the font is there), `+1` flag bit, `+8` the font's address, `+16` its
size. The type numbers are the Switch 1 `SharedFontType` ones.

The fonts come from where the Switch 1 calls get theirs:
1. the user's firmware fonts (`tools/extract_fonts.py`, from the user's own firmware with their keys);
2. else the system fallback font;
3. and a synthesized Nintendo extension font for the button glyphs.

So a game runs without firmware fonts, with fonts that look different. For the exact look, extract the user's firmware
fonts.

### 4f. Notes for whoever runs the next test

- Run the tools with the Python that has `lz4`, `zstandard`, `capstone`, `unicorn` and `numpy` (here
  `C:\Python315\python.exe`, user site-packages). Do not put `C:\msys64\ucrt64\bin` first on PATH: its own Python has
  no numpy and the lift fails. The build scripts find MSYS2's clang and ninja themselves.
- `--seconds S` stops only at the first present after S seconds. A game that never presents runs on, so give every
  test run an outer time limit.
- `TOTK_TRACE=svc,ipc,sched,fs,host` with `TOTK_GPU=null` traces a boot without a window. Repeated `svc 0xb` (sleep)
  lines with the same stack argument mean a thread polling for something.

### 4d. What still ties the engine to particular games (from the review of `main`, 2026-11-20)

- **`tools/build_game.py` picks per-game link wrappers by text in the output path.** `'ff' in str(out)` adds Fast
  Fusion's wrappers, and `mkw` / `mtf` work the same way. Any path containing "ff" (for example, a folder named
  `Effects`) gets Fast Fusion's hooks. It also falls back to Mario Tennis Fever's title ID and resource file (`mtf.rc`), and names the
  translator's ID file `mkw_xlate.id`.
- **One game's knowledge is spread over six places:** `runtime/game_profile.c`, `recomp/patches-<ver>.txt`,
  `tools/data/expected-<ver>.json`, `build_game.py`'s wrapper lists, `__wrap_f_…` functions inside shared runtime files
  (`resolution.c`, `ov_system.c`), and a launcher, installer and `.spec` per game.
- **Hooks name raw addresses** (`f_700006ec74`), which only exist in one build of one game, and fail silently on an
  update.
- **`main` is a product, not the engine.** README, VERSION and remotes are Mario Tennis Fever's. Fast Fusion lives on
  branches 32 commits behind.
- **Config names are mixed.** New code still reads `TOTK_RESOLUTION` and `TOTK_RES_HOOK`, not `NS2_…`.

### 4g. Earlier post-title failure (historical; superseded)

The following sequence documents an earlier, unpatched run only. It is superseded by the user's confirmation that the
separately supplied, fully patched local build works. Do not treat this old crash as a current bug or as the installer
input.

**Reproduce:**
```
set TOTK_GPU=vulkan
set NS2_INPUT_SCRIPT=<local-build-output>\to_level.txt
<local-build-output>\smbw.exe --seconds 45
```
`to_level.txt` presses L + R at tick 800 (the title's "Press L + R to Start"), then A every 2 s. Ticks are 60 Hz of game
time. The run ends at the first A press after the title screen, every time.

**What happens, in order:**

1. **Title screen.** It takes L + R; the next screen starts drawing and new pipelines build.

2. **The game's GPU allocator fails.** It is the engine's own allocator, `f_7000286ef0`, with the debug names
   `gsys::…` / `agl::…`.
   - **The failing request:** `gsys::ModelResource(MatBlock)`, a model's material block of **0x4800 bytes (18 KB)**,
     requested from `main+0x1ff084`.
   - **The failure path:** `f_7000287020` returns false and the allocator takes `L_7000286fe0`, leaving the block's NVN
     memory pool empty.
   - **Twice:** a second request fails the same way just after.
   - **Measured** with a temporary log line in the generated C (since removed).

3. **The game carries on with the empty block and crashes:**
   - `f_700019ace0` copies the block's `{pool, offset}` into the model (`x19+0x178`).
   - `f_70021b7980` creates an NVN buffer in it: `BufferBuilderSetDefaults`, `SetDevice`, `SetStorage(NULL pool)`,
     `nvnBufferInitialize`, then `nvnMemoryPoolGetFlags(NULL)`.
   - The runtime now logs that NULL call with its guest call chain instead of faulting.
   - The game then writes through a null pointer (`memset` at `main+0x19a4f8`, address `0x20`) and the runtime's crash
     reporter stops it.

4. **The GPU heaps the engine created before the failure** (allocations of 1 MB and up):

   | Size | Name |
   |---|---|
   | 4 MB | `agl::driver::GraphicsDriverMgr(TemporayDL)` |
   | 416 MB | `agl::utl::DynamicTextureAllocator` |
   | 4 MB | `agl::utl::DynamicUniformBlockAllocator` |
   | 12 MB | `agl::lyr::RenderDLBuffer` |
   | 15 MB, 31.9 MB, 31.9 MB, 1 MB | Unknown |
   | 3.4 MB | `agl::lght::LightMapMgr(LightMap)` |

   - **The request's descriptor word** (`w1` in the log) is `0x300000100` for MatBlock. That reads as alignment 0x100
     plus a type or flag of 3, so MatBlock comes from one specific heap, which ran out at 18 KB.

**Ruled out:**
- System memory: every `AllocateMemoryPages` / `AllocateAddressRegion` succeeds.
- The DLC: the same crash happens with `aoc-1` hidden.
- The device-info answers: the info IDs the capability code could ask (`0x0a`, `0x71`–`0x73`) were never queried.
- The texture and sampler descriptor pools' getters: now implemented, same crash.

**The leading theory:** the heap MatBlock comes from was sized, or consumed, from numbers the runtime answers
differently than the console, so it is full when the console's would not be. Likely suspects:
- the storage sizes and alignments the runtime reports: `nvnTextureBuilderGetStorageSize` / `…Alignment`,
  `nvnBufferBuilder…`, and `nvnDeviceGetInteger` alignment queries;
- a heap the engine sizes from the display or render resolution (Resolution reports the docked size).

**Next steps, in order:**
1. **Find the heap MatBlock uses.**
   - Log `f_7000287020`'s arguments, and the heap object it reads, the same way as above: a temporary `rt_log` in
     `main_0016.c`, which the next lift overwrites.
   - Find where that heap was created, with what size, and what fills it before the failure.
2. **Compare the runtime's storage-size answers with the console's** for the textures and buffers that heap holds. A
   per-texture `GetStorageSize` log, then check against Ryujinx's/Eden's NVN size rules.
3. **Fix the size rule in the runtime,** not in the game, so every title benefits. Then continue the script into a level.

**A correction:** an NVN proc that is listed in `runtime/nvn_procs.inc` but not implemented does **not** return 0. Its
weak stand-in in `runtime/nvn_procs.c` stops the game with `NVN <name> is not implemented`. The 174 unimplemented procs
therefore fail loudly and by name; they are not behind this crash. They are still worth implementing before titles reach
them: the getters mostly return a stored field.

### 4h. The F1 menu: universal, with a theme library (2026-11-20)

**Stripped, because they did nothing:**
- **Frame Generation** ("Nodix SMFG", "AMD FSR 3 FG", "Intel XeFG"): no frame-interpolation code exists. The status
  panel showed "(3x Active)" anyway.
- **Low latency**, under frame generation: read by nothing.
- **Audio channels:** read by nothing.
- **"Xbox prompts"** pad layout: it needs one game's RomFS patch pack.
- **The status panel's invented names:** "Nodix SMRS (Docked 1620p…)" was the FSR path, and the XeLL line had no XeLL
  code behind it.

**Kept, because they are wired:** the latency line shows NVIDIA Reflex or AMD Anti-Lag 2, which call the real Vulkan
APIs. Checked by searching what reads each menu setting outside the menu.

**The theme library** (`runtime/ui/theme.h`):
- **Dark and Light:** the Mario Kart World PC menu's own palettes. A registered game
  theme is the default until the player sets `NS2_MENU_THEME`.
- **A game's own theme** (`NS2_MENU_THEME=game`): shown as the third option when the running title has one in
  `kGameThemes`, keyed by base title ID:

  | Game | Theme | Look |
  |---|---|---|
  | Mario Tennis Fever | SteelTemple ShadowRacket | turf green, tennis motif |
  | Fast Fusion | SteelTemple SlowSeparation | indigo and magenta, anti-grav craft; from `ff-main-reconcile` |
  | Super Mario Bros. Wonder | SteelTemple WonderBloom | bright sky, warm cream, sunshine yellow, animated blooms and sparkles |

- **Adding a game:** a `Palette`, a `kGameThemes` row, and optionally a motif case in `menu.cpp` `draw_game_motif`.
  Colours and shapes only, no game artwork.
- **Checked** with the menu test hook (`NS2_MENU_TEST=600:20`, `NS2_MENU_TEST_DIR`): every tab in every theme on
  Wonder. The WonderBloom motif sits between the title and the version text, and its sidebar cluster shows only where
  it clears the tabs.
- Set `NS2_MENU_TEST_MOTION=1` when taking test captures intended to show the moving motif; by default the test hook
  holds it still for repeatable screenshots.

**Resolution:**
- **TotK:** its own output and scene patches.
- **MTF:** a patched frame-lines value plus one wrapped function.
- **Fast Fusion's branch:** eight wrapped camera and DLSS functions.
- **Every other title:** the universal hook is the display size the runtime reports (`res_display_size` →
  `nn::oe::GetDefaultDisplayResolution`), which the Resolution row sets. Whether a title renders at that size is the
  title's choice. Not yet measured on Wonder.

### 4i. Per-game exe icons from the user's cover art (2026-11-20)

- **The source:** the user keeps a folder of cover art, one picture per game named by its title, and adds to it over
  time. It's set as `[assets] icons` in `config.local.toml`, or `NS2_ICON_DIR`, or `--icons`.
- **Matching** (`tools/game_icon.py`): the build matches the container's own title name from `title.json`, letters and
  digits only, then by containment, then by word overlap. All seven known titles matched their pictures; an unknown
  title matches none.
- **Embedding:** `build_game.py --icon` makes a 16-256 px `.ico` and a `.rc` in the build folder, and the exe carries
  it. `build --folder` passes it automatically.
- **Nothing from the folder enters the repository.**


### 4j. Frame rate: 60 fps at the right speed; 90 and 120 not yet (2026-11-20, Claude after Gemini)

**The bug:**
- **The controller:** Wonder's engine runs an adaptive frame-rate controller, `f_70001bbee0`, called each frame. It sets
  `vsyncs = toint(measured_seconds * 60 + 0.05)`, `interval = clamp(vsyncs + 1, 1, 2)` and `rate = 60 / interval`.
- **On a PC:** the measured time includes the host's pacing (16.3-16.6 ms at 60 fps), so the controller picked interval
  2 and a 30 fps rate.
- **The double speed:** the runtime's real-time pacer (`frame_step_realtime()` is true unless `DKB_REALTIME=0`)
  presented at 60 anyway. The engine's VFR steps the game by interval x 1/60 s per frame, so the game ran at double
  speed. `DKB_REALTIME=0` honours interval 2 and gives a correct-speed 30 fps.

**The fix:** `recomp/patches-smbw100.txt`, set `fps60` (`NS2_FPS60`, on by default).
- `main+0x1bbf64` `fcvtzs w9, s0` becomes `mov w9, wzr`, so the interval stays 1 and the rate stays 60.
- `runtime/frame_rate.c` `frame_limit_live` switches the set off at a 30 fps limit, as for TotK.
- **Verified (30 s, Vulkan, input script):** `patches: fps60 on`, no interval changes, every window 60.0 fps with
  interval 1/2/3+ 120/0/0, 1,790 frames, 0 validation errors, 0 FATAL. It reaches "Select How to Play".

**Diagnostic added:** `nvnWindowSetPresentInterval` logs its first 8 interval changes with the guest call chain. That's
how any title's frame-rate controller is found.

**90 / 120 fps: partly built, off by default.**

- **The VFR step:** found right after the controller call. `main+0x1bb9d0`…`9f0` computes `60.0 / rate` and stores it at
  `main+0x3aac460` (1.0 at 60 fps, 2.0 at 30).
- **The patch:** set `realtime`, switch `NS2_VFR_REALTIME`, default **0**. It reads the measured step instead: page +0
  is seconds x 30, doubled.
- **The runtime:**
  - `frame_rate.c` accepts limits of 30, 60, 90 and 120. It allows above 60 only while the title's `realtime` set is on
    (`step_patched`); otherwise it caps at 60.
  - The menu row offers exactly 30 / 60 / 90 / 120. The old 144/165/240/"display" entries were clamped to 60 and did
    nothing.
- **Why it is off:**
  - With it on, 60/90/120 hold their rates (perf: speed 1.000). But in 30 s of wall time the 90 and 120 runs reached
    the character select while the 60 run was still on "Select How to Play".
  - The menus, and possibly more of the game, count whole frames rather than using the step.
  - The global has only one other direct reader (`f_7000026410`, a timer that adds it per object). The rest of the
    game's per-frame time comes from elsewhere, most likely the integer interval or rate (ctrl+0x40 / +0x50,
    system+0x88), which `fps60` holds at 1 and 60.
- **Next:**
  1. Find the per-frame consumers: the layout (UI) animation step, and the gameplay update's frame advance.
  2. Feed each the measured step.
  3. Then re-check by game progress per wall second, not by the runtime's speed line (it only describes the value
     written to the page).

**Verified defaults:** a 120 limit runs at 60.0 fps (`realtime off`); `NS2_VFR_REALTIME=1` gives 120.0 fps.

**Clean-up pending (Gemini's uncommitted changes in `runtime/nvn_api_obj.c`):**
- **Revert the `o->pace` fallback in `nvnWindowAcquireTexture`:** fps_base and fps_fix measure the same.
- **Move `smbw_clamp_crop` to per-title data:** it names "smbw" in the shared runtime.


### 4k. Stability and hitches (2026-11-20, evening)

**Crash on starting the first level: fixed for every title.**
- **The cause:** the play-report API (`nn::prepo`, telemetry) was stubbed one function at a time, 12 of the 33 Wonder
  imports. `SetBuffer` was a stub, so the report had no buffer, while `PlayReport::Add(const char*, Any64BitId)` still
  ran the SDK's report builder, which read address 0 (`ReportGenerator::CheckKeyDuplication`).
- **The fix:** `runtime/hostfn.c` answers whole SDK families by name prefix. Every `nn::prepo` function without its own
  override returns 0 (success, nothing done), except `GetOverSaveFrequencyLimitEvent` (an event), which keeps its own
  code.
- **Verified:** a 105 s scripted run into the level, with no fault.

**Shader hitches: ahead-of-time library prebuild, on by default.**
- **The setting:** `TOTK_LIB_PREBUILD_KEEP` defaults to 1500 (it was 0). At boot, idle-priority threads build the vertex
  and fragment pipeline libraries of up to 1500 variants met in earlier play, so a new pipeline only fast-links
  (0.01 ms).
- **A/B on the same 100 s route, no `--shot`:**

  | | Before | After |
  |---|---|---|
  | Library misses | 242 | 0 |
  | Pipeline waits | 65 | 2 |
  | Frames over 25 / 50 / 100 ms, first 60 s | 28 / 14 / 8 | 9 / 2 / 1 |
  | 1% low, last stretch | 27 fps | 56 fps |
  | Peak memory | 3.6 GB | 3.6 GB |

- **Note for testing:** `--shot` turns background pipeline building off (`boot.c`: a screenshot must not depend on build
  timing), so measure hitches without it.

**Fullscreen start showed a cropped picture: fixed.**
- **The cause:** the swapchain was made at the windowed 1920x1080 before the window reached 3840x2160, and no resize
  event followed. Toggling fullscreen fixed it.
- **The fix:** `runtime/gfx_present.c` compares the client size with the swapchain at each present and rebuilds on a
  mismatch, once per window size.

**Prepare graphics during setup.**
- The installer scans supported shader containers in the player's RomFS and ExeFS, including compressed and nested
  archives. BNSH Switch 2 shaders go through the same SM86 lowering used during play. Setup prepares shaders and stage
  libraries from the final install folder so the Vulkan driver can reuse its cache.
- Setup then runs the Wonder 1.0.0 intro for 105 game seconds with a temporary profile, no sound, and no controller or
  keyboard input. The checked-in route supplies the input. The game records exact graphics state as it draws, including
  all active graphics stages and the full vertex input layout. The next boot reuses compatible records from
  `pipeline-keys.bin`. It can still read the earlier version 3 records.
- Private testers with the same game version can use `tools/prepare_shaders.py --full-scan --variant-hints <answers>`
  with a trusted recorded `shader-answers.bin`. The tool matches shader hashes against the target's local game files and
  computes the input IDs on that PC. An empty test install can load known-version `pipeline-keys.bin` records as well.
  Any pipeline whose shader is absent from the local scan waits until the game encounters it. Keep hints and recorded
  keys outside release packages. Vulkan's `pipeline-cache.bin`, translated shaders, and captured shader programs stay on
  the machine that generated them.
- Compiler PGO is separate. On MasterSword it measured no gain on top of the measured hot split, so measure before
  adopting it.

## 5. Self-correction: what the tool does on its own now

### 5a. The bring-up loop (`tools/bringup.py`, `universal_ns2_to_pc.py bringup` / after `port`)

Each round runs the built title headless (`TOTK_GPU=null --seconds S`, inside an outer time limit) and reads the log:

| Stop | What it means | What the tool does |
|---|---|---|
| **passed** | frames presented, S seconds reached | done; a Vulkan run saves `bringup_shot.png` and checks validation and shader errors |
| **fault** at an SDK function's entry (`in lifted function … (_ZN2nn…+0)`) | that function's system service is missing on a PC | tries generic answers (`ret1`, `ret0`, `noop`, likeliest first by the function's name) and keeps the first that **helps** |
| **poll** (the runtime's poll detector) | a thread sleeps from the same frame 500 times | logs the guest call chain; if it names an SDK function, tries it as a fault, answering "ready" first |
| **fatal**, **stalled** | a named runtime error, or nothing at all | recorded for a person |

- **What counts as "helps":** the game presents frames, or it reaches another missing SDK service (this hole is
  filled, the next one shows).
- **What doesn't:** a crash in the game's own code right after. A generic answer that hands back nothing usable (a
  font, a buffer) only moves the crash.
- **How it stops:** when none of the three answers helps, the loop stops and reports *needs a real implementation*. It
  never keeps a bad answer.

Where answers are kept:
- **Per title:** `<exe dir>/learned_overrides.txt`.
- **Shared, for every later title:** `knowledge/learned_overrides.txt`, but only once the title actually boots with the
  answer. It is copied beside each build as `learned_overrides.shared.txt`.
- **Loading them:** `runtime/learned_overrides.c` registers both files before the modules bind. A real implementation
  (`HOST_OVERRIDE`) always wins over a learned answer, every learned answer is logged, and `NS2_LEARNED=0` turns them off.

Every run writes `bringup_report.md` / `.json` beside the exe: each round, the polling chain, and the NVN procs the
runtime lacks.

**Tested on Wonder by taking a service away** (`NS2_UNHOOK=<symbol>` leaves a linked override out, `runtime/hostfn.c`).
With the font service removed, the loop:
1. found the fault in `GetBuiltInFontData`;
2. tried "true": a crash in game code (no font behind it);
3. tried "false": the 1 ms poll loop;
4. tried "do nothing": the same loop;
5. stopped with *needs a real implementation*, and left the shared knowledge empty.

That is the right answer: a font has to be served, which the font service does. For the many system calls whose only
job is "succeed" or "report ready" (online, telemetry, parental controls and the like), the loop finds and records the
answer by itself.

### 5b. Diagnostics added for this

- **Poll detector** (`runtime/kernel.c`, `SleepThread`): 500 sleeps from the same guest frame log the guest call chain
  once. `NS2_POLL_LOG=0` turns it off. It found Wonder's second blocker in one run.
- **`NS2_UNHOOK=<symbol>[,…]`** (`runtime/hostfn.c`): run a title without one of the runtime's services.

## 6. Where the tool should go: the target design

1. **A folder per title, keyed by title ID: `games/<TITLEID>/`.** It holds:
   - `game.toml`: name, short name, versions and their ExeFS hashes, exe/ini names, default resolutions, quirk flags,
     link wrappers;
   - `patches-<ver>.txt`;
   - `hooks.c`, compiled only into that game;
   - optional launcher art.

   The engine reads the manifest of the title it is building and never names a game. Adding a game means adding a folder,
   and `init` writes the first version of it.
2. **One shared knowledge base the tool learns into: `knowledge/`.** It holds:
   - the host overrides;
   - the NVN procs;
   - the SM86 opcode coverage;
   - known quirk patterns ("games importing X need Y").

   `scan` reads it to say what a new game is missing. A fix for one game adds an entry, so the next game's scan already
   knows. This is what "designed to learn" needs: learning that lands as data the tool reads back.
3. **Hooks found by pattern, not by address.** Each hook records a byte signature and the module it lives in. The lifter
   finds it, and the build stops if it isn't there, instead of linking a wrapper onto the wrong function after an update.
4. **One launcher and one installer**, driven by the manifest: its name, icon, hashes and defaults. Not one per game.
5. **A regression runner over every dump the user has.** For each registered title found on the PC, it:
   - builds it;
   - runs `--selftest`;
   - plays a short scripted headless run;
   - compares a few screenshots and the frame rate.

   Run it after every engine change. This is what keeps "one engine" honest: a fix for one game must not break another.
6. **The engine is versioned on its own.** Game builds record the engine version they were made with.

## 7. Next steps

1. **Wonder past its first screen** (4g): find the heap the engine's MatBlock request comes from, why it is full (the
   runtime's storage sizes and alignments against the console's), and fix the size rule in the runtime. Then continue
   the input script into a level.
2. **The 174 unimplemented NVN procs:** they stop the game by name, so `bringup` already reports them. Implement the
   getters ahead of time: most return a field the runtime stores.
3. **Theme library as data:** move `kGameThemes` palettes to `games/<TITLE_ID>/game.toml` (read at start), so a theme is
   added without a rebuild.
4. **Teach `bringup` to drive input** (the `NS2_INPUT_SCRIPT` format in 4g), so "passed" can mean "reached gameplay".
5. **Move `build_game.py`'s per-game settings into `games/<TITLE_ID>/game.toml`:** the path-based wrapper lists, the MTF
   title-ID fallback, `mtf.rc`, `mkw_xlate.id`.
6. **Decode the control block** (NUP record 2) for the real display version and localized names. The menu's version
   line shows "update 040015100B514001" without it.
7. **Test the update path** on a container with an update package.
8. **Measure the universal resolution hook on Wonder.**

## 8. Debugging recipes (what worked on Wonder)

| Question | Tool |
|---|---|
| Where did it crash? | The crash reporter names the lifted function, its exported SDK symbol when there is one, and the guest frames. For a crash in runtime code (`totk+0x…` past the end of the lifted code, `exe+0xb303290` here), look the address up in `<build>\<short>.map` (RVA to symbol). |
| Why is it stuck? | The poll detector (`runtime/kernel.c`, `NS2_POLL_LOG`) logs the guest call chain of a thread that sleeps from one frame 500 times. |
| What did it call? | `TOTK_TRACE=svc,ipc,sched,fs,host,gfx` (pick a subset; `gfx` logs NVN calls). |
| What does a game function do? | Read `dump\generated\smbw100\main\main_NNNN.c`: `grep -l "^void f_<addr>(Cpu \*c) {"`. Calls through `0x7003a57xxx` are the game's NVN function-pointer table. |
| Which strings or names? | `decode_nso_sections` (`tools/universal_ns2_to_pc.py`) on `exefs\main`, then read the bytes at `main+offset`. Allocators pass debug names. |
| A value at run time? | A temporary `rt_log` in the generated C file, then `tools/build_game.py` with the build's arguments (no re-lift). The next lift restores the file. Keep a copy and restore it when done. |
| Without one of our services? | `NS2_UNHOOK=<mangled symbol>`. |
| See the menu? | `NS2_MENU_TEST=600:20` + `NS2_MENU_TEST_DIR=<dir>` + `NS2_MENU_THEME=dark\|light\|game`. |
| A screenshot? | `--seconds S --shot name.png` with `TOTK_GPU=vulkan`. Use a file name without spaces, relative to the build folder. |
