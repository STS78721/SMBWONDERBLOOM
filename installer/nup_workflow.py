"""Prepare and install a local game from a NUP file or extracted folders.

This module is the orchestration layer only. It leaves the NUP extractor and game
builder as separate existing tools, and delegates the final allowlisted copy to
``installer.local_build``. Workspaces are never removed.
"""

from __future__ import annotations

import os
import queue
import re
import signal
import stat
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


ProgressCallback = Callable[["WorkflowProgress"], None]
_FILE_PROGRESS = re.compile(
    r"(?P<done>[\d,]+)/(?P<total>[\d,]+)\s+files,\s*"
    r"(?P<done_gb>[\d.]+)\s+of\s+(?P<total_gb>[\d.]+)\s+GB",
    re.IGNORECASE,
)
_MAX_ERROR_LINES = 32
_MAX_LINE_CHARS = 1200


@dataclass(frozen=True)
class WorkflowProgress:
    """One UI-friendly phase or progress update.

    ``phase`` is ``validate``, ``extract``, ``build``, ``install``, ``shaders`` or ``complete``.
    Extract progress reports files and, when the tool provides it, bytes. Install
    progress mirrors local_build's copy/backup byte counts and file stages.
    """

    phase: str
    status: str
    completed: int | None = None
    total: int | None = None
    unit: str | None = None
    message: str = ""
    relative_path: str = ""


@dataclass(frozen=True)
class NupWorkflowResult:
    workspace: Path
    dump_dir: Path
    build_dir: Path
    destination: Path
    install_result: Any
    shader_warning: str = ""


class NupWorkflowError(RuntimeError):
    """A validation, extraction, build, or install failure."""

    def __init__(self, phase: str, message: str, *, returncode: int | None = None):
        super().__init__(message)
        self.phase = phase
        self.returncode = returncode


class NupWorkflowCancelled(NupWorkflowError):
    """The caller cancelled the workflow."""

    def __init__(self, phase: str):
        super().__init__(phase, f"NUP workflow cancelled during {phase}")


@dataclass(frozen=True)
class _Inputs:
    repo_root: Path
    build_python: Path
    source: Path
    workspace: Path
    destination: Path


def _is_reparse(st: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & reparse_flag)


def _path_without_reparse(value: str | os.PathLike[str], label: str) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    raw = Path(os.path.abspath(raw))

    # Inspect existing components before resolve() follows them. This keeps the
    # path relationship checks meaningful on Windows reparse points as well.
    current = Path(raw.anchor)
    for part in raw.parts[1:]:
        current /= part
        try:
            st = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise NupWorkflowError("validate", f"Cannot inspect {label}: {exc}") from None
        if _is_reparse(st):
            raise NupWorkflowError("validate", f"{label} contains a symbolic link or reparse point: {current}")
    return raw.resolve(strict=False)


def _overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _require_file(path: Path, label: str) -> None:
    try:
        st = path.lstat()
    except OSError as exc:
        raise NupWorkflowError("validate", f"{label} is unavailable: {path} ({exc})") from None
    if _is_reparse(st) or not stat.S_ISREG(st.st_mode):
        raise NupWorkflowError("validate", f"{label} must be a regular file: {path}")


_SETUP_SCRIPTS = ("tools/extract_nup.py", "tools/universal_ns2_to_pc.py", "installer/local_build.py")
_PORTABLE_FILES = ("python/python.exe", "llvm/bin/clang.exe", "bin/ninja.exe", "tools/dkb_pack_romfs.py")
_PORTABLE_FOLDERS = ("runtime/deps/include", "runtime/deps/lib")
_ROMFS_NAMES = ("romfs", "romfs_packed", "ExtractedRomFS")
_EXEFS_FILE = re.compile(r"(?:main(?:\.npdm)?|sdk|rtld|subsdk[0-9]+)", re.IGNORECASE)


def _has_git_marker(root: Path) -> bool:
    try:
        git_stat = (root / ".git").lstat()
    except OSError:
        return False
    return not _is_reparse(git_stat) and (stat.S_ISREG(git_stat.st_mode) or stat.S_ISDIR(git_stat.st_mode))


