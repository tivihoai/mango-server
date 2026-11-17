"""Chế độ khóa máy của MangoMCP (bản 0.9.0, cập nhật 0.10.0, 0.10.1).

0.10.1: trong lúc tạm ngưng (người dùng đã mở khóa tại máy), một cửa
sổ nhỏ đếm lùi hiện ở đầu màn hình, cho người dùng biết còn bao nhiêu
thời gian được dùng máy trước khi khóa lại. Cửa sổ này bấm xuyên qua
được, không cướp focus, và tự ẩn khi khóa lại hoặc khi tắt chế độ khóa.
Hết giờ mà người dùng vẫn đang thao tác thì đếm lùi không đếm âm mà
hiện "Hết giờ — khóa lại khi bạn nghỉ tay" cho tới khi đủ nghỉ tay.

0.12.0: thêm chế độ hiện (screen_mode "visible") — Quản trị viên lệnh
30/10/2026, không cần ẩn nữa: Agent thao tác gì trên máy thì người
ngồi máy cũng thấy hết. Ở chế độ này, bật "cho phép bot điều khiển"
nhưng KHÔNG che màn hình, KHÔNG nuốt chuột/phím vật lý, KHÔNG hiện
ô nhập pass: trạng thái là "visible", Agent không bao giờ bị chặn
input/ảnh (không có tạm ngưng vì không có ô mở khóa để bắt đầu tạm
ngưng). Đổi chế độ trong app cấu hình có hiệu lực trong vài giây mà
không cần khởi động lại server: đang khóa đen mà chuyển sang hiện thì
mở màn + gỡ hook ngay; đang hiện mà chuyển về khóa đen/tắt màn thì
khóa lại ngay. Hết tạm ngưng mà chế độ đã đổi sang hiện thì không
khóa đen lại. Mật khẩu khóa máy vẫn giữ nguyên để quay lại chế độ
khóa bất cứ lúc nào.

Quản trị viên chốt 26/10/2026, nói lại cho rõ để khỏi làm lệch:
- Nút "cho phép bot điều khiển" (0.10.0) chính là nút bật khóa này:
  bật lên thì màn hình local không còn hiển thị gì khác, chỉ còn giao
  diện nhập mật khẩu mở khóa (chế độ black_window mặc định), kèm thông
  báo "Agent đang sử dụng máy". Bên trong máy, Agent có toàn quyền,
  KHÔNG cần tool khóa/mở gì cả — khóa là trạng thái cấu hình, không
  phải tool phiên.
- Người ngồi máy nhập đúng mật khẩu thì các tiến trình của Agent tạm
  ngưng 15 phút (mặc định, cấu hình được). Hết 15 phút, nếu người dùng
  không thao tác gì nữa (nghỉ tay >= 60 giây) thì khóa lại và chạy tiếp
  các việc đang ngưng; nếu lúc hết giờ người dùng vẫn đang thao tác
  thì chờ tới khi nghỉ tay 60 giây rồi mới khóa lại.
- Mật khẩu chỉ lưu dạng hash SHA-256 trong config.json, giống token
  chủ. Không bao giờ lưu mật khẩu thô, không ghi vào audit.

Cách chặn input và che màn hình trên Windows:
1. Hook mức thấp WH_KEYBOARD_LL / WH_MOUSE_LL nuốt phím/chuột vật lý,
   nhưng cho input do SendInput của Agent qua (cờ INJECTED). Đây là
   lớp chính, chạy được cả khi server không elevated (BlockInput thì
   chưa chắc, nên chỉ thử thêm, hỏng cũng không sao).
2. Tắt nguồn màn hình (SC_MONITORPOWER) khi khóa: người ngồi máy thấy
   đen, còn framebuffer vẫn chạy nên screenshot của Agent vẫn thấy
   màn hình thật. Cú bấm/phím vật lý đầu tiên làm "đánh thức": lock
   thread hiện cửa sổ đen + ô nhập pass trong 60 giây; không nhập thì
   tắt màn hình lại và ẩn cửa sổ đi, Agent lại nhìn thấy màn hình.
3. Cửa sổ khóa là cửa sổ Win32 thuần bằng ctypes, luôn topmost và
   phủ toàn bộ màn hình ảo. Nó chặn Alt+Tab, phím Win, Alt+F4/đóng
   cửa sổ trong lúc khóa; chỉ ô nhập pass của nó mới nhận phím.
   Ctrl+Alt+Del thì Windows không cho chặn — đó là đường thoát cuối
   theo thiết kế của Windows, không phải lỗi.

Failsafe, để không khóa chết máy của Quản trị viên:
- Hết giờ tạm ngưng + nghỉ tay 60 giây là khóa lại tự động.
- Server tắt/crash thì hook và cửa sổ khóa chết theo tiến trình,
  BlockInput cũng tự nhả khi thread gọi nó kết thúc.
- Chế độ này mặc định TẮT. Muốn bật phải đặt mật khẩu trước trong
  app cấu hình; không có mật khẩu thì server không khóa.

Trên máy không phải Windows, controller vẫn chạy ở chế độ logic
(không hook, không cửa sổ) để test được state machine; các hàm
Windows-only trả PLATFORM_UNSUPPORTED qua adapter.
"""
from __future__ import annotations

import hashlib
import hmac
import threading
import time

from .errors import MangoError, platform_unsupported

DEFAULT_PAUSE_MINUTES = 15
IDLE_RESUME_SECONDS = 60
UNLOCK_WINDOW_SECONDS = 60
STATE_OFF = "off"
STATE_LOCKED = "locked"
STATE_PAUSED = "paused"
STATE_VISIBLE = "visible"
SCREEN_MODES = ("black_window", "monitor_off", "visible")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _verify(password: str, stored_hash: str) -> bool:
    if not password or not stored_hash:
        return False
    return hmac.compare_digest(_sha256(password), stored_hash)


def _set_overlay_suppressed(suppressed: bool):
    """Khi khóa: overlay không được vẽ đè lên giao diện nhập pass.
    Chỉ tắt nén khi khóa tắt hẳn (không phải khi tạm ngưng, vì lúc đó
    người dùng đang dùng máy, banner bot cũng không được hiện)."""
    try:
        from . import overlay

        overlay.set_suppressed(suppressed)
    except Exception:
        pass


