# Installer

## Super Mario Bros. Wonder 1.0.0

The port label is **0.2.1**. These versions identify different things: **1.0.0** is the Wonder game version, and **0.2.1** is the port build version.

The standalone Windows EXE includes the tools it needs to prepare your game. Your game files, keys, settings, saves and cover art stay on your PC.

## Start the installer

Open the standalone WonderBloom Setup EXE. If you downloaded the ZIP, extract `Super Mario Bros. WonderBloom Setup.exe` first.

- Choose **Install from a game file** to use your own `.nup` file.
- Choose **Install from game folders** to use your ROMFS folder with its matching ExeFS next to it. You can also point setup at the folder that contains both.
- Choose where to install the game and click **Install**.

Allow about **60 GB of free space** while setup prepares the game. Setup keeps its working files in a new folder beside the install folder. A retry starts in a fresh folder. Use an empty install folder or the folder where this setup already installed the same game.

## Install from a prepared folder

Choose **Use a prepared folder** if you already have a local game build.

Select a compiled output folder containing `ns2-build-manifest.json`. A discovered folder build from
`tools/universal_ns2_to_pc.py build --folder <dump>` writes that manifest when the ExeFS and packed RomFS use the supported paths. The manifest records the game title, game and port versions, title ID, exact runtime file list, ExeFS hashes, and the permitted RomFS source path and size. It stores no absolute machine paths or game contents. Rebuild a folder with no manifest to create one; use a separate `--out` path if the existing output must remain untouched.

When the compiled folder does not include portable ExeFS and RomFS, select the matching local game-data folder. For Wonder, it must contain `exefs/` and `romfs_packed/romfs.bin`. The installer checks the listed ExeFS SHA-256 hashes and the expected RomFS image size, then copies those exact files along with the manifest-listed runtime files. It does not recurse through either source folder. It skips settings, profiles, saves, logs, screenshots, object files and caches.

Choose an install destination separate from both source folders. A first install requires an empty destination. An update requires an installer marker for the same game. Updates replace only files recorded by that marker and preserve unrelated settings, saves and files already in the destination.

## Build the installer from source

Run `python -m installer.local_build_gui` to open the installer from a checkout with the local build dependencies already set up. Building the portable Windows package requires PyInstaller, Pillow, and a prepared dependency cache:

```powershell
python tools/build_local_build_installer.py --portable --tool-cache "<tool-cache>"
```

The standalone EXE, the optional ZIP containing that EXE, and their checksums go under ignored `build/local-build-installer/release/`. Setup unpacks its internal tools to a temporary folder during a local build. See [building.md](building.md) for developer setup.

Use the game or repository name in the executable filename, window title, and Windows file details. The shared installer name is defined in `installer/setup_brand.py`.

### Display sizing

Size the installer to the usable area of the monitor where it opens, and lay out each page using the current window size. Keep text readable and all controls reachable as the window resizes. Check the packaged installer at compact laptop resolutions, on wide and 4K displays, and with Windows display scaling above 100%. Include a check where the installer moves between monitors with different scaling.

The artwork uses a separate flower layer, orbit, and stars. The welcome screen follows the Windows animation setting by default. Players can start or pause the motion on the artwork. Rebuild the original artwork by running `python installer/assets/generate_setup_art.py` with Pillow and NumPy installed.

### What setup does

For a `.nup` file, the installer verifies file hashes during extraction and includes matching updates and add-ons in the package. For game folders, the installer stages the required data and packs loose ROMFS in its working folder. It then runs:

```text
tools/universal_ns2_to_pc.py port --folder <workspace>/dump --no-bringup --seed-shaders-only
```

The installer uses the generated manifest to check ExeFS hashes and the expected RomFS size, then copies the listed files to the install folder.

### Graphics preparation

Setup scans supported shader containers in your game files, including Switch 2 shaders, and compiles the shaders on your PC. For Wonder 1.0.0 it then plays a short intro in the background to build the exact graphics pipelines used there. This pass uses a temporary profile and muted audio. The **Skip graphics preparation** option lets you finish setup early. New scenes can still need new pipelines, which the game records for later launches.

Each PC builds its graphics cache from its own game files and GPU. The setup package includes the intro input script. The compiled shaders and graphics pipelines stay in the installed game folder.

## Documentation and verification

- Build tools and dependencies: [`building.md`](building.md)
- Current project handover and Wonder status: [`UNIVERSAL_TOOL.md`](UNIVERSAL_TOOL.md)
- Local installer source and generated manifest: `installer/local_build_gui.py`, `installer/nup_workflow.py`, `installer/local_build.py`

Lightweight validation commands (they do not use a real game dump):

```powershell
python -m unittest tests.local_build_test tests.local_build_manifest_test tests.nup_workflow_test -v
python -m installer.local_build_gui --selftest --shots "<local-temp-folder>"
```
