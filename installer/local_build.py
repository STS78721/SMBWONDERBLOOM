"""Install a locally compiled build from an explicit, safety-checked manifest.

The source build stays outside the repository. Only files named in
``ns2-build-manifest.json`` are staged and copied to the destination.

Schema 1 requires ``schema``, ``game_id``, ``game_title``, ``game_version``,
``port_version``, ``executable``, ``files`` and ``game_data``. ``game_data`` contains
``exefs_dir``, ``exefs_sha256``, ``romfs_path`` and ``romfs_size``. The manifest is
supplied by a trusted local build step; this module deliberately does not walk a
build or dump folder to invent a file list.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

MANIFEST_NAME = "ns2-build-manifest.json"
MARKER_NAME = "ns2-build-install.json"
SCHEMA = 1
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_FILES = 20_000
_GAME_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                 *(f"LPT{i}" for i in range(1, 10))}

_BLOCKED_DIRS = {
    "profile", "profiles", "save", "saves", "save-data", "userdata", "user-data",
    "screenshots", "screenshot", "logs", "log", "cover-art", "exefs", "romfs",
}
_BLOCKED_SUFFIXES = {
    ".ini", ".log", ".err", ".out", ".trace", ".dmp",
    ".obj", ".o", ".pdb", ".ilk", ".lib", ".a", ".exp", ".map", ".ninja", ".pyc", ".pyo",
    ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".cab", ".zst", ".lz4",
    ".nup", ".nsp", ".nsz", ".nca", ".ncz", ".xci", ".xcz", ".tik", ".cert",
    ".nso", ".nro", ".nrr", ".npdm", ".romfs", ".rom",
}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
_SCREENSHOT_WORDS = ("screenshot", "menu-test", "launcher-check", "preview-")
_ROM_NAMES = {"main", "rtld", "sdk", "subsdk0", "subsdk1", "main.npdm"}
_ALLOWED_RUNTIME_BINS = {
    "romfs-index.bin", "aoc-index.bin", "seed-answers.bin", "seed-programs.bin",
    "shader-answers.bin", "shader-programs.bin", "shader-prepared.bin",
}
_AOC_DIR = re.compile(r"aoc-[0-9a-f]{1,8}\Z", re.IGNORECASE)
_EXEFS_FILE = re.compile(r"(?:main(?:\.npdm)?|rtld|sdk|subsdk[0-9]{1,3})\Z")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
_ROMFS_SOURCES = {"romfs_packed/romfs.bin", "romfs/romfs.bin"}
_PATCH_TREE = re.compile(r"romfs-patches(?:-[a-z0-9_-]+)?\Z", re.IGNORECASE)
_BLOCKED_NAMES = {
    "config.local.toml", "config.toml", "launcher_config.json", "settings.json", "settings.toml",
    "preferences.json", "profile.json", MANIFEST_NAME.casefold(), MARKER_NAME.casefold(),
}


class LocalBuildError(ValueError):
    """The local build or destination failed a safety or format check."""


@dataclass(frozen=True)
class BuildManifest:
    game_id: str
    game_title: str
    game_version: str
    port_version: str
    executable: str
    files: tuple[str, ...]
    game_data: GameDataManifest


@dataclass(frozen=True)
class GameDataManifest:
    exefs_dir: str
    exefs_sha256: dict[str, str]
    romfs_path: str | None
    romfs_size: int | None


@dataclass(frozen=True)
class InstallResult:
    game_id: str
    game_title: str
    game_version: str
    port_version: str
    executable: Path
    files: tuple[Path, ...]
    marker: Path


ProgressCallback = Callable[[str, int, int, str], None]
_WARM_RECEIPT = "ns2-shaders-ready.bin"
_SHADER_WARNING = "Graphics preparation couldn’t finish. You can still play."
_SHADER_SKIPPED = "Graphics preparation was skipped. You can still play."
_WARMUP_DATA = Path(__file__).resolve().parents[1] / "tools" / "data"
SHADER_WARMUP_ROUTES = {"040015100B514001": ("1.0.0", 105)}


_CLOUD_TAG_MASK = 0xFFFF0FFF
_CLOUD_TAG_BASE = 0x9000001A
_ONEDRIVE_TAG = 0x80000021


def _is_cloud_sync_tag(st: os.stat_result) -> bool:
    tag = getattr(st, "st_reparse_tag", 0)
    return bool(tag) and (((tag & _CLOUD_TAG_MASK) == _CLOUD_TAG_BASE) or tag == _ONEDRIVE_TAG)


def _is_reparse(st: os.stat_result) -> bool:
    if stat.S_ISLNK(st.st_mode):
        return True
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if not (getattr(st, "st_file_attributes", 0) & reparse):
        return False
    return not _is_cloud_sync_tag(st)


def _lstat(path: Path, what: str) -> os.stat_result:
    try:
        st = path.lstat()
    except FileNotFoundError:
        raise LocalBuildError(f"{what} does not exist: {path}") from None
    except OSError as exc:
        raise LocalBuildError(f"Cannot inspect {what}: {path}: {exc}") from None
    if _is_reparse(st):
        raise LocalBuildError(f"Reparse points and symbolic links are not allowed: {path}")
    return st


def _absolute(path: str | os.PathLike[str], what: str) -> Path:
    try:
        raw = os.fspath(path)
    except TypeError:
        raise LocalBuildError(f"{what} must be a filesystem path") from None
    if not isinstance(raw, str) or not raw or "\0" in raw:
        raise LocalBuildError(f"{what} must be a non-empty filesystem path")
    return Path(os.path.abspath(raw))


def _check_existing_ancestors(path: Path, what: str) -> None:
    """Reject a symlink/junction anywhere in an existing path prefix."""
    for part in reversed((path, *path.parents)):
        try:
            st = part.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise LocalBuildError(f"Cannot inspect {what}: {part}: {exc}") from None
        if _is_reparse(st):
            raise LocalBuildError(f"Reparse points and symbolic links are not allowed in {what}: {part}")


def _overlap(a: Path, b: Path) -> bool:
    na, nb = os.path.normcase(os.path.abspath(a)), os.path.normcase(os.path.abspath(b))
    try:
        common = os.path.commonpath((na, nb))
    except ValueError:  # Different Windows drives.
        return False
    return common == na or common == nb


def _metadata_string(data: dict, key: str, maximum: int) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise LocalBuildError(f"Manifest field {key!r} must be a non-empty string of at most {maximum} characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise LocalBuildError(f"Manifest field {key!r} contains a control character")
    return value


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\0" in value or "\\" in value or ":" in value:
        raise LocalBuildError(f"Manifest file path is not a safe relative path: {value!r}")
    if value.startswith("/"):
        raise LocalBuildError(f"Manifest file path is not relative: {value!r}")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise LocalBuildError(f"Manifest file path contains an unsafe component: {value!r}")
    if any(part.endswith((".", " ")) for part in parts):
        raise LocalBuildError(f"Manifest file path has a Windows-ambiguous component: {value!r}")
    if any(part.split(".", 1)[0].upper() in _DEVICE_NAMES for part in parts):
        raise LocalBuildError(f"Manifest file path uses a reserved device name: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value:
        raise LocalBuildError(f"Manifest file path is not canonical: {value!r}")
    _check_blocked(value)
    return value


def _check_blocked(value: str) -> None:
    parts = [part.casefold() for part in value.split("/")]
    name = parts[-1]
    suffix = Path(name).suffix.casefold()
    in_patch_tree = bool(_PATCH_TREE.fullmatch(parts[0]))
    if name in _BLOCKED_NAMES:
        raise LocalBuildError(f"Manifest includes a personal settings or installer metadata file: {value}")
    if any(part in _BLOCKED_DIRS for part in parts):
        raise LocalBuildError(f"Manifest includes a blocked personal-data or source-data directory: {value}")
    if any("cache" in part for part in parts):
        raise LocalBuildError(f"Manifest includes a cache path: {value}")
    if name in _ROM_NAMES or _EXEFS_FILE.fullmatch(name):
        raise LocalBuildError(f"Manifest includes a raw game module or ROM image: {value}")
    in_aoc_dir = len(parts) == 2 and bool(_AOC_DIR.fullmatch(parts[0]))
    aoc_romfs = in_aoc_dir and name == "romfs.bin"
    aoc_index = in_aoc_dir and name == "aoc-index.bin"
    if name == "romfs.bin" and not aoc_romfs:
        raise LocalBuildError(f"Manifest includes a raw RomFS image outside a recognized AOC folder: {value}")
    if suffix in _BLOCKED_SUFFIXES:
        raise LocalBuildError(f"Manifest includes a blocked settings, build, archive, or ROM/container file: {value}")
    if suffix == ".bin" and not (aoc_romfs or aoc_index) and not (len(parts) == 1 and name in _ALLOWED_RUNTIME_BINS):
        raise LocalBuildError(f"Manifest includes an unrecognized binary cache or game-data file: {value}")
    if suffix in _IMAGE_SUFFIXES and not (in_patch_tree or (len(parts) == 1 and name == "launcher_icon.png")):
        raise LocalBuildError(f"Manifest includes an image that may be cover art or a screenshot: {value}")
    if any(word in name for word in _SCREENSHOT_WORDS):
        raise LocalBuildError(f"Manifest includes a screenshot or preview file: {value}")


def _parse_manifest(source: Path) -> BuildManifest:
    manifest_path = source / MANIFEST_NAME
    st = _lstat(manifest_path, "build manifest")
    if not stat.S_ISREG(st.st_mode) or st.st_size > _MAX_MANIFEST_BYTES:
        raise LocalBuildError(f"Build manifest is not a regular file or is too large: {manifest_path}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LocalBuildError(f"Cannot read build manifest: {exc}") from None
    expected = {"schema", "game_id", "game_title", "game_version", "port_version", "executable", "files",
                "game_data"}
    if not isinstance(data, dict) or set(data) != expected:
        raise LocalBuildError(f"Manifest must contain exactly these fields: {', '.join(sorted(expected))}")
    if type(data["schema"]) is not int or data["schema"] != SCHEMA:
        raise LocalBuildError(f"Unsupported manifest schema: {data['schema']!r}")
    game_id = _metadata_string(data, "game_id", 128)
    if not _GAME_ID.fullmatch(game_id):
        raise LocalBuildError("Manifest game_id may contain only letters, digits, dot, underscore and hyphen")
    title = _metadata_string(data, "game_title", 256)
    game_version = _metadata_string(data, "game_version", 64)
    port_version = _metadata_string(data, "port_version", 64)
    executable = _safe_relative(data["executable"])
    raw_files = data["files"]
    if not isinstance(raw_files, list) or not raw_files or len(raw_files) > _MAX_FILES:
        raise LocalBuildError(f"Manifest files must be a non-empty list of at most {_MAX_FILES} paths")
    files = tuple(_safe_relative(path) for path in raw_files)
    if len({path.casefold() for path in files}) != len(files):
        raise LocalBuildError("Manifest lists the same file more than once (case-insensitive)")
    if executable.casefold() not in {path.casefold() for path in files}:
        raise LocalBuildError("Manifest executable must also appear in files")
    if executable == MANIFEST_NAME or executable == MARKER_NAME:
        raise LocalBuildError("Manifest executable cannot be an installer metadata file")
    raw_game_data = data["game_data"]
    if (not isinstance(raw_game_data, dict)
            or set(raw_game_data) != {"exefs_dir", "exefs_sha256", "romfs_path", "romfs_size"}):
        raise LocalBuildError("Manifest game_data must contain exefs_dir, exefs_sha256, romfs_path and romfs_size")
    exefs_dir = raw_game_data["exefs_dir"]
    if exefs_dir != "exefs":
        raise LocalBuildError("Manifest game_data.exefs_dir must be the safe build-relative folder 'exefs'")
    exefs_sha256 = raw_game_data["exefs_sha256"]
    if not isinstance(exefs_sha256, dict) or not exefs_sha256 or "main" not in exefs_sha256:
        raise LocalBuildError("Manifest game_data.exefs_sha256 must map exact module names and include main")
    checked_hashes: dict[str, str] = {}
    for module, digest in exefs_sha256.items():
        if not isinstance(module, str) or not _EXEFS_FILE.fullmatch(module):
            raise LocalBuildError(f"Invalid ExeFS file name: {module!r}")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise LocalBuildError(f"Invalid SHA-256 for ExeFS module {module!r}")
        checked_hashes[module] = digest.lower()
    romfs_path = raw_game_data["romfs_path"]
    if romfs_path is not None and (not isinstance(romfs_path, str) or romfs_path not in _ROMFS_SOURCES):
        raise LocalBuildError("Manifest game_data.romfs_path must be null, romfs_packed/romfs.bin or romfs/romfs.bin")
    romfs_size = raw_game_data["romfs_size"]
    if romfs_size is not None and (type(romfs_size) is not int or romfs_size <= 0):
        raise LocalBuildError("Manifest game_data.romfs_size must be null or a positive integer")
    return BuildManifest(game_id, title, game_version, port_version, executable, files,
                         GameDataManifest(exefs_dir, checked_hashes, romfs_path, romfs_size))


def _source_file(source: Path, relative: str) -> Path:
    current = source
    parts = relative.split("/")
    for index, part in enumerate(parts):
        current = current / part
        st = _lstat(current, "manifest file")
        if index < len(parts) - 1:
            if not stat.S_ISDIR(st.st_mode):
                raise LocalBuildError(f"A manifest path parent is not a directory: {current}")
        elif not stat.S_ISREG(st.st_mode):
            raise LocalBuildError(f"Manifest entry is not a regular file: {current}")
    return current


def _game_data_file(root: Path, relative: str) -> Path:
    """Resolve one whitelisted game-data source without walking its folder tree."""
    current = root
    parts = relative.split("/")
    for index, part in enumerate(parts):
        current /= part
        st = _lstat(current, "selected game-data file")
        if index < len(parts) - 1:
            if not stat.S_ISDIR(st.st_mode):
                raise LocalBuildError(f"A selected game-data path parent is not a directory: {current}")
        elif not stat.S_ISREG(st.st_mode):
            raise LocalBuildError(f"Selected game-data entry is not a regular file: {current}")
    return current


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while block := stream.read(8 * 1024 * 1024):
                digest.update(block)
    except OSError as exc:
        raise LocalBuildError(f"Cannot hash selected game-data file {path}: {exc}") from None
    return digest.hexdigest()


def _select_game_data(build_dir: Path, destination: Path, manifest: BuildManifest,
                      game_data_dir: str | os.PathLike[str] | None) -> dict[str, Path]:
    """Return exact destination paths mapped to source files; never enumerate either source root."""
    data = manifest.game_data
    if game_data_dir is None:
        root = build_dir
        try:
            exefs_st = _lstat(root / data.exefs_dir, "portable ExeFS folder")
        except LocalBuildError as exc:
            if "does not exist" not in str(exc):
                raise
            raise LocalBuildError("Select the local game-data folder; this build has no portable exefs folder") from None
        if not stat.S_ISDIR(exefs_st.st_mode):
            raise LocalBuildError(f"Portable ExeFS path is not a folder: {root / data.exefs_dir}")
        # A compiled build may already carry the portable RomFS. If it does not,
        # the manifest must name an external source and the caller must select it.
        romfs_source = None
        if data.romfs_path is None:
            try:
                romfs_source = _game_data_file(root, "romfs/romfs.bin")
            except LocalBuildError as exc:
                if "does not exist" not in str(exc):
                    raise
        else:
            try:
                romfs_source = _game_data_file(root, "romfs/romfs.bin")
            except LocalBuildError as exc:
                if "does not exist" not in str(exc):
                    raise
                raise LocalBuildError("Select the local game-data folder; this build has no portable romfs/romfs.bin") from None
    else:
        root = _absolute(game_data_dir, "Game-data folder")
        _check_existing_ancestors(root, "game-data folder")
        root_st = _lstat(root, "game-data folder")
        if not stat.S_ISDIR(root_st.st_mode):
            raise LocalBuildError(f"Game-data path is not a directory: {root}")
        if _overlap(root, destination):
            raise LocalBuildError("Game-data folder and destination must not contain one another")
        romfs_source = (_game_data_file(root, data.romfs_path) if data.romfs_path is not None else None)

    sources: dict[str, Path] = {}
    for module, expected in data.exefs_sha256.items():
        relative = f"{data.exefs_dir}/{module}"
        source = _game_data_file(root, relative)
        got = _sha256_file(source)
        if got != expected:
            raise LocalBuildError(f"ExeFS module {module} failed its SHA-256 check")
        sources[f"exefs/{module}"] = source

    if romfs_source is not None:
        if data.romfs_size is not None and romfs_source.stat().st_size != data.romfs_size:
            raise LocalBuildError(f"RomFS image size mismatch: expected {data.romfs_size} bytes, found {romfs_source.stat().st_size}")
        sources["romfs/romfs.bin"] = romfs_source
    elif data.romfs_size is not None:
        raise LocalBuildError("Manifest gives a RomFS size, but no RomFS source is available")
    return sources


def read_manifest(build_dir: str | os.PathLike[str]) -> BuildManifest:
    """Read and validate a build manifest and every listed source file, without copying anything."""
    source = _absolute(build_dir, "Build folder")
    _check_existing_ancestors(source, "build folder")
    st = _lstat(source, "build folder")
    if not stat.S_ISDIR(st.st_mode):
        raise LocalBuildError(f"Build folder is not a directory: {source}")
    manifest = _parse_manifest(source)
    for relative in manifest.files:
        _source_file(source, relative)
    return manifest


def _read_marker(destination: Path) -> tuple[dict | None, set[str]]:
    marker = destination / MARKER_NAME
    try:
        st = marker.lstat()
    except FileNotFoundError:
        try:
            next(destination.iterdir())
        except StopIteration:
            return None, set()
        except OSError as exc:
            raise LocalBuildError(f"Cannot inspect destination folder: {exc}") from None
        raise LocalBuildError("Destination is not empty and has no installer marker")
    except OSError as exc:
        raise LocalBuildError(f"Cannot inspect installer marker: {exc}") from None
    if _is_reparse(st):
        raise LocalBuildError(f"Installer marker cannot be a reparse point or symbolic link: {marker}")
    if not stat.S_ISREG(st.st_mode) or st.st_size > _MAX_MANIFEST_BYTES:
        raise LocalBuildError("Installer marker is not a regular file or is too large")
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LocalBuildError(f"Cannot read installer marker: {exc}") from None
    if (not isinstance(data, dict) or type(data.get("schema")) is not int or data.get("schema") != SCHEMA
            or not isinstance(data.get("files"), list)):
        raise LocalBuildError("Installer marker has an unsupported format")
    game_id = data.get("game_id")
    if not isinstance(game_id, str) or not _GAME_ID.fullmatch(game_id):
        raise LocalBuildError("Installer marker has an invalid game_id")
    owned = set()
    for value in data["files"]:
        owned.add(_safe_installed_relative(value).casefold())
    return data, owned


def _safe_installed_relative(value: object) -> str:
    if isinstance(value, str):
        if value == "romfs/romfs.bin":
            return value
        parts = value.split("/")
        if (len(parts) == 2 and parts[0] == "exefs" and _EXEFS_FILE.fullmatch(parts[1])
                and "\\" not in value and ":" not in value):
            return value
    return _safe_relative(value)


def _existing_target(destination: Path, relative: str) -> Path | None:
    """Return an existing file target in destination, or None if it or any parent is missing."""
    current = destination
    parts = relative.split("/")
    for part in parts[:-1]:
        current /= part
        try:
            st = current.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise LocalBuildError(f"Cannot inspect destination folder {current}: {exc}") from None
        if _is_reparse(st) or not stat.S_ISDIR(st.st_mode):
            raise LocalBuildError(f"Destination path contains a reparse point or non-folder: {current}")
    target = current / parts[-1]
    try:
        st = target.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LocalBuildError(f"Cannot inspect destination file {target}: {exc}") from None
    if _is_reparse(st) or not stat.S_ISREG(st.st_mode):
        raise LocalBuildError(f"Destination target is not a regular file: {target}")
    return target


def _target_path(destination: Path, relative: str, *, create: bool = False,
                 created_dirs: list[Path] | None = None) -> Path:
    current = destination
    parts = relative.split("/")
    for part in parts[:-1]:
        current /= part
        try:
            st = current.lstat()
        except FileNotFoundError:
            if not create:
                raise LocalBuildError(f"Destination parent folder is missing: {current}") from None
            try:
                current.mkdir()
            except FileExistsError:
                pass
            except OSError as exc:
                raise LocalBuildError(f"Cannot create destination folder {current}: {exc}") from None
            if created_dirs is not None and current.is_dir():
                created_dirs.append(current)
            st = _lstat(current, "destination folder")
        except OSError as exc:
            raise LocalBuildError(f"Cannot inspect destination folder {current}: {exc}") from None
        if _is_reparse(st) or not stat.S_ISDIR(st.st_mode):
            raise LocalBuildError(f"Destination path contains a reparse point or non-folder: {current}")
    target = current / parts[-1]
    try:
        st = target.lstat()
    except FileNotFoundError:
        return target
    except OSError as exc:
        raise LocalBuildError(f"Cannot inspect destination file {target}: {exc}") from None
    if _is_reparse(st) or not stat.S_ISREG(st.st_mode):
        raise LocalBuildError(f"Destination target is not a regular file: {target}")
    return target


def _write_json(path: Path, value: dict) -> None:
    data = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _copy_with_progress(source: Path, destination: Path, phase: str, relative: str,
                        completed: int, total: int, callback: ProgressCallback | None) -> int:
    """Copy in bounded chunks so a multi-gigabyte data image can report progress and be cancelled."""
    try:
        with source.open("rb") as inp, destination.open("xb") as out:
            while block := inp.read(8 * 1024 * 1024):
                out.write(block)
                completed += len(block)
                if callback:
                    callback(phase, completed, total, relative)
        shutil.copystat(source, destination)
    except OSError as exc:
        raise LocalBuildError(f"Cannot copy selected file {relative}: {exc}") from None
    if total == 0 and callback:
        callback(phase, completed, total, relative)
    return completed


def _marker(manifest: BuildManifest, installed_files: tuple[str, ...]) -> dict:
    return {
        "schema": SCHEMA,
        "game_id": manifest.game_id,
        "game_title": manifest.game_title,
        "game_version": manifest.game_version,
        "port_version": manifest.port_version,
        "executable": manifest.executable,
        "files": list(installed_files),
        "game_data": {"exefs_sha256": manifest.game_data.exefs_sha256,
                      "romfs_size": manifest.game_data.romfs_size},
    }


def _ensure_parent(path: Path) -> None:
    _check_existing_ancestors(path, "destination parent")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LocalBuildError(f"Cannot create destination parent {path}: {exc}") from None
    _check_existing_ancestors(path, "destination parent")


def _rollback(installed: list[Path], backups: dict[Path, Path], created_dirs: list[Path]) -> None:
    for target in reversed(installed):
        backup = backups.get(target)
        try:
            if backup and backup.exists():
                os.replace(backup, target)
            else:
                target.unlink(missing_ok=True)
        except OSError:
            pass
    for path in reversed(created_dirs):
        try:
            path.rmdir()
        except OSError:
            pass


def install_local_build(build_dir: str | os.PathLike[str], destination: str | os.PathLike[str],
                        progress_callback: ProgressCallback | None = None, *,
                        game_data_dir: str | os.PathLike[str] | None = None) -> InstallResult:
    """Install the files in a schema-1 local build manifest.

    An empty destination is published with a same-volume directory rename. For an
    existing install from the same game, files are staged first, atomically replaced
    one by one, and the marker is atomically written last. Unlisted files are never
    traversed, changed, or deleted. If supplied, ``progress_callback`` receives
    ``(phase, completed, total, relative_path)``. ``copy-bytes`` and ``backup-bytes``
    report byte totals for large files; ``stage`` and ``install`` report file counts;
    ``publish`` marks the final directory rename. Callback paths are relative. A
    callback exception cancels the operation and staged or replaced files are rolled
    back where needed. ``game_data_dir`` selects the local data root containing the
    manifest's ``exefs_dir`` and optional ``romfs_path``; without it, portable assets
    must already be beside the compiled build.
    """
    source = _absolute(build_dir, "Build folder")
    dest = _absolute(destination, "Destination folder")
    _check_existing_ancestors(source, "build folder")
    _check_existing_ancestors(dest, "destination folder")
    if _overlap(source, dest):
        raise LocalBuildError("Build folder and destination must not contain one another")
    manifest = read_manifest(source)
    # Older manifests listed the temporary build's shader list. Warm the installed
    # executable instead, and leave its local list outside update ownership.
    source_files = {relative: _source_file(source, relative) for relative in manifest.files
                    if relative.casefold() != "shader-prepared.bin"}
    game_data_files = _select_game_data(source, dest, manifest, game_data_dir)
    all_sources = {**source_files, **game_data_files}
    installed_files = tuple(all_sources)
    if len({relative.casefold() for relative in installed_files}) != len(installed_files):
        raise LocalBuildError("Manifest files collide with a game-data install path")

    source_sizes = {relative: _lstat(path, "selected install source").st_size
                    for relative, path in all_sources.items()}
    copy_total = sum(source_sizes.values())
    _ensure_parent(dest.parent)
    if dest.exists():
        dst_st = _lstat(dest, "destination folder")
        if not stat.S_ISDIR(dst_st.st_mode):
            raise LocalBuildError(f"Destination is not a directory: {dest}")
        previous, owned = _read_marker(dest)
        if previous is not None and previous.get("game_id") != manifest.game_id:
            raise LocalBuildError("Destination is marked for a different game")
        if previous is not None:
            # Never overwrite an unowned path in an existing destination.
            backup_total = 0
            for relative in installed_files:
                target = _existing_target(dest, relative)
                if target is not None:
                    if relative.casefold() not in owned:
                        raise LocalBuildError(f"Refusing to replace a file not recorded by this installer: {relative}")
                    backup_total += _lstat(target, "owned destination file").st_size
        is_empty_install = previous is None
    else:
        previous, owned = None, set()
        backup_total = 0
        is_empty_install = True

    stage = Path(tempfile.mkdtemp(prefix=f".{dest.name or 'install'}.ns2-stage-", dir=dest.parent))
    try:
        copied_bytes = 0
        for index, (relative, src) in enumerate(all_sources.items(), 1):
            staged = stage.joinpath(*relative.split("/"))
            staged.parent.mkdir(parents=True, exist_ok=True)
            # Recheck immediately before opening each source file; no links are ever copied.
            _check_existing_ancestors(src, "selected install source")
            src_st = _lstat(src, "selected install source")
            if not stat.S_ISREG(src_st.st_mode):
                raise LocalBuildError(f"Selected install source is not a regular file: {src}")
            copied_bytes = _copy_with_progress(src, staged, "copy-bytes", relative, copied_bytes, copy_total,
                                               progress_callback)
            if progress_callback:
                progress_callback("stage", index, len(all_sources), relative)
        stage_marker = stage / MARKER_NAME
        _write_json(stage_marker, _marker(manifest, installed_files))

        if is_empty_install:
            if progress_callback:
                progress_callback("publish", 0, 1, "")
            if dest.exists():
                # The directory was verified empty. Its removal cannot discard user files.
                try:
                    dest.rmdir()
                except OSError as exc:
                    raise LocalBuildError(f"Destination changed during install and is no longer empty: {exc}") from None
            try:
                os.replace(stage, dest)
            except OSError as exc:
                if not dest.exists():
                    dest.mkdir(exist_ok=True)
                raise LocalBuildError(f"Cannot publish the staged install atomically: {exc}") from None
        else:
            backups_dir = stage / ".rollback"
            installed: list[Path] = []
            backups: dict[Path, Path] = {}
            created_dirs: list[Path] = []
            backed_up_bytes = 0
            try:
                for relative in installed_files:
                    target = _target_path(dest, relative, create=True, created_dirs=created_dirs)
                    staged = stage.joinpath(*relative.split("/"))
                    if target.exists():
                        backup = backups_dir.joinpath(*relative.split("/"))
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        backed_up_bytes = _copy_with_progress(target, backup, "backup-bytes", relative,
                                                              backed_up_bytes, backup_total, progress_callback)
                        backups[target] = backup
                    os.replace(staged, target)
                    installed.append(target)
                    if progress_callback:
                        progress_callback("install", len(installed), len(installed_files), relative)
                marker_target = dest / MARKER_NAME
                _lstat(marker_target, "installer marker")
                os.replace(stage_marker, marker_target)
            except Exception:
                _rollback(installed, backups, created_dirs)
                raise
    except LocalBuildError:
        raise
    except OSError as exc:
        raise LocalBuildError(f"Local build install failed: {exc}") from None
    finally:
        if stage and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)

    installed_paths = tuple(dest.joinpath(*relative.split("/")) for relative in installed_files)
    return InstallResult(manifest.game_id, manifest.game_title, manifest.game_version, manifest.port_version,
                         dest.joinpath(*manifest.executable.split("/")), installed_paths, dest / MARKER_NAME)


def _run_shader_child(command: list[str], *, cwd: Path, env: dict[str, str], stderr, timeout: int,
                      cancel_event) -> int | None:
    if cancel_event is not None and cancel_event.is_set():
        return None
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=stderr, creationflags=flags) as process:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not (cancel_event is not None and cancel_event.is_set()):
            try:
                return process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return None


def _cache_first_play_graphics(result: InstallResult, *, env: dict[str, str], probe_needed: bool,
                               on_start: Callable[[], None] | None, cancel_event) -> str:
    title_id = result.game_id.upper()
    route = SHADER_WARMUP_ROUTES.get(title_id)
    if not route or result.game_version != route[0]:
        return ""
    _, seconds = route
    script = _WARMUP_DATA / f"shader-warmup-{title_id}.txt"
    if not script.is_file() or (cancel_event is not None and cancel_event.is_set()):
        return ""

    folder = result.executable.parent
    exefs, romfs = folder / "exefs", folder / "romfs"
    keys = folder / "pipeline-keys.bin"
    if exefs / "main" not in result.files or romfs / "romfs.bin" not in result.files:
        return ""
    warning = "Graphics caching couldn’t finish. You can still play."
    try:
        for path in (exefs / "main", romfs / "romfs.bin", keys,
                     folder / "shader-answers.bin", folder / "shader-programs.bin"):
            _check_existing_ancestors(path, "graphics caching file")
        if probe_needed:
            # Older builds may accept timed runs without respecting the setup safeguards.
            status = _run_shader_child([str(result.executable), "--probe-setup-warmup"], cwd=folder, env=env,
                                       stderr=subprocess.DEVNULL, timeout=5, cancel_event=cancel_event)
            if status != 0:
                return ""
        if on_start:
            on_start()
        with tempfile.TemporaryDirectory(prefix="ns2-graphics-") as temp:
            work = Path(temp)
            # Keep training output with the temporary profile.
            with (work / "graphics.log").open("wb") as log:
                status = _run_shader_child(
                    [str(result.executable), "--exefs", str(exefs), "--romfs", str(romfs),
                     "--profile", str(work / "profile"), "--seconds", str(seconds)],
                    cwd=folder, env=dict(env, NS2_AUDIO_OFF="1", NS2_NO_LAUNCHER="1", NS2_PIPE_SYNC="0",
                                         NS2_INPUT="none", NS2_ASSUME_FOCUS="1",
                                         NS2_BACKGROUND_WINDOW="1", NS2_INPUT_SCRIPT=str(script)),
                    stderr=log, timeout=240, cancel_event=cancel_event,
                )
        if cancel_event is not None and cancel_event.is_set():
            return ""
        if status != 0:
            return warning
        saved = _lstat(keys, "graphics caching output")
        if not stat.S_ISREG(saved.st_mode) or saved.st_size <= 16:
            return warning
        with keys.open("rb") as stream:
            return "" if stream.read(8) == b"TOTKPKEY" else warning
    except (LocalBuildError, OSError, subprocess.SubprocessError):
        return warning


def _prepare_installed_variants(result: InstallResult, *, cache: Path, env: dict[str, str],
                                on_start: Callable[[], None] | None, cancel_event) -> str:
    folder = result.executable.parent
    receipt = cache / _WARM_RECEIPT
    installed = set(result.files)
    seed = (folder / "seed-answers.bin", folder / "seed-programs.bin")
    recorded = (folder / "shader-answers.bin", folder / "shader-programs.bin")
    pair = seed if any(path.exists() for path in seed) else recorded
    if any(path not in installed for path in pair):
        return _SHADER_WARNING

    try:
        for path in (receipt, folder / "shader-prepared.bin", *pair):
            _check_existing_ancestors(path, "shader preparation file")
        for path, magic in zip(pair, (b"TOTKSANS", b"TOTKSPRG")):
            if _lstat(path, "shader preparation input").st_size <= 16:
                return _SHADER_WARNING
            with path.open("rb") as stream:
                if stream.read(8) != magic:
                    return _SHADER_WARNING
        before = receipt.stat() if receipt.is_file() else None
        if on_start:
            on_start()
        status = _run_shader_child([str(result.executable), "--prepare-shaders"], cwd=folder, env=env,
                                   stderr=subprocess.DEVNULL, timeout=1200, cancel_event=cancel_event)
        if status != 0:
            return _SHADER_SKIPPED if cancel_event is not None and cancel_event.is_set() else _SHADER_WARNING
        after = _lstat(receipt, "shader preparation receipt")
        if after == before or not stat.S_ISREG(after.st_mode) or after.st_size != 96:
            return _SHADER_WARNING
        with receipt.open("rb") as stream:
            if stream.read(8) != b"NS2WARM1":
                return _SHADER_WARNING
    except (LocalBuildError, OSError, subprocess.SubprocessError):
        return _SHADER_WARNING
    return ""


def prepare_installed_shaders(result: InstallResult, *, on_start: Callable[[], None] | None = None,
                              on_train: Callable[[], None] | None = None, cancel_event=None) -> str:
    """Warm at the final executable path. A returned warning leaves the committed install usable."""
    if cancel_event is not None and cancel_event.is_set():
        return _SHADER_SKIPPED
    folder = result.executable.parent
    cache, pipeline_cache = folder / "shader-cache", folder / "pipeline-cache.bin"
    suffix = result.executable.suffix if os.name == "nt" else ""
    xlate = next((path for name in ("ns2_xlate", "totk_xlate")
                  if (path := folder / f"{name}{suffix}") in result.files), None)
    if xlate is None or result.executable not in result.files:
        return _SHADER_WARNING
    try:
        for path in (result.executable, xlate, cache, pipeline_cache):
            _check_existing_ancestors(path, "graphics preparation file")
    except LocalBuildError:
        return _SHADER_WARNING

    env = dict(os.environ, NS2_SETUP_WARMUP="1", NS2_GPU="vulkan", NS2_XLATE=str(xlate),
               NS2_SHADER_CACHE=str(cache), NS2_PIPELINE_CACHE=str(pipeline_cache))
    preparation = _prepare_installed_variants(result, cache=cache, env=env, on_start=on_start, cancel_event=cancel_event)
    training = _cache_first_play_graphics(result, env=env, probe_needed=bool(preparation),
                                         on_start=on_train, cancel_event=cancel_event)
    return training or preparation

