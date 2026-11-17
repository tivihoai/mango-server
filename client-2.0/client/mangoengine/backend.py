"""Lớp thao tác hệ điều hành của MangoMCP.

Windows là đích chính. Các nền tảng khác vẫn chạy được các tool không cần
màn hình thật, và trả lỗi PLATFORM_UNSUPPORTED có cấu trúc cho phần còn lại
thay vì sập hoặc báo lỗi mơ hồ.
"""
import platform
import subprocess
import time

from .errors import platform_unsupported

IS_WINDOWS = platform.system() == "Windows"


# ---------------- Chuột và bàn phím (Windows: SendInput qua ctypes) ----------------

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
    KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
    MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
    MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
    MOUSEEVENTF_WHEEL, MOUSEEVENTF_ABSOLUTE = 0x0800, 0x8000
    WHEEL_DELTA = 120

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]

    def _send(inputs):
        arr = (_INPUT * len(inputs))(*inputs)
        user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT))

    def _abs(x, y):
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        return int(x * 65535 / max(sw - 1, 1)), int(y * 65535 / max(sh - 1, 1))

    def mouse_move(x, y):
        ax, ay = _abs(x, y)
        i = _INPUT(type=INPUT_MOUSE)
        i.u.mi = _MOUSEINPUT(ax, ay, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0, None)
        _send([i])

    def mouse_button(button, down):
        flags = {
            ("left", True): MOUSEEVENTF_LEFTDOWN, ("left", False): MOUSEEVENTF_LEFTUP,
            ("right", True): MOUSEEVENTF_RIGHTDOWN, ("right", False): MOUSEEVENTF_RIGHTUP,
            ("middle", True): MOUSEEVENTF_MIDDLEDOWN, ("middle", False): MOUSEEVENTF_MIDDLEUP,
        }[(button, down)]
        i = _INPUT(type=INPUT_MOUSE)
        i.u.mi = _MOUSEINPUT(0, 0, 0, flags, 0, None)
        _send([i])

    def mouse_scroll(clicks):
        i = _INPUT(type=INPUT_MOUSE)
        i.u.mi = _MOUSEINPUT(0, 0, int(clicks) * WHEEL_DELTA, MOUSEEVENTF_WHEEL, 0, None)
        _send([i])

    def type_text(text, interval_seconds=0.005):
        """Gõ Unicode thật bằng KEYEVENTF_UNICODE: gõ được tiếng Việt có dấu.

        Đây là điểm khác biệt cốt lõi so với cách gõ qua pyautogui.write
        vốn hỏng với nhiều ký tự và từng làm tool gõ chữ chết hoàn toàn.
        """
        for ch in text:
            code = ord(ch)
            for flags, scan in ((KEYEVENTF_UNICODE, code),
                                (KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, code)):
                i = _INPUT(type=INPUT_KEYBOARD)
                i.u.ki = _KEYBDINPUT(0, scan, flags, 0, None)
                _send([i])
            if interval_seconds:
                time.sleep(interval_seconds)

    VK = {
        "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10,
        "win": 0x5B, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
        "tab": 0x09, "space": 0x20, "backspace": 0x08, "delete": 0x2E,
        "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
        "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    }
    for n in range(1, 13):
        VK[f"f{n}"] = 0x6F + n

    def _vk_of(key):
        k = key.lower()
        if k in VK:
            return VK[k]
        if len(k) == 1:
            return user32.VkKeyScanW(ord(k)) & 0xFF
        raise platform_unsupported("keyboard_hotkey", f"unknown key: {key}")

    def hotkey(keys):
        vks = [_vk_of(k) for k in keys]
        for vk in vks:
            i = _INPUT(type=INPUT_KEYBOARD)
            i.u.ki = _KEYBDINPUT(vk, 0, 0, 0, None)
            _send([i])
        for vk in reversed(vks):
            i = _INPUT(type=INPUT_KEYBOARD)
            i.u.ki = _KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, None)
            _send([i])

