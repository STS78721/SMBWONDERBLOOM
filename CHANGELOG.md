# Changelog

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
