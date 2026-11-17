"""Danh sach user Windows dung de dang nhap / auto-logon (MangoMCP 0.14.2).

Yeu cau (Quan tri vien, 8/11/2026): app phai co MUC NHAP DANH SACH USERS
(name/pass) cac tai khoan dung de dang nhap tren may, de SWITCH tai
khoan khi can; tai khoan SO 1 la mac dinh.

Luu tru: section `users` trong config.json — danh sach cac entry
{"username", "password", "default": bool}. Entry dau tien (index 0)
la tai khoan so 1 = mac dinh. BAT BUOC BANG: mac dinh LUON o index 0
va la entry duy nhat co default=True (khi danh sach khong rong).
- user_add: them vao cuoi; neu la user dau tien thi no la mac dinh.
- user_set_default: dua user chon len index 0, danh dau default.
- user_remove: xoa user mac dinh thi user ke tiep (len index 0)
  thanh mac dinh.

CANH BAO BAO MAT — MAT KHAU LUU PLAINTEXT TRONG CONFIG:
- Password luu dang chu thuong trong config.json vi auto-logon BAT
  BUOC can plaintext (registry DefaultPassword cung plaintext — day
  la tradeoff da biet cua auto-logon Windows, khong co cach nao khac).
- Ai doc duoc config.json (hoac co quyen admin tren may) deu thay
  duoc mat khau cac tai khoan nay. Chi them user khi Quan tri vien chap nhan.
- Mat khau KHONG BAO GIO duoc: tra ve qua user_list() / ket qua tool
  (chi username + is_default), ghi vao audit log (audit.summarize_args
  che khoa password), hay luu o dau khac ngoai config.json + registry
  DefaultPassword khi bat auto-logon.
- user_add tu choi mat khau trong (auto-logon mat khau trong khong
  chay tren Windows 10 — da kiem chung 8/11/2026).

Module nay chi thao tac tren list (thuan, de test); tang server.py
lo viec doc/ghi config.json (config.save()).
"""
from .errors import MangoError, invalid_args


def _norm(username):
    return str(username or "").strip()


def _find(users, username=None, index=None):
    """Tim user theo username (khong phan biet hoa/thuong) hoac index.

    Tra (entry, index) hoac (None, None). Uu tien index neu ca hai
    deu dua.
    """
    if index is not None:
        try:
            idx = int(index)
        except (TypeError, ValueError):
            return None, None
        if 0 <= idx < len(users):
            return users[idx], idx
        return None, None
    name = _norm(username)
    if not name:
        return None, None
    for i, entry in enumerate(users):
        if _norm(entry.get("username")).lower() == name.lower():
            return entry, i
    return None, None


def find(users, username=None, index=None):
    """Tim user (tra entry hoac None)."""
    entry, _idx = _find(users, username=username, index=index)
    return entry


def get_default(users):
    """Tai khoan mac dinh (so 1) — entry dau tien, hoac None neu rong."""
    if not users:
        return None
    return users[0]


def list_public(users):
    """Danh sach user de tra ve qua tool: chi username + is_default.

    KHONG BAO GIO tra password.
    """
    return [
        {"index": i, "username": entry.get("username"),
         "is_default": (i == 0)}
        for i, entry in enumerate(users)
    ]


def _sync_default_flags(users):
    """Dong bo co default: chi entry index 0 co default=True."""
    for i, entry in enumerate(users):
        entry["default"] = (i == 0)


def add(users, username, password):
    """Them user vao cuoi danh sach. Tra {"index", "username", "is_default"}.

    - username: khong duoc trong, khong duoc trung (khong phan biet hoa/thuong).
    - password: khong duoc trong (auto-logon can mat khau that).
    - User dau tien (danh sach dang rong) tro thanh mac dinh.
    """
    name = _norm(username)
    if not name:
        raise invalid_args("username khong duoc trong.")
    if not password:
        raise invalid_args(
            "password khong duoc trong: auto-logon mat khau trong "
            "khong chay duoc tren Windows 10 (da kiem chung 8/11)."
        )
    if find(users, username=name) is not None:
        raise MangoError(
            "USER_EXISTS",
            f"User '{name}' da co trong danh sach.",
            retryable=False,
        )
    entry = {"username": name, "password": str(password), "default": False}
    users.append(entry)
    _sync_default_flags(users)
    return {"index": len(users) - 1, "username": name,
            "is_default": (len(users) == 1)}


def set_password(users, username=None, index=None, password=None):
    """Doi mat khau cua user da co (khong doi username / thu tu).

    Tra {"index", "username", "is_default"}. KHONG BAO GIO tra password.
    Mat khau trong bi tu choi (auto-logon / dang nhap can mat khau that).
    """
    entry, idx = _find(users, username=username, index=index)
    if entry is None:
        raise MangoError(
            "USER_NOT_FOUND",
            "Khong tim thay user (kiem tra username hoac index).",
            retryable=False,
        )
    if not password:
        raise invalid_args(
            "password khong duoc trong (can mat khau that de dang nhap)."
        )
    entry["password"] = str(password)
    return {"index": idx, "username": entry.get("username"),
            "is_default": (idx == 0)}


def remove(users, username=None, index=None):
    """Xoa user theo username hoac index.

    - Khong cho xoa khi chi con 1 user (USER_LAST_ONE).
    - Xoa user mac dinh (index 0) thi user ke tiep len index 0 va
      thanh mac dinh.
    Tra {"removed": {"index", "username", "was_default": bool},
         "new_default": {"index", "username"} | None}.
    """
    entry, idx = _find(users, username=username, index=index)
    if entry is None:
        raise MangoError(
            "USER_NOT_FOUND",
            "Khong tim thay user (kiem tra username hoac index).",
            retryable=False,
        )
    if len(users) <= 1:
        raise MangoError(
            "USER_LAST_ONE",
            "Khong xoa duoc: danh sach chi con 1 user. Them user moi "
            "truoc roi moi xoa user nay.",
            retryable=False,
        )
    was_default = (idx == 0)
    removed = users.pop(idx)
    _sync_default_flags(users)
    new_default = users[0] if users else None
    return {
        "removed": {"index": idx, "username": removed.get("username"),
                    "was_default": was_default},
        "new_default": ({"index": 0, "username": new_default.get("username")}
                        if new_default else None),
    }


def set_default(users, username=None, index=None):
    """Dat tai khoan mac dinh (so 1): dua user chon len index 0.

    Tra {"index": 0, "username": ..., "is_default": True}.
    """
    entry, idx = _find(users, username=username, index=index)
    if entry is None:
        raise MangoError(
            "USER_NOT_FOUND",
            "Khong tim thay user (kiem tra username hoac index).",
            retryable=False,
        )
    users.pop(idx)
    users.insert(0, entry)
    _sync_default_flags(users)
    return {"index": 0, "username": entry.get("username"),
            "is_default": True}
