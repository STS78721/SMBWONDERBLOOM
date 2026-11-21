"""Safety checks for installing a synthetic compiled build from a local manifest."""

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from installer.local_build import (  # noqa: E402
    MANIFEST_NAME,
    MARKER_NAME,
    LocalBuildError,
    install_local_build,
    prepare_installed_shaders,
)


class LocalBuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "local-build"
        self.source.mkdir()
        self.game_data = self.root / "dump"
        (self.game_data / "exefs").mkdir(parents=True)
        (self.game_data / "romfs_packed").mkdir()
        (self.game_data / "exefs/main").write_bytes(b"synthetic main module")
        (self.game_data / "exefs/sdk").write_bytes(b"synthetic sdk module")
        (self.game_data / "romfs_packed/romfs.bin").write_bytes(b"synthetic RomFS payload")
        (self.game_data / "settings.ini").write_text("private setting", encoding="utf-8")
        (self.game_data / "profile").mkdir()
        (self.game_data / "profile/save.dat").write_bytes(b"private save")
        (self.game_data / "shader-cache").mkdir()
        (self.game_data / "shader-cache/cache.bin").write_bytes(b"private cache")
        self.dest = self.root / "installed"
        self.write_build()

    def write_build(self, *, game_id="synthetic.game", game_version="1.0.0", port_version="0.1.0",
                    files=None, extra_files=()):
        files = files or ["app.exe", "runtime/SDL3.dll", "launcher_icon.png", "romfs-index.bin",
                          "aoc-index.bin", "aoc-1/aoc-index.bin", "aoc-1/romfs.bin", "seed-answers.bin",
                          "seed-programs.bin", "shader-answers.bin", "shader-programs.bin",
                          "shader-prepared.bin", "romfs-patches/manifest.tsv"]
        (self.source / "runtime").mkdir(exist_ok=True)
        for relative in files:
            path = self.source.joinpath(*relative.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("synthetic " + relative).encode())
        for relative in extra_files:
            path = self.source.joinpath(*relative.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"unlisted synthetic data")
        data = {
            "schema": 1,
            "game_id": game_id,
            "game_title": "Synthetic Game",
            "game_version": game_version,
            "port_version": port_version,
            "executable": "app.exe",
            "files": files,
            "game_data": {
                "exefs_dir": "exefs",
                "exefs_sha256": {
                    "main": hashlib.sha256((self.game_data / "exefs/main").read_bytes()).hexdigest(),
                    "sdk": hashlib.sha256((self.game_data / "exefs/sdk").read_bytes()).hexdigest(),
                },
                "romfs_path": "romfs_packed/romfs.bin",
                "romfs_size": (self.game_data / "romfs_packed/romfs.bin").stat().st_size,
            },
        }
        (self.source / MANIFEST_NAME).write_text(json.dumps(data), encoding="utf-8")

    def test_installs_only_manifest_files_and_marks_destination(self):
        self.write_build(extra_files=("unused/developer.log", "unused/settings.ini"))
        events = []
        result = install_local_build(self.source, self.dest, lambda *event: events.append(event),
                                     game_data_dir=self.game_data)

        self.assertEqual(result.game_id, "synthetic.game")
        self.assertEqual(result.game_version, "1.0.0")
        self.assertEqual(result.port_version, "0.1.0")
        self.assertEqual(result.executable, self.dest / "app.exe")
        self.assertTrue(result.executable.is_file())
        self.assertTrue((self.dest / "runtime/SDL3.dll").is_file())
        self.assertTrue((self.dest / "launcher_icon.png").is_file())
        self.assertTrue((self.dest / "romfs-index.bin").is_file())
        self.assertTrue((self.dest / "aoc-1/aoc-index.bin").is_file())
        self.assertTrue((self.dest / "aoc-1/romfs.bin").is_file())
        self.assertEqual((self.dest / "exefs/main").read_bytes(), b"synthetic main module")
        self.assertEqual((self.dest / "exefs/sdk").read_bytes(), b"synthetic sdk module")
        self.assertEqual((self.dest / "romfs/romfs.bin").read_bytes(), b"synthetic RomFS payload")
        self.assertFalse((self.dest / "unused/developer.log").exists())
        self.assertFalse((self.dest / "unused/settings.ini").exists())
        self.assertFalse((self.dest / MANIFEST_NAME).exists())
        marker = json.loads((self.dest / MARKER_NAME).read_text(encoding="utf-8"))
        self.assertEqual(marker["game_id"], "synthetic.game")
        self.assertEqual(marker["files"], ["app.exe", "runtime/SDL3.dll", "launcher_icon.png", "romfs-index.bin",
                                           "aoc-index.bin", "aoc-1/aoc-index.bin", "aoc-1/romfs.bin",
                                           "seed-answers.bin", "seed-programs.bin", "shader-answers.bin",
                                           "shader-programs.bin", "romfs-patches/manifest.tsv", "exefs/main",
                                           "exefs/sdk", "romfs/romfs.bin"])
        self.assertEqual([event[0] for event in events].count("stage"), 15)
        self.assertIn("copy-bytes", [event[0] for event in events])
        self.assertEqual(events[-1][0], "publish")
        self.assertTrue(all(not Path(event[3]).is_absolute() for event in events if event[3]))
        self.assertEqual((self.game_data / "settings.ini").read_text(encoding="utf-8"), "private setting")
        self.assertEqual((self.game_data / "profile/save.dat").read_bytes(), b"private save")
        self.assertEqual((self.game_data / "shader-cache/cache.bin").read_bytes(), b"private cache")
        self.assertFalse((self.dest / "settings.ini").exists())
        self.assertFalse((self.dest / "profile").exists())
        self.assertFalse((self.dest / "shader-cache").exists())

    def shader_test_install(self, game_id="synthetic.game"):
        xlate = "ns2_xlate.exe" if os.name == "nt" else "ns2_xlate"
        self.write_build(game_id=game_id,
                         files=["app.exe", xlate, "seed-answers.bin", "seed-programs.bin", "shader-prepared.bin"])
        for name, magic in (("seed-answers.bin", b"TOTKSANS"), ("seed-programs.bin", b"TOTKSPRG")):
            (self.source / name).write_bytes(magic + b"synthetic data for mock")
        return install_local_build(self.source, self.dest, game_data_dir=self.game_data), xlate

    def test_shader_preparation_runs_from_final_install_and_requires_new_local_receipt(self):
        result, xlate = self.shader_test_install()
        receipt = self.dest / "shader-cache" / "ns2-shaders-ready.bin"
        self.assertFalse((self.dest / "shader-prepared.bin").exists())

        def completed(timeout):
            receipt.parent.mkdir()
            receipt.write_bytes(b"NS2WARM1" + bytes(88))
            return 0

        with patch("installer.local_build.subprocess.Popen") as popen:
            popen.return_value.__enter__.return_value.wait.side_effect = completed
            self.assertEqual(prepare_installed_shaders(result), "")
        self.assertEqual(popen.call_args.args[0], [str(self.dest / "app.exe"), "--prepare-shaders"])
        self.assertEqual(popen.call_args.kwargs["cwd"], self.dest)
        self.assertEqual(popen.call_args.kwargs["env"]["NS2_XLATE"], str(self.dest / xlate))
        self.assertNotIn(receipt.relative_to(self.dest).as_posix(),
                         json.loads(result.marker.read_text(encoding="utf-8"))["files"])

        with patch("installer.local_build.subprocess.Popen") as popen:
            popen.return_value.__enter__.return_value.wait.return_value = 0
            self.assertIn("couldn’t finish", prepare_installed_shaders(result))
        self.assertTrue(result.executable.is_file())
        self.assertTrue(result.marker.is_file())

    def test_shader_preparation_cancel_or_failed_driver_keeps_install(self):
        result, _ = self.shader_test_install()
        cancel = threading.Event()
        cancel.set()
        with patch("installer.local_build.subprocess.Popen") as popen:
            self.assertIn("was skipped", prepare_installed_shaders(result, cancel_event=cancel))
            popen.assert_not_called()
        with patch("installer.local_build.subprocess.Popen") as popen:
            popen.return_value.__enter__.return_value.wait.return_value = 1
            self.assertIn("couldn’t finish", prepare_installed_shaders(result))
        self.assertTrue(result.executable.is_file())
        self.assertTrue(result.marker.is_file())

    def test_first_play_graphics_runs_the_known_route_with_a_temporary_profile(self):
        title_id = "040015100B514001"
        result, _ = self.shader_test_install(title_id.lower())
        script = self.root / f"shader-warmup-{title_id}.txt"
        script.write_text("# synthetic test script, never executed\n", encoding="utf-8")
        profile = self.dest / "profile"
        profile.mkdir()
        save = profile / "keep.dat"
        save.write_bytes(b"existing synthetic save")
        phases = []
        args_used = []

        def run_child(command, *, cwd, env, stderr, timeout, cancel_event):
            args_used.append(command)
            self.assertEqual(cwd, self.dest)
            self.assertEqual(env["NS2_GPU"], "vulkan")
            if command[-1] == "--prepare-shaders":
                receipt = self.dest / "shader-cache" / "ns2-shaders-ready.bin"
                receipt.parent.mkdir()
                receipt.write_bytes(b"NS2WARM1" + bytes(88))
            else:
                self.assertEqual(command[1:5], ["--exefs", str(self.dest / "exefs"),
                                                 "--romfs", str(self.dest / "romfs")])
                self.assertEqual(command[5], "--profile")
                temp_profile = Path(command[6])
                self.assertNotEqual(temp_profile, profile)
                self.assertEqual(Path(stderr.name).parent, temp_profile.parent)
                self.assertEqual(command[7:], ["--seconds", "105"])
                self.assertEqual(env["NS2_INPUT_SCRIPT"], str(script))
                self.assertEqual(env["NS2_BACKGROUND_WINDOW"], "1")
                self.assertEqual(env["NS2_INPUT"], "none")
                self.assertEqual(env["NS2_AUDIO_OFF"], "1")
                self.assertEqual(env["NS2_SETUP_WARMUP"], "1")
                self.assertEqual(timeout, 240)
                (self.dest / "pipeline-keys.bin").write_bytes(b"TOTKPKEY" + bytes(32))
            return 0

        with patch("installer.local_build._WARMUP_DATA", self.root), \
             patch("installer.local_build._run_shader_child", side_effect=run_child):
            self.assertEqual(prepare_installed_shaders(result, on_start=lambda: phases.append("prepare"),
                                                       on_train=lambda: phases.append("graphics")), "")
        self.assertEqual(phases, ["prepare", "graphics"])
        self.assertEqual(len(args_used), 2)
        self.assertFalse(Path(args_used[1][6]).parent.exists())
        self.assertEqual(save.read_bytes(), b"existing synthetic save")

    def test_partial_preparation_checks_for_quiet_mode_before_starting_route(self):
        title_id = "040015100B514001"
        result, _ = self.shader_test_install(title_id)
        (self.root / f"shader-warmup-{title_id}.txt").write_text("# synthetic route\n", encoding="utf-8")
        receipt = self.dest / "shader-cache" / "ns2-shaders-ready.bin"
        receipt.parent.mkdir()

        for supports_quiet_mode in (False, True):
            with self.subTest(supports_quiet_mode=supports_quiet_mode):
                commands = []
                phases = []

                def run_child(command, **_options):
                    commands.append(command[1])
                    if command[1] == "--prepare-shaders":
                        receipt.write_bytes(b"broken receipt")
                        return 0
                    if command[1] == "--probe-setup-warmup":
                        return 0 if supports_quiet_mode else 2
                    (self.dest / "pipeline-keys.bin").write_bytes(b"TOTKPKEY" + bytes(32))
                    return 0

                with patch("installer.local_build._WARMUP_DATA", self.root), \
                     patch("installer.local_build._run_shader_child", side_effect=run_child):
                    warning = prepare_installed_shaders(result, on_train=lambda: phases.append("graphics"))
                expected = ["--prepare-shaders", "--probe-setup-warmup"]
                if supports_quiet_mode:
                    expected.append("--exefs")
                self.assertEqual(commands, expected)
                self.assertEqual(phases, ["graphics"] if supports_quiet_mode else [])
                self.assertIn("Graphics preparation couldn’t finish", warning)
                self.assertTrue(result.executable.is_file())

    def test_cancelling_graphics_child_during_wait_terminates_process(self):
        from installer.local_build import _run_shader_child

        cancel = threading.Event()

        def cancel_during_wait(timeout):
            if timeout == 0.2:
                cancel.set()
                raise subprocess.TimeoutExpired("synthetic process", timeout)
            return 1

        with patch("installer.local_build.subprocess.Popen") as popen:
            process = popen.return_value.__enter__.return_value
            process.wait.side_effect = cancel_during_wait
            self.assertIsNone(_run_shader_child(["synthetic.exe"], cwd=self.root, env={},
                                                stderr=subprocess.DEVNULL, timeout=240, cancel_event=cancel))
            process.terminate.assert_called_once()

    def test_updates_same_game_and_preserves_settings_saves_and_unlisted_files(self):
        install_local_build(self.source, self.dest, game_data_dir=self.game_data)
        (self.dest / "settings.ini").write_text("private setting", encoding="utf-8")
        (self.dest / "profile").mkdir()
        (self.dest / "profile/save.dat").write_bytes(b"private save")
        (self.dest / "notes.txt").write_text("keep", encoding="utf-8")
        (self.dest / "shader-prepared.bin").write_bytes(b"local prepared list")
        self.write_build(game_version="1.0.1", port_version="0.1.1")

        events = []
        result = install_local_build(self.source, self.dest, lambda *event: events.append(event),
                                     game_data_dir=self.game_data)

        self.assertEqual(result.game_version, "1.0.1")
        self.assertIn("backup-bytes", [event[0] for event in events])
        self.assertEqual((self.dest / "settings.ini").read_text(encoding="utf-8"), "private setting")
        self.assertEqual((self.dest / "profile/save.dat").read_bytes(), b"private save")
        self.assertEqual((self.dest / "notes.txt").read_text(encoding="utf-8"), "keep")
        self.assertEqual((self.dest / "shader-prepared.bin").read_bytes(), b"local prepared list")

    def test_installs_verified_npdm_metadata_from_exefs(self):
        metadata = b"synthetic ExeFS metadata"
        (self.game_data / "exefs/main.npdm").write_bytes(metadata)
        manifest_path = self.source / MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["game_data"]["exefs_sha256"]["main.npdm"] = hashlib.sha256(metadata).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        install_local_build(self.source, self.dest, game_data_dir=self.game_data)
        self.assertEqual((self.dest / "exefs/main.npdm").read_bytes(), metadata)
        install_local_build(self.source, self.dest, game_data_dir=self.game_data)

    def test_rejects_unmarked_nonempty_destination_without_changing_it(self):
        self.dest.mkdir()
        personal = self.dest / "settings.ini"
        personal.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(LocalBuildError, "not empty"):
            install_local_build(self.source, self.dest, game_data_dir=self.game_data)

        self.assertEqual(personal.read_text(encoding="utf-8"), "keep")
        self.assertFalse((self.dest / "app.exe").exists())

    def test_rejects_destination_marked_for_another_game(self):
        install_local_build(self.source, self.dest, game_data_dir=self.game_data)
        self.write_build(game_id="different.game")
        with self.assertRaisesRegex(LocalBuildError, "different game"):
            install_local_build(self.source, self.dest, game_data_dir=self.game_data)

    def test_refuses_to_replace_unowned_file_in_marked_destination(self):
        install_local_build(self.source, self.dest, game_data_dir=self.game_data)
        unowned = self.dest / "new-runtime.dll"
        unowned.write_bytes(b"user file")
        self.write_build(files=["app.exe", "new-runtime.dll"])

        with self.assertRaisesRegex(LocalBuildError, "not recorded"):
            install_local_build(self.source, self.dest, game_data_dir=self.game_data)

        self.assertEqual(unowned.read_bytes(), b"user file")

    def test_rejects_source_destination_overlap_in_both_directions(self):
        with self.assertRaisesRegex(LocalBuildError, "must not contain"):
            install_local_build(self.source, self.source / "install")
        (self.source / "child").mkdir()
        with self.assertRaisesRegex(LocalBuildError, "must not contain"):
            install_local_build(self.source / "child", self.root, game_data_dir=self.game_data)

    def test_rejects_missing_manifest_file(self):
        self.write_build(files=["app.exe", "missing.dll"])
        (self.source / "missing.dll").unlink()
        with self.assertRaisesRegex(LocalBuildError, "does not exist"):
            install_local_build(self.source, self.dest, game_data_dir=self.game_data)
        self.assertFalse(self.dest.exists())

    def test_requires_selected_data_folder_when_build_is_not_portable(self):
        with self.assertRaisesRegex(LocalBuildError, "Select the local game-data folder"):
            install_local_build(self.source, self.dest)
        self.assertFalse(self.dest.exists())

    def test_selected_data_root_installs_only_verified_modules_and_romfs(self):
        manifest_path = self.source / MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["game_data"]["exefs_sha256"]["main"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(LocalBuildError, "SHA-256 check"):
            install_local_build(self.source, self.dest, game_data_dir=self.game_data)
        self.assertFalse(self.dest.exists())

    def test_romfs_size_mismatch_and_unsafe_source_are_rejected(self):
        manifest_path = self.source / MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["game_data"]["romfs_size"] += 1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(LocalBuildError, "RomFS image size mismatch"):
            install_local_build(self.source, self.dest, game_data_dir=self.game_data)
        manifest["game_data"]["romfs_path"] = "../romfs.bin"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(LocalBuildError, "romfs_path"):
            install_local_build(self.source, self.dest, game_data_dir=self.game_data)
        self.assertFalse(self.dest.exists())

    def test_internal_portable_assets_are_supported_and_null_romfs_is_optional(self):
        manifest_path = self.source / MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        internal = self.source
        (internal / "exefs").mkdir()
        (internal / "exefs/main").write_bytes(b"internal main")
        (internal / "exefs/sdk").write_bytes(b"internal sdk")
        (internal / "romfs").mkdir()
        (internal / "romfs/romfs.bin").write_bytes(b"internal RomFS")
        manifest["game_data"]["exefs_sha256"] = {
            "main": hashlib.sha256(b"internal main").hexdigest(),
            "sdk": hashlib.sha256(b"internal sdk").hexdigest(),
        }
        manifest["game_data"]["romfs_path"] = None
        manifest["game_data"]["romfs_size"] = len(b"internal RomFS")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        install_local_build(self.source, self.dest)

        self.assertEqual((self.dest / "exefs/main").read_bytes(), b"internal main")
        self.assertEqual((self.dest / "romfs/romfs.bin").read_bytes(), b"internal RomFS")

        second_dest = self.root / "installed-exefs-only"
        other = self.root / "game-data-exefs-only"
        (other / "exefs").mkdir(parents=True)
        (other / "exefs/main").write_bytes(b"external main")
        (other / "exefs/sdk").write_bytes(b"external sdk")
        manifest["game_data"]["exefs_sha256"] = {
            "main": hashlib.sha256(b"external main").hexdigest(),
            "sdk": hashlib.sha256(b"external sdk").hexdigest(),
        }
        manifest["game_data"]["romfs_size"] = None
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        install_local_build(self.source, second_dest, game_data_dir=other)
        self.assertTrue((second_dest / "exefs/main").is_file())
        self.assertFalse((second_dest / "romfs/romfs.bin").exists())

    def test_rejects_unsafe_or_noncanonical_relative_paths(self):
        for bad in ("../outside.dll", "/absolute.dll", "C:/drive.dll", "nested\\file.dll", "a//b.dll", "./app.dll"):
            with self.subTest(path=bad):
                self.write_build(files=["app.exe", bad])
                with self.assertRaises(LocalBuildError):
                    install_local_build(self.source, self.dest, game_data_dir=self.game_data)
                self.assertFalse(self.dest.exists())

    def test_rejects_runtime_binary_outside_root_allowlist(self):
        self.write_build(files=["app.exe", "nested/romfs-index.bin"])
        with self.assertRaisesRegex(LocalBuildError, "unrecognized binary"):
            install_local_build(self.source, self.dest, game_data_dir=self.game_data)
        self.assertFalse(self.dest.exists())

    def test_rejects_unrecognized_bin_inside_aoc_or_other_subdir(self):
        for bad in ("aoc-1/unknown.bin", "other/aoc-index.bin"):
            with self.subTest(path=bad):
                self.write_build(files=["app.exe", bad])
                with self.assertRaisesRegex(LocalBuildError, "unrecognized binary"):
                    install_local_build(self.source, self.dest, game_data_dir=self.game_data)
                self.assertFalse(self.dest.exists())

    def test_updates_existing_install_when_new_build_adds_new_subfolder(self):
        self.write_build(files=["app.exe", "romfs-index.bin"])
        install_local_build(self.source, self.dest, game_data_dir=self.game_data)
        (self.dest / "settings.ini").write_text("private setting", encoding="utf-8")
        (self.dest / "profile").mkdir()
        (self.dest / "profile/save.dat").write_bytes(b"private save")

        self.write_build(port_version="0.2.0",
                         files=["app.exe", "romfs-index.bin", "aoc-1/aoc-index.bin", "aoc-1/romfs.bin"])
        result = install_local_build(self.source, self.dest, game_data_dir=self.game_data)

        self.assertTrue((self.dest / "aoc-1/aoc-index.bin").is_file())
        self.assertTrue((self.dest / "aoc-1/romfs.bin").is_file())
        self.assertEqual((self.dest / "settings.ini").read_text(encoding="utf-8"), "private setting")
        self.assertEqual((self.dest / "profile/save.dat").read_bytes(), b"private save")
        marker = json.loads(result.marker.read_text(encoding="utf-8"))
        self.assertIn("aoc-1/aoc-index.bin", marker["files"])
        self.assertIn("aoc-1/romfs.bin", marker["files"])

    def test_is_reparse_allows_windows_cloud_sync_tag_but_rejects_symlinks_and_junctions(self):
        import stat
        from types import SimpleNamespace
        from installer.local_build import _is_reparse

        dir_mode = stat.S_IFDIR | 0o755
        self.assertFalse(_is_reparse(SimpleNamespace(st_mode=dir_mode, st_file_attributes=0x410, st_reparse_tag=0x9000001A)))
        self.assertFalse(_is_reparse(SimpleNamespace(st_mode=dir_mode, st_file_attributes=0x410, st_reparse_tag=0x9000301A)))
        self.assertFalse(_is_reparse(SimpleNamespace(st_mode=dir_mode, st_file_attributes=0x410, st_reparse_tag=0x80000021)))
        self.assertTrue(_is_reparse(SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_file_attributes=0, st_reparse_tag=0)))
        self.assertTrue(_is_reparse(SimpleNamespace(st_mode=dir_mode, st_file_attributes=0x410, st_reparse_tag=0xA000000C)))
        self.assertTrue(_is_reparse(SimpleNamespace(st_mode=dir_mode, st_file_attributes=0x410, st_reparse_tag=0xA0000003)))
        self.assertTrue(_is_reparse(SimpleNamespace(st_mode=dir_mode, st_file_attributes=0x410, st_reparse_tag=0x8000001B)))
        self.assertTrue(_is_reparse(SimpleNamespace(st_mode=dir_mode, st_file_attributes=0x410, st_reparse_tag=0)))

    def test_rejects_user_data_screenshots_caches_build_files_archives_and_roms(self):
        blocked = (
            "settings.ini", "profile/save.dat", "saves/save.dat", "screenshots/test.png",
            "launcher_config.json", "logs/installer.log", "shader-cache/data.bin", "pipeline-cache.bin",
            "pipeline-keys.bin", "unknown-runtime.bin", "obj/module.obj", "archive.zip", "game.nup",
            "romfs.bin", "exefs/main",
        )
        for bad in blocked:
            with self.subTest(path=bad):
                self.write_build(files=["app.exe", bad])
                with self.assertRaises(LocalBuildError):
                    install_local_build(self.source, self.dest, game_data_dir=self.game_data)
                self.assertFalse(self.dest.exists())

    def test_rejects_case_insensitive_duplicate_files_and_missing_executable_listing(self):
        self.write_build(files=["app.exe", "APP.EXE"])
        with self.assertRaisesRegex(LocalBuildError, "more than once"):
            install_local_build(self.source, self.dest, game_data_dir=self.game_data)
        self.write_build(files=["other.exe"])
        with self.assertRaisesRegex(LocalBuildError, "executable must also appear"):
            install_local_build(self.source, self.dest, game_data_dir=self.game_data)

    def test_failed_update_rolls_back_files_and_keeps_old_marker(self):
        install_local_build(self.source, self.dest, game_data_dir=self.game_data)
        original_files = {p: (self.dest / p).read_bytes()
                          for p in ("app.exe", "runtime/SDL3.dll", "launcher_icon.png", "romfs-index.bin",
                                    "aoc-1/aoc-index.bin", "aoc-1/romfs.bin", "exefs/main", "exefs/sdk",
                                    "romfs/romfs.bin")}
        marker_path = self.dest / MARKER_NAME
        original_marker = marker_path.read_bytes()
        (self.game_data / "exefs/main").write_bytes(b"updated synthetic main")
        (self.game_data / "exefs/sdk").write_bytes(b"updated synthetic sdk")
        (self.game_data / "romfs_packed/romfs.bin").write_bytes(b"updated synthetic RomFS")
        self.write_build(game_version="1.0.1")

        real_replace = os.replace
        failed = False

        def fail_once(src, dst):
            nonlocal failed
            if not failed and Path(dst) == self.dest / "romfs/romfs.bin":
                failed = True
                raise OSError("synthetic replace failure")
            return real_replace(src, dst)

        with patch("installer.local_build.os.replace", side_effect=fail_once):
            with self.assertRaisesRegex(LocalBuildError, "install failed"):
                install_local_build(self.source, self.dest, game_data_dir=self.game_data)

        self.assertTrue(failed)
        for relative, contents in original_files.items():
            self.assertEqual((self.dest / relative).read_bytes(), contents)
        self.assertEqual(marker_path.read_bytes(), original_marker)

    def test_cancel_callback_during_update_rolls_back(self):
        install_local_build(self.source, self.dest, game_data_dir=self.game_data)
        original_exe = (self.dest / "app.exe").read_bytes()
        original_marker = (self.dest / MARKER_NAME).read_bytes()
        self.write_build(game_version="1.0.1")

        def cancel_after_first_replace(phase, completed, total, relative):
            if phase == "install" and completed == 1:
                raise RuntimeError("synthetic cancellation")

        with self.assertRaisesRegex(RuntimeError, "cancellation"):
            install_local_build(self.source, self.dest, cancel_after_first_replace,
                                game_data_dir=self.game_data)

        self.assertEqual((self.dest / "app.exe").read_bytes(), original_exe)
        self.assertEqual((self.dest / MARKER_NAME).read_bytes(), original_marker)

    def test_rejects_symlinked_source_file_when_platform_allows_creation(self):
        outside = self.root / "outside.dll"
        outside.write_bytes(b"outside")
        link = self.source / "linked.dll"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"This account cannot create symlinks: {exc}")
        self.write_build(files=["app.exe", "linked.dll"])
        # Recreate the link because write_build creates regular files for listed paths.
        (self.source / "linked.dll").unlink()
        (self.source / "linked.dll").symlink_to(outside)

        with self.assertRaisesRegex(LocalBuildError, "symbolic links"):
            install_local_build(self.source, self.dest, game_data_dir=self.game_data)
        self.assertFalse(self.dest.exists())

    def test_rejects_symlinked_destination_when_platform_allows_creation(self):
        target = self.root / "redirected-destination"
        target.mkdir()
        try:
            self.dest.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"This account cannot create symlinks: {exc}")

        with self.assertRaisesRegex(LocalBuildError, "symbolic links"):
            install_local_build(self.source, self.dest, game_data_dir=self.game_data)
        self.assertFalse((target / "app.exe").exists())


if __name__ == "__main__":
    unittest.main()
