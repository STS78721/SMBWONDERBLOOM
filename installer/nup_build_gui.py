"""WonderBloom setup for a game file or a folder of game data."""
from __future__ import annotations

import argparse
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

try:
    from PIL import ImageGrab
except ImportError:
    ImageGrab = None

from installer.nup_workflow import (
    NupWorkflowCancelled, NupWorkflowError, WorkflowProgress, is_setup_root, locate_game_folder,
    run_folder_workflow, run_nup_workflow,
)
from installer.setup_art import HeroArt
from installer.setup_brand import SETUP_NAME, SETUP_TOOLS_ARCHIVE
from installer.setup_window import configure_window, desktop_animations_enabled, enable_dpi_awareness


BG = '#0b1020'
PANEL = '#131b2e'
CONTROL = '#1b2540'
CONTROL_HOT = '#273653'
TEXT = '#f6f7ff'
MUTED = '#b4bdd4'
DIM = '#909bb7'
LINE = '#26314b'
YELLOW = '#ffce52'
YELLOW_HOT = '#ffe184'
INK = '#201534'
CYAN = '#8cdef9'
MINT = '#8ce1bb'
CORAL = '#ff9a9f'


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _overlap(first: Path, second: Path) -> bool:
    return _inside(first, second) or _inside(second, first)


def _setup_root() -> Path | None:
    entry = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve()
    return next((folder for folder in entry.parents if is_setup_root(folder)), None)


def bundled_setup_tools() -> Path | None:
    if not getattr(sys, 'frozen', False):
        return None
    payload = Path(__file__).resolve().parents[1] / SETUP_TOOLS_ARCHIVE
    return payload if payload.is_file() else None


def _run_with_bundled_tools(payload, workflow, args, kwargs):
    with tempfile.TemporaryDirectory(prefix='WonderBloom-Setup-') as folder, ZipFile(payload) as archive:
        cancel = kwargs['cancel_event']
        for member in archive.infolist():
            if cancel.is_set():
                raise NupWorkflowCancelled('validate')
            archive.extract(member, folder)
        root = Path(folder)
        python = root / 'python' / 'python.exe'
        options = dict(kwargs, repo_root=root, build_python=python)
        if 'extractor_python' in options:
            options['extractor_python'] = python
        return workflow(*args, **options)


def _setup_python(root: Path, environment: str) -> Path | None:
    candidates = (
        root / 'python' / 'python.exe',
        root / environment / 'Scripts' / 'python.exe',
        Path(sys.executable) if not getattr(sys, 'frozen', False) else None,
        shutil.which('python.exe') if (root / '.git').exists() else None,
    )
    return next((Path(p) for p in candidates if p and Path(p).is_file()), None)


