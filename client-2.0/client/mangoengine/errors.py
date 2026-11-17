"""Lỗi có cấu trúc cho MangoMCP.

Mọi lỗi tool đều mang mã máy đọc được, thông điệp cho người, chi tiết kỹ thuật
và cờ retryable, để phía AI client tự quyết định có thử lại hay không.
"""
import json


class MangoError(Exception):
    def __init__(self, code, message, detail="", retryable=False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
        self.retryable = retryable

    def to_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
            "retryable": self.retryable,
        }

    def to_json_text(self):
        return json.dumps(self.to_dict(), ensure_ascii=False)


def permission_denied(group):
    return MangoError(
        "PERMISSION_DISABLED",
        f"Nhóm quyền '{group}' đang tắt ở máy đích. Hãy bật nhóm quyền này trong giao diện local rồi thử lại.",
        detail=f"permission group: {group}",
        retryable=False,
    )


def platform_unsupported(feature, detail=""):
    return MangoError(
        "PLATFORM_UNSUPPORTED",
        f"Tính năng {feature} chưa khả dụng trên nền tảng hiện tại.",
        detail=detail,
        retryable=False,
    )


def invalid_args(detail):
    return MangoError("INVALID_ARGUMENTS", "Tham số không hợp lệ.", detail=detail, retryable=False)
