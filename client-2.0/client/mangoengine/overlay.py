"""Lớp phủ hiển thị trên màn hình (overlay) của MangoMCP.

Mục đích, học theo cách ChatGPT thông báo khi điều khiển máy tính:
- Một "viên trạng thái" luôn nổi trên màn hình cho biết MangoMCP đang chạy
  (đây cũng là cách chủ máy nhìn thấy app, giống app MangoBot cũ).
- Khi bot đang thao tác: viền xanh lá chớp quanh toàn màn hình và banner
  "BOT ĐANG SỬ DỤNG MÁY — XIN ĐỪNG THAO TÁC", để người ngồi trước máy
  không đụng vào chuột/phím giữa chừng.

Phần hiển thị do ứng dụng bạn đồng hành MangoOverlay.exe đảm nhiệm
(WinForms, thư mục overlay/ trong mã nguồn). Module này chỉ:
- khởi động ứng dụng bạn đồng hành nếu chưa chạy,
- ghi trạng thái ra file JSON mà ứng dụng đó đọc mỗi 200 ms,
- nhận "nhịp hoạt động" từ các tool thao tác để tự bật/tắt trạng thái bận.

Mọi lỗi của overlay đều bị nuốt: lớp hiển thị không bao giờ được phép
làm hỏng tool chính.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from . import backend

_lock = threading.Lock()
_state = {"busy_until": 0, "message": "", "toast": "", "toast_until": 0}
# Khi máy đang khóa (0.10.0), màn hình local chỉ được hiện giao diện
# nhập pass mở khóa — overlay bận/viền/thông báo không được vẽ đè lên
# cửa sổ khóa. LockController bật/tắt cờ này khi khóa/mở.
_suppressed = False


def set_suppressed(suppressed: bool):
    """Bật/tắt chế độ nén overlay khi khóa máy. Nén thì pulse/set_busy/
    notify không vẽ gì thêm, và trạng thái bận cũ được xóa."""
    global _suppressed
    _suppressed = bool(suppressed)
    if _suppressed:
        with _lock:
            _state["busy_until"] = 0
            _state["message"] = ""
            _state["toast"] = ""
            _state["toast_until"] = 0
        _write(force=True)


def is_suppressed():
    return _suppressed
_state_path: Path | None = None
_exe_path: Path | None = None
_started = False
_last_write = 0.0


def _enabled() -> bool:
    return backend.IS_WINDOWS and os.environ.get("MANGO_MCP_OVERLAY", "1") != "0"


def start(config) -> dict:
    """Khởi động ứng dụng bạn đồng hành. Gọi một lần khi server bật."""
    global _state_path, _exe_path, _started
    if not _enabled():
        return {"enabled": False, "reason": "not_windows_or_disabled"}
    try:
        app_dir = Path(config.base_dir).resolve()
    except Exception:
        app_dir = Path.cwd()
    _state_path = app_dir / "overlay_state.json"
    _exe_path = app_dir / "MangoOverlay.exe"
    _write(force=True)
    running = _is_running()
    if not running and _exe_path.exists():
        try:
            subprocess.Popen(
                [str(_exe_path), str(_state_path)],
                cwd=str(app_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            running = True
        except Exception:
            running = False
    _started = True
    return {"enabled": True, "running": running, "exe": str(_exe_path)}


def _is_running() -> bool:
    try:
        import psutil

        return any(p.name().lower() == "mangooverlay.exe" for p in psutil.process_iter())
    except Exception:
        return False


def _write(force: bool = False) -> None:
    global _last_write
    if _state_path is None:
        return
    now = time.time()
    if not force and now - _last_write < 0.4:
        return
    _last_write = now
    try:
        tmp = _state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(_state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _state_path)
    except Exception:
        pass


def pulse(seconds: float = 3.0) -> None:
    """Đánh dấu bot đang hoạt động: overlay bận sáng thêm vài giây."""
    if _suppressed:
        return
    if not _started:
        return
    try:
        with _lock:
            new_until = time.time() + seconds
            if new_until > _state["busy_until"]:
                _state["busy_until"] = int(new_until)
                _write(force=True)
    except Exception:
        pass


def set_busy(active: bool, message: str = "") -> dict:
    """Bật/tắt trạng thái bận thủ công (giữ tới khi tắt, không tự hết hạn)."""
    if _suppressed and active:
        return {"ok": False, "reason": "lock_suppressed"}
    if not _started:
        start_info = {"enabled": _enabled(), "running": False}
        return {"ok": False, "overlay": start_info}
    with _lock:
        _state["busy_until"] = int(time.time()) + 3600 if active else 0
        if message:
            _state["message"] = message
        elif not active:
            _state["message"] = ""
        _write(force=True)
    return {"ok": True, "busy": active}


def notify(text: str, seconds: int = 5) -> dict:
    """Hiện một thông báo ngắn ở cuối màn hình."""
    if _suppressed:
        return {"ok": False, "reason": "lock_suppressed"}
    if not _started:
        return {"ok": False, "reason": "overlay_not_started"}
    with _lock:
        _state["toast"] = text
        _state["toast_until"] = int(time.time()) + max(1, seconds)
        _write(force=True)
    return {"ok": True, "seconds": seconds}


def status() -> dict:
    return {
        "enabled": _enabled(),
        "started": _started,
        "running": _is_running() if _started else False,
        "busy": _state["busy_until"] > time.time(),
    }
