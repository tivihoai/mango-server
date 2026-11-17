"""Lưu trữ file của Mango Server 1.0.

Mọi dữ liệu Server (registry máy, hash token, audit) lưu thành file trong
thư mục data của Server (mặc định ./data, trên máy ảo là
C:\\MangoMCPServer\\data) để dễ backup bằng cách copy file.

- registry.json : danh sách máy (machine_id, tên, bản, trạng thái...).
- auth.json     : hash mật khẩu quản trị, mã đăng ký, token Agent.
- audit.jsonl   : nhật ký metadata (mỗi dòng 1 sự kiện).

Ghi file theo kiểu nguyên tử (ghi file tạm rồi đổi tên) để không rách file
khi Server bị tắt đột ngột. Dùng khóa threading để tránh 2 luồng ghi đè.
"""
import json
import os
import threading
import time
from pathlib import Path


def _utcnow_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class JsonStore:
    """Một file JSON: đọc/lười ghi, khóa luồng, ghi nguyên tử."""

    def __init__(self, path, default):
        self.path = Path(path)
        self._default = default
        self._lock = threading.Lock()
        self.data = self._load()

    def _load(self):
        try:
            if self.path.exists():
                raw = self.path.read_text(encoding="utf-8-sig")
                if raw.strip():
                    loaded = json.loads(raw)
                    if isinstance(loaded, dict) and isinstance(self._default, dict):
                        merged = dict(self._default)
                        merged.update(loaded)
                        return merged
                    return loaded
        except Exception:
            pass
        return json.loads(json.dumps(self._default))

    def save(self):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)

    def get(self, key, default=None):
        with self._lock:
            return self.data.get(key, default)


class AuditLog:
    """Nhật ký metadata (JSONL). Chỉ ghi metadata, KHÔNG ghi tham số đầy
    đủ và KHÔNG ghi bí mật — mọi giá trị nhạy cảm đã được che trước khi
    gọi hàm này (xem security.redact / summarize_args)."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, event: str, **fields):
        entry = {"ts": _utcnow_iso(), "event": event}
        entry.update(fields)
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # Audit không bao giờ được làm hỏng thao tác chính

    def read_last(self, limit: int = 200):
        """Đọc tối đa `limit` dòng cuối (mới nhất trước)."""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        out = []
        for line in reversed(lines[-limit:]):
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out
