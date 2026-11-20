"""Stage the private tool payload embedded in the standalone installer."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from build_mtf_release import clean_env, copy_tree, stage_llvm, stage_python
from make_release import PINS, fetch


ROOT = Path(__file__).resolve().parents[1]
TOOLS = (
    'build_game.py', 'build_shaders.py', 'check_content.py', 'dkb_pack_romfs.py',
    'extract_nup.py', 'game_icon.py', 'hostmem.py', 'pack_shader_cache.py',
    'prepare_shaders.py', 'romfs_index.py', 'shader_census.py', 'shader_list.py',
    'universal_ns2_to_pc.py',
)
RUNTIME_SUFFIXES = {'.c', '.cpp', '.h', '.hpp', '.inc', '.comp', '.spvasm', '.manifest', '.txt', '.md'}
DEPENDENCY_HEADERS = ('SDL3', 'vulkan', 'vk_video', 'vma', 'opus', 'vpx', 'zstd.h', 'zstd_errors.h')
DEPENDENCY_LIBS = ('libSDL3.dll.a', 'libvulkan-1.dll.a', 'libopus.dll.a', 'libvpx.a', 'libzstd.a')
MSYS_LICENSES = {
    'dav1d': ('COPYING', 'PATENTS'),
    'ninja': ('COPYING',),
    'opus': ('COPYING',),
    'zstd': ('LICENSE',),
    'vulkan-headers': ('LICENSE',),
    'vulkan-loader': ('LICENSE',),
}
PRIVATE_SUFFIXES = {'.ini', '.nup', '.nsp', '.nca', '.xci', '.keys', '.nso', '.romfs', '.save', '.log', '.png', '.jpg', '.webp', '.ico'}


def _copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f'Missing portable setup input: {source}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _stage_sources(stage: Path) -> None:
    subprocess.run([sys.executable, str(ROOT / 'tools' / 'check_content.py')], cwd=ROOT, check=True)
    paths = subprocess.check_output([
        'git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', 'runtime', 'recomp',
    ], cwd=ROOT).decode('utf-8')
    for name in sorted(set(paths.split('\0')) - {''}):
        relative = Path(name)
        if relative.parts[0] == 'runtime':
            # The local compiler can create a resource from the user's art. The
            # portable release ships no artwork or resources from other games.
            if relative.suffix not in RUNTIME_SUFFIXES and name != 'runtime/ui/fonts/Roboto-Medium.ttf':
                continue
        elif relative.suffix not in {'.py', '.txt'}:
            continue
        source = ROOT / relative
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError(f'Source must be a regular repository file: {relative}')
        _copy_file(source, stage / relative)
    for name in TOOLS:
        _copy_file(ROOT / 'tools' / name, stage / 'tools' / name)
    for source in sorted((ROOT / 'tools' / 'data').glob('expected-*.json')):
        _copy_file(source, stage / 'tools' / 'data' / source.name)
    for name in ('__init__.py', 'local_build.py'):
        _copy_file(ROOT / 'installer' / name, stage / 'installer' / name)
    for name in ('VERSION', 'LICENSE', 'LICENSE-MIT', 'THIRD_PARTY_NOTICES.md'):
        _copy_file(ROOT / name, stage / name)


def _stage_dependencies(stage: Path, cache: Path, ucrt: Path) -> None:
    source = cache / 'win' / 'deps'
    destination = stage / 'runtime' / 'deps'
    for name in DEPENDENCY_HEADERS:
        header = source / 'include' / name
        if header.is_dir():
            copy_tree(header, destination / 'include' / name, lambda rel: Path(rel).suffix not in {'.h', '.hpp', '.inl'})
        else:
            _copy_file(header, destination / 'include' / name)
    for name in DEPENDENCY_LIBS:
        _copy_file(source / 'lib' / name, destination / 'lib' / name)
    copy_tree(ucrt / 'include' / 'dav1d', destination / 'include' / 'dav1d', lambda rel: not rel.endswith('.h'))
    _copy_file(ucrt / 'lib' / 'libdav1d.a', destination / 'lib' / 'libdav1d.a')
    for name in ('SDL3.dll', 'libopus-0.dll'):
        _copy_file(source / 'bin' / name, destination / 'bin' / name)


def _stage_binaries(stage: Path, ninja: Path) -> None:
    bin_dir = stage / 'bin'
    _copy_file(ninja, bin_dir / 'ninja.exe')
    subprocess.run([str(bin_dir / 'ninja.exe'), '--version'], env=clean_env(bin_dir), check=True)
    xlate_dir = ROOT / 'build' / 'xlate'
    for name in ('totk_xlate.exe', 'totk_xlate.id'):
        _copy_file(xlate_dir / name, bin_dir / name)


def _stage_licenses(stage: Path, cache: Path, ucrt: Path) -> None:
    licenses = stage / 'licenses'
    for library, names in MSYS_LICENSES.items():
        for name in names:
            _copy_file(ucrt / 'share' / 'licenses' / library / name, licenses / f'{library}-{name}.txt')
    _copy_file(ucrt / 'share' / 'licenses' / 'vulkan-memory-allocator' / 'LICENSE.txt', licenses / 'VMA-LICENSE.txt')
    _copy_file(ucrt / 'share' / 'licenses' / 'SDL3' / 'LICENSE.txt', licenses / 'SDL3-LICENSE.txt')
    _copy_file(stage / 'llvm' / 'LICENSE.TXT', licenses / 'llvm-mingw-LICENSE.txt')
    vpx_name = 'libvpx-1.17.0.tar.gz'
    archive = cache / 'win' / 'dl' / vpx_name
    if not archive.is_file():
        archive = fetch('libvpx-src')
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != PINS['libvpx-src'][1]:
            raise ValueError(f'Checksum mismatch for {archive}')
    with tarfile.open(archive) as source:
        for name in ('LICENSE', 'PATENTS'):
            stream = source.extractfile(f'libvpx-1.17.0/{name}')
            if stream is None:
                raise ValueError(f'Missing libvpx {name} in archive')
            with stream:
                (licenses / f'libvpx-{name}.txt').write_bytes(stream.read())


def stage_setup_tools(output: Path, cache: Path, ucrt: Path, ninja: Path | None) -> Path:
    """Stage only the tools and inputs used to build from the player's own game files."""
    if sys.platform != 'win32':
        raise SystemExit('The portable installer is a Windows package.')
    located_ninja = shutil.which('ninja.exe') if ninja is None else None
    if ninja is None and located_ninja is None:
        raise SystemExit('Provide a standalone Ninja executable with --ninja.')
    ninja = (ninja if ninja is not None else Path(located_ninja)).resolve()
    cache, ucrt = cache.resolve(), ucrt.resolve()
    output.mkdir(parents=True, exist_ok=True)
    output = output.resolve()
    stage = Path(tempfile.mkdtemp(prefix='Setup-', dir=output))
    try:
        _stage_sources(stage)
        python = stage_python(stage, cache=cache)
        for module in ('_pyrepl', 'tomllib'):
            (python / 'Lib' / module / 'mypy.ini').unlink(missing_ok=True)
        modules = python / 'Lib'
        numpy_tests = (modules / 'site-packages' / 'numpy').rglob('tests')
        for directory in sorted([modules / 'idlelib', *numpy_tests], key=lambda path: len(path.parts), reverse=True):
            directory = directory.resolve()
            if directory.is_dir() and directory.is_relative_to(stage):
                shutil.rmtree(directory)
        stage_llvm(stage, cache=cache)
        _stage_dependencies(stage, cache, ucrt)
        _stage_binaries(stage, ninja)
        _stage_licenses(stage, cache, ucrt)
        for path in stage.rglob('*'):
            if path.is_file() and path.suffix.lower() in PRIVATE_SUFFIXES:
                raise ValueError(f'Unexpected file in portable setup: {path.relative_to(stage)}')
    except BaseException:
        if stage.resolve().parent == output:
            shutil.rmtree(stage)
        raise
    return stage
