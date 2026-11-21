"""Tests for game setup orchestration using synthetic paths and mocked tools."""

from __future__ import annotations

import io
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from installer import nup_workflow as workflow  # noqa: E402


class FakeProcess:
    commands: list[list[str]] = []
    options: list[dict] = []
    returncodes: list[int] = []
    outputs: list[str] = []

    def __init__(self, command, **kwargs):
        self.command = list(command)
        self.kwargs = kwargs
        self.commands.append(self.command)
        self.options.append(kwargs)
        index = len(self.commands) - 1
        self.returncode = self.returncodes[index] if index < len(self.returncodes) else 0
        self.stdout = io.StringIO(self.outputs[index] if index < len(self.outputs) else "")
        self.pid = 12345 + index
        if "universal_ns2_to_pc.py" in self.command[1]:
            dump = Path(self.command[self.command.index("--folder") + 1])
            manifest_dir = dump / "build" / "sample100"
            manifest_dir.mkdir(parents=True)
            (manifest_dir / "ns2-build-manifest.json").write_text("{}", encoding="utf-8")

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def send_signal(self, _signal):
        self.returncode = -1

    def terminate(self):
        self.returncode = -1

    def kill(self):
        self.returncode = -9


class NupWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / ".git").mkdir()
        for relative in ("tools/extract_nup.py", "tools/universal_ns2_to_pc.py", "tools/dkb_pack_romfs.py",
                         "installer/local_build.py"):
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# synthetic test stub\n", encoding="utf-8")
        self.extractor_python = self.root / "python314.exe"
        self.build_python = self.root / "python312.exe"
        self.extractor_python.write_text("mock executable", encoding="utf-8")
        self.build_python.write_text("mock executable", encoding="utf-8")
        self.nup = self.root / "selected.nup"
        self.nup.write_text("synthetic path-only input; never parsed", encoding="utf-8")
        self.workspace = self.root / "chosen-workspace"
        self.destination = self.root / "separate-install"
        shader_patch = patch("installer.local_build.prepare_installed_shaders", return_value="")
        self.prepare_shaders = shader_patch.start()
        self.addCleanup(shader_patch.stop)
        FakeProcess.commands = []
        FakeProcess.options = []
        FakeProcess.returncodes = []
        FakeProcess.outputs = [
            "extracting package [0] base 0000000000000000 1.0.0\n"
            "  exefs: 2/5 files, 1.25 of 4.00 GB (8 MB/s)\n",
            "Lifting modules from selected dump\nBUILD COMPLETE\n",
        ]

    def run_workflow(self, **kwargs):
        destination = kwargs.pop("destination", self.destination)
        return workflow.run_nup_workflow(
            self.nup, self.workspace, destination,
            repo_root=self.repo,
            extractor_python=self.extractor_python,
            build_python=self.build_python,
            **kwargs,
        )

    def test_runs_default_extract_then_build_then_allowlisted_install(self):
        events = []

        def fake_install(build_dir, destination, *, progress_callback, game_data_dir):
            progress_callback("copy-bytes", 4, 9, "app.exe")
            return {"installed": True}

        with patch("installer.nup_workflow.subprocess.Popen", FakeProcess), \
             patch("installer.local_build.install_local_build", side_effect=fake_install) as install:
            result = self.run_workflow(progress_callback=events.append)

        dump = self.workspace / "dump"
        self.assertEqual(len(FakeProcess.commands), 2)
        extract, build = FakeProcess.commands
        self.assertEqual(os.path.normcase(extract[0]), os.path.normcase(str(self.extractor_python.resolve())))
        self.assertEqual(os.path.normcase(extract[1]),
                         os.path.normcase(str((self.repo / "tools/extract_nup.py").resolve())))
        self.assertEqual(os.path.normcase(extract[2]), os.path.normcase(str(self.nup.resolve())))
        self.assertEqual(extract[3], "--out")
        self.assertEqual(os.path.normcase(extract[4]), os.path.normcase(str(dump.resolve())))
        self.assertNotIn("--no-verify", extract)
        self.assertNotIn("--no-addons", extract)
        self.assertNotIn("--package", extract)
        expected_build = [str(self.build_python.resolve()),
                          str((self.repo / "tools/universal_ns2_to_pc.py").resolve()),
                          "port", "--folder", str(dump.resolve()), "--no-bringup", "--seed-shaders-only"]
        self.assertEqual([os.path.normcase(item) for item in build],
                         [os.path.normcase(item) for item in expected_build])
        self.assertEqual([os.path.normcase(options["cwd"]) for options in FakeProcess.options],
                         [os.path.normcase(str(self.repo.resolve()))] * 2)
        self.assertTrue(all(options["shell"] is False for options in FakeProcess.options))
        self.assertEqual(result.workspace, self.workspace)
        self.assertEqual(result.dump_dir, dump)
        self.assertEqual(result.build_dir, dump / "build" / "sample100")
        self.assertEqual(result.destination, self.destination)
        self.assertEqual(result.install_result, {"installed": True})
        install.assert_called_once()
        self.assertEqual(install.call_args.args, (result.build_dir, self.destination))
        self.assertEqual(install.call_args.kwargs["game_data_dir"], dump)
        self.prepare_shaders.assert_called_once()
        self.assertIs(self.prepare_shaders.call_args.args[0], result.install_result)
        self.assertEqual([event.phase for event in events if event.status == "completed"],
                         ["validate", "extract", "build", "install", "complete"])
        extracted_file_event = next(event for event in events
                                    if event.phase == "extract" and event.unit == "files")
        self.assertEqual((extracted_file_event.completed, extracted_file_event.total), (2, 5))
        byte_event = next(event for event in events if event.phase == "install" and event.unit == "bytes")
        self.assertEqual((byte_event.completed, byte_event.total, byte_event.relative_path), (4, 9, "app.exe"))

    def test_nonzero_extractor_exit_reports_output_and_leaves_workspace(self):
        FakeProcess.returncodes = [7]
        FakeProcess.outputs = ["error: synthetic corrupt container\n"]
        with patch("installer.nup_workflow.subprocess.Popen", FakeProcess), \
             patch("installer.local_build.install_local_build") as install:
            with self.assertRaises(workflow.NupWorkflowError) as caught:
                self.run_workflow()
        self.assertEqual(caught.exception.phase, "extract")
        self.assertEqual(caught.exception.returncode, 7)
        self.assertIn("synthetic corrupt container", str(caught.exception))
        self.assertTrue((self.workspace / "dump").is_dir())
        install.assert_not_called()
        self.assertEqual(len(FakeProcess.commands), 1)

    def test_cancel_after_extract_stops_before_build_and_keeps_data(self):
        cancel = threading.Event()
        events = []

        def report(event):
            events.append(event)
            if event.phase == "extract" and event.status == "completed":
                cancel.set()

        with patch("installer.nup_workflow.subprocess.Popen", FakeProcess), \
             patch("installer.local_build.install_local_build") as install:
            with self.assertRaises(workflow.NupWorkflowCancelled) as caught:
                self.run_workflow(progress_callback=report, cancel_event=cancel)
        self.assertEqual(caught.exception.phase, "build")
        self.assertEqual(len(FakeProcess.commands), 1)
        self.assertTrue((self.workspace / "dump").is_dir())
        install.assert_not_called()

    def test_cancel_callback_during_install_uses_backend_rollback_hook(self):
        cancel = threading.Event()

        def report(event):
            if event.phase == "install" and event.status == "progress":
                cancel.set()

        def fake_install(_build_dir, _destination, *, progress_callback, game_data_dir):
            self.assertEqual(game_data_dir, self.workspace / "dump")
            progress_callback("copy-bytes", 1, 2, "romfs/romfs.bin")
            progress_callback("stage", 1, 3, "romfs/romfs.bin")

        with patch("installer.nup_workflow.subprocess.Popen", FakeProcess), \
             patch("installer.local_build.install_local_build", side_effect=fake_install) as install:
            with self.assertRaises(workflow.NupWorkflowCancelled) as caught:
                self.run_workflow(progress_callback=report, cancel_event=cancel)
        self.assertEqual(caught.exception.phase, "install")
        self.assertEqual(install.call_count, 1)

    def test_cancel_during_build_stops_process_and_skips_install(self):
        cancel = threading.Event()

        def report(event):
            if event.phase == "build" and event.status == "progress":
                cancel.set()

        with patch("installer.nup_workflow.subprocess.Popen", FakeProcess), \
             patch("installer.local_build.install_local_build") as install:
            with self.assertRaises(workflow.NupWorkflowCancelled) as caught:
                self.run_workflow(progress_callback=report, cancel_event=cancel)
        self.assertEqual(caught.exception.phase, "build")
        self.assertEqual(len(FakeProcess.commands), 2)
        self.assertTrue((self.workspace / "dump").is_dir())
        install.assert_not_called()

    def test_rejects_workspace_inside_repo_before_starting_tools(self):
        with patch("installer.nup_workflow.subprocess.Popen", FakeProcess):
            with self.assertRaisesRegex(workflow.NupWorkflowError, "separate from the repository"):
                workflow.run_nup_workflow(self.nup, self.repo / "build-work", self.destination,
                                          repo_root=self.repo, extractor_python=self.extractor_python,
                                          build_python=self.build_python)
        self.assertEqual(FakeProcess.commands, [])

    def test_rejects_destination_inside_workspace_before_starting_tools(self):
        with patch("installer.nup_workflow.subprocess.Popen", FakeProcess):
            with self.assertRaisesRegex(workflow.NupWorkflowError, "separate from the workspace"):
                self.run_workflow(destination=self.workspace / "install")
        self.assertEqual(FakeProcess.commands, [])

    def test_rejects_nonempty_workspace_without_touching_it(self):
        self.workspace.mkdir()
        keep = self.workspace / "keep.txt"
        keep.write_text("user file", encoding="utf-8")
        with patch("installer.nup_workflow.subprocess.Popen", FakeProcess):
            with self.assertRaisesRegex(workflow.NupWorkflowError, "Choose an empty workspace"):
                self.run_workflow()
        self.assertEqual(keep.read_text(encoding="utf-8"), "user file")
        self.assertEqual(FakeProcess.commands, [])

    def test_rejects_nonempty_install_folder_before_preparing_game(self):
        self.destination.mkdir()
        (self.destination / "keep.txt").write_text("user file", encoding="utf-8")
        with self.assertRaisesRegex(workflow.NupWorkflowError, "Destination is not empty"):
            self.run_workflow()
        self.assertFalse(self.workspace.exists())

    def test_rejects_nup_inside_repository_and_missing_interpreter(self):
        repo_nup = self.repo / "private.nup"
        repo_nup.write_text("synthetic", encoding="utf-8")
        with self.assertRaisesRegex(workflow.NupWorkflowError, "outside the repository"):
            workflow.run_nup_workflow(repo_nup, self.workspace, self.destination,
                                      repo_root=self.repo, extractor_python=self.extractor_python,
                                      build_python=self.build_python)
        with self.assertRaisesRegex(workflow.NupWorkflowError, "Build Python executable is unavailable"):
            workflow.run_nup_workflow(self.nup, self.workspace, self.destination,
                                      repo_root=self.repo, extractor_python=self.extractor_python,
                                      build_python=self.root / "missing-python.exe")
        self.assertEqual(FakeProcess.commands, [])

    def make_game_folder(self, romfs_name):
        game = self.root / "game"
        (game / "exefs").mkdir(parents=True)
        (game / "exefs" / "main").write_bytes(b"synthetic program")
        (game / "exefs" / "main.npdm").write_bytes(b"synthetic metadata")
        (game / "exefs" / "private.ini").write_bytes(b"unrelated setting")
        romfs = game / romfs_name
        romfs.mkdir()
        return game, romfs

    def test_loose_game_folder_stages_exefs_and_packs_into_workspace(self):
        game, romfs = self.make_game_folder("romfs")
        (romfs / "sample").write_bytes(b"synthetic asset")
        self.assertEqual(workflow.locate_game_folder(romfs), game)
        with patch("installer.nup_workflow.subprocess.Popen", FakeProcess), \
             patch("installer.local_build.install_local_build", return_value="installed") as install:
            result = workflow.run_folder_workflow(romfs, self.workspace, self.destination,
                                                  repo_root=self.repo, build_python=self.build_python)

        dump = self.workspace / "dump"
        pack, build = FakeProcess.commands
        self.assertEqual([os.path.normcase(value) for value in pack], [os.path.normcase(value) for value in (
            str(self.build_python), str(self.repo / "tools/dkb_pack_romfs.py"),
            "--dir", str(romfs), "--out", str(dump / "romfs_packed"),
        )])
        self.assertEqual(build[2:4], ["port", "--folder"])
        self.assertEqual(Path(build[4]), dump)
        self.assertEqual(build[5:], ["--no-bringup", "--seed-shaders-only"])
        self.assertEqual(install.call_args.kwargs["game_data_dir"], dump)
        self.assertEqual(result.install_result, "installed")
        self.assertEqual((dump / "exefs" / "main").read_bytes(), b"synthetic program")
        self.assertFalse((dump / "exefs" / "private.ini").exists())
        self.assertEqual((game / "exefs" / "private.ini").read_bytes(), b"unrelated setting")
        self.assertEqual({path.name for path in game.iterdir()}, {"exefs", "romfs"})

    def test_packed_source_copies_only_game_files(self):
        _, romfs = self.make_game_folder("romfs_packed")
        (romfs / "romfs.bin").write_bytes(b"synthetic packed asset")
        (romfs / "index.json").write_bytes(b"{}")
        (romfs / "log.txt").write_bytes(b"unrelated file")
        with patch("installer.nup_workflow.subprocess.Popen", FakeProcess), \
             patch("installer.local_build.install_local_build", return_value="installed"):
            workflow.run_folder_workflow(romfs, self.workspace, self.destination,
                                         repo_root=self.repo, build_python=self.build_python)

        packed = self.workspace / "dump" / "romfs_packed"
        self.assertEqual(len(FakeProcess.commands), 1)
        self.assertEqual({path.name for path in packed.iterdir()}, {"romfs.bin", "index.json"})
        self.assertEqual((packed / "romfs.bin").read_bytes(), b"synthetic packed asset")

    def test_missing_exefs_and_destination_inside_source_are_rejected(self):
        game, romfs = self.make_game_folder("romfs")
        with self.assertRaisesRegex(workflow.NupWorkflowError, "separate from your game"):
            workflow.run_folder_workflow(romfs, self.workspace, game / "install",
                                         repo_root=self.repo, build_python=self.build_python)

        (game / "exefs" / "main").unlink()
        with self.assertRaisesRegex(workflow.NupWorkflowError, "both ExeFS and RomFS"):
            workflow.run_folder_workflow(romfs, self.workspace, self.destination,
                                         repo_root=self.repo, build_python=self.build_python)
        self.assertFalse(self.workspace.exists())

    def test_portable_setup_root_does_not_need_git(self):
        (self.repo / ".git").rmdir()
        self.assertFalse(workflow.is_setup_root(self.repo))
        for relative in ("python/python.exe", "llvm/bin/clang.exe", "bin/ninja.exe"):
            executable = self.repo / relative
            executable.parent.mkdir(parents=True)
            executable.touch()
        for relative in ("include", "lib"):
            (self.repo / "runtime/deps" / relative).mkdir(parents=True)
        self.assertTrue(workflow.is_setup_root(self.repo))

    def test_folder_workflow_stages_loose_aoc_and_packs_into_workspace(self):
        game, romfs = self.make_game_folder("romfs")
        (romfs / "sample").write_bytes(b"synthetic asset")
        addon_romfs = game / "aoc" / "1" / "romfs"
        addon_romfs.mkdir(parents=True)
        (addon_romfs / "dlc.bin").write_bytes(b"synthetic addon asset")

        with patch("installer.nup_workflow.subprocess.Popen", FakeProcess), \
             patch("installer.local_build.install_local_build", return_value="installed"):
            workflow.run_folder_workflow(game, self.workspace, self.destination,
                                         repo_root=self.repo, build_python=self.build_python)

        dump = self.workspace / "dump"
        pack_base, pack_addon, build = FakeProcess.commands
        self.assertEqual(Path(pack_base[pack_base.index("--dir") + 1]), romfs)
        self.assertEqual(Path(pack_base[pack_base.index("--out") + 1]), dump / "romfs_packed")
        self.assertEqual(Path(pack_addon[pack_addon.index("--dir") + 1]), addon_romfs)
        self.assertEqual(Path(pack_addon[pack_addon.index("--out") + 1]), dump / "aoc_packed" / "1")
        self.assertTrue((dump / "aoc" / "1" / "romfs").is_dir())
        self.assertEqual(build[2:4], ["port", "--folder"])
        self.assertEqual({path.name for path in game.iterdir()}, {"exefs", "romfs", "aoc"})

    def test_folder_workflow_reuses_prepacked_aoc_without_repacking(self):
        game, romfs = self.make_game_folder("romfs_packed")
        (romfs / "romfs.bin").write_bytes(b"synthetic packed asset")
        (romfs / "index.json").write_bytes(b"{}")
        aoc_packed = game / "aoc_packed" / "1"
        aoc_packed.mkdir(parents=True)
        (aoc_packed / "romfs.bin").write_bytes(b"synthetic packed aoc")
        (aoc_packed / "index.json").write_bytes(b'{"files": []}')
        (game / "aoc" / "1" / "romfs").mkdir(parents=True)

        with patch("installer.nup_workflow.subprocess.Popen", FakeProcess), \
             patch("installer.local_build.install_local_build", return_value="installed"):
            workflow.run_folder_workflow(game, self.workspace, self.destination,
                                         repo_root=self.repo, build_python=self.build_python)

        dump = self.workspace / "dump"
        self.assertEqual(len(FakeProcess.commands), 1)
        self.assertIn("universal_ns2_to_pc.py", FakeProcess.commands[0][1])
        self.assertEqual((dump / "aoc_packed" / "1" / "romfs.bin").read_bytes(), b"synthetic packed aoc")
        self.assertEqual((dump / "aoc_packed" / "1" / "index.json").read_bytes(), b'{"files": []}')
        self.assertTrue((dump / "aoc" / "1" / "romfs").is_dir())

    def test_run_command_scrubs_host_python_env_vars(self):
        FakeProcess.outputs = ["Lifting modules\nBUILD COMPLETE\n"]
        with patch.dict(os.environ, {"PYTHONPATH": "C:\\bad-py", "PYTHONHOME": "C:\\bad-home"}), \
             patch("installer.nup_workflow.subprocess.Popen", FakeProcess), \
             patch("installer.local_build.install_local_build", return_value="installed"):
            _, romfs = self.make_game_folder("romfs_packed")
            (romfs / "romfs.bin").write_bytes(b"packed")
            (romfs / "index.json").write_bytes(b"{}")
            workflow.run_folder_workflow(romfs, self.workspace, self.destination,
                                         repo_root=self.repo, build_python=self.build_python)

        env = FakeProcess.options[0]["env"]
        keys_upper = {k.upper() for k in env}
        self.assertNotIn("PYTHONPATH", keys_upper)
        self.assertNotIn("PYTHONHOME", keys_upper)


if __name__ == "__main__":
    unittest.main()
