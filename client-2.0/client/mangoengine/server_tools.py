"""Tool cau hinh tu server.py (MangoMCP 0.14.2), chuyen thanh ham goi truc tiep
cho Client 2.0 — khong con FastMCP / Core / Agent / IPC.

12 tool: auto_logon_* (3), user_* (4), switch_user (1), control_* (3),
config_set_user_password (1, moi o 2.1).
- auto_logon_*/user_*/switch_user: giu nguyen logic (goi autologon.py,
  users.py, core.run_command). Chi sua thong diep nhac "Agent" /
  "control_login" thanh Client 2.0.
- control_login/logout/status: o Client 2.0, chinh client la phien dieu
  khien (dang chay trong user session) nen khong con Agent de mo/dung.
  O Client 2.1 (chay SYSTEM o session 0), control_login mo GUI agent,
  control_logout dung GUI agent, control_status tra trang thai GUI agent.
"""

import os
import platform

from . import autologon, core, gui, users
from .errors import MangoError

VERSION = "2.1.9"


def _users(config):
    """Danh sach user trong config (luon la list, ke ca config cu)."""
    return config.data.setdefault("users", [])


# ---------- control_* : Client 2.1 chay SYSTEM (session 0) + GUI agent ----------

def control_login(config, username=None):
    """Bat dieu khien (mo GUI agent neu chua chay).

    - Dang o session nguoi dung (2.0): dieu khien da bat, chi kiem tra
      username neu dua (bao WRONG_USER neu session hien tai khac).
    - Dang o session 0 / SYSTEM (2.1): mo GUI agent — co console session
      thi mo vao do; chua ai dang nhap thi dung tai khoan/mat khau da luu
      de dang nhap (co the chi dinh username khac voi username mac dinh
      da luu, mien user do co trong danh sach).
    """
    import getpass
    if not gui.is_system_session():
        current = ""
        try:
            current = getpass.getuser()
        except Exception:
            current = ""
        if username and current and username.strip().lower() != current.strip().lower():
            raise MangoError(
                "WRONG_USER",
                f"Đang đăng nhập là '{current}', không phải '{username}'. "
                f"Đăng xuất rồi đăng nhập bằng '{username}'.",
                retryable=False,
            )
        return {
            "control_active": True,
            "already_connected": True,
            "session": {"username": current},
            "message": "Client 2.1 đang chạy trong session này nên điều khiển đã bật.",
        }
    # Session 0: mo GUI agent (co the chi dinh username cu the).
    if username:
        user_list = config.data.setdefault("users", [])
        entry = users.find(user_list, username=username)
        if entry is None:
            raise MangoError(
                "USER_NOT_FOUND",
                f"User '{username}' chưa có trong danh sách — thêm bằng "
                "user_add trước.",
                retryable=False,
            )
        # Tam dat user nay lam mac dinh de ensure_agent dung no dang nhap.
        users.set_default(user_list, username=username)
        config.save()
    router = gui.get_gui_router(config)
    out = router.ensure_agent()
    return {
        "control_active": True,
        "already_connected": not out.get("launched", False),
        "session": {"username": (out.get("agent") or {}).get("username", "")},
        "agent": out.get("agent"),
        "method": out.get("method"),
        "message": "Đã bật điều khiển (GUI agent đang chạy trong session người dùng).",
    }


def control_logout(config):
    """Dung GUI agent (Client 2.1, session 0) / no-op (session nguoi dung)."""
    if not gui.is_system_session():
        return {
            "control_active": True,
            "was_connected": True,
            "message": "Client 2.1 không có Agent riêng để dừng; điều khiển vẫn bật cùng client.",
        }
    router = gui.get_gui_router(config)
    out = router.shutdown_agent()
    return {
        "control_active": False,
        "was_connected": out.get("was_connected", False),
        "agent": out.get("agent"),
        "message": "Đã dừng GUI agent; tool chỉ đọc vẫn chạy (client SYSTEM vẫn nối Server).",
    }