def is_setup_root(root: Path) -> bool:
    """Identify a source checkout or the complete portable setup package."""
    try:
        root = _path_without_reparse(root, "setup folder")
        for relative in _SETUP_SCRIPTS:
            _require_file(_path_without_reparse(root / relative, "setup tool"), "setup tool")
        if _has_git_marker(root):
            return True
        for relative in _PORTABLE_FILES:
            _require_file(_path_without_reparse(root / relative, "setup tool"), "setup tool")
        return all(_path_without_reparse(root / relative, "setup folder").is_dir()
                   for relative in _PORTABLE_FOLDERS)
    except (NupWorkflowError, OSError, ValueError):
        return False


def _raw_paths(path: Path) -> tuple[Path, Path, Path]:
    selected = _path_without_reparse(path, "game data folder")
    selecting_romfs = selected.name.casefold() in {name.casefold() for name in _ROMFS_NAMES}
    root = selected.parent if selecting_romfs else selected
    exefs = next((root / name for name in ("exefs", "ExtractedExeFS")
                  if (root / name / "main").is_file()
                  and ((root / name / "sdk").is_file() or (root / name / "main.npdm").is_file())), None)
    choices = (selected,) if selecting_romfs else tuple(root / name for name in _ROMFS_NAMES)
    romfs = next((choice for choice in choices if choice.is_dir()), None)
    if exefs is None or romfs is None:
        raise NupWorkflowError("validate", "Choose the folder with both ExeFS and RomFS.")
    return root, _path_without_reparse(exefs, "ExeFS folder"), _path_without_reparse(romfs, "RomFS folder")


def locate_game_folder(path: Path) -> Path:
    """Return the game data root when the root or its RomFS folder was selected."""
    root, _, _ = _raw_paths(path)
    return root


def _validate_inputs(repo_root: str | os.PathLike[str],
                     build_python: str | os.PathLike[str],
                     source: Path,
                     workspace: str | os.PathLike[str],
                     destination: str | os.PathLike[str]) -> _Inputs:
    repo = _path_without_reparse(repo_root, "setup folder")
    build_py = _path_without_reparse(build_python, "build Python executable")
    work = _path_without_reparse(workspace, "workspace")
    dest = _path_without_reparse(destination, "destination")

    if not is_setup_root(repo):
        raise NupWorkflowError("validate", f"Setup files are missing from {repo}")
    _require_file(build_py, "Build Python executable")

    if _overlap(source, repo):
        raise NupWorkflowError("validate", "Keep the selected game file or folder outside the repository")
    if _overlap(work, repo):
        raise NupWorkflowError("validate", "The chosen workspace must be separate from the repository")
    if _overlap(source, work):
        raise NupWorkflowError("validate", "Keep the selected game file or folder separate from the workspace")
    if _overlap(dest, repo):
        raise NupWorkflowError("validate", "The install destination must be separate from the repository")
    if _overlap(dest, work):
        raise NupWorkflowError("validate", "The install destination must be separate from the workspace")
    if _overlap(source, dest):
        raise NupWorkflowError("validate", "Choose an install folder separate from your game file or folder")
    if work.exists() and not work.is_dir():
        raise NupWorkflowError("validate", f"The chosen workspace is not a folder: {work}")
    if dest.exists():
        if not dest.is_dir():
            raise NupWorkflowError("validate", f"The install destination is not a folder: {dest}")
        from .local_build import LocalBuildError, _read_marker
        try:
            _read_marker(dest)
        except LocalBuildError as exc:
            raise NupWorkflowError("validate", str(exc)) from exc
    if work.exists():
        try:
            next(work.iterdir())
        except StopIteration:
            pass
        except OSError as exc:
            raise NupWorkflowError("validate", f"Cannot inspect the chosen workspace: {exc}") from None
        else:
            raise NupWorkflowError("validate", "Choose an empty workspace; existing files are left untouched")

    return _Inputs(repo, build_py, source, work, dest)


def _emit(callback: ProgressCallback | None, event: WorkflowProgress) -> None:
    if callback:
        callback(event)


def _check_cancelled(cancel_event: Any, phase: str) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise NupWorkflowCancelled(phase)


def _sanitize_line(line: str, inputs: _Inputs) -> str:
    clean = line.rstrip("\r\n")[:_MAX_LINE_CHARS]
    hidden = (
        (inputs.source, "<game source>"),
        (inputs.workspace, "<workspace>"),
        (inputs.destination, "<destination>"),
        (inputs.repo_root, "<repository>"),
    )
    for path, replacement in sorted(hidden, key=lambda entry: len(str(entry[0])), reverse=True):
        for spelling in {str(path), path.as_posix()}:
            clean = re.sub(re.escape(spelling), replacement, clean, flags=re.IGNORECASE)
    return clean


