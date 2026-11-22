"""Local installer for a prebuilt output folder.

Run with ``python -m installer.local_build_gui``. This UI reads the selected local build manifest and preview icon, and
passes an explicitly selected own game-data folder to the installer backend when needed. It does not bundle game data,
settings, saves, or cover art.

    --selftest [--shots DIR]   draw every page and close (Pillow is needed only when saving PNGs)
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from installer.setup_art import HeroArt, load_preview
from installer.setup_brand import SETUP_NAME
from installer.setup_window import configure_window, desktop_animations_enabled, enable_dpi_awareness, window_hwnd

try:
    from PIL import ImageGrab
except ImportError:
    ImageGrab = None


# Dark WonderBloom palette: the same sunshine yellow, sky blue, coral and violet as the runtime theme, over a dark
# installer shell. No game artwork is part of this module or its build recipe.
BG = '#0b1020'
BG_HI = '#10172a'
PANEL = '#131b2e'
PANEL_HI = '#1b263d'
PANEL_EDGE = '#303d56'
PAPER = '#fff9e7'
TEXT = '#f8f7ff'
TEXT_SOFT = '#c7d0e5'
TEXT_DIM = '#9baac6'
YELLOW = '#ffce52'
YELLOW_HOT = '#ffe184'
INK = '#211a15'
SKY = '#4bb8e6'
CORAL = '#ff796b'
VIOLET = '#ac83ef'
LEAF = '#68d17b'
ERROR = '#ff877d'
UI_FONT = 'Segoe UI' if os.name == 'nt' else 'DejaVu Sans'
DISPLAY_FONT = 'Segoe UI Variable Display' if os.name == 'nt' else UI_FONT


def _rounded(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, radius: float, *, fill: str,
             outline: str = '', width: float = 1, tags: str = 'visual') -> int:
    """A canvas-only rounded rectangle, with a smooth polygon so no image asset is needed."""
    r = max(0.0, min(radius, (x2 - x1) * 0.5, (y2 - y1) * 0.5))
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
              x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, splinesteps=10, fill=fill, outline=outline, width=width, tags=tags)


class LocalBuildWizard:
    PAGES = ('welcome', 'source', 'destination', 'progress', 'complete')
    STEP_LABELS = ('Game folder', 'Install location', 'Installing', 'Done')

    def __init__(self, root: tk.Tk, *, animate: bool = True, selftest: bool = False):
        self.root = root
        self.animate = animate
        self.animate_art = animate and desktop_animations_enabled()
        self.selftest = selftest
        self.page = 'welcome'
        self.source_var = tk.StringVar()
        self.game_data_var = tk.StringVar()
        self.destination_var = tk.StringVar()
        self.source_info: dict[str, str] | None = None
        self.game_data_paths: tuple[str, ...] = ()
        self.portable_game_data_paths: tuple[str, ...] = ()
        self.game_data_required = False
        self.source_icon = None
        self.source_error = ''
        self.game_data_error = ''
        self.destination_error = ''
        self.destination_touched = False
        self.setting_destination = False
        self.last_source_value = ''
        self.source_validation_job: str | None = None
        self.progress_done = 0
        self.progress_total = 0
        self.progress_phase = 'Getting ready…'
        self.progress_note = ''
        self.graphics_warmup = False
        self.skip_graphics = threading.Event()
        self.error_message = ''
        self.worker: threading.Thread | None = None
        self.events: queue.Queue = queue.Queue()
        self.motion = 0.0
        self.progress_indicator = None
        self.resize_job = None
        self.ui_scale = 0.0
        self.visible_controls: set[str] = set()
        self.widget_items: dict[str, int] = {}
        self.widgets: dict[str, tk.Widget] = {}
        self.nup_window = None
        self.setup_source_kind = ''
        self.closed = False
        self.last_size = (0, 0)

        root.configure(bg=BG)
        root.protocol('WM_DELETE_WINDOW', self.on_close)

        self.canvas = tk.Canvas(root, background=BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill='both', expand=True)
        self.art = HeroArt(self.canvas)
        self._make_widgets()
        configure_window(root, title=SETUP_NAME, design_size=(1280, 800), minimum_size=(760, 560))
        self.source_var.trace_add('write', self._source_changed)
        self.game_data_var.trace_add('write', self._game_data_changed)
        self.destination_var.trace_add('write', self._destination_changed)
        self.canvas.bind('<Configure>', self._on_resize)
        root.bind('<Return>', self._on_return)
        root.bind('<Escape>', self._on_escape)
        root.bind('<Alt-Left>', self._on_back)
        root.update_idletasks()
        self._draw()
        if self.animate:
            self.root.after(45, self._animate)

    # ---- custom controls -----------------------------------------------------------------------------------------

    def _make_widgets(self):
        entry_font = (UI_FONT, -16)
        button_font = (UI_FONT, -16, 'bold')
        self.widgets['source_entry'] = tk.Entry(self.canvas, textvariable=self.source_var, font=entry_font,
                                                bg='#18263b', fg=TEXT, insertbackground=YELLOW,
                                                selectbackground='#377eaa', selectforeground=TEXT,
                                                relief='flat', bd=0, highlightthickness=1,
                                                highlightbackground='#334a67', highlightcolor=YELLOW)
        self.widgets['destination_entry'] = tk.Entry(self.canvas, textvariable=self.destination_var, font=entry_font,
                                                     bg='#18263b', fg=TEXT, insertbackground=YELLOW,
                                                     selectbackground='#377eaa', selectforeground=TEXT,
                                                     relief='flat', bd=0, highlightthickness=1,
                                                     highlightbackground='#334a67', highlightcolor=YELLOW)
        self.widgets['game_data_entry'] = tk.Entry(self.canvas, textvariable=self.game_data_var, font=entry_font,
                                                   bg='#18263b', fg=TEXT, insertbackground=YELLOW,
                                                   selectbackground='#377eaa', selectforeground=TEXT,
                                                   relief='flat', bd=0, highlightthickness=1,
                                                   highlightbackground='#334a67', highlightcolor=YELLOW)
        self._button('source_browse', 'Browse folder', self._browse_source, False, button_font)
        self._button('game_data_browse', 'Browse folder', self._browse_game_data, False, button_font)
        self._button('destination_browse', 'Browse folder', self._browse_destination, False, button_font)
        self._button('back', 'Back', self._back, False, button_font)
        self._button('nup_entry', 'Install from a game file (.nup)', self._open_game_setup, True, button_font)
        self._button('raw_entry', 'Install from game folders', lambda: self._open_game_setup('folder'), False, button_font)
        self._button('prepared_entry', 'Use a prepared folder', self._advance, False, button_font)
        self._button('motion', 'Play animation', self._toggle_art_motion, False, button_font)
        self._button('primary', 'Next', self._advance, True, button_font)
        self._button('skip_graphics', 'Skip graphics prep', self._skip_graphics, False, button_font)
        self._button('aux', 'Open game folder', self._open_destination, False, button_font)
        self._button('error_details', 'Show details', self._show_error_details, False, button_font)
        for key in ('nup_entry', 'raw_entry', 'prepared_entry'):
            self.widgets[key].configure(anchor='w')
        self.widgets['prepared_entry'].configure(bg=BG, fg=TEXT_SOFT, activebackground=BG_HI)
        self.widgets['motion'].configure(bg=BG_HI, fg=TEXT_SOFT, activebackground=PANEL_HI)
        for name, widget in self.widgets.items():
            self.widget_items[name] = self.canvas.create_window(0, 0, window=widget, state='hidden', tags='widget')

    def _button(self, key: str, label: str, command, primary: bool, font):
        self.widgets[key] = tk.Button(
            self.canvas, text=label, command=command, font=font, relief='flat', bd=0, cursor='hand2',
            padx=16, pady=8, takefocus=True,
            bg=YELLOW if primary else PANEL_HI, fg=INK if primary else TEXT,
            activebackground=YELLOW_HOT if primary else PANEL_EDGE,
            activeforeground=INK if primary else PAPER,
            disabledforeground='#69788a', highlightthickness=2, highlightbackground=BG,
            highlightcolor=SKY,
        )

    def _place(self, name: str, x: float, y: float, width: float, height: float):
        item = self.widget_items[name]
        self.visible_controls.add(name)
        self.canvas.coords(item, x + width * 0.5, y + height * 0.5)
        self.canvas.itemconfigure(item, state='normal', width=max(1, width), height=max(1, height))

    # ---- local input and manifest --------------------------------------------------------------------------------

    def _source_changed(self, *_):
        if self.selftest:
            return
        current_source = self.source_var.get().strip()
        if current_source != self.last_source_value:
            self.last_source_value = current_source
            # Never silently carry an explicitly selected dump folder over to another build.
            if self.game_data_var.get().strip():
                self.game_data_var.set('')
        if self.source_validation_job:
            try:
                self.root.after_cancel(self.source_validation_job)
            except tk.TclError:
                pass
        self.source_validation_job = self.root.after(250, self._inspect_source)

    def _game_data_changed(self, *_):
        if self.selftest:
            return
        self._validate_game_data()
        self._set_default_destination()
        if self.page == 'source':
            self._draw()

    def _destination_changed(self, *_):
        if not self.setting_destination:
            self.destination_touched = True
        if self.page == 'destination':
            self._validate_destination()
            self._draw()

    def _browse_source(self):
        path = filedialog.askdirectory(title='Choose a prepared game folder', mustexist=True)
        if path:
            self.source_var.set(os.path.normpath(path))
            self._inspect_source()

    def _browse_game_data(self):
        path = filedialog.askdirectory(title='Choose the folder with your game files', mustexist=True)
        if path:
            self.game_data_var.set(os.path.normpath(path))
            self._validate_game_data()
            self._draw()

    def _browse_destination(self):
        path = filedialog.askdirectory(title='Choose the install location', mustexist=False)
        if path:
            self.destination_var.set(os.path.normpath(path))
            self._validate_destination()
            self._draw()

    def _inspect_source(self):
        self.source_validation_job = None
        self.source_info = None
        self.game_data_paths = ()
        self.portable_game_data_paths = ()
        self.game_data_required = False
        self.source_icon = None
        self.source_error = ''
        raw = self.source_var.get().strip()
        if not raw:
            self.source_error = 'Choose a game folder that was already prepared for PC.'
        else:
            source = Path(raw).expanduser()
            try:
                if not source.is_dir():
                    self.source_error = 'That folder could not be found.'
                else:
                    manifest = source / 'ns2-build-manifest.json'
                    if not manifest.is_file():
                        self.source_error = 'This folder is not ready to install. Choose a prepared game folder.'
                    else:
                        data = json.loads(manifest.read_text(encoding='utf-8'))
                        if not isinstance(data, dict) or data.get('schema') != 1:
                            self.source_error = 'This folder was prepared with an unsupported version of setup.'
                        else:
                            fields = ('game_title', 'game_version', 'port_version', 'game_id')
                            if any(not isinstance(data.get(k), str) or not data[k].strip() for k in fields):
                                self.source_error = 'Setup could not identify the game in this folder.'
                            elif not isinstance(data.get('game_data'), dict):
                                self.source_error = 'This folder is missing information setup needs. Choose another prepared folder.'
                            else:
                                self.source_info = {k: data[k].strip() for k in fields}
                                self.game_data_paths = self._game_data_manifest_paths(data.get('game_data'))
                                self.portable_game_data_paths = self._portable_game_data_manifest_paths(
                                    data.get('game_data'))
                                icon_path = source / 'launcher_icon.png'
                                if icon_path.is_file():
                                    try:
                                        self.source_icon = load_preview(icon_path)
                                    except (tk.TclError, OSError):
                                        self.source_icon = None
            except (OSError, UnicodeError, json.JSONDecodeError):
                self.source_error = 'Setup could not read this folder. Check that you can open it, or choose another.'
        self._validate_game_data()
        self._set_default_destination()
        self._validate_destination()
        if self.page in ('source', 'destination'):
            self._draw()

    @staticmethod
    def _safe_folder_name(title: str) -> str:
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title).strip().rstrip('.')
        return name or 'Local build'

    @staticmethod
    def _game_data_manifest_paths(game_data: object) -> tuple[str, ...]:
        """Extract only schema-declared data paths; never infer them from parent folders."""
        if not isinstance(game_data, dict):
            return ()
        paths: list[str] = []
        exefs_dir = game_data.get('exefs_dir')
        exefs_hashes = game_data.get('exefs_sha256')
        if isinstance(exefs_dir, str) and isinstance(exefs_hashes, dict):
            for leaf in exefs_hashes:
                if isinstance(leaf, str) and leaf and '/' not in leaf and '\\' not in leaf:
                    paths.append(f'{exefs_dir}/{leaf}')
        romfs_path = game_data.get('romfs_path')
        if isinstance(romfs_path, str) and romfs_path:
            paths.append(romfs_path)
        # Ignore malformed/unsafe values here. The backend owns manifest validation; the UI won't
        # use these paths to copy anything and must not treat an unsafe path as portable data.
        return tuple(path for path in paths if LocalBuildWizard._safe_manifest_relative(path))

    @staticmethod
    def _portable_game_data_manifest_paths(game_data: object) -> tuple[str, ...]:
        """Check the build's portable siblings, as the backend does when no data folder is selected."""
        if not isinstance(game_data, dict):
            return ()
        paths: list[str] = []
        exefs_dir = game_data.get('exefs_dir')
        exefs_hashes = game_data.get('exefs_sha256')
        if isinstance(exefs_dir, str) and isinstance(exefs_hashes, dict):
            for leaf in exefs_hashes:
                if isinstance(leaf, str) and leaf and '/' not in leaf and '\\' not in leaf:
                    paths.append(f'{exefs_dir}/{leaf}')
        if game_data.get('romfs_path') is not None or game_data.get('romfs_size') is not None:
            paths.append('romfs/romfs.bin')
        return tuple(path for path in paths if LocalBuildWizard._safe_manifest_relative(path))

    @staticmethod
    def _safe_manifest_relative(value: str) -> bool:
        path = Path(value)
        return (value and '\\' not in value and ':' not in value and not path.is_absolute()
                and all(part not in ('', '.', '..') for part in value.split('/')))

    def _game_data_available(self, root: Path, paths: tuple[str, ...] | None = None) -> bool:
        paths = self.game_data_paths if paths is None else paths
        if not paths:
            return True
        try:
            return all(root.joinpath(*path.split('/')).is_file() for path in paths)
        except OSError:
            return False

    def _validate_game_data(self) -> bool:
        self.game_data_error = ''
        source_raw = self.source_var.get().strip()
        source_has_data = False
        if source_raw and self.game_data_paths:
            source_has_data = self._game_data_available(Path(source_raw).expanduser(),
                                                        self.portable_game_data_paths)
        self.game_data_required = bool(self.game_data_paths) and not source_has_data

        selected = self.game_data_var.get().strip()
        if selected:
            data_root = Path(selected).expanduser()
            if not data_root.is_dir():
                self.game_data_error = 'That game files folder could not be found.'
            elif not self._game_data_available(data_root):
                self.game_data_error = 'This folder is missing files for this game. Choose the folder from your copy.'
        elif self.game_data_required:
            self.game_data_error = 'Choose the folder with the files from your copy of this game.'
        return not self.game_data_error

    def _set_default_destination(self):
        if self.destination_touched or not self.source_info:
            return
        source = Path(self.source_var.get().strip()).expanduser()
        data_root_raw = self.game_data_var.get().strip()
        data_root = Path(data_root_raw).expanduser() if data_root_raw else None
        base = data_root.parent if data_root and data_root.is_dir() else source.parent
        folder = self._safe_folder_name(self.source_info['game_title'])
        self.setting_destination = True
        try:
            self.destination_var.set(str(base / f'{folder} PC'))
        finally:
            self.setting_destination = False

    def _validate_destination(self) -> bool:
        self.destination_error = ''
        raw = self.destination_var.get().strip()
        if not raw:
            self.destination_error = 'Choose an install location.'
            return False
        try:
            destination = Path(raw).expanduser().resolve(strict=False)
            protected_roots: list[Path] = []
            if self.source_var.get().strip() and self.source_info:
                protected_roots.append(Path(self.source_var.get().strip()).expanduser().resolve(strict=False))
            if self.game_data_var.get().strip():
                protected_roots.append(Path(self.game_data_var.get().strip()).expanduser().resolve(strict=False))
            for protected in protected_roots:
                if destination == protected or self._is_inside(destination, protected) or self._is_inside(protected, destination):
                    self.destination_error = 'Choose a different folder for installation to keep your original files in place.'
                    return False
        except (OSError, RuntimeError, ValueError):
            self.destination_error = 'That install location is not valid.'
            return False
        return True

    @staticmethod
    def _is_inside(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    # ---- page flow and installation ------------------------------------------------------------------------------

    def _advance(self):
        if self.page == 'welcome':
            self.page = 'source'
        elif self.page == 'source':
            self._inspect_source()
            if not self.source_info or not self._validate_game_data():
                self.root.bell()
                self._draw()
                return
            self.page = 'destination'
        elif self.page == 'destination':
            if not self.source_info or not self._validate_destination():
                self.root.bell()
                self._draw()
                return
            self._start_install()
            return
        elif self.page == 'complete':
            self.root.destroy()
        elif self.page == 'error':
            self._start_install()
            return
        self._draw()

    def _back(self):
        if self.page == 'source':
            self.page = 'welcome'
        elif self.page == 'destination':
            self.page = 'source'
        elif self.page == 'error':
            self.page = 'destination'
        elif self.page in ('progress', 'complete'):
            return
        self._draw()

    def _on_escape(self, _event=None):
        self._back()
        return 'break'

    def _on_return(self, _event=None):
        if self.page in ('welcome', 'source', 'destination', 'complete', 'error'):
            focused = self.root.focus_get()
            if isinstance(focused, tk.Button):
                focused.invoke()
                return 'break'
            if self.page == 'welcome':
                self._open_game_setup()
                return 'break'
            if focused is self.widgets['source_entry'] and self.page == 'source':
                self._inspect_source()
            elif focused is self.widgets['destination_entry'] and self.page == 'destination':
                self._validate_destination()
            self._advance()
            return 'break'
        return None

    def _on_back(self, _event=None):
        self._back()
        return 'break'

    def _start_install(self):
        source = Path(self.source_var.get().strip()).expanduser()
        destination = Path(self.destination_var.get().strip()).expanduser()
        self.page = 'progress'
        self.progress_done = 0
        self.progress_total = 0
        self.progress_phase = 'Getting ready…'
        self.progress_note = ''
        self.graphics_warmup = False
        self.skip_graphics.clear()
        self.error_message = ''
        selected_data = self.game_data_var.get().strip()
        game_data_dir = Path(selected_data).expanduser() if selected_data else None
        self.worker = threading.Thread(target=self._install_worker,
                                       args=(source, destination, game_data_dir), daemon=True)
        self.worker.start()
        self._draw()
        self.root.after(80, self._poll_worker)

    def _install_worker(self, source: Path, destination: Path, game_data_dir: Path | None):
        try:
            # Imported here so screenshot/selftest mode can run independently of the backend build.
            from installer.local_build import install_local_build, prepare_installed_shaders

            def on_progress(phase: str, completed: int, total: int, _relative_path: str):
                detail = 'Saving a copy of your previous install…' if phase.startswith('backup') else 'Installing your game…'
                byte_phase = phase in ('copy-bytes', 'backup-bytes')
                self.events.put(('progress', completed, total, detail, byte_phase))

            installed = install_local_build(source, destination, progress_callback=on_progress, game_data_dir=game_data_dir)
            warning = prepare_installed_shaders(
                installed, cancel_event=self.skip_graphics,
                on_start=lambda: self.events.put(('graphics', 'Preparing graphics…')),
                on_train=lambda: self.events.put(('graphics', 'Caching graphics for first play…')),
            )
        except Exception as exc:  # shown in the error page; backend remains the authority for safety checks
            self.events.put(('error', f'{type(exc).__name__}: {exc}'))
        else:
            self.events.put(('complete', warning))

    def _poll_worker(self):
        if self.closed:
            return
        changed = False
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == 'progress':
                    if event[4]:
                        self.progress_done = max(0, int(event[1]))
                        self.progress_total = max(0, int(event[2]))
                    self.progress_phase = event[3][:180]
                    changed = True
                elif event[0] == 'graphics':
                    self.graphics_warmup = True
                    self.progress_done = self.progress_total = 0
                    self.progress_phase = event[1]
                    changed = True
                elif event[0] == 'error':
                    self.error_message = event[1][:1200]
                    self.page = 'error'
                    self.worker = None
                    changed = True
                elif event[0] == 'complete':
                    self.progress_note = event[1]
                    self.progress_done = max(1, self.progress_done)
                    self.progress_total = max(1, self.progress_total, self.progress_done)
                    self.page = 'complete'
                    self.worker = None
                    changed = True
        except queue.Empty:
            pass
        if changed:
            self._draw()
        if self.worker:
            self.root.after(80, self._poll_worker)

    def _skip_graphics(self):
        self.skip_graphics.set()
        self.progress_phase = 'Finishing setup…'
        self._draw()

    def _open_destination(self):
        raw = self.destination_var.get().strip()
        if not raw:
            return
        path = Path(raw).expanduser()
        try:
            if os.name == 'nt':
                os.startfile(str(path))
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(['xdg-open', str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self.progress_note = 'Could not open the folder. You can open it in your file browser.'
            self._draw()

    def _show_error_details(self):
        messagebox.showinfo('Install details', self.error_message, parent=self.root)

    def _open_game_setup(self, source_kind='nup'):
        if self.nup_window is not None:
            try:
                if not self.nup_window.closed and self.nup_window.root.winfo_exists():
                    if (self.setup_source_kind == source_kind
                            or (self.nup_window.worker and self.nup_window.worker.is_alive())):
                        self.nup_window.root.lift()
                        self.nup_window.root.focus_force()
                        return
                    self.nup_window.on_close()
            except tk.TclError:
                pass
        from installer.nup_build_gui import NupWorkflowWizard
        self.nup_window = NupWorkflowWizard(self.root, source_kind=source_kind, motion_preference=self.animate_art)
        self.setup_source_kind = source_kind

    def on_close(self):
        if self.worker:
            messagebox.showinfo('Install in progress', 'Please wait for installation to finish before closing.',
                                parent=self.root)
            return
        if self.nup_window is not None and self.nup_window.worker and self.nup_window.worker.is_alive():
            messagebox.showinfo('Install in progress',
                                'Let setup finish, or cancel it before closing this window.', parent=self.root)
            return
        self.closed = True
        self.root.destroy()

    # ---- visual layout --------------------------------------------------------------------------------------------

    def _toggle_art_motion(self):
        self.animate_art = not self.animate_art
        self._draw()

    def _on_resize(self, event):
        size = (event.width, event.height)
        if min(size) < 2 or size == self.last_size:
            return
        self.last_size = size
        if self.resize_job is not None:
            self.root.after_cancel(self.resize_job)
        self.resize_job = self.root.after(48, self._draw_after_resize)

    def _draw_after_resize(self):
        self.resize_job = None
        self._draw()

    def _draw_rect(self, x1, y1, x2, y2, fill):
        return self.canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline='', tags='visual')

    def _draw_text(self, x, y, text, *, size=16, color=TEXT, weight='normal', width=0, anchor='nw',
                   justify='left', family=UI_FONT):
        return self.canvas.create_text(x, y, text=text, font=(family, -max(9, round(size)), weight),
                                       fill=color, width=width, anchor=anchor, justify=justify, tags='visual')

    def _draw_round(self, x1, y1, x2, y2, fill, outline='', radius=16):
        return _rounded(self.canvas, x1, y1, x2, y2, radius, fill=fill, outline=outline)

    def _set_control_sizes(self, scale):
        if abs(self.ui_scale - scale) < .016:
            return
        self.ui_scale = scale
        for name, widget in self.widgets.items():
            if isinstance(widget, tk.Entry):
                widget.configure(font=(UI_FONT, -max(12, round(17 * scale))))
                continue
            hero_action = name in ('nup_entry', 'raw_entry')
            size = 20 if hero_action else 16
            widget.configure(font=(UI_FONT, -max(11, round(size * scale)), 'bold'),
                             padx=round((22 if hero_action else 13) * scale))

    def _draw_brand(self, x, y, scale):
        self.art.brand_mark(x + 14 * scale, y + 15 * scale, 30 * scale)
        self._draw_text(x + 41 * scale, y + 15 * scale, SETUP_NAME,
                        size=18 * scale, weight='bold', anchor='w')

    def _draw(self):
        if self.closed:
            return
        if self.page == 'source':
            self._validate_game_data()
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w < 2 or h < 2:
            return
        s = min(w / 1280, h / 800)
        margin = 64 * s
        self.canvas.delete('visual')
        self.visible_controls.clear()
        self.art.clear_motion()
        self.progress_indicator = None
        self._set_control_sizes(s)
        self._draw_rect(0, 0, w, h, BG)

        # Keep the form comfortable on portrait displays and give the art room on wider windows.
        split = w * .52 if w / h > 1.16 else w
        if split < w:
            self._draw_rect(split, 0, w, h, PANEL)
            self.art.draw(split, 0, w - split, h, animate=self.animate_art and self.page == 'welcome')
            self._draw_rect(split, 0, split + s, h, '#242b49')

        if self.page == 'welcome':
            width = min(542 * s, split - margin * 2)
            x = (split - width) / 2
            self._draw_brand(x, 40 * s, s)
            self._draw_welcome(x, h * .5 - 228 * s, width, s)
            if split < w and self.animate:
                self.widgets['motion'].configure(text='Pause animation' if self.animate_art else 'Play animation')
                self._place('motion', w - 196 * s, h - 65 * s, 162 * s, 38 * s)
        else:
            width = min(580 * s, split - margin * 1.55)
            x = (split - width) / 2
            self._draw_brand(x, 37 * s, s)
            self._draw_steps(x, 102 * s, width, s)
            self._draw_content(x, 157 * s, width, s)
            if self.source_info and split < w:
                self._draw_preview(split, 0, w - split, h, s)
            self._layout_widgets(x, h - 80 * s, width, s)

        for name, item in self.widget_items.items():
            if name not in self.visible_controls:
                self.canvas.itemconfigure(item, state='hidden')

    def _draw_welcome(self, x, y, width, s):
        self._draw_text(x, y, 'Install your', size=70 * s, weight='bold', family=DISPLAY_FONT)
        self._draw_text(x, y + 68 * s, 'game.', size=70 * s, color=YELLOW, weight='bold', family=DISPLAY_FONT)
        self._draw_text(x, y + 170 * s, 'Use the files from your own copy of the game.',
                        size=18 * s, color=TEXT_SOFT, width=width)
        action_w = min(width, 430 * s)
        self._place('nup_entry', x, y + 222 * s, action_w, 60 * s)
        self._place('raw_entry', x, y + 294 * s, action_w, 60 * s)
        self._place('prepared_entry', x - 13 * s, y + 382 * s, min(width, 256 * s), 45 * s)

    def _draw_steps(self, x, y, width, s):
        step = 2 if self.page == 'error' else self.PAGES.index(self.page) - 1
        gap = 12 * s
        segment = (width - gap * 3) / 4
        for index, label in enumerate(self.STEP_LABELS):
            left = x + index * (segment + gap)
            active = index == step
            color = YELLOW if active else LEAF if index < step else PANEL_EDGE
            self._draw_rect(left, y, left + segment, y + 3 * s, color)
            self._draw_text(left, y + 12 * s, label, size=12 * s,
                            color=TEXT if active else TEXT_DIM, weight='bold' if active else 'normal')

    def _draw_content(self, x, title_y, width, s):
        pad = 0
        text_w = width
        if self.page == 'source':
            self._draw_text(x + pad, title_y, 'Prepared game folder', size=39 * s, weight='bold', family=DISPLAY_FONT)
            self._draw_text(x + pad, title_y + 64 * s,
                            'Choose the folder where your game was already prepared for PC.',
                            size=17 * s, color=TEXT_SOFT, width=text_w)
            self._draw_text(x + pad, title_y + 118 * s, 'Game folder', size=14 * s, color=TEXT_DIM, weight='bold')
            status = self.source_error or ('This folder is ready to use.' if self.source_info else '')
            color = ERROR if self.source_error else LEAF if self.source_info else TEXT_DIM
            self._draw_text(x + pad, title_y + 210 * s, status, size=14 * s, color=color, width=text_w)
            if self.source_info and self.game_data_paths:
                label = 'Folder with your original game files' if self.game_data_required else 'Separate game files (optional)'
                self._draw_text(x + pad, title_y + 267 * s, label, size=14 * s,
                                color=YELLOW if self.game_data_required else TEXT_DIM, weight='bold')
                bx, by = x + pad, title_y + 295 * s
                self._place('game_data_entry', bx, by, width - 2 * pad - 134 * s, 52 * s)
                self._place('game_data_browse', x + width - pad - 122 * s, by, 122 * s, 52 * s)
                status = self.game_data_error or ('Leave this blank to use the files in your prepared folder.'
                                                  if not self.game_data_required else '')
                self._draw_text(x + pad, title_y + 360 * s, status, size=14 * s,
                                color=ERROR if self.game_data_error else TEXT_SOFT, width=text_w)
            bx, by = x + pad, title_y + 145 * s
            self._place('source_entry', bx, by, width - 2 * pad - 134 * s, 52 * s)
            self._place('source_browse', x + width - pad - 122 * s, by, 122 * s, 52 * s)
        elif self.page == 'destination':
            self._draw_text(x + pad, title_y, 'Install location', size=39 * s, weight='bold', family=DISPLAY_FONT)
            self._draw_text(x + pad, title_y + 64 * s,
                            'Choose where to install your game.', size=17 * s, color=TEXT_SOFT,
                            width=text_w)
            self._draw_text(x + pad, title_y + 118 * s, 'Install folder', size=14 * s,
                            color=TEXT_DIM, weight='bold')
            by = title_y + 145 * s
            self._place('destination_entry', x + pad, by, width - 2 * pad - 134 * s, 52 * s)
            self._place('destination_browse', x + width - pad - 122 * s, by, 122 * s, 52 * s)
            status = self.destination_error or 'Updating an existing install keeps your saves and settings.'
            self._draw_text(x + pad, title_y + 210 * s, status, size=16 * s,
                            color=ERROR if self.destination_error else TEXT_SOFT, width=text_w)
        elif self.page == 'progress':
            self._draw_text(x + pad, title_y, 'Installing your game', size=39 * s, weight='bold', family=DISPLAY_FONT)
            self._draw_text(x + pad, title_y + 64 * s,
                            'Keep this window open until the installation finishes.', size=17 * s,
                            color=TEXT_SOFT, width=text_w)
            self._draw_text(x + pad, title_y + 152 * s, self.progress_phase or 'Working…', size=17 * s,
                            color=TEXT, width=text_w)
            px, py, pw, ph = x + pad, title_y + 203 * s, text_w, 20 * s
            self._draw_round(px, py, px + pw, py + ph, '#26364c', outline='', radius=10 * s)
            if self.progress_total > 0:
                ratio = max(0.0, min(1.0, self.progress_done / self.progress_total))
                if ratio > 0:
                    self._draw_round(px, py, px + pw * ratio, py + ph, YELLOW, outline='', radius=10 * s)
                self._draw_text(px, py + 32 * s, f'{ratio * 100:.0f}%', size=14 * s, color=YELLOW, weight='bold')
            else:
                item = self._draw_round(px, py, px + pw * .27, py + ph, YELLOW, radius=10 * s)
                self.progress_indicator = (item, pw * .73, 0)
                self._draw_text(px, py + 32 * s, 'Working…', size=14 * s, color=YELLOW, weight='bold')
        elif self.page == 'complete':
            self._draw_round(x + pad, title_y + 8 * s, x + pad + 52 * s, title_y + 60 * s,
                             '#1d493b', outline='#3d8f63', radius=26 * s)
            self._draw_text(x + pad + 26 * s, title_y + 33 * s, '✓', size=25 * s, color=LEAF,
                            weight='bold', anchor='center')
            self._draw_text(x + pad + 72 * s, title_y + 8 * s, 'Your game is ready', size=39 * s, weight='bold', family=DISPLAY_FONT)
            self._draw_text(x + pad, title_y + 100 * s,
                            'Open the game folder to start playing.', size=17 * s,
                            color=TEXT_SOFT, width=text_w)
            self._draw_text(x + pad, title_y + 168 * s, self.destination_var.get().strip(), size=16 * s,
                            color='#b8e5f7', width=text_w)
            if self.progress_note:
                self._draw_text(x + pad, title_y + 230 * s, self.progress_note, size=14 * s,
                                color=ERROR, width=text_w)
        else:  # error
            self._draw_round(x + pad, title_y + 8 * s, x + pad + 52 * s, title_y + 60 * s,
                             '#542c38', outline='#8f4b50', radius=26 * s)
            self._draw_text(x + pad + 26 * s, title_y + 33 * s, '!', size=24 * s, color=ERROR,
                            weight='bold', anchor='center')
            self._draw_text(x + pad + 72 * s, title_y + 8 * s, 'Install did not finish', size=37 * s, weight='bold', family=DISPLAY_FONT)
            self._draw_text(x + pad, title_y + 100 * s,
                            'Check that your drive has free space and that your game files are available. '
                            'Choose Back if you want to use a different folder.',
                            size=17 * s, color=TEXT_SOFT, width=text_w)

    def _draw_preview(self, x, y, width, height, s):
        card_w = min(width - 90 * s, 390 * s)
        side = min(card_w - 52 * s, height * .42)
        has_image = self.source_icon is not None
        card_h = (side if has_image else 0) + 168 * s
        card_x = x + (width - card_w) / 2
        card_y = y + (height - card_h) / 2
        self._draw_round(card_x, card_y, card_x + card_w, card_y + card_h,
                         BG, outline=PANEL_EDGE, radius=24 * s)
        if has_image:
            self.art.cover(self.source_icon, x + (width - side) / 2, card_y + 25 * s, side)
        metadata_y = card_y + (side if has_image else 0) + 40 * s
        text_x = card_x + 22 * s
        self._draw_text(text_x, metadata_y, self.source_info['game_title'], size=23 * s,
                        width=card_w - 44 * s, weight='bold', family=DISPLAY_FONT)
        self._draw_text(text_x, card_y + card_h - 57 * s,
                        f"Game {self.source_info['game_version']}  ·  PC {self.source_info['port_version']}",
                        size=14 * s, color=TEXT_SOFT, width=card_w - 44 * s)

    def _layout_widgets(self, x, y, width, s):
        button_h = 48 * s
        primary_w = 150 * s
        if self.page == 'progress' and self.graphics_warmup and not self.skip_graphics.is_set():
            self._place('skip_graphics', x + width - 182 * s, y, 182 * s, button_h)
        if self.page in ('source', 'destination', 'error'):
            self._place('back', x, y, 102 * s, button_h)
        secondary = 'aux' if self.page == 'complete' else 'error_details' if self.page == 'error' else None
        if secondary:
            self._place(secondary, x + width - primary_w - 174 * s, y, 162 * s, button_h)
        labels = {'source': 'Next', 'destination': 'Install', 'complete': 'Done', 'error': 'Try again'}
        if self.page in labels:
            enabled = True
            if self.page == 'source':
                enabled = bool(self.source_info and not self.game_data_error)
            elif self.page == 'destination':
                enabled = bool(self.source_info and not self.destination_error)
            self.widgets['primary'].configure(text=labels[self.page], state='normal' if enabled else 'disabled',
                                              bg=YELLOW if enabled else PANEL_HI, disabledforeground=TEXT_DIM)
            self._place('primary', x + width - primary_w, y, primary_w, button_h)

    def _animate(self):
        if self.closed:
            return
        self.art.tick()
        if self.progress_indicator:
            item, distance, offset = self.progress_indicator
            self.motion = (self.motion + .014) % 2
            next_offset = distance * (1 - abs(self.motion - 1))
            self.canvas.move(item, next_offset - offset, 0)
            self.progress_indicator = (item, distance, next_offset)
        self.root.after(33 if self.art.animating else 45, self._animate)


def _capture(root: tk.Tk, path: Path):
    if ImageGrab is None:
        raise SystemExit('--shots needs Pillow')
    root.update()
    if os.name == 'nt':
        # Capture the wizard HWND itself, even if another window covers its screen rectangle.
        ImageGrab.grab(window=window_hwnd(root), include_layered_windows=True).save(path)
    else:
        x, y, w, h = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
        ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(path)


def selftest(shots: Path | None = None) -> int:
    enable_dpi_awareness()
    root = tk.Tk()
    app = LocalBuildWizard(root, animate=False, selftest=True)
    root.update()
    app._draw()
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
        _capture(root, shots / 'welcome.png')
    app.source_var.set('<prepared game folder>')
    app.source_info = {'game_title': 'Super Mario Bros. Wonder', 'game_version': '1.0.0',
                       'port_version': '0.2.1', 'game_id': 'sample'}
    app.game_data_paths = ('exefs/main', 'romfs_packed/romfs.bin')
    app.portable_game_data_paths = ('exefs/main', 'romfs/romfs.bin')
    app.source_error = ''
    app.source_icon = None  # selftest uses the vector placeholder; no cover art is loaded or generated
    app.setting_destination = True
    app.destination_var.set('<install folder>')
    app.setting_destination = False
    app.progress_done, app.progress_total, app.progress_phase = 42, 100, 'Copying your game files…'
    app.error_message = 'Sample install error.'
    pages = ('source', 'destination', 'progress', 'complete', 'error')
    for page in pages:
        app.page = page
        app._draw()
        root.update()
        if shots:
            _capture(root, shots / f'{page}.png')
    app.closed = True
    root.destroy()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--selftest', action='store_true')
    parser.add_argument('--shots', type=Path)
    args = parser.parse_args(argv)
    if args.selftest:
        from installer.nup_build_gui import selftest as source_flow_selftest

        return selftest(args.shots) or source_flow_selftest(args.shots)
    enable_dpi_awareness()
    root = tk.Tk()
    LocalBuildWizard(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