class NupWorkflowWizard:
    STEPS = ('Your files', 'Installing', 'Ready')
    PHASES = {
        'validate': 'Checking your files',
        'extract': 'Reading your game data',
        'build': 'Preparing your game',
        'install': 'Installing your game',
        'shaders': 'Preparing graphics',
        'graphics': 'Caching graphics for first play',
    }
    SPACE_NOTE = 'Allow about 60 GB of free space.'

    def __init__(self, parent: tk.Misc | None = None, *, source_kind: str = 'nup',
                 animate: bool = True, selftest: bool = False, motion_preference: bool | None = None):
        self.parent = parent
        self.source_kind = source_kind
        self.animate = animate and not selftest
        self.animate_art = self.animate and (desktop_animations_enabled() if motion_preference is None else motion_preference)
        if parent is None:
            enable_dpi_awareness()
        self.root = tk.Toplevel(parent) if parent is not None else tk.Tk()
        self.root.configure(bg=BG)
        configure_window(self.root, title=SETUP_NAME, design_size=(1280, 800),
                         minimum_size=(760, 560), parent=parent)
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

        self.source_var = tk.StringVar(master=self.root)
        self.destination_var = tk.StringVar(master=self.root)
        self.setup_payload = None if selftest else bundled_setup_tools()
        self.setup_root = None if selftest or self.setup_payload else _setup_root()
        self.extractor_python = _setup_python(self.setup_root, '.venv-py314') if self.setup_root else None
        self.build_python = _setup_python(self.setup_root, '.venv') if self.setup_root else None
        self.setup_available = bool(self.setup_payload or (self.build_python and (source_kind == 'folder' or self.extractor_python)))
        self.workspace: Path | None = None
        self.validation_error = ''
        self.ready = False

        self.page = 'inputs'
        self.progress: WorkflowProgress | None = None
        self.result = None
        self.failure_phase = ''
        self.failure_message = ''
        self.cancel_event = threading.Event()
        self.cancel_requested = False
        self.worker: threading.Thread | None = None
        self.events: queue.Queue = queue.Queue()
        self.closed = False
        self.last_size: tuple[int, int] | None = None
        self.animation_pending = False
        self.progress_segment: tuple[int, float, float, float, float] | None = None
        self.font_sizes = (-17, -17)
        self.widget_items: dict[str, int] = {}
        self.widgets: dict[str, tk.Widget] = {}
        self.entries: dict[str, tk.Entry] = {}
        self.placed: set[str] = set()

        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill='both', expand=True)
        self.art = HeroArt(self.canvas)
        self.font_family = 'Segoe UI' if os.name == 'nt' else 'DejaVu Sans'
        families = tkfont.families(self.root)
        self.display_family = ('Segoe UI Variable Display' if 'Segoe UI Variable Display' in families
                               else self.font_family)
        self.button_font = tkfont.Font(root=self.root, family=self.font_family, size=-17, weight='bold')
        self.entry_font = tkfont.Font(root=self.root, family=self.font_family, size=-17)
        self._make_widgets()
        if not selftest:
            for variable in (self.source_var, self.destination_var):
                variable.trace_add('write', self._inputs_changed)
        self.canvas.bind('<Configure>', self._on_resize)
        self.root.bind('<Return>', self._on_return)
        self.root.bind('<Escape>', self._on_escape)
        self.root.update_idletasks()
        self._draw()
        if not selftest:
            self.entries['source_entry'].focus_set()

    def _button(self, key: str, label: str, command, *, primary=False):
        widget = tk.Button(
            self.canvas, text=label, command=command,
            font=self.button_font,
            relief='flat', bd=0, cursor='hand2', padx=12, pady=7, takefocus=True,
            bg=YELLOW if primary else CONTROL, fg=INK if primary else TEXT,
            activebackground=YELLOW_HOT if primary else CONTROL_HOT,
            activeforeground=INK if primary else TEXT,
            disabledforeground=DIM, highlightthickness=2,
            highlightbackground=BG, highlightcolor=CYAN,
        )
        def invoke(_event):
            widget.invoke()
            return 'break'

        widget.bind('<Return>', invoke)
        self.widgets[key] = widget

    def _make_widgets(self):
        fields = (('source', self.source_var, self._browse_source),
                  ('destination', self.destination_var, self._browse_destination))
        for key, variable, browse in fields:
            shell = tk.Frame(self.canvas, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
            entry = tk.Entry(
                shell, textvariable=variable, font=self.entry_font,
                bg=PANEL, fg=TEXT, insertbackground=YELLOW,
                selectbackground=CONTROL_HOT, selectforeground=TEXT,
                relief='flat', bd=0, highlightthickness=0,
            )
            entry.pack(expand=True, fill='x', padx=14)
            entry.bind('<FocusIn>', lambda _event, box=shell: box.configure(highlightbackground=CYAN))
            entry.bind('<FocusOut>', lambda _event, box=shell: box.configure(highlightbackground=LINE))
            shell.bind('<Button-1>', lambda _event, field=entry: field.focus_set())
            self.entries[f'{key}_entry'] = entry
            self.widgets[f'{key}_entry'] = shell
            self._button(f'{key}_browse', 'Browse…', browse)
        self._button('back', 'Back', self._back)
        self._button('primary', 'Install', self._advance, primary=True)
        self._button('cancel', 'Cancel', self._cancel)
        self._button('details', 'Show details', self._show_details)
        self._button('open_destination', 'Open game folder', lambda: self._open_path(self.destination_var.get()))
        for key, widget in self.widgets.items():
            self.widget_items[key] = self.canvas.create_window(0, 0, window=widget, state='hidden', tags='controls')

    def _inputs_changed(self, *_):
        self.ready = self._validate_inputs()
        self._draw()

    def _browse_source(self):
        if self.source_kind == 'folder':
            path = filedialog.askdirectory(parent=self.root, title='Choose your game data folder')
        else:
            path = filedialog.askopenfilename(
                parent=self.root, title='Choose your game file',
                filetypes=(('Game files', '*.nup'),),
            )
        if path:
            self.source_var.set(os.path.normpath(path))

    def _browse_destination(self):
        path = filedialog.askdirectory(parent=self.root, title='Choose where to install', mustexist=False)
        if path:
            self.destination_var.set(os.path.normpath(path))

    def _validate_inputs(self) -> bool:
        self.validation_error = ''
        source_text, destination_text = self.source_var.get().strip(), self.destination_var.get().strip()
        if not source_text and not destination_text:
            return False
        if not source_text:
            self.validation_error = 'Choose your game data folder.' if self.source_kind == 'folder' else 'Choose your game file.'
            return False
        try:
            source = Path(source_text).expanduser().resolve()
            if self.source_kind == 'folder':
                source = locate_game_folder(source)
            elif not source.is_file() or source.suffix.casefold() != '.nup':
                self.validation_error = 'Choose a game file that ends in .nup.'
                return False
            if not destination_text:
                self.validation_error = 'Choose where you want to install the game.'
                return False
            destination = Path(destination_text).expanduser().resolve()
            if destination == destination.parent or (destination.exists() and not destination.is_dir()):
                self.validation_error = 'Choose a folder to install the game in.'
                return False
            if self.setup_root and _inside(source, self.setup_root) and self.source_kind == 'nup':
                self.validation_error = 'Move your game file out of the setup folder and choose it again.'
                return False
            if _overlap(source, destination) or (self.setup_root and _overlap(destination, self.setup_root)):
                self.validation_error = 'Choose an install folder outside your game and setup folders.'
                return False
        except NupWorkflowError as exc:
            self.validation_error = str(exc)
            return False
        except (OSError, RuntimeError, ValueError):
            self.validation_error = 'Check that both locations are available.'
            return False
        return self.setup_available

    def _advance(self):
        if self.page == 'inputs':
            self.ready = self._validate_inputs()
            if not self.ready:
                self._draw()
                return
            self._start_workflow()
        elif self.page in ('error', 'cancelled'):
            self._back()
        elif self.page == 'complete':
            self.on_close()

    def _back(self):
        if self.page in ('error', 'cancelled'):
            self.page = 'inputs'
            self._inputs_changed()
        else:
            self.on_close()

    def _on_return(self, event):
        if not isinstance(event.widget, tk.Button) and self.page != 'progress':
            self._advance()
            return 'break'
        return None

    def _on_escape(self, _event=None):
        if self.page == 'progress':
            self._cancel()
        else:
            self._back()
        return 'break'

    def _start_workflow(self):
        self.cancel_event = threading.Event()
        self.cancel_requested = False
        self.progress = None
        self.result = None
        self.failure_phase = ''
        self.failure_message = ''
        source = Path(self.source_var.get().strip()).expanduser()
        destination = Path(self.destination_var.get().strip()).expanduser()
        self.workspace = destination.resolve().parent / f'NS2 Setup Files {uuid4().hex[:12]}'
        self.page = 'progress'
        kwargs = {
            'repo_root': self.setup_root,
            'build_python': self.build_python,
            'progress_callback': lambda item: self.events.put(('progress', item)),
            'cancel_event': self.cancel_event,
        }
        workflow = run_folder_workflow if self.source_kind == 'folder' else run_nup_workflow
        if self.source_kind == 'nup':
            kwargs['extractor_python'] = self.extractor_python
        args = (source, self.workspace, destination)
        self.worker = threading.Thread(target=self._run_workflow, args=(workflow, args, kwargs), daemon=True)
        self.worker.start()
        self._draw()
        self.root.after(80, self._poll_worker)

    def _run_workflow(self, workflow, args, kwargs):
        try:
            if self.setup_payload:
                self.events.put(('progress', WorkflowProgress('validate', 'started', message='Preparing setup')))
                result = _run_with_bundled_tools(self.setup_payload, workflow, args, kwargs)
            else:
                result = workflow(*args, **kwargs)
        except NupWorkflowCancelled as exc:
            self.events.put(('cancelled', exc.phase, str(exc)))
        except NupWorkflowError as exc:
            self.events.put(('error', exc.phase, str(exc)))
        except Exception as exc:
            self.events.put(('error', 'workflow', f'{type(exc).__name__}: {exc}'))
        else:
            self.events.put(('complete', result))

    def _poll_worker(self):
        if self.closed:
            return
        changed = False
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == 'progress':
                    item = event[1]
                    self.progress = item
                    changed = True
                elif event[0] == 'complete':
                    self.result = event[1]
                    self.page = 'complete'
                    self.worker = None
                    changed = True
                elif event[0] in ('error', 'cancelled'):
                    self.failure_phase = str(event[1])
                    self.failure_message = str(event[2])[:4000]
                    self.page = event[0]
                    self.worker = None
                    changed = True
        except queue.Empty:
            pass
        if changed:
            self._draw()
        if self.worker:
            self.root.after(80, self._poll_worker)

    def _cancel(self):
        if self.worker and self.worker.is_alive():
            self.cancel_requested = True
            self.cancel_event.set()
            self.widgets['cancel'].configure(text='Stopping…', state='disabled')
            self.widgets['primary'].configure(state='disabled')
            self._draw()

    def _open_path(self, value: str):
        raw = value.strip()
        if not raw:
            return
        path = Path(raw).expanduser()
        if not path.exists():
            messagebox.showinfo('Folder not ready', 'That folder has not been created yet.', parent=self.root)
            return
        try:
            if os.name == 'nt':
                os.startfile(str(path))
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(['xdg-open', str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            messagebox.showerror('Could not open folder', str(exc), parent=self.root)

    def on_close(self):
        if self.worker and self.worker.is_alive():
            self._cancel()
            return
        self.closed = True
        self.root.destroy()

    def _show_details(self):
        detail = self.failure_message
        if self.workspace and self.workspace.exists():
            detail += f'\n\nWorking files: {self.workspace}'
        messagebox.showinfo('Setup details', detail, parent=self.root)

    def _on_resize(self, event):
        size = (event.width, event.height)
        if min(size) > 1 and size != self.last_size:
            self.last_size = size
            self._draw()

    def _draw_text(self, x, y, text, *, size=12, color=TEXT, weight='normal', width=0,
                   anchor='nw', display=False):
        family = self.display_family if display else self.font_family
        self.canvas.create_text(x, y, text=text, font=(family, -max(11, round(size)), weight),
                                fill=color, width=width, anchor=anchor, tags='visual')

    def _draw_rect(self, x1, y1, x2, y2, fill):
        return self.canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline='', tags='visual')

    def _draw(self):
        if self.closed:
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if min(w, h) < 100:
            return
        s = min(w / 1120, h / 750)
        # Favor the form over the artwork on narrow windows and snapped screens.
        show_art = w >= 1040 and w / h >= 1.36
        edge = round(w * 0.58) if show_art else w
        margin = 56 * s
        content_w = min(edge - 2 * margin, 670 * s)
        left = margin if show_art else (edge - content_w) / 2
        self.canvas.delete('visual')
        self.art.clear_motion()
        self.placed.clear()
        self.progress_segment = None
        font_sizes = (-max(13, round(17 * s)), -max(13, round(18 * s)))
        if self.font_sizes != font_sizes:
            self.button_font.configure(size=font_sizes[0])
            self.entry_font.configure(size=font_sizes[1])
            self.font_sizes = font_sizes
        if show_art:
            self._draw_rect(edge, 0, w, h, PANEL)
            self.art.draw(edge, 0, w - edge, h, animate=self.animate_art)
            self._draw_rect(edge, 0, edge + s, h, LINE)

        self.art.brand_mark(left + 14 * s, 52 * s, 29 * s)
        self._draw_text(left + 39 * s, 52 * s, SETUP_NAME, size=20 * s,
                        weight='bold', anchor='w')
        step = 0 if self.page == 'inputs' else 2 if self.page == 'complete' else 1
        step_spacing = min(152 * s, content_w / 3)
        for i, label in enumerate(self.STEPS):
            x = left + i * step_spacing
            color = YELLOW if i == step else MINT if i < step else DIM
            self._draw_text(x, 102 * s, label, size=15 * s, color=color, weight='bold')
            if i == step:
                self._draw_rect(x, 125 * s, x + 26 * s, 128 * s, YELLOW)
        y = 161 * s
        if self.page == 'inputs':
            self._draw_inputs(left, y, content_w, h, s)
        elif self.page == 'progress':
            self._draw_progress(left, y, content_w, s)
        elif self.page == 'complete':
            self._draw_complete(left, y, content_w, s)
        else:
            self._draw_failure(left, y, content_w, s)

        footer = h - 91 * s
        self._draw_rect(left, footer, left + content_w, footer + s, LINE)
        self._layout_buttons(left, left + content_w, footer + 22 * s, s)
        for key in self.widget_items.keys() - self.placed:
            self.canvas.itemconfigure(self.widget_items[key], state='hidden')
        self.canvas.tag_raise('controls')
        self._schedule_animation()

    def _field(self, label, key, x, y, width, s):
        self._draw_text(x, y, label, size=17 * s, weight='bold')
        entry_y, browse_w = y + 29 * s, 111 * s
        self._place(f'{key}_entry', x, entry_y, width - browse_w - 10 * s, 54 * s)
        self._place(f'{key}_browse', x + width - browse_w, entry_y, browse_w, 54 * s)

    def _draw_inputs(self, x, y, width, h, s):
        self._draw_text(x, y, 'Choose your files', size=53 * s, weight='bold', display=True)
        source_label = 'Game data folder (ROMFS)' if self.source_kind == 'folder' else 'Game file (.nup)'
        self._field(source_label, 'source', x, y + 105 * s, width, s)
        self._field('Install folder', 'destination', x, y + 207 * s, width, s)
        status = self.validation_error
        status_color = MUTED
        if not self.setup_available:
            status = 'Some setup files are missing. Unzip the full installer and open it again.'
            status_color = CORAL
        elif self.ready:
            status = 'Ready to install.'
            status_color = MINT
        self._draw_text(x, y + 307 * s, status, size=16 * s, color=status_color, width=width)
        self._draw_text(x, h - 122 * s, self.SPACE_NOTE, size=15 * s, color=DIM, width=width)

    def _draw_progress(self, x, y, width, s):
        progress = self.progress
        phase = progress.phase if progress else 'validate'
        title = 'Stopping…' if self.cancel_requested else self.PHASES.get(phase, 'Installing your game')
        self._draw_text(x, y, title, size=(32 if phase == 'graphics' else 48) * s,
                        weight='bold', width=width, display=True)
        self._draw_text(x, y + 80 * s, 'Setup can take a while. Keep this window open.',
                        size=18 * s, color=MUTED, width=width)
        bar_y, thickness = y + 150 * s, 10 * s
        self._draw_rect(x, bar_y, x + width, bar_y + thickness, CONTROL_HOT)
        if progress and progress.total and progress.completed is not None:
            ratio = max(0.0, min(1.0, progress.completed / progress.total))
            self._draw_rect(x, bar_y, x + width * ratio, bar_y + thickness, YELLOW)
            self._draw_text(x, bar_y + 24 * s, f'{ratio:.0%}', size=17 * s, color=YELLOW, weight='bold')
        else:
            item = self._draw_rect(x, bar_y, x + width * 0.28, bar_y + thickness, YELLOW)
            self.progress_segment = (item, x, width, bar_y, thickness)

    def _draw_complete(self, x, y, width, s):
        self._draw_text(x, y, 'Your game is ready', size=50 * s, weight='bold', width=width, display=True)
        installed = self.result.install_result
        self._draw_text(x, y + 91 * s, installed.game_title, size=24 * s,
                        color=MINT, weight='bold', width=width)
        self._draw_text(x, y + 134 * s, f'Game {installed.game_version}  ·  Port {installed.port_version}',
                        size=16 * s, color=MUTED, width=width)
        self._draw_text(x, y + 194 * s, 'Open the game folder to start playing.',
                        size=18 * s, color=MUTED, width=width)
        if warning := getattr(self.result, 'shader_warning', ''):
            self._draw_text(x, y + 238 * s, warning, size=17 * s, color=CORAL, width=width)

    def _draw_failure(self, x, y, width, s):
        cancelled = self.page == 'cancelled'
        title = 'Setup cancelled' if cancelled else 'Setup couldn’t finish'
        self._draw_text(x, y, title, size=46 * s, weight='bold', width=width, display=True)
        hints = {
            'validate': 'Check that both locations are available and choose an install folder you can write to.',
            'extract': 'Check that you chose a complete copy of your game and that your drive has free space.',
            'build': 'Setup couldn’t prepare this copy of the game. Check that your game files are complete and your drive has free space.',
            'install': 'Choose an empty folder or the folder where this game is already installed.',
        }
        hint = ('You can go back and start again.' if cancelled else
                self.failure_message if self.failure_phase == 'validate' and 'Switch 2 Edition' in self.failure_message else
                hints.get(self.failure_phase, 'Go back to check your choices, then try again.'))
        self._draw_text(x, y + 92 * s, hint, size=18 * s, color=MUTED, width=width)
        if self.workspace is not None:
            self._draw_text(x, y + 180 * s, 'Show details to find the files setup created.',
                            size=16 * s, color=DIM, width=width)

    def _place(self, key, x, y, width, height):
        self.placed.add(key)
        self.canvas.coords(self.widget_items[key], x + width * 0.5, y + height * 0.5)
        self.canvas.itemconfigure(self.widget_items[key], state='normal', width=width, height=height)

    def _layout_buttons(self, left, right, y, s):
        button_h = 52 * s
        if self.page == 'progress':
            preparing = self.progress and self.progress.phase in ('shaders', 'graphics')
            label = 'Skip graphics prep' if preparing else 'Cancel'
            self.widgets['cancel'].configure(state='disabled' if self.cancel_requested else 'normal',
                                             text='Stopping…' if self.cancel_requested else label)
            width = (184 if preparing else 136) * s
            self._place('cancel', right - width, y, width, button_h)
            return

        if self.page == 'inputs':
            self._place('back', left, y, 111 * s, button_h)
        if self.page in ('error', 'cancelled'):
            self._place('details', left, y, 146 * s, button_h)
        if self.page == 'complete':
            self._place('open_destination', right - 345 * s, y, 174 * s, button_h)
        label = {'inputs': 'Install', 'complete': 'Done', 'error': 'Go back', 'cancelled': 'Go back'}[self.page]
        enabled = self.page != 'inputs' or self.ready
        self.widgets['primary'].configure(text=label, state='normal' if enabled else 'disabled',
                                          bg=YELLOW if enabled else CONTROL,
                                          disabledforeground=DIM)
        self._place('primary', right - 159 * s, y, 159 * s, button_h)

    def _schedule_animation(self):
        if self.animate and not self.animation_pending and (self.art.animating or self.progress_segment):
            self.animation_pending = True
            self.root.after(33, self._animate)

    def _animate(self):
        self.animation_pending = False
        if self.closed:
            return
        self.art.tick()
        if self.progress_segment is not None:
            item, x, width, y, thickness = self.progress_segment
            offset = width * 0.36 * (1 + math.sin(time.monotonic() * 2.7))
            self.canvas.coords(item, x + offset, y, x + offset + width * 0.28, y + thickness)
        self._schedule_animation()


def _capture(root: tk.Tk, path: Path):
    if ImageGrab is None:
        raise SystemExit('--shots needs Pillow')
    root.update()
    if os.name == 'nt':
        ImageGrab.grab(window=root.winfo_id(), include_layered_windows=True).save(path)
    else:
        x, y, w, h = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
        ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(path)


def selftest(shots: Path | None = None) -> int:
    for kind in ('nup', 'folder'):
        app = NupWorkflowWizard(None, source_kind=kind, animate=False, selftest=True)
        root = app.root
        root.update()
        app.setup_available = app.ready = True
        app.source_var.set(r'D:\My Game.nup' if kind == 'nup' else r'D:\My Game Files\romfs')
        app.destination_var.set(r'D:\Games\Wonder')
        app.progress = WorkflowProgress('extract', 'progress', 42, 100, 'files')
        app.result = SimpleNamespace(install_result=SimpleNamespace(
            game_title='Super Mario Bros. Wonder', game_version='1.0.0', port_version='0.2.1'))
        app.failure_phase = 'build'
        app.failure_message = 'Sample setup error.'
        if shots:
            shots.mkdir(parents=True, exist_ok=True)
        for page in ('inputs', 'progress', 'complete', 'error', 'cancelled'):
            app.page = page
            app._draw()
            root.update()
            if shots:
                _capture(root, shots / f'{kind}-{page}.png')
        app.on_close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--selftest', action='store_true')
    parser.add_argument('--shots', type=Path)
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest(args.shots)
    app = NupWorkflowWizard(None)
    app.root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
