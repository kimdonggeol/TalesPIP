import sys
import os
import math
import threading
import traceback
import ctypes

def _init_dpi_awareness():
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_init_dpi_awareness()

def _base_dir():
    """Where config.json and error.log live. A PyInstaller onefile build unpacks
    itself into a temp folder that is deleted on exit, so __file__ there would
    silently throw the settings away — use the exe's own folder instead."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _base_dir()
ERROR_LOG_PATH = os.path.join(BASE_DIR, "error.log")


_dialog_shown = False


def log_exception(msg=None, dialog=True):
    """Always logs; shows a blocking dialog at most once per run."""
    global _dialog_shown
    msg = msg or traceback.format_exc()
    try:
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass
    sys.stderr.write(msg)
    if dialog and not _dialog_shown:
        _dialog_shown = True
        try:
            ctypes.windll.user32.MessageBoxW(0, msg[-1500:], "TalesPIP 오류", 0x10)
        except Exception:
            pass


def _excepthook(exc_type, exc_value, exc_tb):
    log_exception("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))


sys.excepthook = _excepthook

try:
    import json
    import copy
    import uuid
    import winreg
    import urllib.request
    import webbrowser
    from ctypes import wintypes

    import psutil

    from PyQt6.QtCore import (
        Qt, QObject, QTimer, QRect, QRectF, QSize, QPoint, QPointF, pyqtSignal,
        QAbstractNativeEventFilter
    )
    from PyQt6.QtGui import (
        QIcon, QAction, QPainter, QColor, QPen, QPixmap, QKeySequence,
        QLinearGradient, QPainterPath, QFont, QTransform
    )
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QMenu, QMessageBox, QLabel,
        QDialog, QListWidget, QListWidgetItem, QPushButton, QHBoxLayout, QVBoxLayout,
        QSystemTrayIcon, QCheckBox, QSpinBox, QSlider, QLineEdit,
        QStackedWidget, QFrame, QGridLayout, QComboBox, QScrollArea
    )
except Exception:
    log_exception()
    sys.exit(1)

TARGET_PROCESS = "InphaseNXD.exe"
TARGET_LABEL = "테일즈위버"  # shown in the UI instead of the process name

APP_VERSION = "1.0.2"
REPO_URL = "https://github.com/kimdonggeol/TalesPIP"
LATEST_RELEASE_API = "https://api.github.com/repos/kimdonggeol/TalesPIP/releases/latest"
RELEASES_URL = REPO_URL + "/releases/latest"
DIALOG_CLASS = "#32770"  # standard Win32 dialog (patcher, message boxes)
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
PRESET_COUNT = 4
# The in-game quick slot bar: F1-F6 on the upper row, F7-F12 below.
# Measured off a 1920x1200 client; the bar is a fixed-size UI anchored to the
# bottom-left, so these pixel values hold at any resolution.
SLOT_COLUMNS, SLOT_ROWS = 6, 2
SLOT_COUNT = SLOT_COLUMNS * SLOT_ROWS
SLOT_SIZE = 26          # one cell, px
SLOT_PITCH_X = 27       # cell + separator
SLOT_PITCH_Y = 40       # row + its F-key label strip
SLOT_LEFT = 27          # F1's left edge, from the client's left
SLOT_BOTTOM = 69        # top of the F1 row, measured up from the client's bottom
SLOT_PIP_SCALE = 2      # quick-slot PIPs open at double size
SLOT_PIP_OFFSET_X = 60  # right of the client's centre

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
HOTKEY_ID = 0xA71C
HOTKEY_ID_PROFILE = 0xA71D
HOTKEY_IDS = {"toggle_hotkey": HOTKEY_ID, "profile_hotkey": HOTKEY_ID_PROFILE}
VK_F1 = 0x70
DEFAULT_TOGGLE_HOTKEY = {"mods": MOD_CONTROL, "vk": 0x7B, "text": "Ctrl+F12"}
DEFAULT_PROFILE_HOTKEY = {"mods": MOD_CONTROL, "vk": 0x7A, "text": "Ctrl+F11"}
# A profile is a set of PIPs inside one preset — typically one per character,
# since two characters at the same resolution want different regions shown.
DEFAULT_PROFILE = {"id": "default", "name": "프로필 1"}
DEFAULT_CONFIG = {
    "always_on_top": True,
    "refresh_ms": 100,
    # Presets follow the game's resolution automatically, so the only
    # shortcut worth a global binding is show/hide.
    "toggle_hotkey": dict(DEFAULT_TOGGLE_HOTKEY),
    "profile_hotkey": dict(DEFAULT_PROFILE_HOTKEY),
    # Remembered so the app can silently reattach when the target restarts.
    # A preset is a resolution profile: crop percentages only hold for the
    # client size they were drawn at, so each preset remembers its own.
    "presets": {str(i): {"name": f"프리셋 {i}", "width": None, "height": None,
                          "profiles": [dict(DEFAULT_PROFILE)],
                          "active_profile": DEFAULT_PROFILE["id"]}
                 for i in range(1, PRESET_COUNT + 1)},
    "active_preset": 1,
    # The game paints its cursor into its own frame, so it cannot be cut out.
    # Fading the PIP instead lets the real cursor show through underneath.
    "notifications": True,
    "dim_on_hover": True,
    "hover_opacity": 60,
    "follow_target": True,
    "only_when_active": True,
    # pip x/y are offsets from the target's client origin, not screen coords.
    "check_updates": True,
    "pip_coords": "relative",
    "regions": [],
}
DEFAULT_REGION_OPTS = {"opacity": 100, "click_through": False, "preset": 1,
                        "profile": DEFAULT_PROFILE["id"]}
# Hotkeys shipped as defaults by earlier versions, replaced on load.

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000

_GetWindowLong = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
_SetWindowLong = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
_GetWindowLong.restype = ctypes.c_longlong
_GetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int]
_SetWindowLong.restype = ctypes.c_longlong
_SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

DWM_TNP_RECTDESTINATION = 0x00000001
DWM_TNP_RECTSOURCE = 0x00000002
DWM_TNP_OPACITY = 0x00000004
DWM_TNP_VISIBLE = 0x00000008
DWM_TNP_SOURCECLIENTAREAONLY = 0x00000010


class DWM_THUMBNAIL_PROPERTIES(ctypes.Structure):
    _fields_ = [
        ("dwFlags", wintypes.DWORD),
        ("rcDestination", wintypes.RECT),
        ("rcSource", wintypes.RECT),
        ("opacity", ctypes.c_ubyte),
        ("fVisible", wintypes.BOOL),
        ("fSourceClientAreaOnly", wintypes.BOOL),
    ]


def dwm_register_thumbnail(hwnd_dest, hwnd_src):
    thumb_id = wintypes.HANDLE()
    hr = dwmapi.DwmRegisterThumbnail(wintypes.HWND(hwnd_dest), wintypes.HWND(hwnd_src), ctypes.byref(thumb_id))
    return thumb_id if hr == 0 else None


def dwm_update_thumbnail(thumb_id, dest_rect, src_rect=None, visible=True, opacity=255):
    if not thumb_id:
        return
    props = DWM_THUMBNAIL_PROPERTIES()
    flags = DWM_TNP_RECTDESTINATION | DWM_TNP_VISIBLE | DWM_TNP_OPACITY | DWM_TNP_SOURCECLIENTAREAONLY
    props.rcDestination = wintypes.RECT(*dest_rect)
    props.fVisible = visible
    props.opacity = max(0, min(255, int(opacity)))
    props.fSourceClientAreaOnly = True
    if src_rect:
        flags |= DWM_TNP_RECTSOURCE
        props.rcSource = wintypes.RECT(*src_rect)
    props.dwFlags = flags
    dwmapi.DwmUpdateThumbnailProperties(thumb_id, ctypes.byref(props))


def dwm_unregister_thumbnail(thumb_id):
    if thumb_id:
        try:
            dwmapi.DwmUnregisterThumbnail(thumb_id)
        except Exception:
            pass


def set_click_through(hwnd, enabled):
    ex = _GetWindowLong(wintypes.HWND(hwnd), GWL_EXSTYLE)
    if enabled:
        ex |= WS_EX_TRANSPARENT | WS_EX_LAYERED
    else:
        ex &= ~WS_EX_TRANSPARENT
    _SetWindowLong(wintypes.HWND(hwnd), GWL_EXSTYLE, ctypes.c_longlong(ex))


# Qt key -> Win32 virtual-key for keys whose codes do not already line up.
QT_SPECIAL_VK = {
    Qt.Key.Key_Space: 0x20, Qt.Key.Key_Tab: 0x09, Qt.Key.Key_Backspace: 0x08,
    Qt.Key.Key_Return: 0x0D, Qt.Key.Key_Enter: 0x0D, Qt.Key.Key_Insert: 0x2D,
    Qt.Key.Key_Delete: 0x2E, Qt.Key.Key_Home: 0x24, Qt.Key.Key_End: 0x23,
    Qt.Key.Key_PageUp: 0x21, Qt.Key.Key_PageDown: 0x22, Qt.Key.Key_Left: 0x25,
    Qt.Key.Key_Up: 0x26, Qt.Key.Key_Right: 0x27, Qt.Key.Key_Down: 0x28,
    Qt.Key.Key_Print: 0x2C, Qt.Key.Key_Pause: 0x13,
    Qt.Key.Key_QuoteLeft: 0xC0, Qt.Key.Key_Minus: 0xBD, Qt.Key.Key_Equal: 0xBB,
    Qt.Key.Key_BracketLeft: 0xDB, Qt.Key.Key_BracketRight: 0xDD,
    Qt.Key.Key_Backslash: 0xDC, Qt.Key.Key_Semicolon: 0xBA,
    Qt.Key.Key_Apostrophe: 0xDE, Qt.Key.Key_Comma: 0xBC,
    Qt.Key.Key_Period: 0xBE, Qt.Key.Key_Slash: 0xBF,
}
MODIFIER_KEYS = (Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift,
                  Qt.Key.Key_Meta, Qt.Key.Key_AltGr)


def qt_key_to_vk(key):
    """Win32 virtual-key code for a Qt key, or None if unsupported."""
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return int(key)          # Qt matches VK for A-Z
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return int(key)          # ... and for 0-9
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        return VK_F1 + int(key) - int(Qt.Key.Key_F1)
    return QT_SPECIAL_VK.get(key)


def qt_modifiers_to_mods(modifiers):
    mods = 0
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        mods |= MOD_CONTROL
    if modifiers & Qt.KeyboardModifier.AltModifier:
        mods |= MOD_ALT
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        mods |= MOD_SHIFT
    if modifiers & Qt.KeyboardModifier.MetaModifier:
        mods |= MOD_WIN
    return mods


def hotkey_text(mods, key):
    parts = []
    if mods & MOD_CONTROL:
        parts.append("Ctrl")
    if mods & MOD_ALT:
        parts.append("Alt")
    if mods & MOD_SHIFT:
        parts.append("Shift")
    if mods & MOD_WIN:
        parts.append("Win")
    parts.append(QKeySequence(key).toString() or "?")
    return "+".join(parts)


def normalize_hotkey(value):
    """Accepts the stored dict and returns a valid one, or None when disabled."""
    if not isinstance(value, dict):
        return None
    mods, vk, text = value.get("mods"), value.get("vk"), value.get("text")
    if not isinstance(mods, int) or not isinstance(vk, int) or not mods or not vk:
        return None
    return {"mods": mods, "vk": vk,
            "text": text if isinstance(text, str) and text else "단축키"}


class HotkeyFilter(QAbstractNativeEventFilter):
    """Catches WM_HOTKEY so the shortcut works while another app has focus."""

    def __init__(self, callbacks):
        super().__init__()
        self.callbacks = callbacks
        self._last = None

    def nativeEventFilter(self, event_type, message):
        try:
            if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
                callback = self.callbacks.get(int(msg.wParam))
                if msg.message == WM_HOTKEY and callback:
                    # Qt runs this filter twice per message (dispatcher +
                    # wndproc), which would toggle twice and cancel itself
                    # out. Drop the duplicate, and consume the event.
                    stamp = (msg.time, msg.lParam, msg.wParam)
                    if stamp != self._last:
                        self._last = stamp
                        callback()
                    return True, 0
        except Exception:
            log_exception(dialog=False)
        return False, 0


user32.GetForegroundWindow.restype = wintypes.HWND

def pid_of_window(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def is_minimized(hwnd):
    return bool(user32.IsIconic(wintypes.HWND(hwnd)))


def client_size_of(hwnd):
    rect = wintypes.RECT()
    user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top


DEFAULT_PIP = {"x": 100, "y": 100, "w": 320, "h": 240}


def parse_version(text):
    """'v1.2.3' -> (1, 2, 3); unparsable parts become 0 so a odd tag never
    reads as newer than everything."""
    digits = []
    for part in str(text).lstrip("vV").split(".")[:4]:
        number = "".join(c for c in part if c.isdigit())
        digits.append(int(number) if number else 0)
    return tuple(digits) or (0,)


def fetch_latest_version(timeout=6):
    """Latest release tag on GitHub, or None. Network problems are not worth
    bothering the user about, so failures are silent."""
    try:
        request = urllib.request.Request(
            LATEST_RELEASE_API,
            headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}",
                      "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response).get("tag_name")
    except Exception:
        return None


class UpdateCheck(QObject):
    """Runs the version check off the UI thread; a slow network must never
    hold up startup."""
    finished = pyqtSignal(object)      # latest tag, or None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        self.finished.emit(fetch_latest_version())


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "TalesPIP"


def startup_command():
    """Command Windows should run at logon — the exe when frozen, otherwise
    pythonw (no console window) plus this script."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    launcher = pythonw if os.path.exists(pythonw) else sys.executable
    return f'"{launcher}" "{os.path.abspath(__file__)}"'


