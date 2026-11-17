"""Quan ly session Windows cho Mango Client 2.1 (SYSTEM chay session 0).

Client 2.1 chay bang SYSTEM luc Windows khoi dong (session 0) nen luon
noi duoc Server ngay ca khi chua ai dang nhap — cac tool KHONG can
desktop (run_command, file, doc...) chay ngay trong tien trinh SYSTEM.
Chi cac tool dieu khien (CONTROL_TOOLS: chuot/phim/manhinh/desktop_*)
can desktop, phai chay trong session nguoi dung — mo bang 2 duong:
  1. Co console session dang Active (ai do dang ngoi may): lay token
     cua session do (WTSQueryUserToken, khong can mat khau) roi mo
     GUI agent vao do — duong chinh, da kiem chung tu MangoMCP 0.14.2.
  2. Chua ai dang nhap: dung tai khoan/mat khau DA LUU trong config
     (users[0]) de dang nhap bang LogonUser roi mo GUI agent vao
     winsta0\\default — duong du phong theo yeu cau cua Quan tri vien (2.1).
     Luu y that: LogonUser tao tien trinh chay bang tai khoan do trong
     window station tuong tac; muc do tuong tac day du voi desktop phu
     thuoc trang thai session cua Windows. Duong (1) luon la duong
     chac chan nhat khi co nguoi dang ngoi may.

Tren may khong phai Windows (dev/Linux), module van import duoc;
find_console_session() tra None, is_system_session() tra False,
launch_agent()/launch_as_user() bao PLATFORM_UNSUPPORTED.
"""
import os
import subprocess
import sys
from pathlib import Path

from .errors import MangoError, platform_unsupported

try:
    import win32con
    import win32process
    import win32profile
    import win32security
    import win32ts

    _WIN32_AVAILABLE = True
except ImportError:  # Linux/dev: khong co pywin32
    win32con = win32process = win32profile = win32security = win32ts = None
    _WIN32_AVAILABLE = False


def _require_win32():
    if not _WIN32_AVAILABLE:
        raise platform_unsupported(
            "session Windows",
            "Can pywin32 (win32ts/win32process/win32profile/win32security) "
            "tren Windows moi mo tien trinh vao session.",
        )


def current_session_id():
    """Id session cua tien trinh hien tai (None neu khong xac dinh duoc).

    Session 0 = session cua service/SYSTEM (khong co desktop tuong tac).
    Session > 0 = session nguoi dung (co desktop).
    """
    if not _WIN32_AVAILABLE:
        return None
    try:
        import ctypes

        pid = os.getpid()
        session_id = ctypes.c_ulong(0)
        ok = ctypes.windll.kernel32.ProcessIdToSessionId(
            pid, ctypes.byref(session_id)
        )
        if ok:
            return int(session_id.value)
    except Exception:
        pass
    try:
        return int(win32ts.WTS_CURRENT_SESSION)
    except Exception:
        return None


def is_system_session():
    """True neu tien trinh dang chay o session 0 (SYSTEM/service).

    Day la dieu kien de DirectEngine chuyen tool dieu khien sang GUI
    agent (chay trong session nguoi dung) thay vi chay truc tiep.
    Tren Linux/dev tra False (chay trong process nhu 2.0).
    """
    sid = current_session_id()
    return sid == 0


def list_sessions():
    """Liet ke cac session (WTSEnumerateSessions).

    Tra list dict: {"session_id", "win_station", "state", "state_name",
    "username"}. Tren may khong co pywin32 thi tra [].
    """
    if not _WIN32_AVAILABLE:
        return []
    rows = []
    for sess in win32ts.WTSEnumerateSessions():
        # pywin32 tra ve list dict tren Windows that
        # ({'SessionId','WinStationName','State'}); ban cu / mock tra tuple.
        if isinstance(sess, dict):
            session_id = sess.get("SessionId")
            win_station = sess.get("WinStationName", "")
            state = sess.get("State")
        else:
            session_id, win_station, state = sess
        username = ""
        try:
            username = win32ts.WTSQuerySessionInformation(
                win32ts.WTS_CURRENT_SERVER_HANDLE, session_id, win32ts.WTSUserName
            ) or ""
        except Exception:
            username = ""
        rows.append(
            {
                "session_id": int(session_id),
                "win_station": str(win_station),
                "state": int(state),
                "state_name": _state_name(state),
                "username": str(username),
            }
        )
    return rows


def _state_name(state):
    names = {
        0: "active",
        1: "connected",
        2: "connect_query",
        3: "shadow",
        4: "disconnected",
        5: "idle",
        6: "listen",
        7: "reset",
        8: "down",
        9: "init",
    }
    try:
        return names.get(int(state), "unknown")
    except Exception:
        return "unknown"


def find_console_session():
    """Tim console session dang Active (nguoi dung dang ngoi may).

    Tra dict session (nhu list_sessions) hoac None neu khong co.
    Tren Linux/dev (khong co pywin32) tra None thay vi nem loi, de
    control_status van tra ve duoc "khong co session".
    """
    if not _WIN32_AVAILABLE:
        return None
    for sess in list_sessions():
        if sess["win_station"].lower() == "console" and sess["state_name"] == "active":
            return sess
    return None


def get_session_info(session_id):
    """Thong tin mot session theo id (None neu khong thay)."""
    if not _WIN32_AVAILABLE:
        return None
    for sess in list_sessions():
        if sess["session_id"] == int(session_id):
            return sess
    return None


def app_root():
    """Thu muc client (noi co run_client.py / gui_agent.py)."""
    return Path(__file__).resolve().parent.parent


