"""The generated local installer manifest contains only named runtime files."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import universal_ns2_to_pc as port


class LocalBuildManifestTest(unittest.TestCase):
    def test_folder_build_manifest_omits_user_state_and_carries_correct_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            game_root = Path(temp) / "dump"
            exefs = game_root / "exefs"
            packed_romfs = game_root / "romfs_packed"
            build = game_root / "build" / "smbw100"
            exefs.mkdir(parents=True)
            packed_romfs.mkdir(parents=True)
            build.mkdir(parents=True)

            module = exefs / "main"
            module.write_bytes(b"synthetic ExeFS module")
            (packed_romfs / "romfs.bin").write_bytes(b"synthetic RomFS image")

            included = (
                "smbw.exe", "SDL3.dll", "libiconv-2.dll", "libopus-0.dll",
                "ns2_xlate.exe", "ns2_xlate.id", "totk_xlate.exe", "totk_xlate.id",
                "Roboto-Medium.ttf", "LICENSE-Roboto.txt", "launcher_icon.png", "romfs-index.bin", "ns2-release-repo.txt",
                "seed-answers.bin", "seed-programs.bin", "shader-answers.bin", "shader-programs.bin",
            )
            for name in included:
                (build / name).write_bytes(b"runtime artifact")
            (build / "smbw.ini").write_text("[profile]\nplayer_name=private\n", encoding="utf-8")
            (build / "pipeline-cache.bin").write_bytes(b"user cache")
            (build / "shader-prepared.bin").write_bytes(b"local warmup state")
            (build / "screenshots").mkdir()
            (build / "screenshots" / "launcher.png").write_bytes(b"screenshot")
            (build / "logs").mkdir()
            (build / "logs" / "game.log").write_text("private log", encoding="utf-8")
            (build / "obj").mkdir()
            (build / "obj" / "runtime.o").write_bytes(b"object")
            addon = build / "aoc-1"
            addon.mkdir()
            (addon / "romfs.bin").write_bytes(b"addon")
            (addon / "aoc-index.bin").write_bytes(b"index")
            (addon / "debug.log").write_text("not an install artifact", encoding="utf-8")

            metadata = {
                "title_id": "040015100B514001",
                "exefs_sha256": {"main": hashlib.sha256(module.read_bytes()).hexdigest()},
            }
            manifest_path = port._write_local_build_manifest(
                build,
                {"folder": game_root},
                exefs,
                packed_romfs,
                metadata,
                "smbw",
                "Super Mario Bros. Wonder",
                "1.0.0",
            )

            self.assertIsNotNone(manifest_path)
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(data["game_id"], "040015100B514001")
            self.assertEqual(data["game_title"], "Super Mario Bros. Wonder")
            self.assertEqual(data["game_version"], "1.0.0")
            self.assertEqual(data["port_version"], "Alpha 0.1.0a")
            self.assertEqual(data["executable"], "smbw.exe")
            self.assertEqual(data["game_data"], {
                "exefs_dir": "exefs",
                "exefs_sha256": metadata["exefs_sha256"],
                "romfs_path": "romfs_packed/romfs.bin",
                "romfs_size": len(b"synthetic RomFS image"),
            })
            self.assertEqual(
                set(data["files"]),
                set(included) | {"aoc-1/romfs.bin", "aoc-1/aoc-index.bin"},
            )
            serialized = manifest_path.read_text(encoding="utf-8")
            for private in ("smbw.ini", "pipeline-cache.bin", "shader-prepared.bin", "screenshots", "logs", "obj", str(game_root)):
                self.assertNotIn(private, serialized)

    def test_manifest_skips_game_data_paths_outside_the_selected_dump(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game_root = root / "dump"
            external = root / "elsewhere" / "exefs"
            build = game_root / "build" / "test"
            build.mkdir(parents=True)
            external.mkdir(parents=True)
            (build / "test.exe").write_bytes(b"exe")
            metadata = {"title_id": "0400000000000000", "exefs_sha256": {"main": "0" * 64}}
            result = port._write_local_build_manifest(build, {"folder": game_root}, external, None,
                                                      metadata, "test", "Test", "1.0.0")
            self.assertIsNone(result)
            self.assertFalse((build / "ns2-build-manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