else:
    def _no_input(feature):
        raise platform_unsupported(feature, f"platform={platform.system()}")

    def mouse_move(x, y):
        _no_input("mouse_move")

    def mouse_button(button, down):
        _no_input("mouse_button")

    def mouse_scroll(clicks):
        _no_input("mouse_scroll")

    def type_text(text, interval_seconds=0.005):
        _no_input("keyboard_type")

    def hotkey(keys):
        _no_input("keyboard_hotkey")


def mouse_click(x=None, y=None, button="left", clicks=1):
    if x is not None and y is not None:
        mouse_move(x, y)
        time.sleep(0.03)
    for _ in range(max(1, clicks)):
        mouse_button(button, True)
        time.sleep(0.03)
        mouse_button(button, False)
        time.sleep(0.03)


def mouse_path(points, total_duration_seconds=1.0, button="left"):
    """Kéo chuột qua nhiều điểm trong một lần gọi: nền của thao tác vẽ nét."""
    if len(points) < 2:
        from .errors import invalid_args
        raise invalid_args("points cần ít nhất 2 điểm")
    step = total_duration_seconds / max(len(points) - 1, 1)
    mouse_move(points[0][0], points[0][1])
    mouse_button(button, True)
    try:
        for (x, y) in points[1:]:
            mouse_move(x, y)
            time.sleep(step)
    finally:
        mouse_button(button, False)


# ---------------- Màn hình ----------------

def screenshot_image():
    """Trả về PIL Image của màn hình chính."""
    if IS_WINDOWS:
        from PIL import ImageGrab
        return ImageGrab.grab()
    try:
        from PIL import ImageGrab
        return ImageGrab.grab()
    except Exception as exc:
        raise platform_unsupported("screenshot", str(exc))


def display_info():
    if IS_WINDOWS:
        import ctypes
        user32 = ctypes.windll.user32
        return {
            "primary_width": user32.GetSystemMetrics(0),
            "primary_height": user32.GetSystemMetrics(1),
            "monitor_count": user32.GetSystemMetrics(80),
        }
    return {"primary_width": None, "primary_height": None, "monitor_count": None,
            "note": "display metrics chi tiết chỉ có trên Windows trong bản MVP"}


# ---------------- Cửa sổ ----------------

def list_windows():
    if not IS_WINDOWS:
        raise platform_unsupported("list_windows")
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    results = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                results.append({
                    "title": buf.value,
                    "left": rect.left, "top": rect.top,
                    "width": rect.right - rect.left,
                    "height": rect.bottom - rect.top,
                    "active": hwnd == user32.GetForegroundWindow(),
                    "minimized": bool(user32.IsIconic(hwnd)),
                })
        return True

    user32.EnumWindows(enum_proc, 0)
    return results


def focus_window(title_contains):
    """Đưa cửa sổ lên trước, dùng mẹo AttachThreadInput để vượt qua cơ chế
    khóa foreground của Windows (SetForegroundWindow đơn thuần rất hay bị
    hệ thống từ chối lặng lẽ, khiến các cú bấm sau đó như bị "nuốt")."""
    if not IS_WINDOWS:
        raise platform_unsupported("focus_window")
    for w in list_windows():
        if title_contains.lower() in w["title"].lower():
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = user32.FindWindowW(None, w["title"])
            if hwnd:
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                fg = user32.GetForegroundWindow()
                cur = kernel32.GetCurrentThreadId()
                fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
                attached = False
                try:
                    if fg_thread and fg_thread != cur:
                        attached = bool(user32.AttachThreadInput(fg_thread, cur, True))
                    user32.BringWindowToTop(hwnd)
                    user32.SetForegroundWindow(hwnd)
                    user32.SetActiveWindow(hwnd)
                finally:
                    if attached:
                        user32.AttachThreadInput(fg_thread, cur, False)
            return {"ok": True, "title": w["title"]}
    from .errors import MangoError
    raise MangoError("WINDOW_NOT_FOUND", f"Không thấy cửa sổ chứa '{title_contains}'.",
                     retryable=True)


# ---------------- Clipboard ----------------