def control_status(config):
    """Trang thai dieu khien cua Client 2.1.

    - Session nguoi dung: trang thai noi bo (nhu 2.0).
    - Session 0 / SYSTEM: trang thai GUI agent (co noi khong, user nao,
      mo bang cach nao) + session hien tai cua may.
    """
    import getpass
    try:
        current = getpass.getuser()
    except Exception:
        current = ""
    if not gui.is_system_session():
        return {
            "core_up": True,
            "core_version": VERSION,
            "client_version": VERSION,
            "hostname": platform.node(),
            "console_session": {"username": current},
            "agent_connected": True,
            "agent": {"version": VERSION, "username": current},
            "control_active": True,
        }
    router = gui.get_gui_router(config)
    st = router.status()
    return {
        "core_up": True,
        "core_version": VERSION,
        "client_version": VERSION,
        "hostname": platform.node(),
        "system_session": True,
        "console_session": {"username": current},
        "agent_connected": st.get("agent_connected", False),
        "agent": st.get("agent"),
        "launch": st.get("launch"),
        "ipc": st.get("ipc"),
        "control_active": st.get("agent_connected", False),
    }


# ---------- auto-logon ----------

def auto_logon_status(config):
    """Xem trang thai auto-logon. Khong bao gio tra ve mat khau."""
    return autologon.get_status()


def auto_logon_enable(config, username=None, password=None):
    """Bat auto-logon Windows: tu dang nhap khi bat may."""
    user_list = config.data.setdefault("users", [])
    source = "provided"
    if username:
        entry = users.find(user_list, username=username)
        if entry is not None:
            if not password:
                password = entry.get("password")
                source = "stored"
        elif not password:
            raise MangoError(
                "INVALID_ARGUMENTS",
                f"User '{username}' chưa có trong danh sách — thêm bằng "
                "user_add hoặc đưa kèm password.",
                retryable=False,
            )
    else:
        default_user = users.get_default(user_list)
        if default_user is None:
            if not password:
                raise MangoError(
                    "INVALID_ARGUMENTS",
                    "Chưa có user nào trong danh sách — thêm bằng user_add "
                    "hoặc đưa username + password.",
                    retryable=False,
                )
            raise MangoError(
                "INVALID_ARGUMENTS",
                "Chưa có user nào trong danh sách — đưa username kèm "
                "password, hoặc thêm user bằng user_add trước.",
                retryable=False,
            )
        username = default_user.get("username")
        if not password:
            password = default_user.get("password")
            source = "stored"
    out = autologon.enable(username, password)
    out["password_source"] = source
    return out


def auto_logon_disable(config):
    """Tat auto-logon Windows va xoa mat khau khoi registry."""
    return autologon.disable()


# ---------- danh sach user ----------

def user_list(config):
    """Liet ke cac tai khoan Windows trong danh sach.

    Chi tra username + is_default. KHONG BAO GIO tra mat khau.
    """
    return {"users": users.list_public(_users(config))}


def user_add(config, username, password):
    """Them tai khoan Windows vao danh sach. User dau tien la mac dinh."""
    out = users.add(_users(config), username, password)
    config.save()
    return out


def user_remove(config, username=None, index=None):
    """Xoa tai khoan khoi danh sach. Can username HOAC index."""
    if username is None and index is None:
        raise MangoError(
            "INVALID_ARGUMENTS",
            "Cần username hoặc index để xóa user.",
            retryable=False,
        )
    out = users.remove(_users(config), username=username, index=index)
    config.save()
    return out


def user_set_default(config, username=None, index=None):
    """Dat tai khoan mac dinh (so 1). Can username HOAC index."""
    if username is None and index is None:
        raise MangoError(
            "INVALID_ARGUMENTS",
            "Cần username hoặc index để đặt user mặc định.",
            retryable=False,
        )
    out = users.set_default(_users(config), username=username, index=index)
    config.save()
    return out


