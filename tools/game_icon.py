"""A per-game icon for the built exe, from the user's own folder of cover art.

The folder (config.local.toml [assets] icons, or NS2_ICON_DIR, or --icons) holds one picture per game, named by the
game's title ("Super Mario Bros. Wonder - Nintendo Switch 2 Edition + Meetup in Bellabel Park.png"). The user adds to it
over time; nothing from it goes into the repository. tools/build_game.py --icon embeds the match: this module finds it
(find_icon), turns it into a multi-size .ico and writes the .rc that windres compiles into the exe (make_icon_rc).

    python tools\\game_icon.py --name "<title name>" [--icons DIR]     (which picture would be used)
"""
import argparse
import os
import re
import sys
import tomllib
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.ico')
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def icon_dirs(explicit=None):
    """--icons, then NS2_ICON_DIR, then config.local.toml [assets] icons (a string or a list)."""
    dirs = []
    if explicit:
        dirs.append(Path(explicit))
    if os.environ.get('NS2_ICON_DIR'):
        dirs.append(Path(os.environ['NS2_ICON_DIR']))
    cfg = ROOT / 'config.local.toml'
    if cfg.is_file():
        icons = tomllib.loads(cfg.read_text(encoding='utf-8')).get('assets', {}).get('icons')
        dirs += [Path(d) for d in ([icons] if isinstance(icons, str) else icons or [])]
    return [d for d in dirs if d.is_dir()]


def norm(s):
    """Letters and digits only, lower case, accents dropped: "Fire Emblem꞉ Fortune’s Weave" -> "fireemblemfortunesweave"."""
    s = unicodedata.normalize('NFKD', s)
    return re.sub(r'[^a-z0-9]', '', ''.join(ch for ch in s if not unicodedata.combining(ch)).lower())


def words(s):
    s = unicodedata.normalize('NFKD', s).lower()
    return {w for w in re.split(r'[^a-z0-9]+', s) if w and w not in {'the', 'of', 'and', 'a', 'nintendo', 'switch', '2', 'edition'}}


def find_icon(name, title_id='', dirs=()):
    """The picture for a game: a file named by its title ID, else by its name (exact after norm(), then the longest name
    that one contains, then the best word overlap of at least two thirds). None when nothing fits."""
    files = [p for d in dirs for p in d.iterdir() if p.suffix.lower() in EXTS]
    if title_id:
        for p in files:
            if norm(p.stem) in (norm(title_id), norm(title_id)[:-3] + '000'):
                return p
    want = norm(name)
    if not want:
        return None
    for p in files:
        if norm(p.stem) == want:
            return p
    contained = [p for p in files if norm(p.stem) and (norm(p.stem) in want or want in norm(p.stem))]
    if contained:
        return max(contained, key=lambda p: len(norm(p.stem)))
    ww = words(name)
    best, score = None, 0.0
    for p in files:
        pw = words(p.stem)
        if ww and pw:
            s = len(ww & pw) / max(len(ww), len(pw))
            if s > score:
                best, score = p, s
    return best if score >= 2 / 3 else None


def make_icon_rc(picture, out_dir, stem):
    """<out_dir>/<stem>.ico from the picture (square-padded, 16..256 px) and <out_dir>/<stem>.rc that embeds it with the
    runtime's manifest. Returns the .rc path."""
    from PIL import Image
    im = Image.open(picture).convert('RGBA')
    side = max(im.size)
    square = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    square.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    ico = Path(out_dir) / f'{stem}.ico'
    square.resize((256, 256), Image.LANCZOS).save(ico, sizes=ICO_SIZES)
    # the start screen's logo and picture (runtime/ui/launcher/launcher.cpp #embed "launcher_icon.png", the build folder
    # is on its include path): the same picture, so it never reaches the repository either
    square.resize((512, 512), Image.LANCZOS).save(Path(out_dir) / 'launcher_icon.png')
    rc = Path(out_dir) / f'{stem}.rc'
    rc.write_text('/* Written by tools/game_icon.py from the user\'s cover art; not in the repository. */\n'
                  '1 24 "totk.manifest"\n'
                  f'1 ICON "{ico.as_posix()}"\n', encoding='utf-8')
    return rc


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--name', required=True)
    ap.add_argument('--title-id', default='')
    ap.add_argument('--icons')
    args = ap.parse_args()
    dirs = icon_dirs(args.icons)
    if not dirs:
        sys.exit('no icon folder: pass --icons, set NS2_ICON_DIR, or [assets] icons in config.local.toml')
    p = find_icon(args.name, args.title_id, dirs)
    print(p if p else f'no picture fits "{args.name}" in {", ".join(map(str, dirs))}')
    return 0 if p else 1


if __name__ == '__main__':
    sys.exit(main())
