# Super Mario Bros. WonderBloom — 0.2.0

WonderBloom **0.2.0** is the first full Windows release of Super Mario Bros. Wonder **1.0.0** on the **SteelTemple Universal NS2 Engine**. It resolves installer failures for packages and folders containing add-on content, fixes in-place updates, and addresses gameplay crashes and fullscreen startup.

## ■ Major Fixes

- Fixed GPU crashes and device resets when deflecting projectiles as Elephant Mario on NVIDIA graphics cards (`FIX_SABS_MINMAX=auto` safely rewrites affected shader integer select instructions at pipeline build time).
- Fixed mid-level freezes where the screen locked for several seconds before closing. Shader loops now stop at a safe limit (`vk: loop guard:` is written to `logs\smbw.log` if reached) so play continues safely.
- Fixed the game starting in a window even when fullscreen mode was enabled in settings.

## ■ Setup & Installer

- Fixed setup failing on `aoc-1/aoc-index.bin` during `.nup` and prepared-folder installs that include add-on content.
- Game-folder installs now include matching add-on content (`aoc/` and `aoc_packed/`) alongside ExeFS and RomFS.
- Updating an existing WonderBloom folder (`Alpha 0.1.0a` or later) now preserves saves and settings even when the new version introduces files in new subfolders such as `aoc-1/`.
- Setup now supports Windows OneDrive-synced folders cleanly while continuing to block symbolic links and junctions, and isolates its bundled setup tools from host Python environment variables.

## ■ Other

- The Windows download is a ZIP containing only the standalone Setup EXE. Your game files, keys, cover art, saves, settings, and graphics caches stay on your PC.
- The first launch after updating may briefly rebuild graphics pipelines. New scenes can still compile additional pipelines during gameplay.
- Existing `Alpha 0.1.0a` launchers will automatically detect `0.2.0` on the start screen and link directly to this release.

## ■ Update

1. Download `SteelTemple-SMBWONDERBLOOM-0.2.0-Full-Setup-Wizard.zip`. Extract and open **Super Mario Bros. WonderBloom Setup.exe**.
2. Install to a new folder, or choose your existing WonderBloom folder to update in place while keeping your saves and settings. Allow about 60 GB of free space while setup prepares the game.
3. Open the start screen and press **Play**. [WonderBloom releases](https://github.com/STS78721/SMBWONDERBLOOM/releases)

**Setup ZIP SHA-256** `2f82b4d0123f7f4594b3d4983846663d7fe213e746da4fdcf087b3efb9aece2e`
