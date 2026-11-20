# Super Mario Bros. WonderBloom — Alpha 0.1.0a

The first WonderBloom PC alpha brings Super Mario Bros. Wonder 1.0.0 to Windows with an animated setup and launcher. It runs on the SteelTemple Universal NS2 Engine, developed by SteelTemple.

## ■ Major Updates

- Install from your own `.nup` game file or game folders. Pick your source and where to install.
- Setup prepares Switch 2 shaders from your copy and learns graphics pipelines before you play.
- The start screen checks for later WonderBloom releases and shows a short changelog. Choose **Update now** to open the matching GitHub release.

## ■ New & Improvements

### ○ Setup

- The dark WonderBloom wizard sizes itself to the available display area. Its flower artwork animates, follows the Windows motion preference, and can be paused from the welcome screen.
- Graphics warm-up runs with a temporary player profile and saves the pipelines it learns in the installed folder for your next play session.
- Choose **Use a prepared folder** if you already have a compatible local PC build.

### ○ Launcher and in-game settings

- Choose Dark, Light, or WonderBloom. Set your player name in **Profile**, switch your display mode, and choose whether the launcher opens at startup.
- Press **F1** or click the touchpad button on a DualShock 4 or DualSense to open or close the in-game settings.

## ■ Bug Fixes

- Corrected the version labels shown to players. **1.0.0** is the game version. **Alpha 0.1.0a** is the PC port version.

## ■ Other

- The Windows download is a ZIP containing only the standalone Setup EXE. Your game files, keys, cover art, saves, settings, and graphics caches stay on your PC.
- Graphics preparation reuses the shaders and pipelines it finds or learns. New scenes can still create pipelines during gameplay.
- A fresh game-folder install, graphics preparation and a game boot passed local testing. The `.nup` path was tested with synthetic packages. Physical PlayStation controllers still need verification.

## ■ Update

1. Download `SteelTemple-SMBWONDERBLOOM-0.1.0a-Full-Setup-Wizard.zip`. Extract and open **Super Mario Bros. WonderBloom Setup.exe**.
2. Choose **Install from game folders** for a RomFS folder with its matching ExeFS alongside it, or **Install from a game file** for a `.nup`. Choose where to install and click **Install**. Allow about 60 GB of free space while setup prepares the game.
3. Open the start screen and press **Play**. Future updates appear there as they become available. [WonderBloom releases](https://github.com/STS78721/SMBWONDERBLOOM/releases)

**Setup ZIP SHA-256** `2ab27459fa59323479f923840c3ae8bf6ffdabaf4a00ed63e8612b75149133f0`
