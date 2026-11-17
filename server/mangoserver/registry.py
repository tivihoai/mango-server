"""Registry máy của Mango Server 1.0.

Mỗi máy 1 bản ghi trong registry.json:
  {"machine_id", "name", "version", "status", "secret_sha256",
   "created_at", "last_heartbeat", "last_ip", "agent_connected",
   "approved_by", "approved_at"}

Trạng thái (status):
- "pending"  : mới enroll, CHỜ SẾP DUYỆT (mặc định theo thiết kế).
- "approved" : Quản trị viên đã duyệt, được điều khiển qua machine_call.
- "rejected" : Quản trị viên từ chối (máy lạ). Không được điều khiển.
- "revoked"  : đã thu hồi credential. Máy đó nối lại sẽ bị từ chối.

Online/offline: máy gửi heartbeat ~30s; quá 90s không thấy heartbeat thì
coi là offline. Trạng thái online chỉ là suy ra từ last_heartbeat, không
lưu riêng.
"""
import time

from .security import sha256

HEARTBEAT_TIMEOUT_SECONDS = 90  # quá 90s không heartbeat => offline


def _now() -> int:
    return int(time.time())


class Registry:
    def __init__(self, store):
        self.store = store

    def _machines(self):
        return self.store.data.setdefault("machines", {})

    def enroll(self, name: str, version: str, secret: str, machine_id: str):
        """Ghi máy mới vào registry ở trạng thái pending. Trả bản ghi."""
        now = _now()
        rec = {
            "machine_id": machine_id,
            "name": (name or machine_id).strip() or machine_id,
            "version": version or "",
            "status": "pending",
            "secret_sha256": sha256(secret),
            "created_at": now,
            "last_heartbeat": 0,
            "last_ip": "",
            "agent_connected": False,
            "approved_by": None,
            "approved_at": 0,
            # Field 1.1 (Nấc 2): client báo qua heartbeat, Server lưu.
            "client_version": "",
            "reported_tools": [],
            "desired_scope": None,
            "target_version": None,
            "upgrade_status": "",
            "upgrade_status_at": 0,
            "last_seen_scope_at": 0,
        }
        self._machines()[machine_id] = rec
        self.store.save()
        return rec

    def get(self, machine_id: str):
        return self._machines().get(machine_id)

    def verify_machine(self, machine_id: str, secret: str):
        """Kiểm tra credential máy. Trả bản ghi nếu đúng secret và chưa bị
        thu hồi; ngược lại None. Máy pending/rejected vẫn xác thực được
        (để gửi heartbeat và hiện trong dashboard) nhưng không được gọi
        machine_call cho tới khi approved."""
        rec = self._machines().get(machine_id)
        if not rec or not secret:
            return None
        if rec.get("status") == "revoked":
            return None
        if sha256(secret) != str(rec.get("secret_sha256", "")):
            return None
        return rec

    def update_reported(self, machine_id: str, client_version=None,
                        allowed_tools=None):
        """Lưu thông tin client báo qua heartbeat (Nấc 2, §2.2).
        `client_version`/`allowed_tools` là None khi client 1.0 không gửi
        (giữ nguyên giá trị cũ). Trả bản ghi hoặc None."""
        rec = self._machines().get(machine_id)
        if not rec:
            return None
        changed = False
        if client_version is not None:
            rec["client_version"] = str(client_version or "")
            changed = True
        if allowed_tools is not None:
            if not isinstance(allowed_tools, list):
                allowed_tools = []
            rec["reported_tools"] = [str(t) for t in allowed_tools]
            rec["last_seen_scope_at"] = _now()
            changed = True
        if changed:
            self.store.save()
        return rec

    def sync_name(self, machine_id: str, hostname) -> bool:
        """Đồng bộ tên máy theo hostname thực tế (dashboard 1.2.x).

        Monitor gọi sau mỗi lượt lấy system_info: tên Windows đổi thì
        dashboard hiện tên mới ngay lượt quét sau, không cần enroll lại.
        Chỉ cập nhật khi hostname là chuỗi không rỗng và khác tên hiện
        tại. Không đổi machine_id hay trường nào khác. Trả True nếu đã
        đổi tên, False nếu không đổi/không tìm thấy máy."""
        if not isinstance(hostname, str):
            return False
        hostname = hostname.strip()
        if not hostname:
            return False
        rec = self._machines().get(machine_id)
        if not rec:
            return False
        if rec.get("name") == hostname:
            return False
        rec["name"] = hostname
        self.store.save()
        return True

    def set_desired_scope(self, machine_id: str, scope) -> bool:
        """Đặt scope Quản trị viên muốn cho máy (Nấc 2, §2.3). `scope` phải là
        list[str], mỗi phần tử là tên tool không rỗng; scope rỗng [] =
        cấm hết (cho phép, Quản trị viên tự chịu). Sai định dạng -> ValueError.
        Trả False nếu không tìm thấy máy."""
        if (not isinstance(scope, list)
                or any(not isinstance(t, str) or not t.strip() for t in scope)):
            raise ValueError("desired_scope phai la danh sach ten tool (chuoi khong rong)")
        rec = self._machines().get(machine_id)
        if not rec:
            return False
        rec["desired_scope"] = [t.strip() for t in scope]
        self.store.save()
        return True

    def set_target_version(self, machine_id: str, version) -> bool:
        """Đặt bản client đích Quản trị viên muốn máy nâng cấp tới (None = xóa).
        Trả False nếu không tìm thấy máy."""
        rec = self._machines().get(machine_id)
        if not rec:
            return False
        rec["target_version"] = (str(version).strip() or None) if version is not None else None
        self.store.save()
        return True

    def set_upgrade_status(self, machine_id: str, status: str) -> bool:
        """Cập nhật trạng thái nâng cấp client báo về: "" | "downloading" |
        "applying" | "done" | "failed" | "restarting". Trạng thái lạ bị
        bỏ qua (trả False). Trả False nếu không tìm thấy máy."""
        if status not in ("", "downloading", "applying", "done", "failed",
                          "restarting"):
            return False
        rec = self._machines().get(machine_id)
        if not rec:
            return False
        rec["upgrade_status"] = status
        rec["upgrade_status_at"] = _now()
        self.store.save()
        return True

    def machines_with_target(self, version: str):
        """Danh sách machine_id đang có target_version == version
        (dùng để chặn xóa gói đang là đích nâng cấp)."""
        return [m_id for m_id, rec in self._machines().items()
                if rec.get("target_version") == version]

    def heartbeat(self, machine_id: str, version: str = "",
                  agent_connected: bool = False, ip: str = ""):
        rec = self._machines().get(machine_id)
        if not rec:
            return None
        rec["last_heartbeat"] = _now()
        if version:
            rec["version"] = version
        rec["agent_connected"] = bool(agent_connected)
        if ip:
            rec["last_ip"] = ip
        self.store.save()
        return rec

    def set_status(self, machine_id: str, status: str, by: str = "") -> bool:
        """Đổi trạng thái máy: pending/approved/rejected/revoked.
        Chỉ dashboard/CLI (quản trị) được gọi, không phải máy tự đổi."""
        if status not in ("pending", "approved", "rejected", "revoked"):
            return False
        rec = self._machines().get(machine_id)
        if not rec:
            return False
        rec["status"] = status
        if status == "approved":
            rec["approved_by"] = by or "admin"
            rec["approved_at"] = _now()
        self.store.save()
        return True

    def rotate_secret(self, machine_id: str, new_secret: str) -> bool:
        """Xoay secret của máy (credential cũ hết hiệu lực ngay)."""
        rec = self._machines().get(machine_id)
        if not rec:
            return False
        rec["secret_sha256"] = sha256(new_secret)
        self.store.save()
        return True

    def delete(self, machine_id: str) -> bool:
        if machine_id in self._machines():
            del self._machines()[machine_id]
            self.store.save()
            return True
        return False

    def is_online(self, rec, now: int = None) -> bool:
        if not rec:
            return False
        if now is None:
            now = _now()
        last = int(rec.get("last_heartbeat", 0))
        return last > 0 and (now - last) <= HEARTBEAT_TIMEOUT_SECONDS

    def public(self, rec, now: int = None):
        """Bản ghi máy đã lược bỏ secret (dùng trả cho MCP/dashboard).
        Không bao giờ chứa secret_sha256 hay secret thô."""
        if not rec:
            return None
        return {
            "machine_id": rec.get("machine_id"),
            "name": rec.get("name"),
            "version": rec.get("version", ""),
            "status": rec.get("status"),
            "online": self.is_online(rec, now),
            "last_heartbeat": rec.get("last_heartbeat", 0),
            "last_ip": rec.get("last_ip", ""),
            "agent_connected": bool(rec.get("agent_connected", False)),
            "created_at": rec.get("created_at", 0),
            "approved_at": rec.get("approved_at", 0),
            # Field 1.1 (Nấc 2) — không bao giờ chứa secret.
            "client_version": rec.get("client_version", ""),
            "reported_tools": list(rec.get("reported_tools") or []),
            "desired_scope": rec.get("desired_scope"),
            "target_version": rec.get("target_version"),
            "upgrade_status": rec.get("upgrade_status", ""),
            "upgrade_status_at": rec.get("upgrade_status_at", 0),
            "last_seen_scope_at": rec.get("last_seen_scope_at", 0),
        }

    def list_public(self):
        now = _now()
        return [self.public(r, now) for r in self._machines().values()]
