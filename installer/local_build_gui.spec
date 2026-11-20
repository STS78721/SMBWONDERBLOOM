# PyInstaller recipe for the local build installer and its original setup artwork.
from pathlib import Path
import os
import re
import sys

from PyInstaller.utils.win32 import versioninfo

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT))
from installer.local_build import SHADER_WARMUP_ROUTES
from installer.setup_brand import SETUP_NAME, SETUP_TOOLS_ARCHIVE

ASSETS = ROOT / 'installer' / 'assets'
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8-sig').strip()
MATCH = re.search(r'(\d+)\.(\d+)\.(\d+)', VERSION)
payload_dir = os.environ.get('WONDERBLOOM_SETUP_PAYLOAD_DIR')
payload = [(str(Path(payload_dir) / SETUP_TOOLS_ARCHIVE), '.')] if payload_dir else []
FILE_VERSION = (*map(int, MATCH.groups()), 0) if MATCH else (0, 0, 0, 0)
VERSION_INFO = versioninfo.VSVersionInfo(
    ffi=versioninfo.FixedFileInfo(filevers=FILE_VERSION, prodvers=FILE_VERSION, fileType=1),
    kids=[
        versioninfo.StringFileInfo([versioninfo.StringTable('040904B0', [
            versioninfo.StringStruct('FileDescription', SETUP_NAME),
            versioninfo.StringStruct('ProductName', SETUP_NAME),
            versioninfo.StringStruct('FileVersion', VERSION),
            versioninfo.StringStruct('ProductVersion', VERSION),
        ])]),
        versioninfo.VarFileInfo([versioninfo.VarStruct('Translation', [1033, 1200])]),
    ],
)

a = Analysis(
    [str(ROOT / 'installer' / 'local_build_gui.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ASSETS / name), 'installer/assets') for name in ('setup-hero.png', 'setup-bloom.png', 'setup.ico')]
          + [(str(ROOT / 'tools' / 'data' / f'shader-warmup-{title_id}.txt'), 'tools/data')
             for title_id in SHADER_WARMUP_ROUTES] + payload,
    hiddenimports=['installer.local_build', 'installer.nup_workflow', 'installer.nup_build_gui'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=SETUP_NAME,
    icon=str(ASSETS / 'setup.ico'),
    manifest=str(ROOT / 'installer' / 'setup.manifest'),
    version=VERSION_INFO,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
