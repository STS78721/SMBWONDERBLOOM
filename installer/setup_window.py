"""Native window setup shared by the installer and its game source wizard."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from functools import lru_cache
import os
from pathlib import Path
import tkinter as tk


_APP_ID = 'SteelTemple.WonderBloom.Setup'
_ICON_PATH = Path(__file__).resolve().with_name('assets') / 'setup.ico'
_GA_ROOT = 2
_MONITOR_DEFAULTTONEAREST = 2
_DPI_PER_MONITOR_V2 = ctypes.c_void_p(-4)
_DWM_DARK_MODE = (20, 19)
_DWM_BORDER_COLOR = 34
_DWM_CAPTION_COLOR = 35
_DWM_TEXT_COLOR = 36


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ('size', wintypes.DWORD),
        ('monitor', wintypes.RECT),
        ('work', wintypes.RECT),
        ('flags', wintypes.DWORD),
    ]


@lru_cache(maxsize=None)
def _win_api(dll, name, result_type, *argument_types):
    function = getattr(getattr(ctypes.windll, dll), name)
    function.restype = result_type
    function.argtypes = argument_types
    return function


def enable_dpi_awareness():
    """Call before creating the first Tk instance."""
    if os.name != 'nt':
        return

    try:
        set_app_id = _win_api('shell32', 'SetCurrentProcessExplicitAppUserModelID',
                              wintypes.LONG, wintypes.LPCWSTR)
        set_app_id(_APP_ID)
    except (AttributeError, OSError):
        pass

    try:
        set_process = _win_api('user32', 'SetProcessDpiAwarenessContext',
                               wintypes.BOOL, ctypes.c_void_p)
        if not set_process(_DPI_PER_MONITOR_V2):
            # The executable manifest or an embedding process can already own the
            # default. Set the Tk thread's context before it creates its first HWND.
            set_thread = _win_api('user32', 'SetThreadDpiAwarenessContext',
                                  ctypes.c_void_p, ctypes.c_void_p)
            set_thread(_DPI_PER_MONITOR_V2)
        return
    except (AttributeError, OSError):
        pass

    try:
        set_process = _win_api('shcore', 'SetProcessDpiAwareness', wintypes.LONG, ctypes.c_int)
        set_process(2)  # Per-monitor awareness on Windows 8.1.
    except (AttributeError, OSError):
        try:
            _win_api('user32', 'SetProcessDPIAware', wintypes.BOOL)()
        except (AttributeError, OSError):
            pass


def desktop_animations_enabled():
    if os.name != 'nt':
        return True
    try:
        query = _win_api('user32', 'SystemParametersInfoW', wintypes.BOOL,
                         wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT)
        enabled = wintypes.BOOL(1)
        if query(0x1042, 0, ctypes.byref(enabled), 0):  # SPI_GETCLIENTAREAANIMATION
            return bool(enabled.value)
    except (AttributeError, OSError):
        pass
    return True


def window_hwnd(window: tk.Misc) -> int:
    """Return the native outer HWND on Windows, where the title bar lives."""
    inner = window.winfo_id()
    if os.name != 'nt':
        return inner
    ancestor = _win_api('user32', 'GetAncestor', wintypes.HWND, wintypes.HWND, wintypes.UINT)
    return ancestor(inner, _GA_ROOT) or inner


def _window_bounds(window):
    if os.name != 'nt':
        return None
    get_rect = _win_api('user32', 'GetWindowRect', wintypes.BOOL,
                        wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    rect = wintypes.RECT()
    if get_rect(window_hwnd(window), ctypes.byref(rect)):
        return rect.left, rect.top, rect.right, rect.bottom
    return None


def _frame_size(window, outer):
    get_client = _win_api('user32', 'GetClientRect', wintypes.BOOL,
                          wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    client = wintypes.RECT()
    if get_client(window_hwnd(window), ctypes.byref(client)):
        x1, y1, x2, y2 = outer
        return max(0, x2 - x1 - client.right), max(0, y2 - y1 - client.bottom)
    return 24, 60


def _monitor_work_area(window):
    monitor = None
    if window is not None:
        find = _win_api('user32', 'MonitorFromWindow', wintypes.HMONITOR,
                        wintypes.HWND, wintypes.DWORD)
        monitor = find(window_hwnd(window), _MONITOR_DEFAULTTONEAREST)
    if monitor is None:
        pointer = wintypes.POINT()
        get_pointer = _win_api('user32', 'GetCursorPos', wintypes.BOOL, ctypes.POINTER(wintypes.POINT))
        get_pointer(ctypes.byref(pointer))
        find = _win_api('user32', 'MonitorFromPoint', wintypes.HMONITOR,
                        wintypes.POINT, wintypes.DWORD)
        monitor = find(pointer, _MONITOR_DEFAULTTONEAREST)
    get_info = _win_api('user32', 'GetMonitorInfoW', wintypes.BOOL,
                        wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo))
    info = _MonitorInfo(size=ctypes.sizeof(_MonitorInfo))
    if not get_info(monitor, ctypes.byref(info)):
        raise OSError('Could not get the monitor work area')
    area = info.work
    return area.left, area.top, area.right, area.bottom


def work_area(window: tk.Misc | None = None) -> tuple[int, int, int, int]:
    """Return work-area bounds in desktop pixels, using the pointer if no window is given."""
    if os.name == 'nt':
        try:
            return _monitor_work_area(window)
        except (AttributeError, OSError):
            pass
    if window is None:
        window = tk._default_root
    if window is None:
        raise RuntimeError('A Tk window is needed to find the screen size')
    x, y = window.winfo_vrootx(), window.winfo_vrooty()
    return x, y, x + window.winfo_vrootwidth(), y + window.winfo_vrootheight()


def _colorref(color: str) -> int:
    red, green, blue = bytes.fromhex(color.removeprefix('#'))
    return red | green << 8 | blue << 16


def _style_title_bar(window, caption):
    try:
        hwnd = window_hwnd(window)
        set_attribute = _win_api('dwmapi', 'DwmSetWindowAttribute', wintypes.LONG,
                                 wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
        for attribute in _DWM_DARK_MODE:
            enabled = wintypes.BOOL(1)
            if set_attribute(hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)) == 0:
                break
        # Windows 11 supports explicit colors. Earlier builds keep the dark mode
        # selected above when available and ignore these newer attributes.
        colors = ((_DWM_BORDER_COLOR, '#323c60'), (_DWM_CAPTION_COLOR, caption), (_DWM_TEXT_COLOR, '#f5f3ff'))
        for attribute, color in colors:
            value = wintypes.DWORD(_colorref(color))
            set_attribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
        redraw = _win_api('user32', 'RedrawWindow', wintypes.BOOL,
                          wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT)
        redraw(hwnd, None, None, 0x0400 | 0x0100 | 0x0001)  # FRAME, UPDATENOW, INVALIDATE
    except (AttributeError, OSError, tk.TclError):
        pass


def configure_window(window: tk.Tk | tk.Toplevel, *, title: str, design_size=(1280, 800),
                     minimum_size=(760, 560), parent: tk.Misc | None = None,
                     caption: str = '#101421'):
    """Set the installer identity and fit its initial window to the active display."""
    initially_hidden = os.name == 'nt' and window.state() == 'normal' and not window.winfo_ismapped()
    if initially_hidden:
        window.withdraw()
    window.title(title)
    # Tk's point conversion stays stable because the installer layout scales its
    # pixel geometry and fonts together as a function of canvas width and height.
    window.tk.call('tk', 'scaling', 96.0 / 72.0)

    left, top, right, bottom = work_area(parent)
    available_width, available_height = right - left, bottom - top
    margin = max(12, min(36, round(available_height * .018)))
    frame_width, frame_height = (24, 60) if os.name == 'nt' else (12, 36)
    if initially_hidden and parent is None:
        # Measure the real border and caption on the chosen monitor. Fixed estimates
        # can clip a compact work area when Windows renders a high DPI caption.
        window.geometry(f'320x240+{left + margin}+{top + margin}')
        window.update_idletasks()
        bounds = _window_bounds(window)
        if bounds:
            frame_width, frame_height = _frame_size(window, bounds)
    scale = min(available_width * .82 / design_size[0], available_height * .80 / design_size[1])
    width, height = (round(length * scale) for length in design_size)
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    if parent is not None and parent.winfo_ismapped():
        width, height = parent.winfo_width(), parent.winfo_height()
        bounds = _window_bounds(parent)
        if bounds:
            x1, y1, x2, y2 = bounds
            frame_width, frame_height = _frame_size(parent, bounds)
            center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
        else:
            center_x = parent.winfo_rootx() + width / 2
            center_y = parent.winfo_rooty() + height / 2
    width_limit = max(1, available_width - margin * 2 - frame_width)
    height_limit = max(1, available_height - margin * 2 - frame_height)
    min_width = min(minimum_size[0], width_limit)
    min_height = min(minimum_size[1], height_limit)
    width = min(max(min_width, width), width_limit)
    height = min(max(min_height, height), height_limit)
    x = min(max(left + margin, round(center_x - (width + frame_width) / 2)),
            right - margin - width - frame_width)
    y = min(max(top + margin, round(center_y - (height + frame_height) / 2)),
            bottom - margin - height - frame_height)
    window.minsize(min_width, min_height)
    window.geometry(f'{width}x{height}+{x}+{y}')

    if os.name == 'nt':
        if _ICON_PATH.is_file():
            try:
                if parent is None:
                    window.iconbitmap(default=str(_ICON_PATH))
                window.iconbitmap(str(_ICON_PATH))
            except tk.TclError:
                pass

        def mapped(event):
            if event.widget == window:
                _style_title_bar(window, caption)

        window.bind('<Map>', mapped, add=True)
        if initially_hidden:
            # Build Tk's wrapper while withdrawn so its first visible frame already
            # has the app's icon and dark chrome. The caller can lay out the UI before it maps.
            window.update_idletasks()
            _style_title_bar(window, caption)
            window.after_idle(window.deiconify)
        elif window.winfo_ismapped():
            _style_title_bar(window, caption)