def clipboard_get():
    if not IS_WINDOWS:
        raise platform_unsupported("clipboard_get_text")
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) or ""
        finally:
            win32clipboard.CloseClipboard()
    except ImportError:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout


def clipboard_set(text):
    if not IS_WINDOWS:
        raise platform_unsupported("clipboard_set_text")
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    except ImportError:
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard"],
                              input=text, text=True, timeout=10)
        if proc.returncode != 0:
            from .errors import MangoError
            raise MangoError("CLIPBOARD_FAILED", "Không đặt được clipboard.", retryable=True)
    return {"ok": True, "characters": len(text)}


# ---------------- Quản lý cửa sổ nâng cao (bản 0.2.0) ----------------

def _find_hwnd(title_contains):
    """Tìm handle cửa sổ đầu tiên có tiêu đề chứa chuỗi cho trước."""
    import ctypes
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_proc(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if title_contains.lower() in buf.value.lower():
                    found.append((hwnd, buf.value))
                    return False
        return True

    user32.EnumWindows(enum_proc, 0)
    if not found:
        from .errors import MangoError
        raise MangoError("WINDOW_NOT_FOUND", f"Không thấy cửa sổ chứa '{title_contains}'.",
                         retryable=True)
    return found[0]


def close_window(title_contains):
    if not IS_WINDOWS:
        raise platform_unsupported("close_window")
    import ctypes
    user32 = ctypes.windll.user32
    hwnd, title = _find_hwnd(title_contains)
    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    return {"ok": True, "title": title}


def set_window_state(title_contains, state=None, x=None, y=None, width=None, height=None):
    """Đổi trạng thái hoặc vị trí/kích thước cửa sổ theo tiêu đề.

    state thuộc: maximize, minimize, restore, normal.
    """
    if not IS_WINDOWS:
        raise platform_unsupported("set_window_state")
    import ctypes
    user32 = ctypes.windll.user32
    hwnd, title = _find_hwnd(title_contains)
    SW = {"maximize": 3, "minimize": 6, "restore": 9, "normal": 1}
    if state in ("snap_left", "snap_right"):
        # Ghim cửa sổ nửa trái/phải vùng làm việc (học Windows-MCP App resize)
        user32.ShowWindow(hwnd, 9)  # restore trước khi đặt kích thước
        wa = work_area()
        half = wa[2] // 2
        nx = wa[0] if state == "snap_left" else wa[0] + half
        user32.SetWindowPos(hwnd, 0, nx, wa[1], half, wa[3], 0x0004)
        return {"ok": True, "title": title, "state": state, "rect": [nx, wa[1], half, wa[3]]}
    if state:
        if state not in SW:
            from .errors import invalid_args
            raise invalid_args(f"state phải thuộc {sorted(SW)} + snap_left/snap_right")
        user32.ShowWindow(hwnd, SW[state])
    if None not in (x, y, width, height):
        user32.SetWindowPos(hwnd, 0, int(x), int(y), int(width), int(height), 0x0004)
    return {"ok": True, "title": title, "state": state}


def open_path(path):
    """Mở file/thư mục/URL bằng ứng dụng mặc định của Windows (ShellExecute)."""
    if not IS_WINDOWS:
        raise platform_unsupported("open_path")
    import os
    os.startfile(path)  # noqa: S606 - chủ máy chủ động cấp quyền input
    return {"ok": True, "path": path}


# ---------------- Điều khiển Win32 trực tiếp (bản 0.4.0) ----------------

def enum_child_controls(hwnd):
    """Liệt kê mọi control con của một cửa sổ (nút bấm, ô nhập, nhãn...)."""
    import ctypes
    user32 = ctypes.windll.user32
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_proc(child, _lparam):
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(child, cls, 256)
        length = user32.SendMessageW(child, 0x000E, 0, 0)  # WM_GETTEXTLENGTH
        text = ""
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.SendMessageW(child, 0x000D, length + 1, buf)  # WM_GETTEXT
            text = buf.value
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(child, ctypes.byref(rect))
        out.append({"handle": int(child), "class_name": cls.value, "text": text,
                    "rect": [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top],
                    "enabled": bool(user32.IsWindowEnabled(child)),
                    "visible": bool(user32.IsWindowVisible(child))})
        return True

    user32.EnumChildWindows(hwnd, enum_proc, 0)
    return out


def click_control(handle):
    """Bấm một nút bằng tin nhắn BM_CLICK: không cần chuột, không cần tọa độ."""
    import ctypes
    user32 = ctypes.windll.user32
    if not user32.IsWindow(handle):
        from .errors import MangoError
        raise MangoError("INVALID_HANDLE", f"Handle {handle} không còn hợp lệ.", retryable=True)
    user32.PostMessageW(handle, 0x00F5, 0, 0)  # BM_CLICK
    return {"ok": True, "handle": handle}


def set_control_text(handle, text):
    """Đặt chữ thẳng vào một ô nhập bằng WM_SETTEXT: tức thì, không phải gõ từng phím."""
    import ctypes
    user32 = ctypes.windll.user32
    if not user32.IsWindow(handle):
        from .errors import MangoError
        raise MangoError("INVALID_HANDLE", f"Handle {handle} không còn hợp lệ.", retryable=True)
    user32.SendMessageW(handle, 0x000C, 0, ctypes.c_wchar_p(text))  # WM_SETTEXT
    return {"ok": True, "handle": handle}


def get_control_text(handle):
    import ctypes
    user32 = ctypes.windll.user32
    if not user32.IsWindow(handle):
        from .errors import MangoError
        raise MangoError("INVALID_HANDLE", f"Handle {handle} không còn hợp lệ.", retryable=True)
    length = user32.SendMessageW(handle, 0x000E, 0, 0)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.SendMessageW(handle, 0x000D, length + 1, buf)
    return {"handle": handle, "text": buf.value}


def set_display_resolution(width, height):
    """Đổi độ phân giải màn hình chính bằng ChangeDisplaySettingsW.

    Ghim độ phân giải trước khi thao tác theo tọa độ giúp giao diện không
    "trôi" giữa chừng như sự cố 1024x599 -> 1164x608 ngày 24/10/2026.
    """
    import ctypes
    from ctypes import wintypes

    class DEVMODE(ctypes.Structure):
        _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
                    ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD),
                    ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
                    ("dmPosition", wintypes.POINTL), ("dmDisplayOrientation", wintypes.DWORD),
                    ("dmDisplayFixedOutput", wintypes.DWORD), ("dmColor", ctypes.c_short),
                    ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
                    ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short),
                    ("dmFormName", wintypes.WCHAR * 32), ("dmLogPixels", wintypes.WORD),
                    ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
                    ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                    ("dmDisplayFrequency", wintypes.DWORD)]

    user32 = ctypes.windll.user32
    dm = DEVMODE()
    dm.dmSize = ctypes.sizeof(DEVMODE)
    if not user32.EnumDisplaySettingsW(None, -1, ctypes.byref(dm)):  # ENUM_CURRENT_SETTINGS
        from .errors import MangoError
        raise MangoError("DISPLAY_ERROR", "Không đọc được cấu hình màn hình hiện tại.")
    previous = [int(dm.dmPelsWidth), int(dm.dmPelsHeight)]
    dm.dmPelsWidth, dm.dmPelsHeight = int(width), int(height)
    dm.dmFields = 0x00080000 | 0x00100000  # DM_PELSWIDTH | DM_PELSHEIGHT
    test = user32.ChangeDisplaySettingsW(ctypes.byref(dm), 0x00000002)  # CDS_TEST
    if test != 0:
        from .errors import MangoError
        raise MangoError("DISPLAY_ERROR", f"Độ phân giải {width}x{height} không được hỗ trợ (mã {test}).")
    result = user32.ChangeDisplaySettingsW(ctypes.byref(dm), 0)
    if result != 0:
        from .errors import MangoError
        raise MangoError("DISPLAY_ERROR", f"Đổi độ phân giải thất bại (mã {result}).")
    import time as _t
    _t.sleep(0.7)
    now = screenshot_size()
    return {"ok": True, "previous": previous, "current": [now[0], now[1]]}


