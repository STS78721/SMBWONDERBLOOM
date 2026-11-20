# games/: one folder per title, named by its title ID

Everything the engine needs to know about one game lives here, so the engine itself never names a game
(docs/UNIVERSAL_TOOL.md, "Target design"). `<TITLE_ID>/game.toml` holds:

| Key | Used by | Meaning |
|---|---|---|
| `short_name`, `display_name`, `ini` | build, runtime, launcher | names; the exe is `<short_name>.exe` |
| `quirks` | runtime (`game_profile.c` `GAME_QUIRK_*`) | per-title runtime behaviour switches |
| `resource` | `tools/build_game.py` | `runtime/<resource>.rc` (icon, manifest); default `totk` |
| `runtime_lib`, `xlate_names` | `tools/build_game.py` | release library name and shader translator copies |
| `[link] wrap` | `tools/build_game.py` | lifted functions the runtime wraps (`-Wl,--wrap,<name>`) |
| `[link] wrap_if_module` | `tools/build_game.py` | the same, only when that module is linked |

The folder name is the application's base title ID (an update's or program's ID masked with `0xFFFFFFFFFFFFE000`).
Game data never goes here: names, hashes, addresses and settings only.