def is_startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def set_startup_enabled(enabled):
    """Returns True on success. Writes only under HKEY_CURRENT_USER, so no
    administrator rights are needed."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                             winreg.KEY_SET_VALUE) as key:
            if enabled:
                # Always rewrite: the exe may have been moved since last time.
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, startup_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        log_exception(dialog=False)
        return False


def load_config():
    config = copy.deepcopy(DEFAULT_CONFIG)
    loaded = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                loaded = data
                config.update(data)
        except Exception:
            log_exception(dialog=False)

    # Older configs stored absolute screen coordinates; convert once the target
    # window is known (see PipController.migrate_pip_coords). Inspect the file
    # itself — the merged defaults always carry the new marker.
    config["_needs_pip_migration"] = (
        bool(loaded.get("regions")) and loaded.get("pip_coords") != "relative")
    config["pip_coords"] = "relative"
    # Settings that no longer exist: the target is fixed and auto-detected,
    # preset switching always follows the resolution, and per-preset hotkeys
    # were replaced by a single show/hide binding.
    for obsolete in ("target_process", "target_window_title", "target_window_class",
                      "auto_switch_preset", "preset_hotkeys", "show_cursor_over_pip"):
        config.pop(obsolete, None)

    raw = config.get("regions")
    regions = []
    for region in raw if isinstance(raw, list) else []:
        if not isinstance(region, dict) or not isinstance(region.get("rel"), dict):
            continue
        region.setdefault("id", str(uuid.uuid4()))
        region.setdefault("name", "영역")
        pip = region.get("pip")
        region["pip"] = dict(DEFAULT_PIP) if not isinstance(pip, dict) else {
            key: int(pip.get(key, DEFAULT_PIP[key])) for key in DEFAULT_PIP}
        for key, value in DEFAULT_REGION_OPTS.items():
            region.setdefault(key, copy.deepcopy(value))
        # A region used to be able to sit in several presets; with presets now
        # meaning "resolution profile" it belongs to exactly one.
        legacy = region.pop("presets", None)
        if isinstance(legacy, list) and legacy:
            candidates = [int(p) for p in legacy
                           if str(p).isdigit() and 1 <= int(p) <= PRESET_COUNT]
            if candidates:
                region["preset"] = min(candidates)
        preset = region.get("preset")
        if not (isinstance(preset, int) and 1 <= preset <= PRESET_COUNT):
            region["preset"] = 1
        regions.append(region)
    config["regions"] = regions

    raw_presets = config.get("presets")
    presets = {}
    for i in range(1, PRESET_COUNT + 1):
        entry = (raw_presets or {}).get(str(i)) if isinstance(raw_presets, dict) else None
        entry = entry if isinstance(entry, dict) else {}
        name = entry.get("name")
        width, height = entry.get("width"), entry.get("height")
        profiles, seen = [], set()
        raw_profiles = entry.get("profiles")
        for prof in raw_profiles if isinstance(raw_profiles, list) else []:
            if not isinstance(prof, dict):
                continue
            pid = str(prof.get("id") or "").strip()
            if not pid or pid in seen:
                continue
            seen.add(pid)
            label = prof.get("name")
            profiles.append({
                "id": pid,
                "name": label if isinstance(label, str) and label.strip()
                else f"프로필 {len(profiles) + 1}"})
        # Configs written before profiles existed: whatever the preset already
        # holds becomes its single starting profile.
        if not profiles:
            profiles = [dict(DEFAULT_PROFILE)]
        active_profile = entry.get("active_profile")
        if active_profile not in seen:
            active_profile = profiles[0]["id"]
        presets[str(i)] = {
            "name": name if isinstance(name, str) and name.strip() else f"프리셋 {i}",
            "width": int(width) if isinstance(width, int) and width > 0 else None,
            "height": int(height) if isinstance(height, int) and height > 0 else None,
            "profiles": profiles,
            "active_profile": active_profile,
        }
    config["presets"] = presets

    for region in regions:
        entry = presets[str(region["preset"])]
        if region.get("profile") not in {p["id"] for p in entry["profiles"]}:
            region["profile"] = entry["profiles"][0]["id"]

    active = config.get("active_preset")
    config["active_preset"] = active if isinstance(active, int) and 1 <= active <= PRESET_COUNT else 1

    config["toggle_hotkey"] = normalize_hotkey(config.get("toggle_hotkey"))
    config["profile_hotkey"] = normalize_hotkey(config.get("profile_hotkey"))
    # Always-on-top is not user-configurable; a PIP that can hide behind the
    # game window is useless.
    config["always_on_top"] = True

    # 25 was an earlier default that turned out too faint to read through.
    if config.get("hover_opacity") == 25:
        config["hover_opacity"] = DEFAULT_CONFIG["hover_opacity"]
    return config


def save_config(config):
    """Atomic write so a crash mid-save cannot truncate the config."""
    tmp = CONFIG_PATH + ".tmp"
    payload = {k: v for k, v in config.items() if not k.startswith("_")}
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
    except Exception:
        log_exception(dialog=False)


def get_client_rect_on_screen(hwnd):
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    l, t = pt.x, pt.y
    w, h = rect.right - rect.left, rect.bottom - rect.top
    return (l, t, l + w, t + h)


def get_window_rect(hwnd):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


def get_class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def list_visible_windows():
    results = []

    def callback(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd) or user32.GetParent(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title:
            return True
        l, t, r, b = get_window_rect(hwnd)
        if (r - l) < 50 or (b - t) < 50:
            return True
        pid_out = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_out))
        try:
            pname = psutil.Process(pid_out.value).name()
        except Exception:
            pname = "?"
        results.append((hwnd, title, pname))
        return True

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return results


QSS = """
* { font-family: 'Segoe UI', 'Malgun Gothic', sans-serif; font-size: 13px; }
QDialog, QWidget#Root { background: #16181d; color: #e6e8ee; }
/* Right pane sits visually behind the left: darker ground, divider, no accent. */
QWidget#SidePanel { background: #0f1116; border-left: 1px solid #262b36; }
QScrollArea { background: transparent; border: none; }
QScrollArea#Root > QWidget > QWidget { background: #16181d; }
QScrollArea#SidePanel > QWidget > QWidget { background: #0f1116; }
QLabel#PanelTitle { font-size: 14px; font-weight: 600; color: #aab2c5; }
QLabel#UpdateBadge {
    background: #1d2a44; border: 1px solid #2f4a8f; border-radius: 8px;
    padding: 8px 10px; color: #cfe0ff;
}
QWidget#SidePanel QFrame#Card { background: #171a21; border-color: #242936; }
QLabel { color: #e6e8ee; background: transparent; }
QLabel#Title { font-size: 20px; font-weight: 600; }
QLabel#Caption { color: #8b93a7; font-size: 12px; }
QLabel#SectionTitle { font-size: 13px; font-weight: 600; color: #aab2c5; }
QFrame#Card { background: #1e2128; border: 1px solid #2a2f3a; border-radius: 10px; }
QFrame#Divider { background: #2a2f3a; max-height: 1px; border: none; }
QPushButton {
    background: #272b34; color: #e6e8ee; border: 1px solid #333945;
    border-radius: 8px; padding: 8px 14px;
}
QPushButton:hover { background: #303541; border-color: #3d434f; }
QPushButton:pressed { background: #23262e; }
QPushButton#Primary { background: #4c7dff; border: none; color: #ffffff; font-weight: 600; }
QPushButton#Primary:hover { background: #5d8aff; }
QPushButton#Danger { background: #2a1e22; border-color: #5a2a35; color: #ff8fa3; }
QPushButton#Danger:hover { background: #3a252c; }
QListWidget {
    background: #1a1d23; border: 1px solid #2a2f3a; border-radius: 8px;
    padding: 4px; outline: none;
}
QListWidget::item { padding: 9px 10px; border-radius: 6px; color: #c9cfdd; }
QListWidget::item:selected { background: #2f4a8f; color: #ffffff; }
QListWidget::item:hover { background: #232732; }
QLineEdit, QSpinBox {
    background: #1a1d23; border: 1px solid #2a2f3a; border-radius: 7px;
    padding: 6px 8px; color: #e6e8ee; selection-background-color: #4c7dff;
}
/* Reserve room for the arrows so long values do not run underneath them.
   Only padding: styling the buttons themselves makes Qt stop drawing the
   arrow indicators altogether. */
QSpinBox { padding-right: 26px; }
QLineEdit:focus, QSpinBox:focus { border-color: #4c7dff; }
QCheckBox { spacing: 8px; color: #e6e8ee; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid #3a4150; background: #1a1d23; }
QCheckBox::indicator:checked { background: #4c7dff; border-color: #4c7dff; }
QSlider::groove:horizontal { height: 5px; background: #2a2f3a; border-radius: 3px; }
QSlider::sub-page:horizontal { background: #4c7dff; border-radius: 3px; }
QSlider::handle:horizontal {
    background: #ffffff; width: 16px; height: 16px;
    margin: -6px 0; border-radius: 8px;
}
/* A recessed track behind a lighter, fully rounded handle — without the track
   the handle had nothing to read against on these dark panels. */
QScrollBar:vertical {
    background: #12141a; width: 14px; margin: 2px; border-radius: 7px;
}
QScrollBar::handle:vertical {
    background: #49505f; border-radius: 5px; min-height: 36px;
    margin: 2px; border: 1px solid rgba(120, 130, 150, 0.35);
}
QScrollBar::handle:vertical:hover { background: #5d6577; }
QScrollBar::handle:vertical:pressed { background: #6f778a; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
"""
QSS = QSS.replace("#3d4椒a", "#3d434f")


ICON_JELLY_HI = QColor(150, 196, 255)
ICON_JELLY_LO = QColor(70, 116, 226)
ICON_OUTLINE = QColor(28, 58, 130)
ICON_TEXT = QColor(255, 251, 240)


def _jelly_blob(rect):
    """Squishy silhouette — rounder on top, settling to one side at the bottom."""
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path = QPainterPath(QPointF(x + w * 0.5, y))
    path.cubicTo(QPointF(x + w * 0.95, y), QPointF(x + w, y + h * 0.18),
                  QPointF(x + w, y + h * 0.55))
    path.cubicTo(QPointF(x + w, y + h * 0.88), QPointF(x + w * 0.80, y + h),
                  QPointF(x + w * 0.55, y + h))
    path.cubicTo(QPointF(x + w * 0.34, y + h), QPointF(x + w * 0.14, y + h * 0.94),
                  QPointF(x, y + h * 0.66))
    path.cubicTo(QPointF(x - w * 0.02, y + h * 0.30), QPointF(x + w * 0.12, y),
                  QPointF(x + w * 0.5, y))
    path.closeSubpath()
    return path


def _tw_path(rect):
    font = QFont("Segoe UI", 100)
    font.setWeight(QFont.Weight.Black)
    probe = QPainterPath()
    probe.addText(0, 0, font, "TW")
    box = probe.boundingRect()
    if box.width() <= 0 or box.height() <= 0:
        return probe
    scale = min(rect.width() / box.width(), rect.height() / box.height())
    transform = QTransform()
    transform.translate(rect.center().x(), rect.center().y())
    transform.scale(scale, scale)
    transform.translate(-box.center().x(), -box.center().y())
    return transform.map(probe)


def icon_pixmap(size):
    """A TW jelly bead with a PIP panel tucked into its corner. Drawn in code so
    there is no external asset to ship, and rendered per size for small icons."""
    s = float(size)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    blob = _jelly_blob(QRectF(s * 0.06, s * 0.06, s * 0.78, s * 0.74))
    gradient = QLinearGradient(0, s * 0.06, 0, s * 0.80)
    gradient.setColorAt(0.0, ICON_JELLY_HI)
    gradient.setColorAt(0.55, ICON_JELLY_LO)
    gradient.setColorAt(1.0, QColor(40, 86, 196))
    p.setPen(QPen(ICON_OUTLINE, s * 0.055, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(gradient)
    p.drawPath(blob)

    # Glossy top, clipped to the blob so it reads as a wet surface.
    p.save()
    p.setClipPath(blob)
    shine = QLinearGradient(0, s * 0.06, 0, s * 0.44)
    shine.setColorAt(0.0, QColor(255, 255, 255, 165))
    shine.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(shine)
    p.drawRoundedRect(QRectF(s * 0.06, s * 0.06, s * 0.78, s * 0.36),
                       s * 0.05, s * 0.05)
    p.restore()

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ICON_TEXT)
    p.drawPath(_tw_path(QRectF(s * 0.16, s * 0.28, s * 0.54, s * 0.26)))

    p.setBrush(QColor(255, 255, 255, 210))
    p.drawEllipse(QRectF(s * 0.19, s * 0.15, s * 0.15, s * 0.10))

    # The inset panel overlaps the bead's edge, which is what makes it read as
    # picture-in-picture rather than just a badge.
    p.setPen(QPen(ICON_OUTLINE, s * 0.055, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(ICON_TEXT)
    p.drawRoundedRect(QRectF(s * 0.50, s * 0.54, s * 0.42, s * 0.36),
                       s * 0.09, s * 0.09)
    p.end()
    return pixmap


def app_icon():
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(icon_pixmap(size))
    return icon


def max_pip_size():
    """Cap a PIP just under the screen so it can never swallow the desktop."""
    geom = QApplication.primaryScreen().availableGeometry()
    return max(64, geom.width() - 8), max(64, geom.height() - 8)


def make_card(title=None):
    card = QFrame()
    card.setObjectName("Card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    if title:
        label = QLabel(title)
        label.setObjectName("SectionTitle")
        layout.addWidget(label)
    return card, layout


class Hud(QWidget):
    """Frameless, always-on-top, input-transparent overlay. DWM thumbnails paint
    over a window's own child widgets, so every bit of selection UI has to live
    in a separate top-level window like this one."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                             Qt.WindowType.WindowStaysOnTopHint |
                             Qt.WindowType.Tool |
                             Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def bump(self):
        """Keep above the picker, which raises itself when activated."""
        user32.SetWindowPos(wintypes.HWND(int(self.winId())), wintypes.HWND(-1),
                             0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


class SelectionFrame(Hud):
    """Accent border around the whole capture area: unmistakable 'selecting' state."""

    def paintEvent(self, e):
        painter = QPainter(self)
        rect = self.rect().adjusted(2, 2, -3, -3)
        painter.setPen(QPen(QColor(76, 125, 255), 4))
        painter.drawRect(rect)
        painter.setPen(QPen(QColor(255, 255, 255, 160), 1))
        painter.drawRect(rect.adjusted(2, 2, -2, -2))


class SelectionBox(Hud):
    """The rubber band drawn over the live thumbnail."""

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor(76, 125, 255, 48))
        painter.setPen(QPen(QColor(140, 180, 255), 2))
        painter.drawRect(self.rect().adjusted(1, 1, -2, -2))


class SpawnFlash(Hud):
    """Brief pulse over a newly created PIP so the user sees where it landed.
    Has to be its own window: a DWM thumbnail paints over the PIP's own widgets."""

    DURATION_MS = 2600
    INTERVAL_MS = 30
    PULSES = 3

    def __init__(self, label=""):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.label = label
        self._elapsed = 0
        self._alpha = 1.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self, rect):
        left, top, right, bottom = rect
        if right - left <= 0 or bottom - top <= 0:
            self.close()
            return
        self.show()
        user32.SetWindowPos(wintypes.HWND(int(self.winId())), wintypes.HWND(-1),
                             left, top, right - left, bottom - top,
                             SWP_NOACTIVATE)
        self._timer.start(self.INTERVAL_MS)

    def _tick(self):
        self._elapsed += self.INTERVAL_MS
        t = self._elapsed / self.DURATION_MS
        if t >= 1.0:
            self._timer.stop()
            self.close()
            return
        # Pulse a few times while fading out, so it draws the eye then leaves.
        self._alpha = abs(math.sin(math.pi * self.PULSES * t)) * (1.0 - t)
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        a = max(0.0, min(1.0, self._alpha))
        painter.fillRect(self.rect(), QColor(76, 125, 255, int(70 * a)))
        painter.setPen(QPen(QColor(120, 170, 255, int(255 * a)), 6))
        painter.drawRect(self.rect().adjusted(3, 3, -4, -4))
        if not self.label:
            return
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(self.label) + 22
        height = metrics.height() + 12
        if width > self.width() - 8 or height > self.height() - 8:
            return
        chip = QRect((self.width() - width) // 2, (self.height() - height) // 2,
                      width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(18, 20, 25, int(235 * a)))
        painter.drawRoundedRect(chip, 8, 8)
        painter.setPen(QColor(240, 243, 250, int(255 * a)))
        painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, self.label)


class HudBanner(Hud):
    """Instruction strip naming the current mode."""

    def __init__(self, title, subtitle):
        super().__init__()
        self.title = title
        self.subtitle = subtitle

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        box = self.rect().adjusted(0, 0, -1, -1)
        painter.setBrush(QColor(18, 20, 25, 238))
        painter.setPen(QPen(QColor(76, 125, 255), 2))
        painter.drawRoundedRect(box, 12, 12)

        dot = QRect(box.left() + 16, box.center().y() - 5, 10, 10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 92, 110))
        painter.drawEllipse(dot)

        text_area = box.adjusted(38, 8, -14, -8)
        font = painter.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        painter.setFont(font)
        painter.setPen(QColor(240, 243, 250))
        painter.drawText(text_area, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                          self.title)
        font.setBold(False)
        font.setPointSize(font.pointSize() - 2)
        painter.setFont(font)
        painter.setPen(QColor(150, 160, 180))
        painter.drawText(text_area, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                          self.subtitle)


class RegionPickerWindow(QWidget):
    """Frameless 1:1 mirror laid exactly over the target's client area."""
    finished = pyqtSignal(float, float, float, float)
    closed = pyqtSignal()

    def __init__(self, hwnd, editing=False):
        super().__init__()
        self.hwnd = hwnd
        self.thumb_id = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                             Qt.WindowType.WindowStaysOnTopHint |
                             Qt.WindowType.Tool)
        self.setStyleSheet("background-color:#101216;")
        self.setCursor(Qt.CursorShape.CrossCursor)

        self.origin = None
        self._drag_rect = None
        self._last_rect = None
        self.box = SelectionBox()
        self.frame = SelectionFrame()
        self.banner = HudBanner(
            "영역 수정 중" if editing else "영역 추가 중",
            "드래그해서 범위를 지정하세요   ·   ESC 로 취소")

    def set_prompt(self, title, subtitle):
        self.banner.title = title
        self.banner.subtitle = subtitle
        self.banner.update()

    def _place_native(self):
        """Qt's logical<->native mapping is per-screen and origin-anchored, so
        dividing by devicePixelRatio breaks on multi-monitor / mixed-DPI setups.
        Position natively instead, in real pixels."""
        rect = get_client_rect_on_screen(self.hwnd)
        cl, ct, cr, cb = rect
        if cr - cl <= 0 or cb - ct <= 0:
            return
        self._last_rect = rect
        user32.SetWindowPos(wintypes.HWND(int(self.winId())), None,
                             cl, ct, cr - cl, cb - ct,
                             SWP_NOZORDER | SWP_NOACTIVATE)
        self._update_thumbnail()
        self._place_hud()
        if self._drag_rect is not None:
            self._place_box(self._drag_rect)

    def _track_target(self):
        """Follow the target window if it is moved while picking."""
        try:
            if not user32.IsWindow(self.hwnd):
                self.close()
                return
            if is_minimized(self.hwnd):
                return
            rect = get_client_rect_on_screen(self.hwnd)
            if rect != self._last_rect:
                self._place_native()
                self._raise_hud()
        except Exception:
            log_exception(dialog=False)

    def showEvent(self, e):
        super().showEvent(e)
        if self.thumb_id is None:
            self.thumb_id = dwm_register_thumbnail(int(self.winId()), self.hwnd)
        self._place_native()
        # Qt applies its own geometry right after show(); re-assert afterwards.
        QTimer.singleShot(0, self._place_native)
        self.frame.show()
        self.banner.show()
        self.activateWindow()
        self.setFocus()
        # activateWindow() raises this window above the HUD; put it back on top.
        QTimer.singleShot(0, self._raise_hud)
        QTimer.singleShot(180, self._raise_hud)
        self.track_timer = QTimer(self)
        self.track_timer.timeout.connect(self._track_target)
        self.track_timer.start(50)

    def _raise_hud(self):
        # show() makes Qt re-apply its own logical geometry, undoing the native
        # placement, so re-assert position as well as z-order.
        self._place_hud()
        self.frame.bump()
        self.banner.bump()
        if self.box.isVisible():
            self.box.bump()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_thumbnail()
        self._place_hud()

    def _place_hud(self):
        # Match the picker's native rect exactly; going through Qt's logical
        # coordinates leaves the frame a couple of pixels off under DPI scaling.
        left, top, right, bottom = get_window_rect(int(self.winId()))
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            return
        user32.SetWindowPos(wintypes.HWND(int(self.frame.winId())), None,
                             left, top, width, height,
                             SWP_NOZORDER | SWP_NOACTIVATE)
        banner_w = min(round(460 * (self.devicePixelRatioF() or 1.0)),
                        max(280, width - 80))
        banner_h = round(62 * (self.devicePixelRatioF() or 1.0))
        user32.SetWindowPos(wintypes.HWND(int(self.banner.winId())), None,
                             left + (width - banner_w) // 2, top + 30,
                             banner_w, banner_h,
                             SWP_NOZORDER | SWP_NOACTIVATE)

    def _dest_rect(self):
        w, h = client_size_of(int(self.winId()))
        return (0, 0, max(1, w), max(1, h))

    def _update_thumbnail(self):
        dwm_update_thumbnail(self.thumb_id, self._dest_rect(), visible=True)

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self.origin = e.pos()
        self._show_box(QRect(self.origin, QSize(1, 1)))

    def mouseMoveEvent(self, e):
        if self.origin is not None:
            self._show_box(QRect(self.origin, e.pos()).normalized())

    def _show_box(self, rect):
        self._drag_rect = rect
        self._place_box(rect)

    def _place_box(self, rect):
        top_left = self.mapToGlobal(rect.topLeft())
        self.box.setGeometry(top_left.x(), top_left.y(),
                              max(1, rect.width()), max(1, rect.height()))
        if not self.box.isVisible():
            self.box.show()
            self.box.bump()
        self.box.update()

    def mouseReleaseEvent(self, e):
        if self.origin is None:
            return
        start, end = self.origin, e.pos()
        self.origin = None
        self._drag_rect = None
        self.box.hide()

        # QRect.width() counts both endpoints (+1); use the raw dragged extent
        # so the region matches the pixels the user actually swept.
        w, h = self.width(), self.height()
        x0 = max(0, min(start.x(), end.x()))
        y0 = max(0, min(start.y(), end.y()))
        x1 = min(w, max(start.x(), end.x()))
        y1 = min(h, max(start.y(), end.y()))
        rw, rh = x1 - x0, y1 - y0
        if rw > 5 and rh > 5 and w > 0 and h > 0:
            self._cleanup()
            self.finished.emit(x0 / w, y0 / h, rw / w, rh / h)
            self.close()

    def _cleanup(self):
        timer = getattr(self, "track_timer", None)
        if timer:
            timer.stop()
        dwm_unregister_thumbnail(self.thumb_id)
        self.thumb_id = None
        for hud in (self.box, self.frame, self.banner):
            hud.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self._cleanup()
            self.close()

    def closeEvent(self, e):
        self._cleanup()
        self.closed.emit()
        super().closeEvent(e)


class PipWindow(QWidget):
    add_requested = pyqtSignal()
    edit_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    settings_requested = pyqtSignal()
    click_through_toggled = pyqtSignal(str, bool)

    MARGIN = 6
    MIN_SIDE = 8

    def __init__(self, region, controller):
        super().__init__()
        self.region = region
        self.controller = controller
        self.thumb_id = None
        self._apply_window_flags()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background-color:black; border:1px solid #555;")
        self.setMinimumSize(self.MIN_SIDE, self.MIN_SIDE)
        self.setMaximumSize(*max_pip_size())
        self.setMouseTracking(True)
        pip = region["pip"]
        x, y = controller.pip_screen_pos(region)
        self.setGeometry(x, y, pip["w"], pip["h"])
        self._drag_pos = None
        self._resize_edge = None
        self._hover = False
        self._geom_at_press = self.geometry()

    def _apply_window_flags(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                             Qt.WindowType.Tool |
                             Qt.WindowType.WindowStaysOnTopHint)

    def refresh_window_flags(self):
        visible = self.isVisible()
        self._apply_window_flags()
        if visible:
            self.show()
        # setWindowFlags strips WS_EX_TRANSPARENT, so click-through must be
        # reapplied whether or not the window is currently visible.
        self.apply_options()
        if visible:
            QTimer.singleShot(0, self.rebind_target)

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self.rebind_target)

    def rebind_target(self):
        if self.thumb_id:
            dwm_unregister_thumbnail(self.thumb_id)
            self.thumb_id = None
        target = self.controller.target_hwnd
        if target and user32.IsWindow(target):
            self.thumb_id = dwm_register_thumbnail(int(self.winId()), target)
        self.apply_options()
        self.refresh_thumbnail()

    def apply_stored_geometry(self):
        """Re-derive the screen position from the stored client-relative offset.
        Hidden PIPs do not follow the target, so this must run before showing."""
        pip = self.region["pip"]
        x, y = self.controller.pip_screen_pos(self.region)
        self.setGeometry(x, y, pip["w"], pip["h"])

    def effective_opacity(self):
        opacity = int(self.region.get("opacity", 100))
        if self._hover:
            opacity = min(opacity, int(self.controller.config.get("hover_opacity", 60)))
        return max(5, min(100, opacity))

    def set_hover(self, hovering):
        if hovering == self._hover:
            return
        self._hover = hovering
        self.apply_options()
        self.refresh_thumbnail()

    def apply_options(self):
        self.setWindowOpacity(self.effective_opacity() / 100.0)
        set_click_through(int(self.winId()), bool(self.region.get("click_through", False)))

    def refresh_thumbnail(self):
        target = self.controller.target_hwnd
        if not self.thumb_id or not target or not user32.IsWindow(target):
            return
        cl, ct, cr, cb = get_client_rect_on_screen(target)
        tw, th = cr - cl, cb - ct
        if tw <= 0 or th <= 0:
            return
        rel = self.region["rel"]
        sx = int(rel["x"] * tw)
        sy = int(rel["y"] * th)
        sw = max(1, int(rel["w"] * tw))
        sh = max(1, int(rel["h"] * th))
        cw, ch = client_size_of(int(self.winId()))
        # Fill the whole client area: any inset would shrink the mirrored region
        # so it no longer matches the selection 1:1.
        dwm_update_thumbnail(
            self.thumb_id,
            (0, 0, max(1, cw), max(1, ch)),
            (sx, sy, sx + sw, sy + sh),
            opacity=round(255 * self.effective_opacity() / 100))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.refresh_thumbnail()

    def closeEvent(self, e):
        dwm_unregister_thumbnail(self.thumb_id)
        self.thumb_id = None
        super().closeEvent(e)

    def _edge_at(self, pos):
        # On a tiny PIP a fixed 6px margin would leave no draggable interior.
        m = max(1, min(self.MARGIN, min(self.width(), self.height()) // 4))
        left = pos.x() <= m
        right = pos.x() >= self.width() - m
        top = pos.y() <= m
        bottom = pos.y() >= self.height() - m
        if top and left:
            return "tl"
        if top and right:
            return "tr"
        if bottom and left:
            return "bl"
        if bottom and right:
            return "br"
        if left:
            return "l"
        if right:
            return "r"
        if top:
            return "t"
        if bottom:
            return "b"
        return None

    def _cursor_for_edge(self, edge):
        return {
            "l": Qt.CursorShape.SizeHorCursor,
            "r": Qt.CursorShape.SizeHorCursor,
            "t": Qt.CursorShape.SizeVerCursor,
            "b": Qt.CursorShape.SizeVerCursor,
            "tl": Qt.CursorShape.SizeFDiagCursor,
            "br": Qt.CursorShape.SizeFDiagCursor,
            "tr": Qt.CursorShape.SizeBDiagCursor,
            "bl": Qt.CursorShape.SizeBDiagCursor,
        }.get(edge, Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._geom_at_press = self.geometry()
        edge = self._edge_at(e.position().toPoint())
        if edge:
            self._resize_edge = edge
            self._press_global = e.globalPosition().toPoint()
            self._orig_geom = self.geometry()
        else:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._resize_edge:
            diff = e.globalPosition().toPoint() - self._press_global
            g = QRect(self._orig_geom)
            if "l" in self._resize_edge:
                g.setLeft(g.left() + diff.x())
            if "r" in self._resize_edge:
                g.setRight(g.right() + diff.x())
            if "t" in self._resize_edge:
                g.setTop(g.top() + diff.y())
            if "b" in self._resize_edge:
                g.setBottom(g.bottom() + diff.y())
            if (self.minimumWidth() <= g.width() <= self.maximumWidth()
                    and self.minimumHeight() <= g.height() <= self.maximumHeight()):
                self.setGeometry(g)
        elif self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
        else:
            self.setCursor(self._cursor_for_edge(self._edge_at(e.position().toPoint())))

    def mouseReleaseEvent(self, e):
        moved = self._drag_pos is not None or self._resize_edge is not None
        self._drag_pos = None
        self._resize_edge = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        # Only persist on an actual drag/resize; a right-click that opens the
        # context menu must not rewrite config or reset the settings dialog.
        if moved and self.geometry() != self._geom_at_press:
            self.controller.save_pip_geometry(self.region["id"], self.geometry())

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        act_settings = menu.addAction("설정 열기")
        menu.addSeparator()
        act_add = menu.addAction("영역 추가")
        act_edit = menu.addAction("영역 수정")
        act_del = menu.addAction("영역 삭제")
        menu.addSeparator()
        act_click = menu.addAction("마우스 통과")
        act_click.setCheckable(True)
        act_click.setChecked(bool(self.region.get("click_through", False)))
        chosen = menu.exec(e.globalPos())
        # Emit after the menu's nested event loop has fully unwound: opening a
        # window from inside it leaves the new window unable to show/activate.
        if chosen == act_add:
            QTimer.singleShot(0, self.add_requested.emit)
        elif chosen == act_edit:
            QTimer.singleShot(0, lambda: self.edit_requested.emit(self.region["id"]))
        elif chosen == act_del:
            QTimer.singleShot(0, lambda: self.delete_requested.emit(self.region["id"]))
        elif chosen == act_settings:
            QTimer.singleShot(0, self.settings_requested.emit)
        elif chosen == act_click:
            enabled = act_click.isChecked()
            QTimer.singleShot(
                0, lambda: self.click_through_toggled.emit(self.region["id"], enabled))


class HotkeyEdit(QPushButton):
    """Click, then press a combination. Emits the hotkey dict, or nothing if
    the user cancels with Escape."""

    captured = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.value = None
        self._capturing = False
        self.setAutoDefault(False)
        self.clicked.connect(self._begin)

    def set_value(self, value):
        self.value = value
        self._refresh_text()

    def _refresh_text(self):
        self.setText(self.value["text"] if self.value else "단축키 없음")

    def _begin(self):
        self._capturing = True
        self.setText("조합을 누르세요…  (Esc 취소)")
        self.grabKeyboard()

    def _end(self):
        self._capturing = False
        self.releaseKeyboard()

    def keyPressEvent(self, e):
        if not self._capturing:
            super().keyPressEvent(e)
            return
        key = e.key()
        if key in MODIFIER_KEYS:
            return                        # wait for the non-modifier key
        if key == Qt.Key.Key_Escape:
            self._end()
            self._refresh_text()
            return
        mods = qt_modifiers_to_mods(e.modifiers())
        vk = qt_key_to_vk(key)
        if not mods:
            self.setText("Ctrl / Alt / Shift 와 함께 눌러주세요")
            return
        if vk is None:
            self.setText("지원하지 않는 키입니다")
            return
        self._end()
        self.captured.emit({"mods": mods, "vk": vk, "text": hotkey_text(mods, key)})

    def focusOutEvent(self, e):
        if self._capturing:
            self._end()
            self._refresh_text()
        super().focusOutEvent(e)


class SettingsDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._loading = 0
        self.viewing_preset = controller.active_preset
        self.viewing_profile = controller.active_profile_id(self.viewing_preset)
        self.preview_thumb = None
        self.preview_source = None
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self.update_preview)
        self.setWindowTitle("TalesPIP")
        self.setStyleSheet(QSS)
        self.resize(910, 780)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left = QWidget()
        left.setObjectName("Root")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(18, 18, 12, 18)
        left_layout.setSpacing(12)

        title = QLabel(f"TalesPIP <span style='font-size:12px; color:#7d8698;'>"
                        f"v{APP_VERSION}</span>")
        title.setObjectName("Title")
        left_layout.addWidget(title)

        self.lbl_update = QLabel("")
        self.lbl_update.setObjectName("UpdateBadge")
        self.lbl_update.setWordWrap(True)
        self.lbl_update.setOpenExternalLinks(True)
        self.lbl_update.hide()
        left_layout.addWidget(self.lbl_update)

        target_card, target_layout = make_card("대상 프로그램")
        self.lbl_status = QLabel("-")
        target_layout.addWidget(self.lbl_status)
        left_layout.addWidget(target_card)

        preset_card, preset_layout = make_card("프리셋 (해상도별)")
        self.combo_preset = QComboBox()
        self.combo_preset.currentIndexChanged.connect(self._on_preset_picked)
        preset_layout.addWidget(self.combo_preset)

        self.lbl_preset_res = QLabel("-")
        self.lbl_preset_res.setObjectName("Caption")
        self.lbl_preset_res.setWordWrap(True)
        preset_layout.addWidget(self.lbl_preset_res)

        # Stacked, not side by side: two buttons in the 300px pane clipped
        # their labels ("현재 해상도로 지정" rendered as "재 해상도로 지").
        left_layout.addWidget(preset_card)

        profile_card, profile_layout = make_card("프로필 (캐릭터별)")
        self.combo_profile = QComboBox()
        self.combo_profile.currentIndexChanged.connect(self._on_profile_picked)
        profile_layout.addWidget(self.combo_profile)

        self.edit_profile_name = QLineEdit()
        self.edit_profile_name.setPlaceholderText("프로필 이름")
        self.edit_profile_name.editingFinished.connect(self._commit_profile_name)
        profile_layout.addWidget(self.edit_profile_name)

        profile_row = QHBoxLayout()
        btn_profile_new = QPushButton("새 프로필")
        btn_profile_new.clicked.connect(lambda: self._add_profile(copy_current=False))
        btn_profile_copy = QPushButton("현재 복제")
        btn_profile_copy.clicked.connect(lambda: self._add_profile(copy_current=True))
        self.btn_profile_del = QPushButton("삭제")
        self.btn_profile_del.setObjectName("Danger")
        self.btn_profile_del.clicked.connect(self._delete_profile)
        for button in (btn_profile_new, btn_profile_copy, self.btn_profile_del):
            profile_row.addWidget(button)
        profile_layout.addLayout(profile_row)

        self.lbl_profile_hint = QLabel("")
        self.lbl_profile_hint.setObjectName("Caption")
        self.lbl_profile_hint.setWordWrap(True)
        profile_layout.addWidget(self.lbl_profile_hint)
        left_layout.addWidget(profile_card)

        list_card, list_layout = make_card("이 프로필의 PIP")
        self.list_widget = QListWidget()
        # Five stacked cards squeeze this to a couple of rows otherwise.
        self.list_widget.setMinimumHeight(220)
        self.list_widget.currentItemChanged.connect(lambda *_: self._load_selected())
        list_layout.addWidget(self.list_widget, 1)
        row = QHBoxLayout()
        btn_add = QPushButton("추가")
        btn_add.setObjectName("Primary")
        btn_add.clicked.connect(self._add)
        btn_del = QPushButton("삭제")
        btn_del.setObjectName("Danger")
        btn_del.clicked.connect(self._delete)
        row.addWidget(btn_add)
        row.addWidget(btn_del)
        list_layout.addLayout(row)
        left_layout.addWidget(list_card, 1)

        slot_card, slot_layout = make_card("빠른 추가 (퀵슬롯)")
        self.slot_buttons = {}
        slot_grid = QGridLayout()
        slot_grid.setHorizontalSpacing(6)
        slot_grid.setVerticalSpacing(6)
        for index in range(SLOT_COUNT):
            btn = QPushButton(f"F{index + 1}")
            btn.setAutoDefault(False)
            btn.clicked.connect(lambda _=False, i=index: self._quick_add(i))
            self.slot_buttons[index] = btn
            slot_grid.addWidget(btn, index // SLOT_COLUMNS, index % SLOT_COLUMNS)
        slot_layout.addLayout(slot_grid)

        self.lbl_slots = QLabel("")
        self.lbl_slots.setObjectName("Caption")
        self.lbl_slots.setWordWrap(True)
        slot_layout.addWidget(self.lbl_slots)
        left_layout.addWidget(slot_card)

        # App-wide options live here so they stay reachable with zero regions.
        global_card, global_layout = make_card("전체 설정")
        self.chk_follow = QCheckBox("대상 창을 따라 이동")
        self.chk_follow.toggled.connect(self._commit_follow)
        self.chk_active = QCheckBox("게임이 활성 창일 때만 표시")
        self.chk_active.toggled.connect(self._commit_only_when_active)
        self.chk_startup = QCheckBox("윈도우 시작 시 자동 실행")
        self.chk_startup.toggled.connect(self._commit_startup)
        self.chk_updates = QCheckBox("시작할 때 업데이트 확인")
        self.chk_updates.toggled.connect(self._commit_check_updates)
        self.chk_notify = QCheckBox("트레이 알림 표시")
        self.chk_notify.toggled.connect(self._commit_notifications)
        self.chk_hover = QCheckBox("커서가 올라간 마우스 통과 PIP는 흐리게")
        self.chk_hover.toggled.connect(self._commit_dim_on_hover)
        hover_row = QHBoxLayout()
        self.slider_hover = QSlider(Qt.Orientation.Horizontal)
        self.slider_hover.setRange(5, 100)
        self.slider_hover.valueChanged.connect(self._commit_hover_opacity)
        self.lbl_hover = QLabel("60%")
        self.lbl_hover.setFixedWidth(48)
        hover_row.addWidget(QLabel("흐림 정도"))
        hover_row.addWidget(self.slider_hover, 1)
        hover_row.addWidget(self.lbl_hover)
        refresh_row = QHBoxLayout()
        self.spin_refresh = self._make_spin(50, 2000, self._commit_refresh)
        self.spin_refresh.setSingleStep(50)
        self.spin_refresh.setSuffix(" ms")
        refresh_row.addWidget(QLabel("갱신 주기"))
        refresh_row.addWidget(self.spin_refresh)
        refresh_row.addStretch()
        global_layout.addWidget(self.chk_follow)
        global_layout.addWidget(self.chk_active)
        global_layout.addWidget(self.chk_startup)
        global_layout.addWidget(self.chk_updates)
        global_layout.addWidget(self.chk_notify)
        global_layout.addWidget(self.chk_hover)
        global_layout.addLayout(hover_row)
        global_layout.addLayout(refresh_row)

        left_layout.addWidget(global_card)

        hotkey_card, hotkey_layout = make_card("단축키")
        self.hotkey_edit = HotkeyEdit()
        self.hotkey_edit.captured.connect(self._commit_hotkey)
        hotkey_layout.addWidget(QLabel("PIP 표시 / 숨김"))
        hotkey_layout.addWidget(self.hotkey_edit)
        self.profile_hotkey_edit = HotkeyEdit()
        self.profile_hotkey_edit.captured.connect(
            lambda hk: self._commit_hotkey(hk, "profile_hotkey"))
        hotkey_layout.addWidget(QLabel("다음 프로필로 전환"))
        hotkey_layout.addWidget(self.profile_hotkey_edit)
        btn_clear_hotkey = QPushButton("단축키 모두 해제")
        btn_clear_hotkey.clicked.connect(self._clear_hotkeys)
        hotkey_layout.addWidget(btn_clear_hotkey)
        hint = QLabel("버튼을 누른 뒤 원하는 조합을 입력하세요. 게임 중에도 동작합니다. "
                       "프리셋은 해상도에 따라 자동 전환되고, 프로필은 이 단축키로 바꿉니다.")
        hint.setObjectName("Caption")
        hint.setWordWrap(True)
        hotkey_layout.addWidget(hint)
        self.lbl_preset_state = QLabel("")
        self.lbl_preset_state.setObjectName("Caption")
        hotkey_layout.addWidget(self.lbl_preset_state)
        left_layout.addWidget(hotkey_card)

        # Scrollable so shrinking the window never makes a control unreachable.
        left_scroll = QScrollArea()
        left_scroll.setObjectName("Root")
        left_scroll.setWidget(left)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(392)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(left_scroll)

        right = QWidget()
        right.setObjectName("SidePanel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(10)

        self.lbl_detail_title = QLabel("선택한 PIP 상세")
        self.lbl_detail_title.setObjectName("PanelTitle")
        detail_caption = QLabel("왼쪽에서 고른 PIP 하나에만 적용되는 설정입니다.")
        detail_caption.setObjectName("Caption")
        right_layout.addWidget(self.lbl_detail_title)
        right_layout.addWidget(detail_caption)

        self.stack = QStackedWidget()
        empty = QLabel("왼쪽에서 PIP를 선택하거나 추가하세요.")
        empty.setObjectName("Caption")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(empty)

        # Scrollable: the detail page is taller than most windows.
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setObjectName("SidePanel")
        self.detail_scroll.setWidget(self._build_detail())
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # The preview is a DWM thumbnail painted at fixed window coordinates,
        # so it has to be repositioned whenever the page scrolls.
        self.detail_scroll.verticalScrollBar().valueChanged.connect(
            lambda *_: self.update_preview())
        self.stack.addWidget(self.detail_scroll)
        right_layout.addWidget(self.stack, 1)

        bottom = QHBoxLayout()
        self.lbl_path = QLabel(CONFIG_PATH)
        self.lbl_path.setObjectName("Caption")
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        bottom.addWidget(self.lbl_path, 1)
        bottom.addWidget(btn_close)
        right_layout.addLayout(bottom)

        root.addWidget(right, 1)
        # Otherwise Enter in a text field triggers the first button (프로그램 지정).
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        self.refresh()

    def _build_detail(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        preview_card, preview_layout = make_card("미리보기")
        self.preview_box = QWidget()
        self.preview_box.setMinimumHeight(200)
        self.preview_box.setStyleSheet("background:#0b0d11; border-radius:6px;")
        preview_layout.addWidget(self.preview_box)
        self.lbl_preview = QLabel("")
        self.lbl_preview.setObjectName("Caption")
        preview_layout.addWidget(self.lbl_preview)
        layout.addWidget(preview_card)

        name_card, name_layout = make_card("이름")
        self.edit_name = QLineEdit()
        self.edit_name.editingFinished.connect(self._commit_name)
        name_layout.addWidget(self.edit_name)
        layout.addWidget(name_card)

        area_card, area_layout = make_card("캡처 영역")
        self.lbl_area = QLabel("-")
        self.lbl_area.setObjectName("Caption")
        self.lbl_area.setWordWrap(True)
        area_layout.addWidget(self.lbl_area)

        # Editable source coordinates, in the game's own pixels.
        area_grid = QGridLayout()
        area_grid.setHorizontalSpacing(12)
        area_grid.setVerticalSpacing(8)
        self.spin_src_x = self._make_spin(0, 20000, self._commit_source_rect)
        self.spin_src_y = self._make_spin(0, 20000, self._commit_source_rect)
        self.spin_src_w = self._make_spin(1, 20000, self._commit_source_rect)
        self.spin_src_h = self._make_spin(1, 20000, self._commit_source_rect)
        area_grid.addWidget(QLabel("X"), 0, 0)
        area_grid.addWidget(self.spin_src_x, 0, 1)
        area_grid.addWidget(QLabel("Y"), 0, 2)
        area_grid.addWidget(self.spin_src_y, 0, 3)
        area_grid.addWidget(QLabel("너비"), 1, 0)
        area_grid.addWidget(self.spin_src_w, 1, 1)
        area_grid.addWidget(QLabel("높이"), 1, 2)
        area_grid.addWidget(self.spin_src_h, 1, 3)
        area_layout.addLayout(area_grid)

        btn_edit_area = QPushButton("영역 다시 지정")
        btn_edit_area.clicked.connect(self._edit_area)
        area_layout.addWidget(btn_edit_area)
        layout.addWidget(area_card)

        geom_card, geom_layout = make_card("위치 및 크기")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        vgeom = QApplication.primaryScreen().virtualGeometry()
        lo = min(-2000, vgeom.left() - 2000)
        hi = max(2000, vgeom.right() + 2000, vgeom.bottom() + 2000)
        self.spin_x = self._make_spin(lo, hi, self._commit_geometry)
        self.spin_y = self._make_spin(lo, hi, self._commit_geometry)
        max_w, max_h = max_pip_size()
        self.spin_w = self._make_spin(PipWindow.MIN_SIDE, max_w, self._commit_geometry)
        self.spin_h = self._make_spin(PipWindow.MIN_SIDE, max_h, self._commit_geometry)
        note = QLabel("좌표는 대상 프로그램 화면의 좌측 상단(0,0) 기준입니다.")
        note.setObjectName("Caption")
        note.setWordWrap(True)
        geom_layout.addWidget(note)
        grid.addWidget(QLabel("X"), 0, 0)
        grid.addWidget(self.spin_x, 0, 1)
        grid.addWidget(QLabel("Y"), 0, 2)
        grid.addWidget(self.spin_y, 0, 3)
        grid.addWidget(QLabel("너비"), 1, 0)
        grid.addWidget(self.spin_w, 1, 1)
        grid.addWidget(QLabel("높이"), 1, 2)
        grid.addWidget(self.spin_h, 1, 3)
        geom_layout.addLayout(grid)
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel("배율"))
        for percent in (100, 150, 200, 300):
            btn = QPushButton(f"{percent}%")
            btn.setAutoDefault(False)
            btn.clicked.connect(lambda _=False, p=percent: self._zoom_to(p))
            zoom_row.addWidget(btn)
        geom_layout.addLayout(zoom_row)
        fit_hint = QLabel("100%는 게임 화면에 보이던 크기 그대로입니다.")
        fit_hint.setObjectName("Caption")
        fit_hint.setWordWrap(True)
        geom_layout.addWidget(fit_hint)
        layout.addWidget(geom_card)

        opacity_card, opacity_layout = make_card("반투명")
        opacity_row = QHBoxLayout()
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(10, 100)
        self.slider_opacity.valueChanged.connect(self._commit_opacity)
        self.lbl_opacity = QLabel("100%")
        self.lbl_opacity.setFixedWidth(48)
        opacity_row.addWidget(self.slider_opacity, 1)
        opacity_row.addWidget(self.lbl_opacity)
        opacity_layout.addLayout(opacity_row)
        layout.addWidget(opacity_card)

        behave_card, behave_layout = make_card("동작")
        self.chk_click_through = QCheckBox("마우스 통과 (PIP를 눌러도 아래 프로그램이 눌림)")
        self.chk_click_through.toggled.connect(self._commit_click_through)
        hint = QLabel("마우스 통과를 켜면 이 PIP는 우클릭할 수 없습니다. "
                       "해제는 이 설정 창이나 트레이 아이콘에서 하세요.")
        hint.setObjectName("Caption")
        hint.setWordWrap(True)
        behave_layout.addWidget(self.chk_click_through)
        behave_layout.addWidget(hint)
        layout.addWidget(behave_card)

        layout.addStretch()
        return page

    def _make_spin(self, lo, hi, slot):
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setKeyboardTracking(False)
        spin.valueChanged.connect(slot)
        return spin

    def refresh(self):
        hwnd = self.controller.target_hwnd
        connected = bool(hwnd and user32.IsWindow(hwnd))
        self.lbl_status.setText(f"{TARGET_LABEL} 연결됨" if connected
                                 else f"{TARGET_LABEL} 실행 대기 중")

        self._loading += 1
        try:
            self.chk_follow.setChecked(bool(self.controller.config.get("follow_target", True)))
            self.chk_active.setChecked(bool(self.controller.config.get("only_when_active", True)))
            # The registry is the source of truth, not config.json.
            self.chk_startup.setChecked(is_startup_enabled())
            self.chk_updates.setChecked(bool(self.controller.config.get("check_updates", True)))
            self.chk_notify.setChecked(bool(self.controller.config.get("notifications", True)))
            self.chk_hover.setChecked(bool(self.controller.config.get("dim_on_hover", True)))
            hover = int(self.controller.config.get("hover_opacity", 60))
            self.slider_hover.setValue(hover)
            self.lbl_hover.setText(f"{hover}%")
            self.spin_refresh.setValue(int(self.controller.config.get("refresh_ms", 100)))
            self.hotkey_edit.set_value(self.controller.config.get("toggle_hotkey"))
            self.profile_hotkey_edit.set_value(
                self.controller.config.get("profile_hotkey"))
        finally:
            self._loading -= 1
        self._loading += 1
        try:
            self.combo_preset.clear()
            for preset in range(1, PRESET_COUNT + 1):
                self.combo_preset.addItem(self._preset_caption(preset), preset)
            index = self.combo_preset.findData(self.viewing_preset)
            self.combo_preset.setCurrentIndex(max(0, index))
        finally:
            self._loading -= 1
        if self.controller.latest_version:
            self.show_update(self.controller.latest_version)
        self._load_preset_fields()
        self._reload_profile_combo()
        self.update_preset_state()
        self.reload_region_list()

    def _preset_caption(self, preset):
        name = self.controller.preset_name(preset)
        count = len(self.controller.regions_in_preset(preset))
        mark = " ●" if preset == self.controller.active_preset else ""
        return f"{name} — PIP {count}개{mark}"

    def _load_preset_fields(self):
        preset = self.viewing_preset
        width, height = self.controller.preset_resolution(preset)
        if width and height:
            self.lbl_preset_res.setText(
                f"이 프리셋은 {width}x{height} 기준입니다. "
                "게임이 이 해상도가 되면 자동으로 전환됩니다.")
        else:
            self.lbl_preset_res.setText(
                "해상도가 지정되지 않았습니다. 영역을 처음 추가하면 그때의 "
                "해상도가 기록됩니다.")
        self._sync_slot_card()

    def reload_region_list(self):
        current = self._selected_id()
        self._loading += 1
        try:
            self.list_widget.clear()
            for region in self.controller.regions_in_profile(self.viewing_preset,
                                                              self.viewing_profile):
                item = QListWidgetItem(region.get("name", "영역"))
                item.setData(Qt.ItemDataRole.UserRole, region["id"])
                self.list_widget.addItem(item)
                if region["id"] == current:
                    self.list_widget.setCurrentItem(item)
        finally:
            self._loading -= 1
        if self.list_widget.currentItem() is None and self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        else:
            self._load_selected()

    def on_active_profile_changed(self):
        self.viewing_preset = self.controller.active_preset
        self.viewing_profile = self.controller.active_profile_id(self.viewing_preset)
        self.refresh()

    def on_active_preset_changed(self):
        self.viewing_preset = self.controller.active_preset
        self.viewing_profile = self.controller.active_profile_id(self.viewing_preset)
        self.refresh()

    def _selected_id(self):
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_region(self):
        region_id = self._selected_id()
        return self.controller.find_region(region_id) if region_id else None

    def _load_selected(self):
        region = self._selected_region()
        if not region:
            self.stack.setCurrentIndex(0)
            self._release_preview()
            return
        self.stack.setCurrentIndex(1)
        self._loading += 1
        try:
            pip = region["pip"]
            self.edit_name.setText(region.get("name", ""))
            self.spin_x.setValue(pip["x"])
            self.spin_y.setValue(pip["y"])
            self.spin_w.setValue(pip["w"])
            self.spin_h.setValue(pip["h"])
            opacity = int(region.get("opacity", 100))
            self.slider_opacity.setValue(opacity)
            self.lbl_opacity.setText(f"{opacity}%")
            self.chk_click_through.setChecked(bool(region.get("click_through", False)))
        finally:
            self._loading -= 1
        self._load_area_fields(region)
        self.update_preview()

    def update_preview(self):
        """Live view of the selected region, rendered by DWM straight into this
        dialog. A thumbnail paints over the window's own widgets, so the
        placeholder box below it just reserves the space."""
        try:
            region = self._selected_region()
            target = self.controller.target_hwnd
            if (not self.isVisible() or region is None or not target
                    or not user32.IsWindow(target)):
                self._release_preview()
                if region is not None and not target:
                    self.lbl_preview.setText("게임이 실행 중이 아닙니다.")
                return

            if self.preview_thumb is None or self.preview_source != target:
                self._release_preview()
                self.preview_thumb = dwm_register_thumbnail(int(self.winId()), target)
                self.preview_source = target
            if not self.preview_thumb:
                return

            cw, ch = client_size_of(target)
            if cw <= 0 or ch <= 0:
                return
            rel = region["rel"]
            sx, sy = int(rel["x"] * cw), int(rel["y"] * ch)
            sw = max(1, int(rel["w"] * cw))
            sh = max(1, int(rel["h"] * ch))

            # A thumbnail paints at fixed window coordinates and would spill
            # over other widgets, so drop it while scrolled out of view.
            box_rect = QRect(self.preview_box.mapTo(self, QPoint(0, 0)),
                              self.preview_box.size())
            viewport = self.detail_scroll.viewport()
            visible = QRect(viewport.mapTo(self, QPoint(0, 0)), viewport.size())
            if not visible.contains(box_rect):
                dwm_update_thumbnail(self.preview_thumb, (0, 0, 1, 1), visible=False)
                self.lbl_preview.setText("")
                return

            dpr = self.devicePixelRatioF() or 1.0
            box_w = round(self.preview_box.width() * dpr)
            box_h = round(self.preview_box.height() * dpr)
            box_x = round(box_rect.x() * dpr)
            box_y = round(box_rect.y() * dpr)
            if box_w <= 0 or box_h <= 0:
                return

            # Letterbox so the region keeps its shape instead of being stretched.
            scale = min(box_w / sw, box_h / sh)
            dw, dh = max(1, int(sw * scale)), max(1, int(sh * scale))
            dx = box_x + (box_w - dw) // 2
            dy = box_y + (box_h - dh) // 2
            dwm_update_thumbnail(self.preview_thumb, (dx, dy, dx + dw, dy + dh),
                                  (sx, sy, sx + sw, sy + sh))
            self.lbl_preview.setText(f"원본 크기 {sw} x {sh} px")
        except Exception:
            log_exception(dialog=False)

    def _release_preview(self):
        dwm_unregister_thumbnail(self.preview_thumb)
        self.preview_thumb = None
        self.preview_source = None

    def showEvent(self, e):
        super().showEvent(e)
        self.preview_timer.start(200)
        self.update_preview()

    def hideEvent(self, e):
        self.preview_timer.stop()
        self._release_preview()
        super().hideEvent(e)

    def closeEvent(self, e):
        self.preview_timer.stop()
        self._release_preview()
        super().closeEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.update_preview()

    def sync_geometry(self, region_id):
        """Update only the position/size spinners for the given region."""
        if region_id != self._selected_id():
            return
        region = self.controller.find_region(region_id)
        if not region:
            return
        pip = region["pip"]
        self._loading += 1
        try:
            self.spin_x.setValue(pip["x"])
            self.spin_y.setValue(pip["y"])
            self.spin_w.setValue(pip["w"])
            self.spin_h.setValue(pip["h"])
        finally:
            self._loading -= 1

    def _commit_name(self):
        region = self._selected_region()
        if not region or self._loading:
            return
        name = self.edit_name.text().strip()
        if not name:
            self.edit_name.setText(region.get("name", ""))
            return
        if name != region.get("name"):
            region["name"] = name
            save_config(self.controller.config)
            self.refresh()

    def _commit_geometry(self):
        region = self._selected_region()
        if not region or self._loading:
            return
        region["pip"] = {"x": self.spin_x.value(), "y": self.spin_y.value(),
                          "w": self.spin_w.value(), "h": self.spin_h.value()}
        save_config(self.controller.config)
        window = self.controller.pip_windows.get(region["id"])
        if window:
            x, y = self.controller.pip_screen_pos(region)
            window.setGeometry(x, y, region["pip"]["w"], region["pip"]["h"])

    def _zoom_to(self, percent):
        region = self._selected_region()
        if not region:
            return
        source = self.controller.source_rect_px(region)
        if not source:
            QMessageBox.information(self, "안내",
                                     f"{TARGET_LABEL} 이(가) 실행 중이 아닙니다.")
            return
        dpr = QApplication.primaryScreen().devicePixelRatio() or 1.0
        max_w, max_h = max_pip_size()
        scale = percent / 100.0
        self._loading += 1
        try:
            self.spin_w.setValue(max(PipWindow.MIN_SIDE,
                                      min(max_w, round(source["w"] * scale / dpr))))
            self.spin_h.setValue(max(PipWindow.MIN_SIDE,
                                      min(max_h, round(source["h"] * scale / dpr))))
        finally:
            self._loading -= 1
        self._commit_geometry()

    def _commit_source_rect(self):
        """Typed source coordinates, in the game's pixels."""
        region = self._selected_region()
        if not region or self._loading:
            return
        size = self.controller.target_client_size()
        if not size:
            return
        cw, ch = size
        width = max(1, min(self.spin_src_w.value(), cw))
        height = max(1, min(self.spin_src_h.value(), ch))
        x = max(0, min(self.spin_src_x.value(), cw - width))
        y = max(0, min(self.spin_src_y.value(), ch - height))
        region["rel"] = {"x": x / cw, "y": y / ch, "w": width / cw, "h": height / ch}
        save_config(self.controller.config)
        window = self.controller.pip_windows.get(region["id"])
        if window:
            window.refresh_thumbnail()
        self._load_area_fields(region)
        self.update_preview()

    def _load_area_fields(self, region):
        source = self.controller.source_rect_px(region)
        rel = region["rel"]
        self._loading += 1
        try:
            for spin in (self.spin_src_x, self.spin_src_y,
                          self.spin_src_w, self.spin_src_h):
                spin.setEnabled(source is not None)
            if source:
                self.spin_src_x.setValue(source["x"])
                self.spin_src_y.setValue(source["y"])
                self.spin_src_w.setValue(source["w"])
                self.spin_src_h.setValue(source["h"])
                self.lbl_area.setText(
                    f"게임 화면 좌측 상단(0,0) 기준 픽셀 좌표입니다. "
                    f"화면 비율로는 {rel['x'] * 100:.1f}%, {rel['y'] * 100:.1f}% 지점 · "
                    f"{rel['w'] * 100:.1f}% x {rel['h'] * 100:.1f}%")
            else:
                self.lbl_area.setText(
                    f"{TARGET_LABEL} 실행 중에만 좌표를 볼 수 있습니다. "
                    f"화면 비율 {rel['x'] * 100:.1f}%, {rel['y'] * 100:.1f}% 지점 · "
                    f"{rel['w'] * 100:.1f}% x {rel['h'] * 100:.1f}%")
        finally:
            self._loading -= 1

    def _commit_opacity(self, value):
        self.lbl_opacity.setText(f"{value}%")
        region = self._selected_region()
        if not region or self._loading:
            return
        region["opacity"] = value
        save_config(self.controller.config)
        window = self.controller.pip_windows.get(region["id"])
        if window:
            window.apply_options()

    def _commit_click_through(self, checked):
        region = self._selected_region()
        if not region or self._loading:
            return
        region["click_through"] = checked
        save_config(self.controller.config)
        window = self.controller.pip_windows.get(region["id"])
        if window:
            window.apply_options()

    def _commit_follow(self, checked):
        if self._loading:
            return
        self.controller.config["follow_target"] = checked
        save_config(self.controller.config)

    def _commit_only_when_active(self, checked):
        if self._loading:
            return
        self.controller.config["only_when_active"] = checked
        save_config(self.controller.config)
        self.controller.sync_active_state()

    def _commit_startup(self, checked):
        if self._loading:
            return
        if set_startup_enabled(checked):
            return
        QMessageBox.warning(self, "안내", "시작 프로그램 등록에 실패했습니다.")
        self._loading += 1
        try:
            self.chk_startup.setChecked(not checked)
        finally:
            self._loading -= 1

    def show_update(self, tag):
        self.lbl_update.setText(
            f"새 버전 {tag} 이(가) 나왔습니다 &nbsp;"
            f"<a href='{RELEASES_URL}' style='color:#8fb4ff;'>다운로드</a>")
        self.lbl_update.show()

    def _commit_check_updates(self, checked):
        if self._loading:
            return
        self.controller.config["check_updates"] = checked
        save_config(self.controller.config)

    def _commit_notifications(self, checked):
        if self._loading:
            return
        self.controller.config["notifications"] = checked
        save_config(self.controller.config)

    def _commit_dim_on_hover(self, checked):
        if self._loading:
            return
        self.controller.config["dim_on_hover"] = checked
        save_config(self.controller.config)
        if not checked:
            for w in self.controller.pip_windows.values():
                w.set_hover(False)

    def _commit_hover_opacity(self, value):
        self.lbl_hover.setText(f"{value}%")
        if self._loading:
            return
        self.controller.config["hover_opacity"] = value
        save_config(self.controller.config)
        for w in self.controller.pip_windows.values():
            if w._hover:
                w.apply_options()
                w.refresh_thumbnail()

    def _commit_refresh(self, value):
        if self._loading:
            return
        self.controller.config["refresh_ms"] = value
        save_config(self.controller.config)
        self.controller.track_timer.setInterval(value)

    def _on_preset_picked(self, _index):
        if self._loading:
            return
        preset = self.combo_preset.currentData()
        if preset and preset != self.viewing_preset:
            self.viewing_preset = preset
            self.viewing_profile = self.controller.active_profile_id(preset)
            self._load_preset_fields()
            self._reload_profile_combo()
            self.reload_region_list()

    def _hotkey_editor(self, key):
        return (self.profile_hotkey_edit if key == "profile_hotkey"
                else self.hotkey_edit)

    def _clear_hotkeys(self):
        for key in HOTKEY_IDS:
            self._commit_hotkey(None, key)

    def _commit_hotkey(self, hotkey, key="toggle_hotkey"):
        if self._loading:
            return
        editor = self._hotkey_editor(key)
        previous = self.controller.config.get(key)
        self.controller.config[key] = normalize_hotkey(hotkey)
        if not self.controller.register_hotkey(key):
            self.controller.config[key] = previous
            self.controller.register_hotkey(key)
            editor.set_value(previous)
            QMessageBox.warning(
                self, "단축키 사용 불가",
                f"{hotkey['text']} 은(는) 다른 프로그램이 사용 중입니다.\n"
                "다른 조합을 눌러보세요.")
            return
        save_config(self.controller.config)
        editor.set_value(self.controller.config[key])
        self._reload_profile_combo()
        self.update_preset_state()

    def update_preset_state(self):
        preset = self.controller.active_preset
        name = self.controller.preset_name(preset)
        profile = self.controller.profile_name(preset,
                                                self.controller.active_profile_id(preset))
        state = "숨김" if self.controller.pips_hidden else "표시 중"
        self.lbl_preset_state.setText(
            f"현재 사용 중: {name} / {profile} ({state})")

    def _reload_profile_combo(self):
        controller = self.controller
        profiles = controller.preset_profiles(self.viewing_preset)
        active = controller.active_profile_id(self.viewing_preset)
        if self.viewing_profile not in {p["id"] for p in profiles}:
            self.viewing_profile = active
        self._loading += 1
        try:
            self.combo_profile.clear()
            for prof in profiles:
                count = len(controller.regions_in_profile(self.viewing_preset, prof["id"]))
                mark = " ●" if prof["id"] == active else ""
                self.combo_profile.addItem(f"{prof['name']} — PIP {count}개{mark}",
                                            prof["id"])
            index = self.combo_profile.findData(self.viewing_profile)
            self.combo_profile.setCurrentIndex(max(0, index))
            self.edit_profile_name.setText(
                controller.profile_name(self.viewing_preset, self.viewing_profile))
        finally:
            self._loading -= 1
        self.btn_profile_del.setEnabled(len(profiles) > 1)
        hotkey = controller.config.get("profile_hotkey")
        key_text = hotkey["text"] if hotkey else "단축키 미지정"
        self.lbl_profile_hint.setText(
            "같은 해상도에서 캐릭터마다 PIP 세트를 나눠 쓸 수 있습니다. "
            f"{key_text} 로 다음 프로필로 넘어가며, "
            "마지막으로 쓴 프로필이 기억됩니다.")

    def _on_profile_picked(self, _index):
        if self._loading:
            return
        profile_id = self.combo_profile.currentData()
        if not profile_id or profile_id == self.viewing_profile:
            return
        self.viewing_profile = profile_id
        # Picking inside the preset that is actually in use switches the PIPs
        # too; browsing another preset only changes what the list shows.
        if self.viewing_preset == self.controller.active_preset:
            self.controller.set_active_profile(self.viewing_preset, profile_id)
        else:
            self._reload_profile_combo()
            self.reload_region_list()

    def _commit_profile_name(self):
        if self._loading:
            return
        name = self.edit_profile_name.text().strip()
        for prof in self.controller.preset_profiles(self.viewing_preset):
            if prof["id"] != self.viewing_profile:
                continue
            if not name:
                self.edit_profile_name.setText(prof["name"])
            elif name != prof["name"]:
                prof["name"] = name
                save_config(self.controller.config)
                self.controller.update_tray_tooltip()
                self.refresh()
            return

    def _add_profile(self, copy_current=False):
        source = self.viewing_profile if copy_current else None
        self.viewing_profile = self.controller.add_profile(self.viewing_preset, source)
        self.refresh()
        self.edit_profile_name.setFocus()
        self.edit_profile_name.selectAll()

    def _delete_profile(self):
        profiles = self.controller.preset_profiles(self.viewing_preset)
        if len(profiles) < 2:
            QMessageBox.information(self, "안내",
                                     "프로필은 최소 하나는 남아 있어야 합니다.")
            return
        name = self.controller.profile_name(self.viewing_preset, self.viewing_profile)
        count = len(self.controller.regions_in_profile(self.viewing_preset,
                                                        self.viewing_profile))
        if QMessageBox.question(
                self, "프로필 삭제",
                f"{name} 을(를) 삭제합니다. 이 프로필의 PIP {count}개도 함께 사라집니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.controller.delete_profile(self.viewing_preset, self.viewing_profile)
        self.viewing_profile = self.controller.active_profile_id(self.viewing_preset)
        self.refresh()

    def _quick_add(self, index):
        if not self.controller.quick_add_slot(index, on_done=self.refresh):
            QMessageBox.information(self, "안내",
                                     f"{TARGET_LABEL} 이(가) 실행 중이 아닙니다.")

    def _sync_slot_card(self):
        connected = bool(self.controller.target_hwnd
                          and user32.IsWindow(self.controller.target_hwnd))
        editable = (self.viewing_preset == self.controller.active_preset
                     and self.viewing_profile == self.controller.active_profile_id())
        for btn in self.slot_buttons.values():
            btn.setEnabled(connected and editable)
        if not editable:
            self.lbl_slots.setText("사용 중인 프로필에서만 추가할 수 있습니다.")
        elif connected:
            self.lbl_slots.setText(
                "누르면 그 슬롯 한 칸이 PIP로 바로 추가됩니다.")
        else:
            self.lbl_slots.setText(f"{TARGET_LABEL} 실행 후 사용할 수 있습니다.")

    def _add(self):
        # The picker always adds to whatever is on screen, so browsing another
        # preset or profile has to switch to it first or the new PIP vanishes.
        if (self.viewing_preset != self.controller.active_preset
                or self.viewing_profile != self.controller.active_profile_id()):
            QMessageBox.information(
                self, "안내", "사용 중인 프로필에만 추가할 수 있습니다.")
            return
        self.controller.begin_add_region(on_done=self.refresh)

    def _edit_area(self):
        region_id = self._selected_id()
        if region_id:
            self.controller.begin_edit_region(region_id, on_done=self.refresh)

    def _delete(self):
        region_id = self._selected_id()
        if region_id and self.controller.delete_region(region_id, parent=self):
            self.refresh()


class PipController(QObject):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.target_hwnd = None
        self.pip_windows = {}
        self.picker = None
        self._update_check = None
        self.latest_version = None
        self.target_active = True
        self._flashes = []
        self.settings_dialog = None
        self.was_running = False
        self._busy = False
        self.active_preset = self.config["active_preset"]
        self.pips_hidden = False
        self._hotkey_hwnd = None
        self._hotkey_holder = None
        self._registered_hotkeys = set()
        self._hotkey_filter = HotkeyFilter({HOTKEY_ID: self.toggle_hidden,
                                            HOTKEY_ID_PROFILE: self.cycle_profile})
        QApplication.instance().installNativeEventFilter(self._hotkey_filter)

        self.process_timer = QTimer()
        self.process_timer.timeout.connect(self.check_process)
        self.process_timer.start(1000)

        self.track_timer = QTimer()
        self.track_timer.timeout.connect(self.track_tick)
        self.track_timer.start(int(self.config.get("refresh_ms", 100)))

        # Position-follow needs to be much faster than the thumbnail refresh so
        # dragging the target window does not visibly lag the PIPs.
        self._last_client_rect = None
        self.follow_timer = QTimer()
        self.follow_timer.timeout.connect(self.sync_target_position)
        self.follow_timer.start(50)

        self.cursor_timer = QTimer()
        self.cursor_timer.timeout.connect(self.sync_cursor_hover)
        self.cursor_timer.start(25)

        # Persist moved geometry only once the target stops moving.
        self._save_geom_timer = QTimer()
        self._save_geom_timer.setSingleShot(True)
        self._save_geom_timer.setInterval(600)
        self._save_geom_timer.timeout.connect(self.persist_pip_geometry)

        self.tray = QSystemTrayIcon(app_icon())
        self.tray.setToolTip("TalesPIP")
        menu = QMenu()
        menu.setStyleSheet(QSS)
        act_settings = QAction("설정 열기", menu)
        act_settings.triggered.connect(self.open_settings)
        menu.addAction(act_settings)
        menu.addSeparator()

        self.preset_actions = {}
        for preset in range(1, PRESET_COUNT + 1):
            action = QAction(self.preset_name(preset), menu)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _=False, p=preset: self.activate_preset(p, from_auto=True))
            menu.addAction(action)
            self.preset_actions[preset] = action
        menu.addSeparator()
        self.profile_menu = menu.addMenu("프로필")
        self.profile_actions = []
        menu.addSeparator()
        self.act_hide = QAction("PIP 숨기기", menu)
        self.act_hide.setCheckable(True)
        self.act_hide.triggered.connect(self.toggle_hidden)
        menu.addAction(self.act_hide)
        menu.addSeparator()

        act_add = QAction("영역 추가", menu)
        act_add.triggered.connect(lambda: self.begin_add_region())
        menu.addAction(act_add)
        act_update = QAction("업데이트 확인", menu)
        act_update.triggered.connect(lambda: self.check_for_updates(manual=True))
        menu.addAction(act_update)
        menu.addSeparator()
        act_quit = QAction("종료", menu)
        act_quit.triggered.connect(QApplication.quit)
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        first_run = not os.path.exists(CONFIG_PATH)
        if first_run:
            # Run at logon by default; the checkbox in settings turns it off.
            set_startup_enabled(True)
            # Write the file straight away rather than waiting for the first
            # change, so it is obvious where settings live.
            save_config(self.config)
        elif is_startup_enabled():
            # The stored command is an absolute path, so moving the exe would
            # leave the entry pointing at a file that is no longer there while
            # the checkbox still reads as enabled. Re-point it at this build.
            set_startup_enabled(True)

        # The tray icon is the only always-available entry point; if it is
        # unavailable (or hidden in the overflow area on first run) the user
        # would have no way to reach settings once every PIP is click-through.
        # Only surface the window on genuine first run; otherwise stay in the tray.
        if not QSystemTrayIcon.isSystemTrayAvailable() or first_run:
            QTimer.singleShot(0, self.open_settings)
        QTimer.singleShot(0, self.check_process)
        QTimer.singleShot(2500, self.check_for_updates)
        self.update_tray_tooltip()

        if not self.register_hotkeys():
            self.notify(
                "단축키 등록 실패",
                "등록하지 못한 단축키가 있습니다. 다른 프로그램이 "
                "쓰고 있을 수 있으니 설정에서 다른 조합으로 바꾸세요.",
                QSystemTrayIcon.MessageIcon.Warning, 5000)

    def hotkey_text(self):
        hotkey = self.config.get("toggle_hotkey")
        return hotkey["text"] if hotkey else "없음"

    def register_hotkeys(self):
        """(Re)binds every global hotkey. True when all of them took."""
        return all([self.register_hotkey(key) for key in HOTKEY_IDS])

    def register_hotkey(self, key="toggle_hotkey"):
        """(Re)binds one global hotkey. True when nothing failed."""
        self.unregister_hotkey(key)
        hotkey = self.config.get(key)
        if not hotkey:
            return True
        if self._hotkey_holder is None:
            # A hidden window owns the hotkey; the tray icon has no HWND.
            self._hotkey_holder = QWidget()
            self._hotkey_holder.setWindowFlags(Qt.WindowType.Tool)
            self._hotkey_holder.resize(1, 1)
        self._hotkey_hwnd = int(self._hotkey_holder.winId())
        if user32.RegisterHotKey(wintypes.HWND(self._hotkey_hwnd), HOTKEY_IDS[key],
                                  hotkey["mods"] | MOD_NOREPEAT, hotkey["vk"]):
            self._registered_hotkeys.add(key)
            return True
        return False

    def unregister_hotkey(self, key=None):
        """No key unregisters the lot — that is what shutdown wants."""
        for name in ([key] if key else list(self._registered_hotkeys)):
            if name in self._registered_hotkeys and self._hotkey_hwnd:
                user32.UnregisterHotKey(wintypes.HWND(self._hotkey_hwnd),
                                         HOTKEY_IDS[name])
            self._registered_hotkeys.discard(name)

    def activate_preset(self, preset, from_auto=False):
        """Switch to a preset. Showing/hiding is a separate action now."""
        try:
            self.active_preset = preset
            self.pips_hidden = False
            self.config["active_preset"] = preset
            save_config(self.config)
            self.apply_visibility()
            self.update_tray_tooltip()
            if self.settings_dialog and self.settings_dialog.isVisible():
                self.settings_dialog.on_active_preset_changed()
        except Exception:
            log_exception(dialog=False)

    def check_for_updates(self, manual=False):
        """manual=True comes from the tray menu, so it reports 'up to date' and
        network failures too; the startup check stays silent."""
        if self._update_check is not None:
            return
        if not manual and not self.config.get("check_updates", True):
            return
        checker = UpdateCheck()
        checker.finished.connect(lambda tag: self._on_update_checked(tag, manual))
        self._update_check = checker
        checker.start()

    def _on_update_checked(self, tag, manual):
        self._update_check = None
        if tag and parse_version(tag) > parse_version(APP_VERSION):
            self.latest_version = tag
            if self.settings_dialog:
                self.settings_dialog.show_update(tag)
            self.tray.showMessage(
                "새 버전이 있습니다",
                f"{tag} 이(가) 나왔습니다. 트레이 메뉴 > 업데이트 확인에서 받으세요.",
                QSystemTrayIcon.MessageIcon.Information, 6000)
            if manual:
                self.open_releases_page()
            return
        if not manual:
            return
        if tag is None:
            QMessageBox.information(None, "업데이트 확인",
                                     "업데이트 정보를 가져오지 못했습니다.\n"
                                     "네트워크 상태를 확인해 주세요.")
        else:
            QMessageBox.information(None, "업데이트 확인",
                                     f"최신 버전을 사용 중입니다. (v{APP_VERSION})")

    def open_releases_page(self):
        try:
            webbrowser.open(RELEASES_URL)
        except Exception:
            log_exception(dialog=False)

    def notify(self, title, message, icon=None, msecs=3000):
        if not self.config.get("notifications", True):
            return
        self.tray.showMessage(title, message,
                               icon or QSystemTrayIcon.MessageIcon.Information, msecs)

    def toggle_hidden(self):
        self.pips_hidden = not self.pips_hidden
        self.apply_visibility()
        self.update_tray_tooltip()

    def preset_name(self, preset):
        """Derived, never typed: the resolution is what tells presets apart,
        so a name field would only ask the user to repeat it."""
        width, height = self.preset_resolution(preset)
        if width and height:
            return f"{width}x{height}"
        return f"프리셋 {preset}"

    def preset_resolution(self, preset):
        entry = self.config["presets"][str(preset)]
        return entry["width"], entry["height"]

    def set_preset_resolution(self, preset, width, height):
        entry = self.config["presets"][str(preset)]
        if (entry["width"], entry["height"]) != (width, height):
            entry["width"], entry["height"] = width, height
            save_config(self.config)
            self.update_tray_tooltip()

    def preset_for_resolution(self, width, height):
        for i in range(1, PRESET_COUNT + 1):
            entry = self.config["presets"][str(i)]
            if entry["width"] == width and entry["height"] == height:
                return i
        return None

    def auto_switch_preset(self, width, height):
        """Follow the game's resolution: crop percentages only hold for the
        client size they were drawn at."""
        preset = self.preset_for_resolution(width, height)
        if preset:
            if preset != self.active_preset:
                self.activate_preset(preset, from_auto=True)
                self.notify(
                    "TalesPIP",
                    f"해상도 {width}x{height} 프리셋으로 전환했습니다.",
                    QSystemTrayIcon.MessageIcon.Information, 3000)
            return

        # Unknown resolution: hand the user a blank preset to set up, rather
        # than leaving regions from a different resolution on screen.
        empty = self.first_empty_preset()
        if empty is None:
            return
        self.set_preset_resolution(empty, width, height)
        self.activate_preset(empty, from_auto=True)
        self.notify(
            "TalesPIP",
            f"새 해상도 {width}x{height} 입니다. 비어 있던 프리셋 {empty} "
            "을(를) 이 해상도에 배정했습니다. 영역을 추가하세요.",
            QSystemTrayIcon.MessageIcon.Information, 4000)

    def first_empty_preset(self):
        """A preset with no regions — reusable for a resolution not seen before."""
        for i in range(1, PRESET_COUNT + 1):
            if not self.regions_in_preset(i):
                return i
        return None

    def preset_profiles(self, preset):
        return self.config["presets"][str(preset)]["profiles"]

    def active_profile_id(self, preset=None):
        return self.config["presets"][str(preset or self.active_preset)]["active_profile"]

    def profile_name(self, preset, profile_id):
        for prof in self.preset_profiles(preset):
            if prof["id"] == profile_id:
                return prof["name"]
        return ""

    def regions_in_profile(self, preset, profile_id):
        return [r for r in self.config["regions"]
                 if r.get("preset") == preset and r.get("profile") == profile_id]

    def set_active_profile(self, preset, profile_id, notify=False):
        """The choice is remembered per preset, so switching resolutions and
        coming back lands on the profile that was last in use there."""
        entry = self.config["presets"][str(preset)]
        if profile_id not in {p["id"] for p in entry["profiles"]}:
            return
        changed = entry["active_profile"] != profile_id
        entry["active_profile"] = profile_id
        save_config(self.config)
        if preset == self.active_preset:
            self.apply_visibility()
            self.update_tray_tooltip()
        # An open settings window follows the switch instead of just marking
        # it, so what it shows is always the profile that is on screen.
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.on_active_profile_changed()
        if changed and notify:
            self.notify("TalesPIP",
                         f"프로필 {self.profile_name(preset, profile_id)} 로 전환했습니다.",
                         QSystemTrayIcon.MessageIcon.Information, 1500)

    def cycle_profile(self):
        """Global-hotkey handler: next profile in the active preset, wrapping."""
        try:
            profiles = self.preset_profiles(self.active_preset)
            if len(profiles) < 2:
                return
            ids = [p["id"] for p in profiles]
            try:
                index = ids.index(self.active_profile_id())
            except ValueError:
                index = -1
            self.set_active_profile(self.active_preset,
                                     ids[(index + 1) % len(ids)], notify=True)
        except Exception:
            log_exception(dialog=False)

    def add_profile(self, preset, copy_from=None):
        """A new profile starts empty, or as a copy of another one's PIPs —
        a second character usually wants the same layout as a starting point."""
        entry = self.config["presets"][str(preset)]
        profile_id = str(uuid.uuid4())
        entry["profiles"].append(
            {"id": profile_id, "name": f"프로필 {len(entry['profiles']) + 1}"})
        if copy_from:
            for region in self.regions_in_profile(preset, copy_from):
                clone = copy.deepcopy(region)
                clone["id"] = str(uuid.uuid4())
                clone["profile"] = profile_id
                self.config["regions"].append(clone)
        save_config(self.config)
        for region in self.regions_in_profile(preset, profile_id):
            self.ensure_pip_window(region)
        self.set_active_profile(preset, profile_id)
        return profile_id

    def delete_profile(self, preset, profile_id):
        entry = self.config["presets"][str(preset)]
        if len(entry["profiles"]) < 2:
            return False
        for region in self.regions_in_profile(preset, profile_id):
            self.config["regions"].remove(region)
            window = self.pip_windows.pop(region["id"], None)
            if window:
                window.hide()
                window.deleteLater()
        entry["profiles"] = [p for p in entry["profiles"] if p["id"] != profile_id]
        save_config(self.config)
        if entry["active_profile"] == profile_id:
            self.set_active_profile(preset, entry["profiles"][0]["id"])
        else:
            self.refresh_settings()
        return True

    def target_client_size(self):
        if not self.target_hwnd or not user32.IsWindow(self.target_hwnd):
            return None
        cw, ch = client_size_of(self.target_hwnd)
        return (cw, ch) if cw > 0 and ch > 0 else None

    def source_rect_px(self, region):
        """The captured area in the game's own pixels, or None when detached."""
        size = self.target_client_size()
        if not size:
            return None
        cw, ch = size
        rel = region["rel"]
        return {"x": round(rel["x"] * cw), "y": round(rel["y"] * ch),
                "w": max(1, round(rel["w"] * cw)), "h": max(1, round(rel["h"] * ch))}

    def slot_rel(self, index):
        """One quick slot as client-relative fractions. index 0..11 -> F1..F12,
        laid out as the game shows them: F1-F6 upper row, F7-F12 below."""
        if not self.target_hwnd or not user32.IsWindow(self.target_hwnd):
            return None
        cw, ch = client_size_of(self.target_hwnd)
        if cw <= 0 or ch <= 0:
            return None
        col, row = index % SLOT_COLUMNS, index // SLOT_COLUMNS
        x = SLOT_LEFT + col * SLOT_PITCH_X
        y = ch - SLOT_BOTTOM + row * SLOT_PITCH_Y
        return {"x": x / cw, "y": y / ch, "w": SLOT_SIZE / cw, "h": SLOT_SIZE / ch}

    def slot_pip_geometry(self):
        """Quick-slot PIPs open at double size, centred on the client and
        nudged right, rather than on top of the slot bar they came from."""
        pip = dict(DEFAULT_PIP)
        if not self.target_hwnd or not user32.IsWindow(self.target_hwnd):
            return pip
        cw, ch = client_size_of(self.target_hwnd)
        if cw <= 0 or ch <= 0:
            return pip
        dpr = QApplication.primaryScreen().devicePixelRatio() or 1.0
        side = SLOT_SIZE * SLOT_PIP_SCALE
        left = cw / 2 + SLOT_PIP_OFFSET_X - side / 2
        top = ch / 2 - side / 2
        return {"x": round(left / dpr), "y": round(top / dpr),
                "w": round(side / dpr), "h": round(side / dpr)}

    def quick_add_slot(self, index, on_done=None):
        preset = self.active_preset
        rel = self.slot_rel(index)
        if not rel:
            return None
        name = f"F{index + 1}"
        region = {
            "id": str(uuid.uuid4()),
            "name": name,
            "rel": rel,
            "pip": self.slot_pip_geometry(),
        }
        region.update(copy.deepcopy(DEFAULT_REGION_OPTS))
        region["preset"] = preset
        region["profile"] = self.active_profile_id(preset)
        self.config["regions"].append(region)
        save_config(self.config)
        window = self.ensure_pip_window(region)
        self.refresh_settings()
        if window:
            QTimer.singleShot(60, lambda: self.flash_pip(window, name))
        if on_done:
            on_done()
        return region

    def regions_in_preset(self, preset):
        return [r for r in self.config["regions"] if r.get("preset") == preset]

    def target_is_foreground(self):
        """True when the game — or this app itself — owns the foreground window.
        Our own windows must count, or dragging a PIP would hide it."""
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = pid_of_window(hwnd)
        if pid == os.getpid():
            return True
        if self.target_hwnd and user32.IsWindow(self.target_hwnd):
            return pid == pid_of_window(self.target_hwnd)
        return False

    def sync_active_state(self):
        if not self.config.get("only_when_active", True):
            active = True
        else:
            active = self.target_is_foreground()
        if active != self.target_active:
            self.target_active = active
            self.apply_visibility()

    def region_is_visible(self, region):
        if not self.was_running or not self.target_active or self.pips_hidden:
            return False
        return (region.get("preset") == self.active_preset
                 and region.get("profile") == self.active_profile_id())

    def apply_visibility(self):
        for region in self.config["regions"]:
            w = self.pip_windows.get(region["id"])
            if not w:
                continue
            if self.region_is_visible(region):
                if not w.isVisible():
                    w.apply_stored_geometry()
                    w.show()
                    QTimer.singleShot(0, w.rebind_target)
            elif w.isVisible():
                w.hide()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_settings()

    def open_settings(self):
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self)
        self.settings_dialog.refresh()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def set_click_through(self, region_id, enabled):
        region = self.find_region(region_id)
        if not region:
            return
        region["click_through"] = bool(enabled)
        save_config(self.config)
        window = self.pip_windows.get(region_id)
        if window:
            window.apply_options()
        self.refresh_settings()

    def focus_target(self):
        """Put the game back on top after picking a region. Otherwise the
        settings window resurfaces and covers the PIP that was just created."""
        hwnd = self.target_hwnd
        if hwnd and user32.IsWindow(hwnd) and not is_minimized(hwnd):
            user32.SetForegroundWindow(wintypes.HWND(hwnd))

    def flash_pip(self, window, label=""):
        """Pulse over a PIP so the user can see where it was created."""
        try:
            if not window or not window.isVisible():
                return
            flash = SpawnFlash(label)
            self._flashes.append(flash)
            flash.destroyed.connect(
                lambda *_, f=flash: f in self._flashes and self._flashes.remove(f))
            flash.start(get_window_rect(int(window.winId())))
        except Exception:
            log_exception(dialog=False)

    def refresh_settings(self):
        """Keep an open settings window in sync with changes made elsewhere."""
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.refresh()

    def find_region(self, region_id):
        for region in self.config["regions"]:
            if region["id"] == region_id:
                return region
        return None

    def is_target_running(self):
        # A live window proves it is running; skip the costly full scan.
        if self.target_hwnd and user32.IsWindow(self.target_hwnd):
            return True
        name = TARGET_PROCESS.lower()
        return any(p.info["name"] and p.info["name"].lower() == name
                   for p in psutil.process_iter(["name"]))

    def auto_resolve_target(self):
        """Find the game's main window. The process is fixed, so no prompting:
        skip dialog windows (patcher, message boxes) and take the largest."""
        candidates = []
        for hwnd, _, pname in list_visible_windows():
            if pname.lower() != TARGET_PROCESS.lower():
                continue
            if get_class_name(hwnd) == DIALOG_CLASS:
                continue
            cw, ch = client_size_of(hwnd)
            if cw > 0 and ch > 0:
                candidates.append((cw * ch, hwnd))
        if not candidates:
            return None
        return max(candidates)[1]

    def check_process(self):
        if self._busy:
            return
        try:
            if self.target_hwnd and not user32.IsWindow(self.target_hwnd):
                self.on_target_lost()
            running = self.is_target_running()
            was_running = self.was_running
            self.was_running = running

            if not running:
                if was_running:
                    self.on_process_stopped()
                return

            # Running: (re)attach as soon as the window exists. The window is
            # often created a moment after the process, so this retries each tick.
            if self.target_hwnd is None:
                hwnd = self.auto_resolve_target()
                if hwnd:
                    self.on_target_connected(hwnd)
        except Exception:
            log_exception()

    def on_target_connected(self, hwnd):
        """Target window is available again: restore the last saved state."""
        self.target_hwnd = hwnd
        # Reset the follow baseline so reattaching never shifts the PIPs.
        self._last_client_rect = get_client_rect_on_screen(hwnd)
        self.migrate_pip_coords()
        cw, ch = client_size_of(hwnd)
        if cw > 0 and ch > 0:
            self.auto_switch_preset(cw, ch)
        for region in self.config["regions"]:
            self.ensure_pip_window(region)
        self.apply_visibility()
        self.rebind_all_pip_windows()
        self.update_tray_tooltip()
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.refresh()

    def on_target_lost(self):
        """Target window is gone: hide every PIP at once."""
        if self.target_hwnd is None and not any(
                w.isVisible() for w in self.pip_windows.values()):
            return
        self.target_hwnd = None
        self._last_client_rect = None
        for w in self.pip_windows.values():
            w.hide()
            dwm_unregister_thumbnail(w.thumb_id)
            w.thumb_id = None
        self.update_tray_tooltip()
        self.refresh_settings()

    def on_process_stopped(self):
        self.on_target_lost()

    def rebuild_profile_menu(self):
        """The tray is the way to switch profiles without a hotkey."""
        menu = getattr(self, "profile_menu", None)
        if menu is None:
            return
        menu.clear()
        self.profile_actions = []
        active = self.active_profile_id()
        for prof in self.preset_profiles(self.active_preset):
            action = QAction(prof["name"], menu)
            action.setCheckable(True)
            action.setChecked(prof["id"] == active)
            action.triggered.connect(
                lambda _=False, p=prof["id"]: self.set_active_profile(self.active_preset, p))
            menu.addAction(action)
            self.profile_actions.append(action)
        menu.setEnabled(bool(self.profile_actions))

    def update_tray_tooltip(self):
        for preset, action in getattr(self, "preset_actions", {}).items():
            action.setText(self.preset_name(preset))
            action.setChecked(preset == self.active_preset)
        self.rebuild_profile_menu()
        if hasattr(self, "act_hide"):
            self.act_hide.setChecked(self.pips_hidden)
        if not self.was_running or not self.target_hwnd:
            self.tray.setToolTip(f"TalesPIP — {TARGET_LABEL} 실행 대기 중")
            return
        state = f"TalesPIP — {self.preset_name(self.active_preset)}"
        if len(self.preset_profiles(self.active_preset)) > 1:
            state += f" / {self.profile_name(self.active_preset, self.active_profile_id())}"
        self.tray.setToolTip(state + (" (숨김)" if self.pips_hidden else ""))

    def ensure_pip_window(self, region):
        existing = self.pip_windows.get(region["id"])
        if existing:
            if self.region_is_visible(region):
                existing.apply_stored_geometry()
                existing.show()
                QTimer.singleShot(0, existing.rebind_target)
            return existing
        w = PipWindow(region, self)
        w.add_requested.connect(lambda: self.begin_add_region())
        w.edit_requested.connect(lambda rid: self.begin_edit_region(rid))
        w.delete_requested.connect(lambda rid: self.delete_region(rid))
        w.settings_requested.connect(self.open_settings)
        w.click_through_toggled.connect(self.set_click_through)
        self.pip_windows[region["id"]] = w
        if self.region_is_visible(region):
            w.show()
        return w

    def apply_window_flags(self):
        for w in self.pip_windows.values():
            w.refresh_window_flags()

    def rebind_all_pip_windows(self):
        for w in self.pip_windows.values():
            w.rebind_target()

    def resolve_target_hwnd(self):
        if self.target_hwnd and user32.IsWindow(self.target_hwnd):
            return self.target_hwnd
        hwnd = self.auto_resolve_target()
        if hwnd:
            self.was_running = True
            self.on_target_connected(hwnd)
        return hwnd

    def _open_picker(self, editing=False):
        """Returns a ready picker window, or None with the user already told why."""
        if self.picker is not None and self.picker.isVisible():
            self.picker.raise_()
            self.picker.activateWindow()
            return None
        hwnd = self.resolve_target_hwnd()
        if not hwnd:
            QMessageBox.information(self.settings_dialog, "안내",
                                     f"{TARGET_LABEL} 이(가) 실행 중이 아닙니다.\n"
                                     "게임을 먼저 실행하세요.")
            return None
        if is_minimized(hwnd):
            QMessageBox.information(self.settings_dialog, "안내",
                                     "대상 프로그램이 최소화되어 있습니다.\n창을 복원한 뒤 다시 시도하세요.")
            return None
        cw, ch = client_size_of(hwnd)
        if cw <= 0 or ch <= 0:
            QMessageBox.information(self.settings_dialog, "안내",
                                     "대상 창의 크기를 읽을 수 없습니다.")
            return None
        picker = RegionPickerWindow(hwnd, editing=editing)
        picker.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        picker.closed.connect(self._on_picker_closed)
        self.picker = picker
        return picker

    def _on_picker_closed(self):
        self.picker = None

    def target_origin(self):
        """Target client top-left in Qt logical coordinates."""
        if not self.target_hwnd or not user32.IsWindow(self.target_hwnd):
            return None
        cl, ct, _, _ = get_client_rect_on_screen(self.target_hwnd)
        dpr = QApplication.primaryScreen().devicePixelRatio() or 1.0
        return (round(cl / dpr), round(ct / dpr))

    def pip_screen_pos(self, region):
        """Stored offset -> absolute screen position."""
        pip = region["pip"]
        origin = self.target_origin()
        if origin is None:
            return pip["x"], pip["y"]
        return origin[0] + pip["x"], origin[1] + pip["y"]

    def pip_offset_from(self, geom):
        """Absolute geometry -> offset from the target's client origin."""
        origin = self.target_origin()
        if origin is None:
            return geom.x(), geom.y()
        return geom.x() - origin[0], geom.y() - origin[1]

    def migrate_pip_coords(self):
        """One-time conversion of legacy absolute coordinates to offsets."""
        if not self.config.pop("_needs_pip_migration", False):
            return
        origin = self.target_origin()
        if origin is None:
            self.config["_needs_pip_migration"] = True
            return
        for region in self.config["regions"]:
            region["pip"]["x"] -= origin[0]
            region["pip"]["y"] -= origin[1]
        save_config(self.config)

    def default_pip_for(self, rel_w, rel_h, rel_x=None, rel_y=None):
        """Start the PIP exactly over the region that was dragged: same size,
        and — when the origin is given — the same spot inside the program."""
        pip = dict(DEFAULT_PIP)
        if not self.target_hwnd or not user32.IsWindow(self.target_hwnd):
            return pip
        cw, ch = client_size_of(self.target_hwnd)
        if cw <= 0 or ch <= 0:
            return pip
        # Qt geometry is logical; convert so the physical client ends up equal
        # to the selected region in real pixels.
        dpr = QApplication.primaryScreen().devicePixelRatio() or 1.0
        max_w, max_h = max_pip_size()
        pip["w"] = max(PipWindow.MIN_SIDE, min(max_w, round(rel_w * cw / dpr)))
        pip["h"] = max(PipWindow.MIN_SIDE, min(max_h, round(rel_h * ch / dpr)))
        if rel_x is not None and rel_y is not None:
            # x/y are offsets from the program's client origin.
            pip["x"] = round(rel_x * cw / dpr)
            pip["y"] = round(rel_y * ch / dpr)
        return pip

    def begin_add_region(self, on_done=None):
        picker = self._open_picker()
        if not picker:
            return
        picker.finished.connect(lambda x, y, w, h: self._on_add_selected(x, y, w, h, on_done))
        picker.show()

    def _on_add_selected(self, x, y, w, h, on_done=None):
        preset = self.active_preset
        region = {
            "id": str(uuid.uuid4()),
            "name": f"영역{len(self.regions_in_profile(preset, self.active_profile_id(preset))) + 1}",
            "rel": {"x": x, "y": y, "w": w, "h": h},
            "pip": self.default_pip_for(w, h, x, y),
        }
        region.update(copy.deepcopy(DEFAULT_REGION_OPTS))
        region["preset"] = preset
        region["profile"] = self.active_profile_id(preset)
        # Stamp the preset with the resolution these percentages were drawn at.
        if self.target_hwnd and user32.IsWindow(self.target_hwnd):
            cw, ch = client_size_of(self.target_hwnd)
            if cw > 0 and ch > 0 and self.preset_resolution(preset) == (None, None):
                self.set_preset_resolution(preset, cw, ch)
        self.config["regions"].append(region)
        save_config(self.config)
        window = self.ensure_pip_window(region)
        self.refresh_settings()
        self.focus_target()
        if window:
            QTimer.singleShot(60, lambda: self.flash_pip(window, region.get("name", "")))
        if on_done:
            on_done()

    def begin_edit_region(self, region_id, on_done=None):
        picker = self._open_picker(editing=True)
        if not picker:
            return
        picker.finished.connect(
            lambda x, y, w, h: self._on_edit_selected(region_id, x, y, w, h, on_done))
        picker.show()

    def _on_edit_selected(self, region_id, x, y, w, h, on_done=None):
        region = self.find_region(region_id)
        if region:
            region["rel"] = {"x": x, "y": y, "w": w, "h": h}
            # The freshly dragged region defines the size; keeping the old one
            # would stretch or squash the new content. Position stays put.
            sized = self.default_pip_for(w, h)
            region["pip"]["w"] = sized["w"]
            region["pip"]["h"] = sized["h"]
            save_config(self.config)
            pw = self.pip_windows.get(region_id)
            if pw:
                px, py = self.pip_screen_pos(region)
                pw.setGeometry(px, py, sized["w"], sized["h"])
                pw.refresh_thumbnail()
                self.focus_target()
                QTimer.singleShot(60, lambda: self.flash_pip(pw, region.get("name", "")))
        self.refresh_settings()
        if on_done:
            on_done()

    def delete_region(self, region_id, parent=None):
        self.config["regions"] = [r for r in self.config["regions"] if r["id"] != region_id]
        save_config(self.config)
        w = self.pip_windows.pop(region_id, None)
        if w:
            # May be invoked from inside the widget's own event handler.
            w.hide()
            w.deleteLater()
        self.refresh_settings()
        return True

    def save_pip_geometry(self, region_id, geom):
        region = self.find_region(region_id)
        if region:
            ox, oy = self.pip_offset_from(geom)
            region["pip"] = {"x": ox, "y": oy, "w": geom.width(), "h": geom.height()}
            save_config(self.config)
        # Refresh only the geometry spinners; a full refresh() would clobber
        # whatever the user is currently typing in the dialog.
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.sync_geometry(region_id)

    def sync_target_position(self):
        """Runs every 50ms: notice the window dying, and follow it when it moves."""
        try:
            target = self.target_hwnd
            if target and not user32.IsWindow(target):
                # Far faster than waiting for the 1s psutil process scan.
                self.on_target_lost()
                return
            self.sync_active_state()
            if not target or is_minimized(target):
                return
            rect = get_client_rect_on_screen(target)
            previous = self._last_client_rect
            self._last_client_rect = rect
            if previous is None or rect == previous:
                return

            dx = rect[0] - previous[0]
            dy = rect[1] - previous[1]
            resized = (rect[2] - rect[0]) != (previous[2] - previous[0]) or \
                      (rect[3] - rect[1]) != (previous[3] - previous[1])
            if resized:
                self.auto_switch_preset(rect[2] - rect[0], rect[3] - rect[1])
                follow = self.config.get("follow_target", True)
                for region in self.config["regions"]:
                    w = self.pip_windows.get(region["id"])
                    if not w or not w.isVisible():
                        continue
                    # Recompute from the stored offset rather than shifting by
                    # the delta: a preset switch has already placed the newly
                    # shown PIPs against the new origin, and shifting them
                    # again would double-apply the move.
                    if follow:
                        w.apply_stored_geometry()
                    w.refresh_thumbnail()
            elif (dx or dy) and self.config.get("follow_target", True):
                self.move_pips_by(dx, dy)
                self._save_geom_timer.start()
        except Exception:
            log_exception(dialog=False)

    def click_through_pip_under_cursor(self, point):
        for region in self.config["regions"]:
            if not region.get("click_through"):
                continue
            w = self.pip_windows.get(region["id"])
            if not w or not w.isVisible():
                continue
            left, top, right, bottom = get_window_rect(int(w.winId()))
            if left <= point.x < right and top <= point.y < bottom:
                return w
        return None

    def sync_cursor_hover(self):
        """Dim a click-through PIP while the pointer is over it, so the game —
        and the cursor it renders itself — shows through. The game bakes its
        cursor into the frame, so there is no way to cut the cursor out of it."""
        try:
            hovered = None
            if self.config.get("dim_on_hover", True):
                point = wintypes.POINT()
                if user32.GetCursorPos(ctypes.byref(point)):
                    hovered = self.click_through_pip_under_cursor(point)
            for w in self.pip_windows.values():
                w.set_hover(w is hovered)
        except Exception:
            log_exception(dialog=False)

    def move_pips_by(self, dx, dy):
        """Move natively in physical pixels; Qt's logical coords would drift."""
        for region in self.config["regions"]:
            w = self.pip_windows.get(region["id"])
            if not w or not w.isVisible():
                continue
            hwnd = int(w.winId())
            left, top, right, bottom = get_window_rect(hwnd)
            user32.SetWindowPos(wintypes.HWND(hwnd), None,
                                 left + dx, top + dy, 0, 0,
                                 SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    def persist_pip_geometry(self):
        changed = False
        for region in self.config["regions"]:
            w = self.pip_windows.get(region["id"])
            if not w or not w.isVisible():
                continue
            geom = w.geometry()
            ox, oy = self.pip_offset_from(geom)
            pip = {"x": ox, "y": oy, "w": geom.width(), "h": geom.height()}
            if region["pip"] != pip:
                region["pip"] = pip
                changed = True
        if changed:
            save_config(self.config)
            if self.settings_dialog and self.settings_dialog.isVisible():
                self.settings_dialog.sync_geometry(self.settings_dialog._selected_id())

    def track_tick(self):
        try:
            if not self.target_hwnd or not user32.IsWindow(self.target_hwnd):
                return
            for region in self.config["regions"]:
                w = self.pip_windows.get(region["id"])
                if w and w.isVisible():
                    w.refresh_thumbnail()
        except Exception:
            log_exception()


ERROR_ALREADY_EXISTS = 183


def acquire_single_instance():
    """Two copies would fight over the global hotkeys and double the PIPs.

    The error code must be read through use_last_error: a separate
    GetLastError() call can pick up an unrelated error set in between, which
    made this refuse to start with no other instance running. Session-local
    namespace, since 'Global\\' needs a privilege we cannot count on."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
    handle = kernel32.CreateMutexW(None, False, "Local\\TalesPIPSingleton")
    if not handle:
        return True          # cannot tell; better to run than to refuse
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return handle


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(QSS)
    app.setWindowIcon(app_icon())

    guard = acquire_single_instance()
    if guard is None:
        ctypes.windll.user32.MessageBoxW(
            0, "Tales PIP가 이미 실행 중입니다.\n트레이 아이콘을 확인하세요.",
            "TalesPIP", 0x40)
        sys.exit(0)
    try:
        controller = PipController()
    except Exception:
        log_exception()
        sys.exit(1)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