def screenshot_size():
    img = screenshot_image()
    return img.size


# ---------------- OCR bằng engine có sẵn của Windows (bản 0.5.0) ----------------
# Học từ sshh12/windows-computer-use-mcp: Windows.Media.Ocr qua PowerShell/WinRT,
# không cần cài thêm bất kỳ thư viện OCR nào.

_OCR_PS = r"""
$ImagePath = $env:MANGO_OCR_IMAGE
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$winRtExt = [System.AppDomain]::CurrentDomain.GetAssemblies() |
    ForEach-Object { $_.GetType('System.WindowsRuntimeSystemExtensions') } |
    Where-Object { $_ } | Select-Object -First 1
$asTaskGeneric = ($winRtExt.GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]
function Await($op, $resultType) {
    $task = $asTaskGeneric.MakeGenericMethod($resultType).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    return $task.Result
}
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime] | Out-Null
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { [Console]::Error.WriteLine('OCR engine unavailable'); exit 2 }
try {
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
} catch {
    $converted = [Windows.Graphics.Imaging.SoftwareBitmap]::Convert($bitmap, [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8)
    $result = Await ($engine.RecognizeAsync($converted)) ([Windows.Media.Ocr.OcrResult])
}
$words = @()
foreach ($line in $result.Lines) {
    foreach ($word in $line.Words) {
        $r = $word.BoundingRect
        $words += [PSCustomObject]@{ t = $word.Text; x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height }
    }
}
[Console]::Out.Write(($words | ConvertTo-Json -Compress))
"""


