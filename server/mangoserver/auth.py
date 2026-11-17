"""Xác thực của Mango Server 1.0.

4 loại credential (theo thiết kế §5). Mọi thứ chỉ lưu dạng hash SHA-256
trong auth.json; giá trị thô chỉ xuất hiện đúng 1 lần lúc tạo rồi đưa cho
người giữ, Server không lưu lại:

(a) Mật khẩu quản trị Server — Quản trị viên đặt, chỉ lưu hash. Dùng đăng nhập
    dashboard và làm mọi việc quản trị.
(b) Mã đăng ký (enrollment token) — dùng 1 lần, hạn ~24h, lưu hash.
    Máy mới dùng mã này đổi lấy credential máy bền vững; mã vô hiệu ngay
    sau khi dùng.
(c) Credential máy (machine_id + secret) — secret chỉ lưu hash trong
    registry.json; thu hồi/xoay được.
(d) Token Agent — mỗi Agent 1 token, gắn phạm vi (máy nào + nhóm tool
    nào), lưu hash, thu hồi được. Token của Quản trị viên = toàn quyền mọi máy.

Không có hàm nào ở đây trả về secret/token thô đã lưu (vì không lưu).
"""
import time

from .security import hash_matches, new_machine_id, new_token, sha256

ENROLLMENT_TTL_SECONDS = 24 * 3600  # mã đăng ký hết hạn sau 24 giờ (mặc định)
ENROLLMENT_TTL_MIN_SECONDS = 60          # 1 phút
ENROLLMENT_TTL_MAX_SECONDS = 30 * 24 * 3600  # 30 ngày
MACHINE_SECRET_TTL_SECONDS = 0      # 0 = credential máy không hết hạn


def _now() -> int:
    return int(time.time())


