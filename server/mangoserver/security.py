"""Hàm bảo mật dùng chung cho Mango Server 1.0.

Luật cứng: secret/password/token thô KHÔNG BAO GIỜ được ghi vào log,
audit hay file nào khác ngoài bộ nhớ lúc tạo. Server chỉ lưu SHA-256.
So sánh hash bằng hmac.compare_digest (chống timing attack).
"""
import hashlib
import hmac
import json
import secrets


def sha256(value: str) -> str:
    """SHA-256 hex của một chuỗi (dùng cho mật khẩu/token/secret)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_matches(candidate: str, stored_hash: str) -> bool:
    """Kiểm tra một giá trị thô có khớp hash đã lưu không (so sánh an toàn)."""
    if not candidate or not stored_hash:
        return False
    return hmac.compare_digest(sha256(candidate), stored_hash)


def new_token(nbytes: int = 32) -> str:
    """Sinh token ngẫu nhiên, URL-safe (dùng cho enrollment, secret máy,
    token Agent, session dashboard)."""
    return secrets.token_urlsafe(nbytes)


def new_machine_id() -> str:
    """Mã máy: 'mango_' + 12 ký tự hex (cùng định dạng với client 0.14.x)."""
    return "mango_" + secrets.token_hex(6)


# --- Che tham số nhạy cảm (cùng luật với mangomcp/audit.py) ---

_SENSITIVE_KEYS = ("password", "passwd", "secret", "token")


def redact(obj):
    """Che giá trị của các khóa nhạy cảm (password/secret/token) bằng '***',
    giữ nguyên cấu trúc còn lại. Dùng trước khi ghi audit/log."""
    if isinstance(obj, dict):
        return {
            k: ("***" if any(s in str(k).lower() for s in _SENSITIVE_KEYS) else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    return obj


def summarize_args(args, limit: int = 200) -> str:
    """Tóm tắt tham số đã che, cắt tối đa `limit` ký tự (mặc định 200,
    giống audit.summarize_args của MangoMCP)."""
    text = json.dumps(redact(args), ensure_ascii=False, default=str)
    return text[:limit]
