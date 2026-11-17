"""Cấu hình MangoMCP: cổng quyền, allowlist mở app, token dạng hash,
và (bản 0.6.0) hệ thống credential cho từng ứng dụng khách (App ID + Secret)
để các client như Gemini kết nối bằng danh tính riêng, phạm vi quyền riêng.
Bản 0.10.0 (Quản trị viên chốt 26/10/2026): token chủ chuyển thành mật khẩu
chủ (master password), đặt/cấu hình trong app MangoMCP-Config. Mật khẩu
chủ chỉ để mở app cấu hình và làm quyền chủ của server; Agent điều khiển
bằng App ID + Secret riêng tạo ở tab Ứng dụng khách — hai loại này tách
biệt, không dùng lẫn. Khi đã đặt mật khẩu chủ thì token chủ cũ không còn
hiệu lực; khi chưa đặt thì token chủ cũ vẫn dùng được để đăng nhập app
lần đầu và đặt mật khẩu mới (đường chuyển đổi, tránh khóa chết chủ máy).
"""
import hashlib
import hmac
import json
import os
import secrets
import time
from contextvars import ContextVar
from pathlib import Path

DEFAULT_CONFIG = {
    "permissions": {
        "input": True,
        "files_read": True,
        "files_write": True,
        "clipboard": False,
        "admin": False,
    },
    "launch_allowlist": [
        "mspaint.exe",
        "notepad.exe",
        "calc.exe",
        "explorer.exe",
    ],
    "audit_log": "logs/audit.jsonl",
    "clients": [],
    # Mật khẩu chủ (0.10.0): chỉ lưu hash. Rỗng = chưa đặt, lúc đó
    # token_sha256 cũ vẫn dùng được để đăng nhập và đặt mật khẩu mới.
    "master_password_sha256": "",
    # Chế độ khóa máy (0.9.0, 0.10.0 đổi mặc định, 0.12.0 thêm chế độ
    # hiện): bật nút "cho phép bot điều khiển" thì màn hình local chỉ
    # còn giao diện nhập pass mở khóa (black_window), Agent toàn quyền,
    # người ngồi máy nhập đúng pass thì Agent tạm ngưng 15 phút rồi
    # khóa lại. screen_mode "visible" thì KHÔNG khóa màn hình: Agent
    # thao tác gì người ngồi máy cũng thấy hết, không nuốt chuột/phím,
    # không có tạm ngưng (vì không có ô mở khóa). Chỉ lưu hash.
    "lock": {
        "enabled": False,
        "password_sha256": "",
        "pause_minutes": 15,
        "screen_mode": "black_window",
    },
    # Shell Tunnel (0.11.0): SSH server rieng chay cung tien trinh
    # MangoMCP, dang nhap bang AppID.Secret cua client, kem SFTP.
    # Mac dinh TAT, bat bang cong tac trong app cau hinh. Co tinh
    # vuot qua scopes/allowlist (toan quyen) nhung van ghi audit.
    "tunnel": {
        "enabled": False,
        "host": "127.0.0.1",
        "port": 8768,
        "shell": "cmd.exe",
    },
    # agent-desktop (0.13.0): binary CLI đọc cây UI Automation của Windows
    # (Vercel Labs v1.2.0), dùng cho các tool desktop_* — snapshot cây giao
    # diện rồi thao tác theo ref, thay cho chụp ảnh + đoán tọa độ. Binary
    # đi kèm gói cài đặt tại C:\MangoMCP\bin\agent-desktop.exe.
    "desktop_binary": r"C:\MangoMCP\bin\agent-desktop.exe",
    # Dieu khien Core/Agent (0.14.0): Core chay session 0 (SYSTEM, boot),
    # Agent chay trong session nguoi dung khi control_login. IPC chi
    # localhost (127.0.0.1:8767). login_timeout_seconds la thoi gian cho
    # Agent noi IPC ve sau khi mo (giay).
    "control": {
        "ipc_host": "127.0.0.1",
        "ipc_port": 8767,
        "login_timeout_seconds": 30,
    },
    # Danh sach user Windows (0.14.2): cac tai khoan dung de dang nhap /
    # auto-logon / switch tren may. Entry dau tien (index 0) la tai
    # khoan so 1 = mac dinh. CANH BAO: password luu PLAINTEXT trong
    # config.json vi auto-logon BAT BUOC can plaintext (registry
    # DefaultPassword cung plaintext — tradeoff da biet cua auto-logon
    # Windows). Ai doc duoc file nay deu thay duoc mat khau.
    "users": [],
}

PERMISSION_GROUPS = ["input", "files_read", "files_write", "clipboard", "admin"]

