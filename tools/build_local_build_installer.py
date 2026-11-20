"""Build the standalone WonderBloom installer for Windows."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from installer.setup_brand import SETUP_NAME, SETUP_TOOLS_ARCHIVE

SPEC = ROOT / 'installer' / 'local_build_gui.spec'
OUTPUT = ROOT / 'build' / 'local-build-installer'


def release_setup(exe: Path) -> None:
    label = (ROOT / 'VERSION').read_text(encoding='utf-8-sig').strip()
    match = re.fullmatch(r'(?:Alpha )?(\d+\.\d+\.\d+[a-z]?)', label)
    if not match:
        raise ValueError(f'Unsupported WonderBloom release version: {label}')
    release = OUTPUT / 'release'
    release.mkdir(parents=True, exist_ok=True)
    name = f'SteelTemple-SMBWONDERBLOOM-{match[1]}-Full-Setup-Wizard'
    with tempfile.TemporaryDirectory(prefix='publish-', dir=release) as folder:
        pending = Path(folder)
        standalone = pending / f'{name}.exe'
        shutil.copy2(exe, standalone)
        archive = pending / f'{name}.zip'
        with zipfile.ZipFile(archive, 'w') as output:
            output.write(standalone, arcname=exe.name)
        with zipfile.ZipFile(archive) as output:
            if output.namelist() != [exe.name] or output.testzip() is not None:
                raise ValueError('The release ZIP must contain only a valid standalone setup EXE.')
        for asset in (standalone, archive):
            with asset.open('rb') as source:
                checksum = hashlib.file_digest(source, 'sha256').hexdigest()
            checksum_file = asset.with_suffix(asset.suffix + '.sha256')
            checksum_file.write_text(f'{checksum}  {asset.name}\n', encoding='ascii')
            destination = asset.replace(release / asset.name)
            checksum_file.replace(release / checksum_file.name)
            print(f'Release asset: {destination}')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--portable', action='store_true', help='embed all tools and produce the standalone release assets')
    parser.add_argument('--tool-cache', type=Path, help='preconfigured build cache containing dist/dl and win tools')
    parser.add_argument('--ucrt', type=Path, default=Path('C:/msys64/ucrt64'), help='MSYS2 UCRT64 developer libraries')
    parser.add_argument('--ninja', type=Path, help='standalone Ninja executable (defaults to PATH)')
    args = parser.parse_args()
    if args.portable and args.tool_cache is None:
        parser.error('--portable needs --tool-cache')
    if importlib.util.find_spec('PyInstaller') is None:
        print('PyInstaller is not installed. Install it in the build environment, then run this script again.',
              file=sys.stderr)
        return 2
    if importlib.util.find_spec('PIL') is None:
        print('Install Pillow in the build environment so the installer can display its artwork.', file=sys.stderr)
        return 2
    dist = OUTPUT / 'dist'
    work = OUTPUT / 'work'
    command = [
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--distpath', str(dist), '--workpath', str(work), str(SPEC),
    ]
    env = dict(os.environ)
    env.pop('WONDERBLOOM_SETUP_PAYLOAD_DIR', None)
    if args.portable:
        from stage_local_build_installer import stage_setup_tools

        OUTPUT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='payload-', dir=OUTPUT) as folder:
            payload = Path(folder)
            stage = stage_setup_tools(payload, args.tool_cache, args.ucrt, args.ninja)
            with zipfile.ZipFile(payload / SETUP_TOOLS_ARCHIVE, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
                for path in sorted(stage.rglob('*')):
                    relative = path.relative_to(stage)
                    if path.is_file() and '__pycache__' not in relative.parts and path.suffix != '.pyc':
                        archive.write(path, relative.as_posix())
            subprocess.run(command, cwd=ROOT, check=True, env=dict(env, WONDERBLOOM_SETUP_PAYLOAD_DIR=str(payload)))
        release_setup(dist / f'{SETUP_NAME}.exe')
    else:
        subprocess.run(command, cwd=ROOT, check=True, env=env)
        print(f'Built prepared-folder installer: {dist / (SETUP_NAME + ".exe")}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