def _token_username(token):
    """Ten nguoi dung cua token (qua win32security), best-effort."""
    try:
        user_sid = win32security.GetTokenInformation(token, win32security.TokenUser)
        # GetTokenInformation tra (sid, attributes) cho TokenUser.
        sid = user_sid[0] if isinstance(user_sid, tuple) else user_sid
        name, domain, _type = win32security.LookupAccountSid(None, sid)
        return f"{domain}\\{name}" if domain else str(name)
    except Exception:
        return ""


def _create_process_as_user(token, command, cwd, extra_env):
    """Tao tien trinh an (hidden, no window) bang token, vao
    winsta0\\default. Tra pid. Dung chung cho ca 2 duong mo GUI agent."""
    username = _token_username(token)
    try:
        env = win32profile.CreateEnvironmentBlock(token, False)
    except Exception:
        env = None
    if env is None:
        env = {}
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})
    startup = win32process.STARTUPINFO()
    startup.lpDesktop = "winsta0\\default"
    startup.dwFlags = win32process.STARTF_USESHOWWINDOW
    startup.wShowWindow = win32con.SW_HIDE
    try:
        proc_info = win32process.CreateProcessAsUser(
            token,
            None,
            command,
            None,
            None,
            False,
            win32process.CREATE_UNICODE_ENVIRONMENT | win32process.CREATE_NO_WINDOW,
            env,
            cwd,
            startup,
        )
    except Exception as exc:
        raise MangoError(
            "AGENT_LAUNCH_FAILED",
            f"Khong mo duoc tien trinh vao session: {exc}",
            detail=f"command: {command}",
            retryable=False,
        )
    return int(proc_info[2]), username


def launch_agent(session_id, command, extra_env=None, cwd=None):
    """Mo mot tien trinh vao console session (dung token cua session).

    - session_id: id console session (lay tu find_console_session()).
    - command: chuoi lenh day du (vd lenh chay gui_agent.py).
    - extra_env: dict bien moi truong them vao.
    - cwd: thu muc lam viec; None thi dung thu muc client.
    Tra {"pid", "session_id", "username", "command"}.
    Loi: NO_SESSION (khong thay session), AGENT_LAUNCH_FAILED.
    """
    _require_win32()
    session_id = int(session_id)
    info = get_session_info(session_id)
    if info is None:
        raise MangoError(
            "NO_SESSION",
            f"Khong co session {session_id}. Dang nhap tai may truoc.",
            retryable=False,
        )
    cwd = cwd or str(app_root())
    token = None
    try:
        token = win32ts.WTSQueryUserToken(session_id)
    except Exception as exc:
        raise MangoError(
            "AGENT_LAUNCH_FAILED",
            f"Khong lay duoc token cua session {session_id}: {exc}",
            detail="WTSQueryUserToken that bai (can quyen SYSTEM/SE_TCB_NAME).",
            retryable=False,
        )
    try:
        pid, username = _create_process_as_user(token, command, cwd, extra_env)
        return {
            "pid": pid,
            "session_id": session_id,
            "username": username or info.get("username", ""),
            "command": command,
        }
    finally:
        if token is not None:
            try:
                import win32api

                win32api.CloseHandle(token)
            except Exception:
                pass


def launch_as_user(username, password, command, cwd=None, extra_env=None,
                   domain=None):
    """Dang nhap bang tai khoan/mat khau DA LUU roi mo tien trinh.

    Duong du phong khi chua ai dang nhap (khong co console session):
    LogonUser(interactive) lay token, roi CreateProcessAsUser vao
    winsta0\\default. Mat khau chi dung de goi LogonUser, khong ghi log.
    Tra {"pid", "session_id", "username", "command"}; session_id la None
    (chua co console session) — tien trinh chay bang token vua dang nhap.
    Loi: INVALID_ARGUMENTS (thieu user/pass), AGENT_LAUNCH_FAILED.
    """
    _require_win32()
    username = str(username or "").strip()
    if not username:
        raise MangoError(
            "INVALID_ARGUMENTS", "username khong duoc trong.",
            retryable=False,
        )
    if not password:
        raise MangoError(
            "INVALID_ARGUMENTS",
            "password khong duoc trong (can mat khau that de dang nhap).",
            retryable=False,
        )
    domain = domain or "."
    cwd = cwd or str(app_root())
    token = None
    try:
        token = win32security.LogonUser(
            username,
            domain,
            str(password),
            win32security.LOGON32_LOGON_INTERACTIVE,
            win32security.LOGON32_PROVIDER_DEFAULT,
        )
    except Exception as exc:
        raise MangoError(
            "AGENT_LAUNCH_FAILED",
            f"Dang nhap bang '{username}' that bai: {exc}",
            detail="Kiem tra lai username/password da luu (user co the "
                   "doi mat khau — cap nhat bang config_set_user_password).",
            retryable=False,
        )
    try:
        pid, token_user = _create_process_as_user(token, command, cwd, extra_env)
        return {
            "pid": pid,
            "session_id": None,
            "username": token_user or username,
            "command": command,
        }
    finally:
        if token is not None:
            try:
                import win32api

                win32api.CloseHandle(token)
            except Exception:
                pass


def gui_agent_command(config_path, ipc_host, ipc_port):
    """Lenh chay GUI agent (pythonw, an, khong cua so).

    Dung sys.executable cua tien trinh hien tai; tren may cai that thi
    Task SYSTEM chay bang pythonw.exe nen gui_agent cung chay pythonw.exe
    (khong cua so). Tra (command_string, cwd).
    """
    script = app_root() / "gui_agent.py"
    cmdline = subprocess.list2cmdline([
        sys.executable, str(script),
        "--config", str(config_path),
        "--ipc-host", str(ipc_host),
        "--ipc-port", str(ipc_port),
    ])
    return cmdline, str(app_root())