def _extract_progress(line: str, callback: ProgressCallback | None) -> None:
    match = _FILE_PROGRESS.search(line)
    if not match:
        return
    done = int(match.group("done").replace(",", ""))
    total = int(match.group("total").replace(",", ""))
    _emit(callback, WorkflowProgress("extract", "progress", done, total, "files", line.strip()))
    done_bytes = int(float(match.group("done_gb")) * 1_000_000_000)
    total_bytes = int(float(match.group("total_gb")) * 1_000_000_000)
    _emit(callback, WorkflowProgress("extract", "progress", done_bytes, total_bytes, "bytes", line.strip()))


def _stop_process(proc: subprocess.Popen[str]) -> None:
    """Try to stop the phase process group, then fall back to terminating its parent."""
    try:
        if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        elif os.name != "nt" and getattr(proc, "pid", None):
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
    except (OSError, ProcessLookupError, AttributeError):
        try:
            proc.terminate()
        except OSError:
            pass
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            if os.name != "nt" and getattr(proc, "pid", None):
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except (OSError, ProcessLookupError, AttributeError):
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass


def _run_command(command: list[str], *, cwd: Path, phase: str, inputs: _Inputs,
                 callback: ProgressCallback | None, cancel_event: Any) -> None:
    _check_cancelled(cancel_event, phase)
    _emit(callback, WorkflowProgress(phase, "started", message=f"Starting {phase}"))
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
        "shell": False,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        raise NupWorkflowError(phase, f"Could not start {phase}: {exc}") from None

    lines: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        try:
            if proc.stdout is not None:
                for value in proc.stdout:
                    lines.put(value)
        finally:
            lines.put(None)

    reader = threading.Thread(target=read_output, name=f"nup-{phase}-output", daemon=True)
    reader.start()
    tail: deque[str] = deque(maxlen=_MAX_ERROR_LINES)
    stream_done = False
    last_build_update = 0.0
    try:
        while not stream_done:
            if cancel_event is not None and cancel_event.is_set():
                if proc.poll() is None:
                    _stop_process(proc)
                raise NupWorkflowCancelled(phase)
            try:
                raw_line = lines.get(timeout=0.1)
            except queue.Empty:
                if proc.poll() is not None and not reader.is_alive():
                    break
                continue
            if raw_line is None:
                stream_done = True
                continue

            line = _sanitize_line(raw_line, inputs)
            if line:
                tail.append(line)
                if phase == "extract":
                    _extract_progress(line, callback)
                elif phase == "build":
                    now = time.monotonic()
                    if now - last_build_update >= 0.25:
                        _emit(callback, WorkflowProgress("build", "progress", message=line))
                        last_build_update = now

        returncode = proc.wait()
    except BaseException:
        if proc.poll() is None:
            _stop_process(proc)
        raise
    finally:
        reader.join(timeout=1)
        if proc.stdout is not None:
            try:
                proc.stdout.close()
            except OSError:
                pass

    if returncode != 0:
        detail = "\n".join(tail)
        message = f"{phase.capitalize()} failed with exit code {returncode}"
        if detail:
            message += f":\n{detail}"
        raise NupWorkflowError(phase, message, returncode=returncode)
    _emit(callback, WorkflowProgress(phase, "completed", message=f"{phase.capitalize()} complete"))