# Danh tính của request hiện tại (master hoặc một client cụ thể).
# Middleware xác thực đặt biến này; tầng core dùng nó để áp phạm vi
# quyền riêng của client bên cạnh cổng quyền toàn cục.
CURRENT_AUTH = ContextVar("mangomcp_current_auth", default=None)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Config:
    def __init__(self, data, base_dir, path=None):
        self.data = data
        self.base_dir = Path(base_dir)
        self.path = Path(path) if path else None
        self._mtime = self.path.stat().st_mtime if self.path and self.path.exists() else 0

    @classmethod
    def load(cls):
        path = os.environ.get("MANGO_MCP_CONFIG")
        if path:
            p = Path(path)
            data = json.loads(p.read_text(encoding="utf-8"))
            return cls(_merge(DEFAULT_CONFIG, data), p.parent, p)
        return cls(json.loads(json.dumps(DEFAULT_CONFIG)), Path.cwd())

    @classmethod
    def load_from(cls, path):
        """Client 2.0: nap config tu 1 file cu the (server-client.json
        hop nhat). Gop voi DEFAULT_CONFIG; neu file chua co thi dung
        mac dinh va ghi duong dan de save() ghi lai dung cho."""
        p = Path(path)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8-sig"))
            return cls(_merge(DEFAULT_CONFIG, data), p.parent, p)
        return cls(json.loads(json.dumps(DEFAULT_CONFIG)), p.parent, p)

    def save(self):
        """Ghi cấu hình hiện tại xuống file JSON (nếu biết đường dẫn)."""
        if self.path is None:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)
        return True

    def reload_if_changed(self):
        """Nạp lại cấu hình khi file config.json bị sửa từ bên ngoài.

        Nhờ cơ chế này, app desktop MangoMCP-Config.exe chỉ cần ghi file
        là server áp dụng ngay (client mới, cổng quyền mới) trong vài
        giây, không cần khởi động lại. Trả True nếu vừa nạp lại."""
        if self.path is None or not self.path.exists():
            return False
        try:
            mtime = self.path.stat().st_mtime
            if mtime == self._mtime:
                return False
            raw = self.path.read_text(encoding="utf-8-sig")
            fresh = _merge(DEFAULT_CONFIG, json.loads(raw))
            self.data = fresh
            self._mtime = mtime
            return True
        except Exception:
            return False



    # ----- Cổng quyền + allowlist (trang cấu hình ghi vào đây) -----

    def permission(self, group):
        return bool(self.data.get("permissions", {}).get(group, False))

    def set_permission(self, group, value):
        if group not in PERMISSION_GROUPS:
            raise ValueError(f"Nhóm quyền lạ: {group}")
        self.data.setdefault("permissions", {})[group] = bool(value)
        self.save()

    def launch_allowlist(self):
        return [x.lower() for x in self.data.get("launch_allowlist", [])]

    def set_allowlist(self, items):
        cleaned = []
        for item in items:
            item = str(item).strip()
            if item and item not in cleaned:
                cleaned.append(item)
        self.data["launch_allowlist"] = cleaned
        self.save()

    # ----- Chế độ khóa máy (0.9.0) -----

    def lock_settings(self):
        data = self.data.get("lock", {}) or {}
        return {
            "enabled": bool(data.get("enabled", False)),
            "password_set": bool(data.get("password_sha256", "")),
            "pause_minutes": data.get("pause_minutes", 15),
            "screen_mode": data.get("screen_mode", "black_window"),
        }

    def set_bot_control(self, enabled):
        """Nút 'cho phép bot điều khiển' (0.10.0, 0.12.0 giữ nguyên
        chế độ màn hình đã chọn): bật là áp dụng chế độ màn hình
        trong screen_mode (black_window khóa đen, monitor_off tắt
        màn hình, visible hiện mọi thao tác của Agent); tắt là mở
        khóa lại cho người ngồi máy dùng bình thường. Trả False nếu
        bật mà chưa đặt mật khẩu khóa máy (tránh khóa chết máy)."""
        enabled = bool(enabled)
        lock_data = self.data.setdefault("lock", {})
        if enabled and not str(lock_data.get("password_sha256", "")).strip():
            return False
        lock_data["enabled"] = enabled
        self.save()
        return True

    def set_lock_screen_mode(self, mode):
        """Đặt cách che màn hình (0.12.0): 'black_window', 'monitor_off'
        hoặc 'visible' (hiện mọi thao tác của Agent, không khóa màn
        hình). Trả False nếu giá trị không hợp lệ."""
        if mode not in ("black_window", "monitor_off", "visible"):
            return False
        self.data.setdefault("lock", {})["screen_mode"] = mode
        self.save()
        return True

    def set_lock_password(self, password):
        """Đặt mật khẩu khóa máy; chỉ lưu hash, trả False nếu pass rỗng."""
        password = (password or "").strip()
        if not password:
            return False
        self.data.setdefault("lock", {})["password_sha256"] = _sha256(password)
        self.save()
        return True

    def set_lock_enabled(self, enabled):
        self.data.setdefault("lock", {})["enabled"] = bool(enabled)
        self.save()

    def set_lock_pause_minutes(self, minutes):
        self.data.setdefault("lock", {})["pause_minutes"] = max(1, int(minutes))
        self.save()

    # ----- Shell Tunnel (0.11.0) -----

    def tunnel_settings(self):
        data = self.data.get("tunnel", {}) or {}
        try:
            port = int(data.get("port", 8768))
        except Exception:
            port = 8768
        if port < 1 or port > 65535:
            port = 8768
        return {
            "enabled": bool(data.get("enabled", False)),
            "host": str(data.get("host", "127.0.0.1") or "127.0.0.1"),
            "port": port,
            "shell": str(data.get("shell", "cmd.exe") or "cmd.exe"),
        }

    def set_tunnel(self, enabled, port=8768, host="127.0.0.1"):
        try:
            port = int(port)
        except Exception:
            port = 8768
        if port < 1 or port > 65535:
            raise ValueError("Cong tunnel phai tu 1 den 65535")
        host = str(host or "").strip() or "127.0.0.1"
        self.data["tunnel"] = {"enabled": bool(enabled), "host": host,
                               "port": port, "shell": "cmd.exe"}
        self.save()

    def authenticate_tunnel(self, client_id, secret):
        """Xac thuc SSH tunnel: CHI client AppID.Secret, khong dung
        mat khau chu (mat khau chu chi mo app cau hinh). Chi doc,
        khong cap nhat last_used_at de tranh ghi de config tu luong
        tunnel. Tra ban ghi client hoac None."""
        client_id = (client_id or "").strip()
        secret = (secret or "").strip()
        if not client_id or not secret:
            return None
        record = self.find_client(client_id)
        if record and record.get("enabled", True):
            if hmac.compare_digest(_sha256(secret), str(record.get("secret_sha256", ""))):
                return record
        return None

    # ----- agent-desktop (0.13.0) -----

    def desktop_binary(self):
        """Đường dẫn binary agent-desktop (config `desktop_binary`).

        Trả mặc định C:\\MangoMCP\\bin\\agent-desktop.exe khi config chưa
        ghi gì, để bản cài cũ (chưa có key này) vẫn tìm đúng binary mới."""
        path = str(self.data.get("desktop_binary", "") or "").strip()
        return path or r"C:\MangoMCP\bin\agent-desktop.exe"

    # ----- Dieu khien Core/Agent (0.14.0) -----

    def control_settings(self):
        """Cau hinh IPC Core<->Agent (config `control`).

        Tra {"ipc_host", "ipc_port", "login_timeout_seconds"}; sai so
        thi ve mac dinh 127.0.0.1:8767 / 30 giay. Ban cai cu (chua co
        key `control`) van chay dung mac dinh."""
        data = self.data.get("control", {}) or {}
        try:
            port = int(data.get("ipc_port", 8767))
        except Exception:
            port = 8767
        if port < 1 or port > 65535:
            port = 8767
        try:
            login_timeout = int(data.get("login_timeout_seconds", 30))
        except Exception:
            login_timeout = 30
        login_timeout = max(5, min(login_timeout, 300))
        return {
            "ipc_host": str(data.get("ipc_host", "127.0.0.1") or "127.0.0.1"),
            "ipc_port": port,
            "login_timeout_seconds": login_timeout,
        }

    def audit_log_path(self):
        p = Path(self.data.get("audit_log", "logs/audit.jsonl"))
        return p if p.is_absolute() else self.base_dir / p

    # ----- Mật khẩu chủ (master password, 0.10.0) -----

    def master_password_set(self):
        return bool(str(self.data.get("master_password_sha256", "")).strip())

    def set_master_password(self, password):
        """Đặt mật khẩu chủ; chỉ lưu hash, trả False nếu pass quá ngắn.

        Khi đã đặt, token chủ cũ lập tức hết hiệu lực (xem token_sha256).
        Mật khẩu chủ khác mật khẩu khóa máy và khác Secret của client."""
        password = (password or "").strip()
        if len(password) < 4:
            return False
        self.data["master_password_sha256"] = _sha256(password)
        self.save()
        return True

    def clear_master_password(self):
        """Xóa mật khẩu chủ: quay lại dùng token chủ cũ (nếu còn)."""
        self.data["master_password_sha256"] = ""
        self.save()

    def token_sha256(self):
        """Hash của credential chủ duy nhất đang có hiệu lực.

        Ưu tiên mật khẩu chủ (0.10.0): nếu đã đặt thì CHỈ mật khẩu đó
        mới xác thực được, token chủ cũ bị bỏ qua hoàn toàn. Chưa đặt
        thì dùng token chủ cũ (env hoặc file) như trước, để chủ máy
        còn đăng nhập được và đặt mật khẩu mới."""
        master_pw = str(self.data.get("master_password_sha256", "")).strip()
        if master_pw:
            return master_pw
        env_hash = os.environ.get("MANGO_MCP_TOKEN_SHA256", "").strip()
        if env_hash:
            return env_hash
        env_token = os.environ.get("MANGO_MCP_TOKEN", "").strip()
        if env_token:
            return _sha256(env_token)
        return str(self.data.get("token_sha256", "")).strip()

    def install_id(self):
        iid = str(self.data.get("install_id", "")).strip()
        if not iid:
            iid = secrets.token_hex(8)
            self.data["install_id"] = iid
            self.save()
        return iid

    # ----- Client (App ID + Secret) cho Gemini và các MCP client khác -----

    def clients(self):
        return self.data.setdefault("clients", [])

    def find_client(self, client_id):
        for c in self.clients():
            if c.get("id") == client_id:
                return c
        return None

    def create_client(self, name, scopes):
        """Tạo client mới; trả (bản ghi công khai, credential đầy đủ).

        Credential có dạng "<client_id>.<secret>" để dán thẳng vào ô
        Bearer token của bất kỳ MCP client nào. Secret thô chỉ xuất hiện
        đúng một lần ở đây; server chỉ lưu hash SHA-256 của nó."""
        name = (name or "").strip() or "client"
        scopes = [g for g in (scopes or []) if g in PERMISSION_GROUPS]
        client_id = "mango_" + secrets.token_hex(6)
        secret = secrets.token_urlsafe(32)
        record = {
            "id": client_id,
            "name": name,
            "secret_sha256": _sha256(secret),
            "scopes": scopes,
            "enabled": True,
            "created_at": int(time.time()),
            "last_used_at": 0,
        }
        self.clients().append(record)
        self.save()
        return record, f"{client_id}.{secret}"

    def rotate_client_secret(self, client_id):
        record = self.find_client(client_id)
        if record is None:
            return None, None
        secret = secrets.token_urlsafe(32)
        record["secret_sha256"] = _sha256(secret)
        self.save()
        return record, f"{client_id}.{secret}"

    def set_client_enabled(self, client_id, enabled):
        record = self.find_client(client_id)
        if record is None:
            return False
        record["enabled"] = bool(enabled)
        self.save()
        return True

    def delete_client(self, client_id):
        before = len(self.clients())
        self.data["clients"] = [c for c in self.clients() if c.get("id") != client_id]
        if len(self.data["clients"]) != before:
            self.save()
            return True
        return False

    def authenticate(self, bearer: str, client_id_header: str = ""):
        """Xác thực một request. Trả dict danh tính hoặc None.

        Chấp nhận 3 dạng:
        - Bearer = mật khẩu chủ (master password, 0.10.0; khi chưa đặt
          thì là token chủ cũ) -> {"kind": "master"}
        - Bearer = "<client_id>.<secret>" -> {"kind": "client", ...}
          (credential điều khiển của Agent, tách biệt mật khẩu chủ)
        - Header X-Client-Id + Bearer = secret thô của client đó.
        """
        bearer = (bearer or "").strip()
        if not bearer:
            return None
        master = self.token_sha256()
        if master and hmac.compare_digest(_sha256(bearer), master):
            return {"kind": "master", "name": "Master password"}
        client_id, secret = "", ""
        if client_id_header:
            client_id, secret = client_id_header.strip(), bearer
        elif "." in bearer:
            client_id, secret = bearer.split(".", 1)
        if client_id and secret:
            record = self.find_client(client_id)
            if record and record.get("enabled", True):
                if hmac.compare_digest(_sha256(secret), str(record.get("secret_sha256", ""))):
                    now = int(time.time())
                    if now - int(record.get("last_used_at", 0)) > 60:
                        record["last_used_at"] = now
                        self.save()
                    return {"kind": "client", "name": record.get("name", client_id),
                            "client": record}
        return None

    def client_public(self, record):
        return {
            "id": record.get("id"),
            "name": record.get("name"),
            "scopes": record.get("scopes", []),
            "enabled": bool(record.get("enabled", True)),
            "created_at": record.get("created_at", 0),
            "last_used_at": record.get("last_used_at", 0),
        }


def _merge(base, override):
    out = json.loads(json.dumps(base))
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out



def watch_config(config, interval: float = 2.0):
    """Luồng nền theo dõi config.json (gọi từ server.main)."""
    import threading
    import time as _time

    def _loop():
        while True:
            _time.sleep(interval)
            try:
                if config.reload_if_changed():
                    print("[config] da nap lai cau hinh tu file", flush=True)
            except Exception as exc:
                print("[config] loi nap lai cau hinh:", exc, flush=True)

    thread = threading.Thread(target=_loop, daemon=True, name="mangomcp-config-watch")
    thread.start()
    return thread