def ocr_image(image, offset_x: int = 0, offset_y: int = 0, timeout: float = 60.0):
    """OCR một ảnh PIL, trả danh sách từ kèm khung tọa độ (đã cộng offset)."""
    import json
    import os
    import subprocess
    import tempfile

    if not IS_WINDOWS:
        raise platform_unsupported("ocr_image")
    fd, path = tempfile.mkstemp(suffix=".png", prefix="mangomcp_ocr_")
    os.close(fd)
    try:
        image.save(path)
        env = dict(os.environ, MANGO_OCR_IMAGE=path)
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _OCR_PS],
            capture_output=True, text=True, timeout=timeout, env=env,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        if proc.returncode != 0:
            from .errors import MangoError
            raise MangoError("OCR_FAILED", "OCR của Windows chạy thất bại.",
                             detail=(proc.stderr or "")[:300], retryable=True)
        raw = (proc.stdout or "").strip()
        words = json.loads(raw) if raw else []
        if isinstance(words, dict):
            words = [words]
        for w in words:
            w["x"] += offset_x
            w["y"] += offset_y
            w["center"] = [w["x"] + w["w"] // 2, w["y"] + w["h"] // 2]
        return words
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------- Tiến trình, PowerShell, Registry (bản 0.5.0) ----------------
# Học từ CursorTouch Windows-MCP (PowerShell là giao diện hệ thống chính,
# Process và Registry là tool riêng).

def list_processes(name_filter: str = None, limit: int = 50):
    import csv
    import io
    import subprocess

    if not IS_WINDOWS:
        raise platform_unsupported("list_processes")
    proc = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                          text=True, timeout=30, creationflags=0x08000000)
    rows = []
    for row in csv.reader(io.StringIO(proc.stdout)):
        if len(row) < 5:
            continue
        name, pid, mem = row[0], row[1], row[4]
        if name_filter and name_filter.lower() not in name.lower():
            continue
        try:
            pid_i = int(pid)
        except ValueError:
            continue
        rows.append({"name": name, "pid": pid_i, "memory": mem})
        if len(rows) >= limit:
            break
    return {"processes": rows, "count": len(rows)}


