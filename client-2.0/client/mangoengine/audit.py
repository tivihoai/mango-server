"""Audit log dạng JSONL: mỗi dòng một lần gọi tool, không ghi bí mật."""
import json
import threading
import time

_lock = threading.Lock()


def write_audit(config, tool, args_summary, ok, error_code=""):
    try:
        path = config.audit_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "tool": tool,
            "args": args_summary,
            "ok": ok,
            "error_code": error_code,
        }
        with _lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Audit không bao giờ được làm hỏng thao tác chính


_SENSITIVE_KEYS = ("password", "passwd", "secret", "token")


def _redact(obj):
    """Che gia tri cua cac khoa nhay cam (password/secret/token) truoc khi ghi log.

    Audit log KHONG BAO GIO duoc chua bi mat — vi du tool auto_logon_enable
    nhan mat khau qua tham so, neu dump nguyen args thi mat khau se nam
    trong audit.jsonl. Che bang "***", giu nguyen cau truc con lai.
    """
    if isinstance(obj, dict):
        return {
            k: ("***" if any(s in str(k).lower() for s in _SENSITIVE_KEYS) else _redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_redact(v) for v in obj]
    return obj


def summarize_args(args, limit=200):
    text = json.dumps(_redact(args), ensure_ascii=False, default=str)
    return text[:limit]
