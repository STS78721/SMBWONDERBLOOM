<p align="center"><img src="installer/assets/setup-bloom.png" width="112" alt="WonderBloom flower"></p>

<h1 align="center">Super Mario Bros. WonderBloom</h1>

<p align="center">Native Windows recompilation of Super Mario Bros. Wonder</p>
<p align="center">Built on the <strong>SteelTemple Universal NS2 Engine</strong></p>

<p align="center">
  <a href="https://github.com/STS78721/SMBWONDERBLOOM/releases/tag/0.2.1"><img alt="Release 0.2.1" src="https://img.shields.io/badge/Release-0.2.1-4a874e"></a>
  <img alt="Windows x64" src="https://img.shields.io/badge/Windows-x64-217dac">
  <img alt="Game version 1.0.0" src="https://img.shields.io/badge/Game_version-1.0.0-4a874e">
</p>

<p align="center">
  <a href="https://github.com/STS78721/SMBWONDERBLOOM/releases/tag/0.2.1"><strong>Download Setup</strong></a> ·
  <a href="#quick-start">Quick Start</a> · <a href="#features">Features</a> ·
  <a href="#status">Release Status</a> · <a href="#credits">Credits</a>
</p>

> Use your own copy of Super Mario Bros. Wonder **1.0.0**. Your game files, saves, settings and cover art stay on your PC.

## Quick Start

1. Download `SteelTemple-SMBWONDERBLOOM-0.2.1-Full-Setup-Wizard.zip` from the [0.2.1 release](https://github.com/STS78721/SMBWONDERBLOOM/releases/tag/0.2.1). Extract and open **Super Mario Bros. WonderBloom Setup.exe**.
2. Choose **Install from game folders** and select your RomFS with its matching ExeFS alongside it. Setup also accepts a `.nup` file. Choose where to install and allow about **60 GB** of free space for setup.
3. Open WonderBloom and press **Play**. Press **F1** for in-game settings.

## Features

- Animated WonderBloom setup and a start screen with Dark, Light and WonderBloom themes.
- Shader preparation on your GPU and a short background pass that builds the intro’s graphics pipelines.
- Player profile, display settings and release checks from the start screen. The launcher shows a short changelog when an update is available.
- In-game settings with **F1** and touchpad-click support for DualShock 4 and DualSense controllers.

## Release Status

Setup targets Windows 10 or later on a 64-bit CPU with AVX2 and a Vulkan 1.3 GPU. The standalone installer has been verified for game-folder installs (including add-on content), updating existing installs in place while preserving saves and settings, `.nup` add-on extraction, graphics preparation, and live gameplay. Touchpad support passed the input self-test; physical PlayStation controllers still need hardware verification. New scenes may compile additional pipelines as you play.

See the [patch notes](docs/release-v0.2.1.md) for the full 0.2.1 changes and the [installer guide](docs/installer.md) for source options.

## Build from Source

The [build guide](docs/building.md) covers the toolchain and the [installer guide](docs/installer.md) covers building the standalone setup. To build a PC executable from a local game dump with the SteelTemple Universal NS2 Engine, run this command from a configured checkout.

```powershell
python tools/universal_ns2_to_pc.py build --folder "<local-dump-folder>"
```

## Credits

SteelTemple developed the Universal NS2 Engine that powers WonderBloom. The [third-party notices](THIRD_PARTY_NOTICES.md) credit upstream contributions from TotK Recomp, LAS Recomp, MKW Recomp, Eglantine, MacNativeGames and others. The engine is distributed under [GPL-3.0-or-later](LICENSE), with [MIT terms](LICENSE-MIT) retained where applicable.
