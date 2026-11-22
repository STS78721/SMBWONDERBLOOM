# Super Mario Bros. WonderBloom — 0.2.1

WonderBloom **0.2.1** is a maintenance update for Super Mario Bros. Wonder – Nintendo Switch 2 Edition (**1.0.0**). It fixes save data placement on Setup installs, ensures multi-edition `.nup` files pick the Switch 2 Edition automatically, and gives an immediate error if a Switch 1 copy is selected.

## ■ Fixes

- **Saves now stay inside your install folder:** Fresh Setup installs previously fell back to the temporary `NS2 Setup Files ...` workspace for `profile\account.uid` and saves when no `profile\` folder existed yet. WonderBloom now always creates and uses `<install folder>\profile` beside `smbw.exe`.
- **Automatic Switch 2 package selection in `.nup` containers:** When a `.nup` file contains both the Switch 1 version (`010015100B514000`) and the Switch 2 Edition (`040015100B514001`), Setup now selects the Switch 2 Edition automatically while keeping add-on content alongside it.
- **Immediate Switch 1 detection in Setup:** If you select a Switch 1 copy of Super Mario Bros. Wonder (`010015100B514000`) with no Switch 2 Edition package present, Setup now stops immediately and tells you clearly instead of spending several minutes compiling an incompatible executable.

## ■ Other

- If you installed `0.2.0` and already created save data, check whether a `profile` folder exists under your temporary `NS2 Setup Files ...\dump\profile` folder and copy it into `<install folder>\profile` before deleting the temporary folder.
- Existing `0.1.0a` and `0.2.0` launchers automatically detect `0.2.1` on the start screen.

## ■ Update

1. Download `SteelTemple-SMBWONDERBLOOM-0.2.1-Full-Setup-Wizard.zip`. Extract and open **Super Mario Bros. WonderBloom Setup.exe**.
2. Install to a new folder, or choose your existing WonderBloom folder to update in place while keeping your saves and settings. Allow about 60 GB of free space while setup prepares the game.
3. Open the start screen and press **Play**. [WonderBloom releases](https://github.com/STS78721/SMBWONDERBLOOM/releases)

**Setup ZIP SHA-256** `821bc2bae1872df165c5e9c916739c656ce18ade0917f1b4b053a012df03646a`
