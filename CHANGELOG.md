# Changelog

## 0.2.1 · 2026-11-22

WonderBloom **0.2.1** fixes save folder placement on Setup installs, adds cross-gen Switch 2 selection for `.nup` containers, and warns immediately if a Switch 1 copy of Wonder is selected.

### Fixed

- Fixed saves and local account data on fresh Setup installs being written to the temporary `NS2 Setup Files ...` workspace instead of `<install folder>\profile`.
- Preferred Switch 2 (`0400...`) packages automatically when extracting cross-gen `.nup` containers that include both Switch 1 and Switch 2 versions.
- Added an immediate check in Setup that reports a clear error if a Switch 1 copy of Super Mario Bros. Wonder (`010015100B514000`) is selected instead of spending several minutes building an incompatible binary.

## 0.2.0 · 2026-11-21

WonderBloom **0.2.0** promotes the Windows port from Alpha to a full release, resolving installer failures with add-on content and in-place updates alongside gameplay stability and display fixes.

### Fixed

- Fixed setup failing with `Manifest includes an unrecognized binary cache or game-data file: aoc-1/aoc-index.bin` when installing `.nup` packages or prepared builds that include add-on content.
- Fixed game-folder installs silently skipping add-on content (`aoc/` and `aoc_packed/`).
- Fixed updating an existing install failing when a newer version adds files inside a new subfolder (such as `aoc-1/`).
- Accepted Windows OneDrive-synced folders in setup without misidentifying them as symbolic links, and isolated the bundled setup Python from host `PYTHONPATH`/`PYTHONHOME` settings.
- Fixed GPU crashes when deflecting projectiles as Elephant Mario on NVIDIA graphics cards (`FIX_SABS_MINMAX=auto` safely lowers integer `SAbs`/`SMin`/`SMax` select patterns at pipeline creation).
- Fixed mid-level freezes and graphics driver resets caused by unbounded shader loops by enforcing a safe shader loop guard (`vk: loop guard:` logged when triggered).
- Fixed `fullscreen = 1` starting in windowed mode instead of launching fullscreen.

### Changed

- Promoted WonderBloom from Alpha `0.1.0a` to full release `0.2.0`.

## 0.1.0a Alpha · 2026-11-21

The first WonderBloom release runs Super Mario Bros. Wonder **1.0.0** on the **SteelTemple Universal NS2 Engine**. The launcher and F1 menu show the game version and the PC build label **Alpha 0.1.0a** separately.

### Added

- A native start screen with Play, Profile, Theme, Display, startup visibility and Quit controls.
- A shared WonderBloom theme for the installer, launcher and in-game F1 menu, with animated flowers and sparkles.
- A local installer for a prebuilt output folder. It reads a generated file manifest and uses an explicit selection of local game data.
- Install from a `.nup` file or game folders. Choose the source and destination, then setup prepares the game using its bundled tools.
- Setup compiles Switch 2 shaders on the player's PC and runs the Wonder intro in the background to prepare the graphics pipelines it uses.
- The launcher checks for WonderBloom releases and shows a short changelog with an **Update now** button.
- A PS4/PS5 touchpad-click event path for toggling the in-game F1 menu. The click-edge selftest passes; physical-controller verification is still outstanding.

### Changed

- Corrected the port label to **Alpha 0.1.0a** and the Wonder game label to **1.0.0**.
- Added the SDL3 Dear ImGui backend attribution to [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
- Tightened repository content checks for local game files, settings, screenshots and build output.

### Distribution

- The Windows download is a ZIP containing only the standalone Setup EXE. Game data, keys, personal settings, saves, screenshots, logs, caches and cover art stay local.
- Setup uses a private working folder beside the install destination. Shader and pipeline caches stay with the installed game.