class AuthStore:
    """Quản lý mật khẩu quản trị + mã đăng ký + token Agent.

    `store` là JsonStore trỏ tới auth.json với cấu trúc:
      {"admin_password_sha256": str,
       "enrollment_tokens": [ {"token_sha256", "created_at", "expires_at",
                               "used": bool, "used_by": str|None, "label": str} ],
       "agent_tokens": [ {"id", "name", "token_sha256", "machines": [...],
                          "tool_groups": [...], "enabled": bool,
                          "created_at": int, "last_used_at": int} ]}
    """

    def __init__(self, store):
        self.store = store

    # ----- (a) Mật khẩu quản trị -----
    def admin_password_set(self) -> bool:
        return bool(str(self.store.data.get("admin_password_sha256", "")).strip())

    def set_admin_password(self, password: str):
        if not password or len(password) < 4:
            raise ValueError("Mat khau quan tri phai co it nhat 4 ky tu")
        self.store.data["admin_password_sha256"] = sha256(password)
        self.store.save()

    def verify_admin_password(self, password: str) -> bool:
        stored = str(self.store.data.get("admin_password_sha256", ""))
        return hash_matches(password or "", stored)

    # ----- (b) Mã đăng ký -----
    def get_enrollment_ttl(self) -> int:
        """Hạn mã đăng ký (giây) từ settings trong auth.json.
        Mặc định ENROLLMENT_TTL_SECONDS; giá trị ngoài khoảng cho phép
        thì rơi về mặc định (fail-safe)."""
        try:
            value = int(self.store.data.get("settings", {}).get(
                "enrollment_ttl_seconds", ENROLLMENT_TTL_SECONDS))
        except (TypeError, ValueError):
            return ENROLLMENT_TTL_SECONDS
        if ENROLLMENT_TTL_MIN_SECONDS <= value <= ENROLLMENT_TTL_MAX_SECONDS:
            return value
        return ENROLLMENT_TTL_SECONDS

    def set_enrollment_ttl(self, seconds: int):
        """Đổi hạn mã đăng ký. `seconds` phải là số nguyên
        60..2592000 (1 phút..30 ngày), ngược lại raise ValueError."""
        seconds = int(seconds)
        if not ENROLLMENT_TTL_MIN_SECONDS <= seconds <= ENROLLMENT_TTL_MAX_SECONDS:
            raise ValueError(
                "Han ma dang ky phai tu 60 den 2592000 giay (1 phut..30 ngay)")
        self.store.data.setdefault("settings", {})["enrollment_ttl_seconds"] = seconds
        self.store.save()

    def create_enrollment_token(self, label: str = "") -> str:
        """Tạo mã đăng ký mới, trả về mã thô (chỉ hiện 1 lần này)."""
        token = new_token(24)
        rec = {
            "token_sha256": sha256(token),
            "label": label or "",
            "created_at": _now(),
            "expires_at": _now() + self.get_enrollment_ttl(),
            "used": False,
            "used_by": None,
        }
        self.store.data.setdefault("enrollment_tokens", []).append(rec)
        self.store.save()
        return token

    def list_enrollment_tokens(self):
        out = []
        for rec in self.store.data.get("enrollment_tokens", []):
            out.append({
                "label": rec.get("label", ""),
                "created_at": rec.get("created_at", 0),
                "expires_at": rec.get("expires_at", 0),
                "used": bool(rec.get("used", False)),
                "used_by": rec.get("used_by"),
                "expired": _now() > int(rec.get("expires_at", 0)),
            })
        return out

    def revoke_enrollment_token(self, token_sha256: str) -> bool:
        for rec in self.store.data.get("enrollment_tokens", []):
            if rec.get("token_sha256") == token_sha256:
                rec["used"] = True
                rec["used_by"] = rec.get("used_by") or "revoked"
                self.store.save()
                return True
        return False

    def consume_enrollment_token(self, token: str):
        """Kiểm tra + vô hiệu mã đăng ký. Trả bản ghi nếu hợp lệ, None nếu
        không hợp lệ / hết hạn / đã dùng. Mã chỉ dùng được 1 lần."""
        if not token:
            return None
        digest = sha256(token)
        for rec in self.store.data.get("enrollment_tokens", []):
            if rec.get("token_sha256") == digest:
                if rec.get("used"):
                    return None
                if _now() > int(rec.get("expires_at", 0)):
                    return None
                rec["used"] = True
                self.store.save()
                return rec
        return None

    # ----- (d) Token Agent -----
    def create_agent_token(self, name: str, machines, tool_groups):
        """Tạo token Agent mới. `machines`: ["*"] (mọi máy) hoặc danh sách
        machine_id. `tool_groups`: subset của {"read","control","files",
        "admin"}. Trả (bản ghi công khai, token thô chỉ hiện 1 lần)."""
        token = "mango_agent_" + new_token(24)
        rec = {
            "id": "agent_" + new_token(6).replace("-", "").replace("_", "")[:12],
            "name": name or "agent",
            "token_sha256": sha256(token),
            "machines": list(machines or []),
            "tool_groups": list(tool_groups or []),
            "enabled": True,
            "created_at": _now(),
            "last_used_at": 0,
        }
        self.store.data.setdefault("agent_tokens", []).append(rec)
        self.store.save()
        return rec, token

    def list_agent_tokens(self):
        out = []
        for rec in self.store.data.get("agent_tokens", []):
            out.append({
                "id": rec.get("id"),
                "name": rec.get("name"),
                "machines": list(rec.get("machines", [])),
                "tool_groups": list(rec.get("tool_groups", [])),
                "enabled": bool(rec.get("enabled", True)),
                "created_at": rec.get("created_at", 0),
                "last_used_at": rec.get("last_used_at", 0),
            })
        return out

    def verify_agent_token(self, token: str):
        """Trả bản ghi token nếu hợp lệ + đang bật, ngược lại None.
        Cập nhật last_used_at tối đa 1 lần/phút."""
        if not token:
            return None
        digest = sha256(token)
        for rec in self.store.data.get("agent_tokens", []):
            if rec.get("token_sha256") == digest and rec.get("enabled", True):
                now = _now()
                if now - int(rec.get("last_used_at", 0)) > 60:
                    rec["last_used_at"] = now
                    self.store.save()
                return rec
        return None

    def set_agent_token_enabled(self, token_id: str, enabled: bool) -> bool:
        for rec in self.store.data.get("agent_tokens", []):
            if rec.get("id") == token_id:
                rec["enabled"] = bool(enabled)
                self.store.save()
                return True
        return False

    def delete_agent_token(self, token_id: str) -> bool:
        before = len(self.store.data.get("agent_tokens", []))
        self.store.data["agent_tokens"] = [
            r for r in self.store.data.get("agent_tokens", [])
            if r.get("id") != token_id
        ]
        if len(self.store.data.get("agent_tokens", [])) != before:
            self.store.save()
            return True
        return False


def make_machine_credential():
    """Sinh credential máy bền vững: (machine_id, secret thô).
    Secret chỉ hiện 1 lần này; Server chỉ lưu hash của nó."""
    return new_machine_id(), new_token(32)