class _NullAdapter:
    """Adapter không làm gì, dùng ngoài Windows và trong test."""

    name = "null"

    def install_hooks(self, controller):
        return False

    def uninstall_hooks(self):
        pass

    def monitor_off(self):
        pass

    def monitor_on(self):
        pass

    def show_lock_window(self, controller):
        return False

    def hide_lock_window(self):
        pass

    # Bộ đếm lùi tạm ngưng (0.10.1): cửa sổ nhỏ hiện trong lúc người
    # dùng được dùng máy, để họ biết còn bao nhiêu thời gian.
    def show_countdown_window(self, controller):
        return False

    def hide_countdown_window(self):
        pass

    def update_countdown(self, text):
        return False

    def block_input(self, on: bool):
        return False

    def idle_seconds(self):
        return 3600.0

    def pump_messages(self, timeout_seconds: float):
        time.sleep(timeout_seconds)


class LockController:
    """State machine của chế độ khóa. Tách khỏi Win32 để test được."""

    def __init__(self, adapter=None, time_fn=None):
        self._adapter = adapter or _NullAdapter()
        self._time = time_fn or time.time
        self._guard = threading.Lock()
        self.enabled = False
        self.password_sha256 = ""
        self.pause_minutes = DEFAULT_PAUSE_MINUTES
        self.screen_mode = "monitor_off"
        self.state = STATE_OFF
        self.paused_until = 0.0
        self.pause_started_at = 0.0
        self.lock_window_until = 0.0
        self.lock_window_shown = False
        self.wake_requested = False
        self.foreground_restore_requested = False
        self.failed_attempts = 0
        self.last_local_unlock_at = 0.0
        self.last_resume_at = 0.0
        self.countdown_shown = False
        self._last_countdown_text = ""
        self.on_event = None  # callback(event_name, detail) do server gán
        self._thread = None
        self._stop = threading.Event()

    # ----- Cấu hình -----

    def sync_from_config(self, config):
        """Đọc lại mục lock trong config.json; server watch gọi định kỳ."""
        data = {}
        try:
            data = config.data.get("lock", {}) or {}
        except Exception:
            data = {}
        with self._guard:
            self.enabled = bool(data.get("enabled", False))
            self.password_sha256 = str(data.get("password_sha256", "") or "")
            try:
                self.pause_minutes = max(1, int(data.get("pause_minutes", DEFAULT_PAUSE_MINUTES)))
            except Exception:
                self.pause_minutes = DEFAULT_PAUSE_MINUTES
            self.screen_mode = str(data.get("screen_mode", "monitor_off") or "monitor_off")
            if self.screen_mode not in SCREEN_MODES:
                # Giá trị lạ (config cũ tay sửa, app cũ): về mặc định an
                # toàn là khóa đen thay vì rơi vào trạng thái không rõ.
                self.screen_mode = "black_window"
        # KHÔNG bật/tắt trực tiếp ở đây: sync chạy ở luồng chính của
        # server, còn hook + cửa sổ khóa phải sống ở cùng một luồng
        # với message pump (luồng lock, xem start()). tick() ở luồng
        # đó sẽ bật/tắt theo cấu hình, chậm nhất 0.5 giây. Bật trực
        # tiếp ở luồng chính làm cửa sổ tạo ở luồng chính nhưng pump
        # ở luồng khác → WM_PAINT/WM_COMMAND không bao giờ tới được
        # cửa sổ, nút bấm và chữ không hiện, bấm cũng không mở khóa.

    def password_set(self):
        return bool(self.password_sha256)

    # ----- Trạng thái -----

    def status(self):
        now = self._time()
        with self._guard:
            remaining = max(0.0, self.paused_until - now) if self.state == STATE_PAUSED else 0.0
            return {
                "enabled": self.enabled,
                "state": self.state,
                "password_set": bool(self.password_sha256),
                "pause_minutes": self.pause_minutes,
                "screen_mode": self.screen_mode,
                "paused_remaining_seconds": round(remaining, 1),
                "countdown_shown": self.countdown_shown,
                "countdown_text": self._last_countdown_text,
                "lock_window_shown": self.lock_window_shown,
                "foreground_restore_pending": self.foreground_restore_requested,
                "failed_attempts": self.failed_attempts,
                "last_local_unlock_at": self.last_local_unlock_at,
                "last_resume_at": self.last_resume_at,
                "agent_input_blocked": self.state == STATE_PAUSED,
                "agent_capture_blocked": self.state == STATE_PAUSED,
            }

    def agent_input_blocked(self):
        return self.state == STATE_PAUSED

    def agent_capture_blocked(self):
        return self.state == STATE_PAUSED

    # ----- Bộ đếm lùi tạm ngưng (0.10.1) -----

    def countdown_text(self, now=None):
        """Chuỗi đếm lùi hiển thị trong lúc tạm ngưng.

        Còn giờ: "Còn MM:SS — hết giờ sẽ khóa lại". Hết giờ nhưng người
        dùng vẫn đang thao tác (chưa đủ nghỉ tay 60 giây): không đếm âm,
        hiện "Hết giờ — khóa lại khi bạn nghỉ tay" để không nói dối."""
        if now is None:
            now = self._time()
        with self._guard:
            remaining = self.paused_until - now if self.state == STATE_PAUSED else 0.0
        if remaining <= 0:
            return "Hết giờ — khóa lại khi bạn nghỉ tay"
        minutes = int(remaining // 60)
        seconds = int(remaining % 60)
        return f"Còn {minutes:02d}:{seconds:02d} — hết giờ sẽ khóa lại"

    def _sync_countdown(self):
        """Hiện/cập nhật/ẩn cửa sổ đếm lùi theo đúng trạng thái hiện tại.

        Chỉ gọi ở luồng lock (tick) hoặc khi khóa tắt hẳn, để cửa sổ
        đếm lùi sống cùng luồng message pump với cửa sổ khóa."""
        with self._guard:
            state = self.state
            shown = self.countdown_shown
        if state == STATE_PAUSED:
            text = self.countdown_text()
            if not shown:
                try:
                    ok = self._adapter.show_countdown_window(self)
                except Exception:
                    ok = False
                with self._guard:
                    self.countdown_shown = bool(ok)
                    shown = bool(ok)
            if shown and text != self._last_countdown_text:
                try:
                    self._adapter.update_countdown(text)
                except Exception:
                    pass
                self._last_countdown_text = text
        elif shown:
            try:
                self._adapter.hide_countdown_window()
            except Exception:
                pass
            with self._guard:
                self.countdown_shown = False
            self._last_countdown_text = ""

    def _emit(self, event, detail=""):
        if self.on_event:
            try:
                self.on_event(event, detail)
            except Exception:
                pass

    # ----- Khóa / mở ở tầng hệ thống -----

    def _enter_visible(self):
        """Chuyển sang chế độ hiện (0.12.0): Agent làm việc mở, người
        ngồi máy thấy hết, không hook, không cửa sổ khóa, không tắt
        màn hình. Dùng khi bật ở chế độ visible, khi đổi chế độ từ
        khóa đen sang hiện, và khi hết tạm ngưng mà chế độ đã là hiện."""
        with self._guard:
            if self.state == STATE_VISIBLE:
                return {"ok": True, "state": STATE_VISIBLE}
            self.state = STATE_VISIBLE
            self.paused_until = 0.0
            self.lock_window_until = 0.0
            self.lock_window_shown = False
            self.wake_requested = False
            self.foreground_restore_requested = False
        _set_overlay_suppressed(False)
        try:
            self._adapter.hide_countdown_window()
        except Exception:
            pass
        with self._guard:
            self.countdown_shown = False
        self._last_countdown_text = ""
        self._adapter.uninstall_hooks()
        self._adapter.hide_lock_window()
        self._adapter.monitor_on()
        self._emit("lock_visible")
        return {"ok": True, "state": STATE_VISIBLE}

    def enable_lock(self):
        """Bật khóa. Chỉ gọi khi đã bật cấu hình và đã đặt mật khẩu."""
        with self._guard:
            if not self.enabled or not self.password_sha256:
                return {"ok": False, "reason": "lock_not_configured"}
            if self.state == STATE_LOCKED:
                return {"ok": True, "state": STATE_LOCKED}
            if self.state == STATE_VISIBLE and self.screen_mode == "visible":
                return {"ok": True, "state": STATE_VISIBLE}
            visible = self.screen_mode == "visible"
            self.state = STATE_VISIBLE if visible else STATE_LOCKED
            self.paused_until = 0.0
            self.lock_window_until = 0.0
            self.lock_window_shown = False
            self.wake_requested = False
            self.foreground_restore_requested = False
        if visible:
            # (0.12.0) Chế độ hiện: không hook, không cửa sổ khóa,
            # không tắt màn hình — người ngồi máy thấy mọi thao tác
            # của Agent, và vẫn dùng được chuột/phím của mình.
            self._adapter.monitor_on()
            self._emit("lock_visible")
            return {"ok": True, "state": STATE_VISIBLE}
        _set_overlay_suppressed(True)
        self._adapter.install_hooks(self)
        # KHÔNG dùng BlockInput: nó chặn cả SendInput của chính Agent,
        # làm Agent mất luôn thao tác của mình khi đang khóa (đã kiểm
        # chứng trên máy thật: mouse_click/keyboard_type trả ok nhưng
        # màn hình không đổi). Hook mức thấp đã đủ: nó nuốt input vật
        # lý, chừa input injected của Agent và ô nhập pass.
        if self.screen_mode == "black_window":
            # Chế độ cửa sổ đen: cửa sổ khóa hiện ngay từ đầu, không
            # tắt màn hình (vì cửa sổ đen đã che hết). Chế độ này cần
            # để test bằng input injected: cửa sổ khóa ở foreground thì
            # hook cho input qua, nên Agent vẫn gõ được pass vào ô.
            self._adapter.monitor_on()
            self.show_unlock_window()
        else:
            # Mặc định monitor_off: tắt màn hình, cửa sổ khóa chỉ hiện
            # khi có input vật lý đánh thức (xem tick/request_wake).
            self._adapter.monitor_off()
        self._emit("lock_enabled")
        return {"ok": True, "state": STATE_LOCKED}

    def disable_lock(self):
        with self._guard:
            if self.state == STATE_OFF:
                return {"ok": True, "state": STATE_OFF}
            self.state = STATE_OFF
            self.paused_until = 0.0
            self.lock_window_shown = False
            self.foreground_restore_requested = False
        _set_overlay_suppressed(False)
        try:
            self._adapter.hide_countdown_window()
        except Exception:
            pass
        with self._guard:
            self.countdown_shown = False
        self._last_countdown_text = ""
        self._adapter.uninstall_hooks()
        self._adapter.hide_lock_window()
        self._adapter.monitor_on()
        self._emit("lock_disabled")
        return {"ok": True, "state": STATE_OFF}

    def request_wake(self):
        """Hook gọi khi có input vật lý đầu tiên lúc đang khóa."""
        with self._guard:
            if self.state != STATE_LOCKED or self.lock_window_shown:
                return
            self.wake_requested = True

    def request_foreground_restore(self):
        """Hook gọi khi có input vật lý mà cửa sổ khóa không còn ở
        foreground (lỗi kẹt 26/10/2026: app khác chiếm foreground thì
        hook nuốt hết input vật lý, người dùng không bấm lại được vào
        cửa sổ khóa để lấy foreground). Tick sẽ đưa cửa sổ khóa về
        foreground lại trong nhịp sau (<= 0.5 giây). Chỉ đặt cờ khi
        đang khóa; khi tạm ngưng hoặc tắt thì cờ vô nghĩa và tick
        sẽ không chạm tới cửa sổ khóa."""
        with self._guard:
            if self.state != STATE_LOCKED:
                return
            self.foreground_restore_requested = True

    def show_unlock_window(self):
        with self._guard:
            if self.state != STATE_LOCKED:
                return
            self.lock_window_shown = True
            self.lock_window_until = self._time() + UNLOCK_WINDOW_SECONDS
            self.wake_requested = False
        if self._adapter.show_lock_window(self):
            self._adapter.monitor_on()
        else:
            # Không dựng được cửa sổ (ví dụ ngoài Windows): vẫn giữ
            # trạng thái khóa, không giả vờ là đã hiện ô nhập pass.
            with self._guard:
                self.lock_window_shown = False

    def hide_unlock_window(self):
        with self._guard:
            self.lock_window_shown = False
            self.lock_window_until = 0.0
            self.wake_requested = False
        self._adapter.hide_lock_window()
        if self.state == STATE_LOCKED and self.screen_mode != "black_window":
            self._adapter.monitor_off()

    def try_local_unlock(self, password: str):
        """Người ngồi máy nhập pass vào ô trên màn đen. Đúng thì tạm ngưng."""
        with self._guard:
            if self.state != STATE_LOCKED:
                return False
            ok = _verify(password or "", self.password_sha256)
            if not ok:
                self.failed_attempts += 1
                return False
            now = self._time()
            self.state = STATE_PAUSED
            self.pause_started_at = now
            self.paused_until = now + self.pause_minutes * 60
            self.last_local_unlock_at = now
            self.lock_window_shown = False
            self.lock_window_until = 0.0
        self._adapter.uninstall_hooks()
        self._adapter.hide_lock_window()
        self._adapter.monitor_on()
        self._emit("local_unlock_pause", f"pause_minutes={self.pause_minutes}")
        return True

    def resume_lock(self):
        """Hết giờ tạm ngưng + người dùng nghỉ tay: khóa lại, chạy tiếp."""
        with self._guard:
            if self.state != STATE_PAUSED:
                return {"ok": False, "state": self.state}
            visible = self.screen_mode == "visible"
            if not visible:
                self.state = STATE_LOCKED
                self.last_resume_at = self._time()
                self.paused_until = 0.0
        if visible:
            # (0.12.0) Hết tạm ngưng mà chế độ đã đổi sang hiện: không
            # khóa đen lại, Agent chạy tiếp trong chế độ hiện.
            with self._guard:
                self.last_resume_at = self._time()
            return self._enter_visible()
        _set_overlay_suppressed(True)
        try:
            self._adapter.hide_countdown_window()
        except Exception:
            pass
        with self._guard:
            self.countdown_shown = False
        self._last_countdown_text = ""
        self._adapter.install_hooks(self)
        if self.screen_mode == "black_window":
            # Chế độ cửa sổ đen: khóa lại thì cửa sổ phải hiện lại ngay,
            # không tắt màn hình (giống enable_lock ở chế độ này).
            self.show_unlock_window()
        else:
            self._adapter.monitor_off()
        self._emit("lock_resumed")
        return {"ok": True, "state": STATE_LOCKED}

    # ----- Vòng lặp nền -----

    def tick(self):
        """Một nhịp kiểm tra, server gọi mỗi ~0.5 giây (và test gọi tay)."""
        # Bật/tắt theo cấu hình, CHỈ ở luồng này (luồng lock) để hook +
        # cửa sổ + message pump cùng một luồng (xem sync_from_config).
        with self._guard:
            enabled = self.enabled
            has_pw = bool(self.password_sha256)
            cur = self.state
            mode = self.screen_mode
        if enabled and has_pw and cur == STATE_OFF:
            self.enable_lock()
        elif enabled and has_pw and cur == STATE_LOCKED and mode == "visible":
            # (0.12.0) Đang khóa đen mà chủ máy chuyển sang chế độ hiện:
            # mở màn + gỡ hook ngay, không cần khởi động lại server.
            self._enter_visible()
        elif enabled and has_pw and cur == STATE_VISIBLE and mode != "visible":
            # Đang hiện mà chủ máy chuyển về khóa đen/tắt màn: khóa lại ngay.
            self.enable_lock()
        elif not enabled and cur != STATE_OFF:
            self.disable_lock()
        now = self._time()
        with self._guard:
            state = self.state
            window_until = self.lock_window_until
            window_shown = self.lock_window_shown
            wake = self.wake_requested
            paused_until = self.paused_until
        if state == STATE_LOCKED and wake and not window_shown:
            self.show_unlock_window()
        elif (state == STATE_LOCKED and window_shown and now >= window_until
              and self.screen_mode != "black_window"):
            # Hết 60 giây không nhập pass: tắt màn lại, Agent nhìn lại được.
            # Chế độ black_window thì cửa sổ ở lại tới khi nhập đúng pass.
            self.hide_unlock_window()
        elif state == STATE_PAUSED and now >= paused_until:
            idle = self._adapter.idle_seconds()
            if idle >= IDLE_RESUME_SECONDS:
                self.resume_lock()
            # Còn thao tác trong 60 giây gần nhất thì tick sau kiểm tra
            # lại; không khóa đè lên tay người dùng đang làm việc.
        # Sửa kẹt foreground (0.10.2): đang khóa, cửa sổ đã hiện mà
        # có input vật lý báo mất foreground thì đưa cửa sổ về
        # foreground lại ngay trong nhịp này. Chỉ làm khi có cờ do
        # input vật lý đặt (không phải mỗi nhịp), để việc Agent mở
        # app lúc đang khóa không bị tick giật foreground liên tục.
        # Xóa cờ trước khi gọi adapter để lần input sau đặt lại được.
        with self._guard:
            restore = (self.state == STATE_LOCKED and self.lock_window_shown
                       and self.foreground_restore_requested)
            if restore:
                self.foreground_restore_requested = False
        if restore:
            try:
                self._adapter.show_lock_window(self)
            except Exception:
                pass
        # Bộ đếm lùi: chạy sau logic khóa/tạm ngưng ở trên để cùng một
        # nhịp tick đã khóa lại thì đếm lùi ẩn ngay, không ở lại một nhịp.
        self._sync_countdown()

    def start(self, config_getter):
        """Luồng nền: đồng bộ config + tick. Daemon, chết theo server."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def _loop():
            while not self._stop.is_set():
                try:
                    cfg = config_getter() if config_getter else None
                    if cfg is not None:
                        self.sync_from_config(cfg)
                except Exception:
                    pass
                try:
                    self.tick()
                except Exception:
                    pass
                # Luồng này cũng là message pump của hook + cửa sổ khóa
                # trên Windows: hook mức thấp chỉ được gọi khi luồng cài
                # nó đang bơm message, ngủ thường sẽ làm hook chết lặng.
                try:
                    self._adapter.pump_messages(0.5)
                except Exception:
                    self._stop.wait(0.5)

        self._thread = threading.Thread(target=_loop, daemon=True, name="mangomcp-lock")
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            self.disable_lock()
        except Exception:
            pass


# ---------- Adapter Windows thật (ctypes, chỉ nạp khi chạy trên Windows) ----------

try:
    from . import backend as _backend

    _IS_WINDOWS = _backend.IS_WINDOWS
except Exception:
    _IS_WINDOWS = False


if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _gdi32 = ctypes.windll.gdi32  # GetStockObject ở gdi32, không phải user32
    # ctypes mặc định ép mọi số nguyên về c_int 32-bit: l_param 64-bit
    # (ví dụ con trỏ) sẽ OverflowError khi gọi DefWindowProcW/SendMessage.
    # Khai argtypes cho các hàm nhận HWND/LPARAM để không bị cắt.
    _user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
    _user32.DefWindowProcW.restype = ctypes.c_long
    _user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR,
                                        wintypes.LPCWSTR, wintypes.DWORD,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                        wintypes.HINSTANCE, wintypes.LPVOID]
    _user32.CreateWindowExW.restype = wintypes.HWND
    _user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int,
                                       wintypes.WPARAM, wintypes.LPARAM]
    _user32.CallNextHookEx.restype = ctypes.c_long
    _user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM]
    _user32.SendMessageW.restype = ctypes.c_long
    _user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p,
                                          wintypes.HINSTANCE, wintypes.DWORD]
    _user32.SetWindowsHookExW.restype = wintypes.HHOOK
    # Vẽ giao diện khóa: font, màu chữ/nền, nút cam vẽ tay.
    _gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
    _gdi32.CreateSolidBrush.restype = wintypes.HANDLE
    _gdi32.CreateFontW.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.DWORD,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.DWORD, wintypes.LPCWSTR]
    _gdi32.CreateFontW.restype = wintypes.HANDLE
    _gdi32.SetBkMode.argtypes = [wintypes.HANDLE, ctypes.c_int]
    _gdi32.SetBkMode.restype = ctypes.c_int
    _gdi32.SetTextColor.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _gdi32.SetTextColor.restype = wintypes.DWORD
    _gdi32.SelectObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _gdi32.SelectObject.restype = wintypes.HANDLE
    _user32.FillRect.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.HANDLE]
    _user32.FillRect.restype = ctypes.c_int
    _user32.DrawTextW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, ctypes.c_int,
                                  ctypes.c_void_p, wintypes.UINT]
    _user32.DrawTextW.restype = ctypes.c_int
    # Cửa sổ đếm lùi: layered + alpha 250 (~0.98, đúng quy tắc phủ:
    # không để 1.0 kẻo Windows bỏ qua pipeline layered) + trong suốt
    # với chuột (WS_EX_TRANSPARENT) + không cướp focus (NOACTIVATE),
    # để người dùng bấm xuyên qua được như lớp phủ cũ.
    _user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD,
                                                   ctypes.c_ubyte, wintypes.DWORD]
    _user32.SetLayeredWindowAttributes.restype = ctypes.c_int

    _WH_KEYBOARD_LL = 13
    _WH_MOUSE_LL = 14
    _WM_SYSCOMMAND = 0x0112
    _SC_MONITORPOWER = 0xF170
    _HWND_BROADCAST = 0xFFFF
    _LLKHF_INJECTED = 0x10
    _LLMHF_INJECTED = 0x01
    _VK_LWIN = 0x5B
    _VK_RWIN = 0x5C
    _VK_TAB = 0x09
    _VK_ESCAPE = 0x1B
    _VK_RETURN = 0x0D

    class _KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                    ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class _MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
                    ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    _HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    # wintypes không có LRESULT: WndProc trả về c_long (tương đương LRESULT).
    _WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM)

    class WinLockAdapter:
        """Hook + cửa sổ khóa + tắt màn hình, chạy trên luồng message pump."""

        name = "windows"

        def __init__(self):
            self.controller = None
            self._kbd_hook = None
            self._mouse_hook = None
            self._kbd_proc = None
            self._mouse_proc = None
            self._wndproc = None
            self._hwnd = None
            self._edit = None
            self._msg_label = None
            self._title = None
            self._hint = None
            self._btn = None
            self._class_atom = None
            self._thread_id = None
            self._fonts = []
            self._bg_brush = None
            self._msg_is_error = False
            # Cửa sổ đếm lùi tạm ngưng (0.10.1).
            self._countdown_hwnd = None
            self._countdown_label = None
            self._countdown_wndproc = None
            self._countdown_class_atom = None
            self._countdown_text = ""

        # ----- Hook: nuốt input vật lý, chừa input của Agent và ô nhập pass -----

        def _lock_window_foreground(self):
            if not self._hwnd:
                return False
            try:
                return _user32.GetForegroundWindow() == self._hwnd
            except Exception:
                return False

        def _kbd_hook_fn(self, n_code, w_param, l_param):
            if n_code < 0:
                return _user32.CallNextHookEx(self._kbd_hook, n_code, w_param, l_param)
            ctrl = self.controller
            if ctrl is None or ctrl.state != STATE_LOCKED:
                return _user32.CallNextHookEx(self._kbd_hook, n_code, w_param, l_param)
            data = ctypes.cast(l_param, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
            if data.flags & _LLKHF_INJECTED:
                return _user32.CallNextHookEx(self._kbd_hook, n_code, w_param, l_param)
            # Input vật lý: đánh thức cửa sổ khóa, rồi nuốt trừ khi đang
            # gõ vào chính cửa sổ khóa (và không phải phím hệ thống).
            # Nếu cửa sổ khóa mất foreground thì đặt cờ để tick đưa nó
            # về foreground lại (sửa kẹt 0.10.2); phím hiện tại vẫn nuốt
            # để không gõ nhầm vào app đang ở foreground, phím sau khi
            # tick lấy lại foreground (<= 0.5 giây) sẽ đi qua bình thường.
            ctrl.request_wake()
            if self._lock_window_foreground():
                vk = data.vkCode
                alt_down = bool(_user32.GetAsyncKeyState(0x12) & 0x8000)
                if vk in (_VK_LWIN, _VK_RWIN) or (vk == _VK_TAB and alt_down):
                    return 1
                return _user32.CallNextHookEx(self._kbd_hook, n_code, w_param, l_param)
            ctrl.request_foreground_restore()
            return 1

        def _mouse_hook_fn(self, n_code, w_param, l_param):
            if n_code < 0:
                return _user32.CallNextHookEx(self._mouse_hook, n_code, w_param, l_param)
            ctrl = self.controller
            if ctrl is None or ctrl.state != STATE_LOCKED:
                return _user32.CallNextHookEx(self._mouse_hook, n_code, w_param, l_param)
            data = ctypes.cast(l_param, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
            if data.flags & _LLMHF_INJECTED:
                return _user32.CallNextHookEx(self._mouse_hook, n_code, w_param, l_param)
            ctrl.request_wake()
            if self._lock_window_foreground():
                # Cửa sổ khóa phủ toàn màn hình và topmost nên click chỉ
                # rơi vào nó, không chạm được desktop bên dưới.
                return _user32.CallNextHookEx(self._mouse_hook, n_code, w_param, l_param)
            # Sửa kẹt 0.10.2: cửa sổ khóa mất foreground nhưng vẫn đang
            # hiện (black_window luôn hiện, monitor_off đang ở cửa sổ
            # mở khóa 60 giây) thì cửa sổ khóa vẫn là topmost phủ toàn
            # màn hình, nên cho chuột đi qua: con trỏ di chuyển được,
            # cú bấm rơi vào chính cửa sổ khóa và kích hoạt nó, không
            # chạm được app bên dưới. Đồng thời đặt cờ để tick đưa
            # cửa sổ về foreground lại, đề phòng cú bấm không kích hoạt
            # được (quy tắc khóa foreground của Windows). Chỉ khi cửa
            # sổ khóa không hiện (monitor_off đang tắt màn) mới nuốt
            # chuột như cũ, vì lúc đó chuột đi qua sẽ chạm desktop.
            ctrl.request_foreground_restore()
            if ctrl.lock_window_shown and self._hwnd:
                return _user32.CallNextHookEx(self._mouse_hook, n_code, w_param, l_param)
            return 1

        def install_hooks(self, controller):
            self.controller = controller
            if self._kbd_hook is not None:
                return True
            try:
                self._kbd_proc = _HOOKPROC(self._kbd_hook_fn)
                self._mouse_proc = _HOOKPROC(self._mouse_hook_fn)
                self._kbd_hook = _user32.SetWindowsHookExW(_WH_KEYBOARD_LL, self._kbd_proc, None, 0)
                self._mouse_hook = _user32.SetWindowsHookExW(_WH_MOUSE_LL, self._mouse_proc, None, 0)
                return bool(self._kbd_hook or self._mouse_hook)
            except Exception:
                return False

        def uninstall_hooks(self):
            try:
                if self._kbd_hook:
                    _user32.UnhookWindowsHookEx(self._kbd_hook)
                if self._mouse_hook:
                    _user32.UnhookWindowsHookEx(self._mouse_hook)
            except Exception:
                pass
            self._kbd_hook = None
            self._mouse_hook = None

        # ----- Màn hình -----

        def monitor_off(self):
            try:
                _user32.SendMessageW(_HWND_BROADCAST, _WM_SYSCOMMAND, _SC_MONITORPOWER, 2)
            except Exception:
                pass

        def monitor_on(self):
            try:
                _user32.SendMessageW(_HWND_BROADCAST, _WM_SYSCOMMAND, _SC_MONITORPOWER, -1)
            except Exception:
                pass

        def block_input(self, on: bool):
            # Cố tình không gọi BlockInput: nó chặn cả SendInput của
            # Agent, làm Agent mất thao tác khi đang khóa. Hook mức
            # thấp đã nuốt input vật lý, đủ cho chế độ khóa.
            return False

        def idle_seconds(self):
            try:
                info = _LASTINPUTINFO()
                info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
                if not _user32.GetLastInputInfo(ctypes.byref(info)):
                    return 3600.0
                return max(0.0, (_kernel32.GetTickCount() - info.dwTime) / 1000.0)
            except Exception:
                return 3600.0

        def pump_messages(self, timeout_seconds: float):
            """Bơm message cho hook + cửa sổ khóa trong đúng luồng này."""
            class _MSG(ctypes.Structure):
                _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                            ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                            ("time", wintypes.DWORD), ("pt", wintypes.POINT)]

            end = time.time() + timeout_seconds
            msg = _MSG()
            while time.time() < end:
                try:
                    if _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE
                        _user32.TranslateMessage(ctypes.byref(msg))
                        _user32.DispatchMessageW(ctypes.byref(msg))
                    else:
                        time.sleep(0.01)
                except Exception:
                    time.sleep(0.01)

        # ----- Cửa sổ khóa -----

        def show_lock_window(self, controller):
            self.controller = controller
            if self._hwnd:
                try:
                    _user32.ShowWindow(self._hwnd, 5)  # SW_SHOW
                    # Sửa kẹt 0.10.2: SetForegroundWindow đơn thuần hay
                    # bị Windows từ chối lặng lẽ khi tiến trình gọi không
                    # phải tiến trình foreground (đúng trường hợp app
                    # khác vừa chiếm foreground). Dùng mẹo AttachThreadInput
                    # như backend.focus_window: gắn luồng lock vào luồng
                    # foreground hiện tại rồi mới đặt foreground, sau đó
                    # tách ra. Thất bại vẫn bỏ qua như cũ, vì tick sẽ thử
                    # lại ở lần input vật lý tiếp theo.
                    try:
                        fg = _user32.GetForegroundWindow()
                        if fg and fg != self._hwnd:
                            cur = _kernel32.GetCurrentThreadId()
                            fg_thread = _user32.GetWindowThreadProcessId(fg, None)
                            attached = False
                            try:
                                if fg_thread and fg_thread != cur:
                                    attached = bool(_user32.AttachThreadInput(fg_thread, cur, True))
                                _user32.BringWindowToTop(self._hwnd)
                                _user32.SetForegroundWindow(self._hwnd)
                                _user32.SetActiveWindow(self._hwnd)
                            finally:
                                if attached:
                                    _user32.AttachThreadInput(fg_thread, cur, False)
                        else:
                            _user32.SetForegroundWindow(self._hwnd)
                    except Exception:
                        _user32.SetForegroundWindow(self._hwnd)
                    # Trả focus về ô nhập pass để người dùng gõ ngay,
                    # không cần bấm lại vào ô sau khi lấy lại foreground.
                    try:
                        if getattr(self, "_edit", None):
                            _user32.SetFocus(self._edit)
                    except Exception:
                        pass
                except Exception:
                    pass
                return True
            try:
                return self._create_window()
            except Exception as exc:
                # Trước đây lỗi ở đây bị nuốt im, server vẫn chạy nhưng
                # lock_window_shown=False mà log không nói lý do.
                print(f"lock window error: {exc!r}", flush=True)
                return False

        def hide_lock_window(self):
            if self._hwnd:
                try:
                    _user32.ShowWindow(self._hwnd, 0)  # SW_HIDE
                except Exception:
                    pass

        # ----- Cửa sổ đếm lùi tạm ngưng (0.10.1) -----

        def show_countdown_window(self, controller):
            self.controller = controller
            if self._countdown_hwnd:
                try:
                    _user32.ShowWindow(self._countdown_hwnd, 5)  # SW_SHOW
                except Exception:
                    pass
                return True
            try:
                return self._create_countdown_window()
            except Exception as exc:
                print(f"countdown window error: {exc!r}", flush=True)
                return False

        def hide_countdown_window(self):
            if self._countdown_hwnd:
                try:
                    _user32.ShowWindow(self._countdown_hwnd, 0)  # SW_HIDE
                except Exception:
                    pass

        def update_countdown(self, text):
            self._countdown_text = text or ""
            if self._countdown_label:
                try:
                    _user32.SetWindowTextW(self._countdown_label, self._countdown_text)
                    return True
                except Exception:
                    return False
            return False

        def _create_countdown_window(self):
            self._countdown_wndproc = _WNDPROC(self._countdown_wndproc_fn)
            class_name = "MangoCountdownWindow"

            class _WNDCLASS_CD(ctypes.Structure):
                _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC),
                            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                            ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                            ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                            ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

            if self._bg_brush is None:
                self._bg_brush = _gdi32.CreateSolidBrush(0x00201A0B)  # #0B1A20
            wc = _WNDCLASS_CD()
            wc.lpfnWndProc = self._countdown_wndproc
            wc.hInstance = _kernel32.GetModuleHandleW(None)
            wc.hbrBackground = self._bg_brush
            wc.lpszClassName = class_name
            self._countdown_class_atom = _user32.RegisterClassW(ctypes.byref(wc))
            vx = _user32.GetSystemMetrics(76)
            vw = _user32.GetSystemMetrics(78)
            width, height = 560, 52
            x = vx + (vw - width) // 2
            y = _user32.GetSystemMetrics(77) + 12
            # TOPMOST | TOOLWINDOW | LAYERED | TRANSPARENT | NOACTIVATE:
            # luôn nổi, không cướp focus, bấm xuyên qua được.
            ex = 0x00000008 | 0x00000080 | 0x00080000 | 0x00000020 | 0x08000000
            hwnd = _user32.CreateWindowExW(
                ex, class_name, "MangoMCP — Đếm lùi tạm ngưng",
                0x80000000 | 0x10000000,  # WS_POPUP | WS_VISIBLE
                x, y, width, height, None, None, wc.hInstance, None)
            if not hwnd:
                return False
            self._countdown_hwnd = hwnd
            try:
                _user32.SetLayeredWindowAttributes(hwnd, 0, 250, 2)  # LWA_ALPHA
            except Exception:
                pass
            font = _gdi32.CreateFontW(-20, 0, 0, 0, 700, 0, 0, 0, 0,
                                      0, 0, 0, 0, "Segoe UI")
            if font:
                self._fonts.append(font)
            self._countdown_label = _user32.CreateWindowExW(
                0, "STATIC", self._countdown_text,
                0x50000000 | 0x10000000 | 0x00000001,  # CHILD|VISIBLE|CENTER
                0, 8, width, 36, hwnd, None, wc.hInstance, None)
            if font and self._countdown_label:
                _user32.SendMessageW(self._countdown_label, 0x0030, font, 1)
            return True

        def _countdown_wndproc_fn(self, hwnd, msg, w_param, l_param):
            if msg == 0x0010:  # WM_CLOSE: không cho đóng cửa sổ đếm lùi
                return 0
            if msg == 0x0138:  # WM_CTLCOLORSTATIC: chữ trắng trên nền tối
                try:
                    _gdi32.SetBkMode(w_param, 1)  # TRANSPARENT
                    _gdi32.SetTextColor(w_param, 0x00FFFFFF)
                    return self._bg_brush or 0
                except Exception:
                    pass
            return _user32.DefWindowProcW(hwnd, msg, w_param, l_param)

        def _create_window(self):
            self._wndproc = _WNDPROC(self._wndproc_fn)
            class_name = "MangoLockWindow"

            class _WNDCLASS(ctypes.Structure):
                # wintypes không có HCURSOR (giống vụ LRESULT ở trên):
                # handle con trỏ dùng HANDLE chung, đủ cho WNDCLASS.
                _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC),
                            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                            ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                            ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                            ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

            # Nền tối xanh đậm thay vì đen thuần, để chữ trắng nổi hơn
            # và trông bớt "cửa sổ hệ thống cũ". Giữ brush sống suốt đời
            # cửa sổ, vì WM_CTLCOLORSTATIC trả về chính brush này.
            self._bg_brush = _gdi32.CreateSolidBrush(0x00201A0B)  # #0B1A20
            wc = _WNDCLASS()
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = _kernel32.GetModuleHandleW(None)
            # Sửa kẹt 0.10.2: trước đây hCursor để 0 nên con trỏ chuột
            # tàng hình khi ở trên cửa sổ khóa (Quản trị viên báo "không thấy con
            # chuột" lúc 22:55). Đặt con trỏ mũi tên mặc định của hệ
            # thống; chỉ đặt restype HANDLE (không đặt argtypes) để
            # handle 64-bit không bị cắt về 32-bit.
            try:
                _user32.LoadCursorW.restype = wintypes.HANDLE
                wc.hCursor = _user32.LoadCursorW(None, 32512)  # IDC_ARROW
            except Exception:
                pass
            wc.hbrBackground = self._bg_brush
            wc.lpszClassName = class_name
            self._class_atom = _user32.RegisterClassW(ctypes.byref(wc))
            vx = _user32.GetSystemMetrics(76)
            vy = _user32.GetSystemMetrics(77)
            vw = _user32.GetSystemMetrics(78)
            vh = _user32.GetSystemMetrics(79)
            hwnd = _user32.CreateWindowExW(
                0x00000008 | 0x00000080,  # WS_EX_TOPMOST | WS_EX_TOOLWINDOW
                class_name, "MangoMCP — Máy đang khóa",
                0x80000000 | 0x10000000,  # WS_POPUP | WS_VISIBLE
                vx, vy, vw, vh, None, None, wc.hInstance, None)
            if not hwnd:
                return False
            self._hwnd = hwnd
            cx, cy = vx + vw // 2, vy + vh // 2
            # Font Segoe UI: tiêu đề lớn đậm, còn lại vừa đọc, không
            # dùng font hệ thống mặc định (nhỏ, xấu, là lý do giao diện
            # cũ bị chê). CreateFontW: chiều cao âm = cỡ điểm.
            def _font(height, weight):
                f = _gdi32.CreateFontW(height, 0, 0, 0, weight, 0, 0, 0, 0,
                                       0, 0, 0, 0, "Segoe UI")
                if f:
                    self._fonts.append(f)
                return f
            _f_title = _font(-36, 700)
            _f_hint = _font(-20, 400)
            _f_edit = _font(-22, 400)
            _f_btn = _font(-20, 700)
            _f_msg = _font(-18, 400)
            self._btn_font = _f_btn
            self._title = _user32.CreateWindowExW(
                0, "STATIC", "Agent đang sử dụng máy này",
                0x50000000 | 0x00000001, cx - 350, cy - 150, 700, 48, hwnd, None, wc.hInstance, None)
            if _f_title:
                _user32.SendMessageW(self._title, 0x0030, _f_title, 1)
            _pause = 15
            try:
                _pause = int(self.controller.pause_minutes) if self.controller else 15
            except Exception:
                _pause = 15
            self._hint = _user32.CreateWindowExW(
                0, "STATIC", f"Nhập mật khẩu để tạm dừng Agent {_pause} phút và dùng máy.",
                0x50000000 | 0x00000001, cx - 350, cy - 92, 700, 32, hwnd, None, wc.hInstance, None)
            if _f_hint:
                _user32.SendMessageW(self._hint, 0x0030, _f_hint, 1)
            self._edit = _user32.CreateWindowExW(
                0x00000200, "EDIT", "",  # WS_EX_CLIENTEDGE
                0x50000000 | 0x10000000 | 0x00000020 | 0x00000080,  # CHILD|VISIBLE|PASSWORD|BORDER
                cx - 210, cy - 34, 420, 44, hwnd, 101, wc.hInstance, None)
            if _f_edit:
                _user32.SendMessageW(self._edit, 0x0030, _f_edit, 1)
            # Nút vẽ tay (BS_OWNERDRAW): nền cam xoài, chữ trắng đậm,
            # vẽ ở WM_DRAWITEM. Nút hệ thống mặc định xám, chìm hẳn
            # trên nền tối nên trước đây nhìn như không có nút.
            self._btn = _user32.CreateWindowExW(
                0, "BUTTON", f"Tạm dừng Agent {_pause} phút",
                0x50000000 | 0x10000000 | 0x0000000B, cx - 160, cy + 30, 320, 48, hwnd, 102, wc.hInstance, None)
            self._msg_label = _user32.CreateWindowExW(
                0, "STATIC", "", 0x50000000 | 0x00000001,
                cx - 350, cy + 96, 700, 32, hwnd, None, wc.hInstance, None)
            if _f_msg:
                _user32.SendMessageW(self._msg_label, 0x0030, _f_msg, 1)
            _user32.SetForegroundWindow(hwnd)
            _user32.SetFocus(self._edit)
            return True

        def _set_msg(self, text):
            self._msg_is_error = "không đúng" in (text or "")
            if self._msg_label:
                try:
                    _user32.SetWindowTextW(self._msg_label, text)
                except Exception:
                    pass

        def _wndproc_fn(self, hwnd, msg, w_param, l_param):
            # WM_CLOSE / SC_CLOSE: không cho đóng cửa sổ khóa bằng Alt+F4.
            if msg == 0x0010:  # WM_CLOSE
                return 0
            if msg == _WM_SYSCOMMAND and (w_param & 0xFFF0) == 0xF060:  # SC_CLOSE
                return 0
            if msg == 0x0138:  # WM_CTLCOLORSTATIC: chữ trắng trên nền tối
                try:
                    _gdi32.SetBkMode(w_param, 1)  # TRANSPARENT
                    if l_param == self._msg_label:
                        # Thông báo lỗi đỏ, còn lại trắng.
                        _gdi32.SetTextColor(w_param, 0x006B6BFF if self._msg_is_error else 0x00FFFFFF)
                    elif l_param == self._hint:
                        _gdi32.SetTextColor(w_param, 0x00CBD5E1)  # xám nhạt
                    else:
                        _gdi32.SetTextColor(w_param, 0x00FFFFFF)
                    return self._bg_brush or 0
                except Exception:
                    pass
            if msg == 0x002B:  # WM_DRAWITEM: vẽ nút cam
                try:
                    if True:
                        class _RECT(ctypes.Structure):
                            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
                        class _DRAWITEM(ctypes.Structure):
                            _fields_ = [("CtlType", wintypes.UINT), ("CtlID", wintypes.UINT),
                                        ("itemID", wintypes.UINT), ("itemAction", wintypes.UINT),
                                        ("itemState", wintypes.UINT), ("hwndItem", wintypes.HWND),
                                        ("hDC", wintypes.HANDLE), ("rcItem", _RECT),
                                        ("itemData", ctypes.c_void_p)]
                        di = ctypes.cast(l_param, ctypes.POINTER(_DRAWITEM)).contents
                        if di.CtlID == 102:
                            pressed = bool(di.itemState & 0x0001)  # ODS_SELECTED
                            brush = _gdi32.CreateSolidBrush(0x000C58EA if pressed else 0x001673F9)
                            _user32.FillRect(di.hDC, ctypes.byref(di.rcItem), brush)
                            _gdi32.SetBkMode(di.hDC, 1)
                            _gdi32.SetTextColor(di.hDC, 0x00FFFFFF)
                            if getattr(self, "_btn_font", None):
                                _gdi32.SelectObject(di.hDC, self._btn_font)
                            _pause = 15
                            try:
                                _pause = int(self.controller.pause_minutes) if self.controller else 15
                            except Exception:
                                _pause = 15
                            _user32.DrawTextW(di.hDC, f"Tạm dừng Agent {_pause} phút", -1,
                                              ctypes.byref(di.rcItem), 0x00000025)
                            return 1
                except Exception:
                    pass
            if msg == 0x0111:  # WM_COMMAND: nút bấm
                if (w_param & 0xFFFF) == 102:
                    self._try_unlock_from_window()
                    return 0
            if msg == 0x0100 and w_param == _VK_RETURN:  # WM_KEYDOWN Enter
                try:
                    if _user32.GetFocus() == self._edit:
                        self._try_unlock_from_window()
                        return 0
                except Exception:
                    pass
            return _user32.DefWindowProcW(hwnd, msg, w_param, l_param)

        def _try_unlock_from_window(self):
            if not self.controller or not self._edit:
                return
            buf = ctypes.create_unicode_buffer(256)
            _user32.GetWindowTextW(self._edit, buf, 256)
            password = buf.value
            _user32.SetWindowTextW(self._edit, "")
            if self.controller.try_local_unlock(password):
                self.hide_lock_window()
            else:
                self._set_msg("Mật khẩu không đúng. Thử lại.")
                try:
                    _user32.SetFocus(self._edit)
                except Exception:
                    pass

    def make_adapter():
        return WinLockAdapter()

else:

    def make_adapter():
        return _NullAdapter()


def lock_paused_error(controller):
    """Lỗi chuẩn khi Agent bị tạm ngưng vì người dùng đã mở khóa tại máy."""
    remaining = 0.0
    try:
        remaining = controller.status()["paused_remaining_seconds"]
    except Exception:
        pass
    _mins = 15
    try:
        _mins = int(controller.pause_minutes) if controller is not None else 15
    except Exception:
        _mins = 15
    return MangoError(
        "LOCK_PAUSED",
        "Agent đang tạm ngưng vì người ngồi máy đã nhập đúng mật khẩu mở khóa. "
        f"Các tool thao tác và chụp màn hình sẽ chạy lại khi khóa lại sau {_mins} phút "
        "(hoặc khi người dùng nghỉ tay). Tool chỉ đọc trạng thái vẫn dùng được.",
        detail=f"paused_remaining_seconds: {remaining}",
        retryable=True,
    )