def _find_build_dir(dump_dir: Path) -> Path:
    build_root = dump_dir / "build"
    try:
        root_stat = build_root.lstat()
    except OSError:
        raise NupWorkflowError("build", "Build command succeeded but created no build folder")
    if _is_reparse(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        raise NupWorkflowError("build", f"Build output is not a regular folder: {build_root}")
    manifests = []
    try:
        for version_dir in build_root.iterdir():
            try:
                version_stat = version_dir.lstat()
            except FileNotFoundError:
                continue
            if _is_reparse(version_stat) or not stat.S_ISDIR(version_stat.st_mode):
                continue
            candidate = version_dir / "ns2-build-manifest.json"
            try:
                st = candidate.lstat()
            except FileNotFoundError:
                continue
            if _is_reparse(st) or not stat.S_ISREG(st.st_mode):
                raise NupWorkflowError("build", f"Build manifest is not a regular file: {candidate}")
            manifests.append(candidate)
    except OSError as exc:
        raise NupWorkflowError("build", f"Cannot inspect build output: {exc}") from None
    if len(manifests) != 1:
        raise NupWorkflowError("build", f"Expected one build manifest under {build_root}; found {len(manifests)}")
    return manifests[0].parent


def _make_dump_folder(inputs: _Inputs) -> Path:
    try:
        inputs.workspace.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise NupWorkflowError("validate", f"Cannot create chosen workspace: {exc}") from None
    # Recheck after creation to catch an unexpected link/race, and use mkdir without
    # exist_ok so pre-existing extracted data is never silently reused or changed.
    _path_without_reparse(inputs.workspace, "workspace")
    dump_dir = inputs.workspace / "dump"
    try:
        dump_dir.mkdir()
    except FileExistsError:
        raise NupWorkflowError("validate", "The workspace already contains a dump folder; choose an empty workspace") from None
    except OSError as exc:
        raise NupWorkflowError("validate", f"Cannot create dump workspace: {exc}") from None
    return dump_dir


def _build_and_install(inputs: _Inputs, dump_dir: Path, *, progress_callback: ProgressCallback | None,
                       cancel_event: Any) -> NupWorkflowResult:
    build_cmd = [str(inputs.build_python), str(inputs.repo_root / "tools" / "universal_ns2_to_pc.py"),
                 "port", "--folder", str(dump_dir), "--no-bringup", "--seed-shaders-only"]
    _run_command(build_cmd, cwd=inputs.repo_root, phase="build", inputs=inputs,
                 callback=progress_callback, cancel_event=cancel_event)
    build_dir = _find_build_dir(dump_dir)
    _check_cancelled(cancel_event, "install")

    _emit(progress_callback, WorkflowProgress("install", "started", message="Installing verified local build"))
    try:
        from .local_build import install_local_build, prepare_installed_shaders

        def install_progress(phase: str, completed: int, total: int, relative_path: str) -> None:
            _check_cancelled(cancel_event, "install")
            unit = "bytes" if phase.endswith("bytes") else "files"
            _emit(progress_callback, WorkflowProgress("install", "progress", completed, total,
                                                       unit, phase, relative_path))

        install_result = install_local_build(build_dir, inputs.destination,
                                             progress_callback=install_progress,
                                             game_data_dir=dump_dir)
    except NupWorkflowCancelled:
        raise
    except Exception as exc:
        raise NupWorkflowError("install", str(exc)) from exc

    _emit(progress_callback, WorkflowProgress("install", "completed", message="Install complete"))
    shader_warning = prepare_installed_shaders(
        install_result, cancel_event=cancel_event,
        on_start=lambda: _emit(progress_callback, WorkflowProgress("shaders", "started", message="Preparing graphics")),
        on_train=lambda: _emit(progress_callback, WorkflowProgress("graphics", "started", message="Caching graphics for first play")),
    )
    _emit(progress_callback, WorkflowProgress("complete", "completed", message="Setup complete"))
    return NupWorkflowResult(inputs.workspace, dump_dir, build_dir, inputs.destination, install_result, shader_warning)


def run_nup_workflow(nup_path: str | os.PathLike[str],
                     workspace: str | os.PathLike[str],
                     destination: str | os.PathLike[str], *,
                     repo_root: str | os.PathLike[str],
                     extractor_python: str | os.PathLike[str],
                     build_python: str | os.PathLike[str],
                     progress_callback: ProgressCallback | None = None,
                     cancel_event: Any = None) -> NupWorkflowResult:
    """Extract, build and install a local `.nup`, retaining the separate work folder."""
    _emit(progress_callback, WorkflowProgress("validate", "started", message="Checking paths and tools"))
    source = _path_without_reparse(nup_path, "NUP source")
    _require_file(source, "NUP source")
    if source.suffix.casefold() != ".nup":
        raise NupWorkflowError("validate", "Select a local .nup file")
    extractor = _path_without_reparse(extractor_python, "extractor Python executable")
    _require_file(extractor, "Extractor Python executable")
    inputs = _validate_inputs(repo_root, build_python, source, workspace, destination)
    _emit(progress_callback, WorkflowProgress("validate", "completed", message="Paths and tools validated"))
    _check_cancelled(cancel_event, "validate")

    dump_dir = _make_dump_folder(inputs)
    extract_cmd = [str(extractor), str(inputs.repo_root / "tools" / "extract_nup.py"),
                   str(inputs.source), "--out", str(dump_dir)]
    _run_command(extract_cmd, cwd=inputs.repo_root, phase="extract", inputs=inputs,
                 callback=progress_callback, cancel_event=cancel_event)
    return _build_and_install(inputs, dump_dir, progress_callback=progress_callback, cancel_event=cancel_event)


def _copy_game_file(source: Path, target: Path, cancel_event: Any) -> None:
    _require_file(source, "Game file")
    with source.open("rb") as original, target.open("xb") as copied:
        while chunk := original.read(8 * 1024 * 1024):
            _check_cancelled(cancel_event, "extract")
            copied.write(chunk)


def _check_romfs_tree(root: Path, cancel_event: Any) -> None:
    # The packer reads file contents. Check for links and other special files before it begins.
    pending = [root]
    has_files = False
    while pending:
        _check_cancelled(cancel_event, "extract")
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if _is_reparse(info) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                    raise NupWorkflowError("extract", f"Game folder contains a link or special file: {entry.path}")
                if stat.S_ISDIR(info.st_mode):
                    pending.append(entry.path)
                elif not entry.name.startswith("."):
                    has_files = True
    if not has_files:
        raise NupWorkflowError("extract", "The RomFS folder is empty. Choose your extracted game folder.")


def run_folder_workflow(game_folder: str | os.PathLike[str],
                        workspace: str | os.PathLike[str],
                        destination: str | os.PathLike[str], *,
                        repo_root: str | os.PathLike[str],
                        build_python: str | os.PathLike[str],
                        progress_callback: ProgressCallback | None = None,
                        cancel_event: Any = None) -> NupWorkflowResult:
    """Prepare a staged copy of extracted game files and install from that copy."""
    _emit(progress_callback, WorkflowProgress("validate", "started", message="Checking paths and tools"))
    source, exefs, romfs = _raw_paths(Path(game_folder))
    inputs = _validate_inputs(repo_root, build_python, source, workspace, destination)
    packer = _path_without_reparse(inputs.repo_root / "tools" / "dkb_pack_romfs.py", "RomFS preparation tool")
    _require_file(packer, "RomFS preparation tool")
    _emit(progress_callback, WorkflowProgress("validate", "completed", message="Paths and tools validated"))
    _check_cancelled(cancel_event, "validate")

    dump_dir = _make_dump_folder(inputs)
    packed = dump_dir / "romfs_packed"
    _emit(progress_callback, WorkflowProgress("extract", "started", message="Preparing game files"))
    try:
        (dump_dir / "exefs").mkdir()
        for item in exefs.iterdir():
            if _EXEFS_FILE.fullmatch(item.name):
                _copy_game_file(item, dump_dir / "exefs" / item.name.lower(), cancel_event)
        if os.path.lexists(source / "title.json"):
            _copy_game_file(source / "title.json", dump_dir / "title.json", cancel_event)

        has_packed_image = os.path.lexists(romfs / "romfs.bin") and os.path.lexists(romfs / "index.json")
        if romfs.name.casefold() == "romfs_packed" and not has_packed_image:
            raise NupWorkflowError("extract", "This packed RomFS folder is incomplete. Choose your extracted game folder.")
        if has_packed_image:
            packed.mkdir()
            for name in ("index.json", "romfs.bin"):
                _copy_game_file(romfs / name, packed / name, cancel_event)
            _emit(progress_callback, WorkflowProgress("extract", "completed", message="Game files prepared"))
        else:
            _check_romfs_tree(romfs, cancel_event)
            pack_cmd = [str(inputs.build_python), str(packer), "--dir", str(romfs), "--out", str(packed)]
            _run_command(pack_cmd, cwd=inputs.repo_root, phase="extract", inputs=inputs,
                         callback=progress_callback, cancel_event=cancel_event)
            if (romfs / ".nrr").is_dir():
                # The builder uses the directory's presence to detect runtime modules in the packed image.
                (packed / ".nrr").mkdir()
    except OSError as exc:
        raise NupWorkflowError("extract", f"Could not prepare the game folder: {exc}") from None

    return _build_and_install(inputs, dump_dir, progress_callback=progress_callback, cancel_event=cancel_event)


__all__ = [
    "NupWorkflowError",
    "NupWorkflowCancelled",
    "NupWorkflowResult",
    "WorkflowProgress",
    "is_setup_root",
    "locate_game_folder",
    "run_folder_workflow",
    "run_nup_workflow",
]