def kill_process(pid: int = None, name: str = None):
    import subprocess

    if not IS_WINDOWS:
        raise platform_unsupported("kill_process")
    args = ["taskkill", "/F"]
    if pid:
        args += ["/PID", str(int(pid))]
    elif name:
        args += ["/IM", name]
    else:
        from .errors import MangoError
        raise MangoError("INVALID_ARGUMENT", "Cần pid hoặc name để kết thúc tiến trình.")
    proc = subprocess.run(args, capture_output=True, text=True, timeout=30,
                          creationflags=0x08000000)
    if proc.returncode != 0:
        from .errors import MangoError
        raise MangoError("KILL_FAILED", "taskkill thất bại.",
                         detail=(proc.stderr or proc.stdout or "")[:300], retryable=True)
    return {"ok": True, "output": (proc.stdout or "").strip()}


def run_powershell(command: str, timeout: float = 60.0):
    import subprocess

    if not IS_WINDOWS:
        raise platform_unsupported("run_powershell")
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=timeout, creationflags=0x08000000)
    return {"stdout": (proc.stdout or "")[:8000], "stderr": (proc.stderr or "")[:2000],
            "exit_code": proc.returncode}


_REG_ROOTS = {}


def _reg_root(prefix: str):
    import winreg

    global _REG_ROOTS
    if not _REG_ROOTS:
        _REG_ROOTS = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
                      "HKCU": winreg.HKEY_CURRENT_USER, "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
                      "HKCR": winreg.HKEY_CLASSES_ROOT, "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
                      "HKU": winreg.HKEY_USERS, "HKEY_USERS": winreg.HKEY_USERS}
    return _REG_ROOTS[prefix.upper()]


_REG_TYPES = {}


def _reg_type(name: str):
    import winreg

    global _REG_TYPES
    if not _REG_TYPES:
        _REG_TYPES = {"SZ": winreg.REG_SZ, "EXPAND_SZ": winreg.REG_EXPAND_SZ,
                      "MULTI_SZ": winreg.REG_MULTI_SZ, "DWORD": winreg.REG_DWORD,
                      "QWORD": winreg.REG_QWORD, "BINARY": winreg.REG_BINARY}
    return _REG_TYPES[name.upper()]


def _split_reg_path(path: str):
    parts = path.replace("/", "\\").split("\\")
    return _reg_root(parts[0]), "\\".join(parts[1:])


def registry_get(path: str, name: str = None):
    import winreg

    if not IS_WINDOWS:
        raise platform_unsupported("registry_get")
    root, sub = _split_reg_path(path)
    try:
        key = winreg.OpenKey(root, sub, 0, winreg.KEY_READ)
    except OSError as exc:
        from .errors import MangoError
        raise MangoError("REGISTRY_NOT_FOUND", f"Không mở được khóa registry '{path}'.",
                         detail=str(exc), retryable=False)
    with key:
        if name is not None:
            try:
                value, _t = winreg.QueryValueEx(key, name)
            except OSError as exc:
                from .errors import MangoError
                raise MangoError("REGISTRY_NOT_FOUND", f"Không có giá trị '{name}' tại '{path}'.",
                                 detail=str(exc), retryable=False)
            return {"path": path, "name": name, "value": value}
        values, subkeys = {}, []
        i = 0
        while True:
            try:
                vname, vdata, _t = winreg.EnumValue(key, i)
                values[vname] = vdata
                i += 1
            except OSError:
                break
        i = 0
        while True:
            try:
                subkeys.append(winreg.EnumKey(key, i))
                i += 1
            except OSError:
                break
        return {"path": path, "values": values, "subkeys": subkeys}


def registry_set(path: str, name: str, value, reg_type: str = "SZ"):
    import winreg

    if not IS_WINDOWS:
        raise platform_unsupported("registry_set")
    root, sub = _split_reg_path(path)
    rtype = _reg_type(reg_type)
    if reg_type.upper() in ("DWORD", "QWORD"):
        value = int(value)
    with winreg.CreateKeyEx(root, sub, 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, name, 0, rtype, value)
    return {"ok": True, "path": path, "name": name, "value": value, "type": reg_type.upper()}


def work_area():
    """Vùng làm việc của màn hình chính (trừ taskbar) để ghim cửa sổ snap."""
    import ctypes
    from ctypes import wintypes

    if not IS_WINDOWS:
        raise platform_unsupported("work_area")
    rect = wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
    return [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top]