def config_set_user_password(config, username=None, password=None, index=None):
    """Doi mat khau cua tai khoan da luu (dung khi user doi mat khau).

    Cap nhat mat khau trong danh sach `users` cua config; neu tai khoan
    nay dang bat auto-logon thi cap nhat luon DefaultPassword trong
    registry Winlogon de auto-logon khong bi sai mat khau.
    KHONG BAO GIO tra ve mat khau (moi hay cu) trong ket qua.
    Can username HOAC index + password moi (khong duoc trong).
    """
    if username is None and index is None:
        raise MangoError(
            "INVALID_ARGUMENTS",
            "Cần username hoặc index để đổi mật khẩu.",
            retryable=False,
        )
    if not password:
        raise MangoError(
            "INVALID_ARGUMENTS",
            "password mới không được trống.",
            retryable=False,
        )
    user_list = _users(config)
    entry = users.find(user_list, username=username, index=index)
    if entry is None:
        raise MangoError(
            "USER_NOT_FOUND",
            "Không tìm thấy user (kiểm tra username hoặc index).",
            retryable=False,
        )
    out = users.set_password(user_list, username=username, index=index,
                             password=password)
    config.save()
    # Neu user nay dang bat auto-logon thi dong bo DefaultPassword.
    autologon_updated = False
    autologon_warning = ""
    try:
        st = autologon.get_status()
        if (st.get("enabled") and st.get("username")
                and entry.get("username")
                and st["username"].strip().lower()
                == entry["username"].strip().lower()):
            autologon.enable(entry["username"], password)
            autologon_updated = True
    except Exception as exc:
        # Tren may khong phai Windows (dev) hoac registry loi: mat khau
        # trong config da doi xong; chi ghi canh bao, khong fail ca lenh.
        autologon_warning = str(exc)
    return {
        "username": out.get("username"),
        "index": out.get("index"),
        "is_default": out.get("is_default"),
        "updated": True,
        "autologon_updated": autologon_updated,
        "autologon_warning": autologon_warning,
        "message": f"Đã đổi mật khẩu cho '{out.get('username')}'"
                   + (" và đồng bộ auto-logon." if autologon_updated
                      else "."),
    }


def switch_user(config, username, confirm_reboot=False):
    """Doi tai khoan dang nhap cua may.

    Dat auto-logon sang user do (dung mat khau da luu) roi khoi dong
    lai may. confirm_reboot PHAI la true thi moi lam that.
    """
    user_list = _users(config)
    entry = users.find(user_list, username=username)
    if entry is None:
        raise MangoError(
            "USER_NOT_FOUND",
            f"User '{username}' chưa có trong danh sách — thêm bằng "
            "user_add trước.",
            retryable=False,
        )
    plan = [
        f"Đặt auto-logon sang '{entry.get('username')}' "
        "(dùng mật khẩu đã lưu trong danh sách).",
        "Khởi động lại máy (shutdown /r /t 5 /f).",
        f"Windows tự đăng nhập bằng '{entry.get('username')}', "
        "Client 2.0 tự chạy.",
    ]
    if confirm_reboot is not True:
        return {
            "reboot": False,
            "username": entry.get("username"),
            "plan": plan,
            "message": "Chưa làm gì — gọi lại với confirm_reboot=true "
                       "để đặt auto-logon và khởi động lại máy thật.",
        }
    autologon.enable(entry.get("username"), entry.get("password"))
    reboot = core.run_command(config, "shutdown /r /t 5 /f",
                              timeout_seconds=30)
    return {
        "reboot": True,
        "username": entry.get("username"),
        "plan": plan,
        "reboot_command": reboot,
        "message": f"Đã đặt auto-logon sang '{entry.get('username')}' và "
                   "gửi lệnh khởi động lại (5 giây).",
    }
