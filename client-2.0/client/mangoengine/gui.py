"""Dinh tuyen tool dieu khien (CONTROL_TOOLS) sang GUI agent — Client 2.1.

Client 2.1 chay bang SYSTEM o session 0 (khong co desktop) nen KHONG
the chay truc tiep cac tool can desktop (chuot/phim/manhinh/desktop_*).
Cac tool do duoc chuyen sang GUI agent — tien trinh thuong tru chay
trong session nguoi dung — qua IPC localhost (xem ipc.py).

- Dang o session nguoi dung (session id != 0, vd chay tay de test):
  tool dieu khien chay truc tiep trong process nhu Client 2.0.
- Dang o session 0 (SYSTEM, Task chay luc khoi dong): tool dieu khien
  duoc gui sang GUI agent qua IPC. Agent duoc mo khi can (ensure_agent):
  co console session thi mo vao do (WTSQueryUserToken, khong can mat
  khau); chua ai dang nhap thi dung tai khoan/mat khau DA LUU de dang
  nhap (LogonUser). Agent chay thuong tru nen cac thao tac lien tiep
  (vd ve tranh bang chuot) nhanh, khong phai khoi dong lai moi lan.

Router la singleton theo (ipc_host, ipc_port) — ca DirectEngine va
server_tools (control_login/logout/status) dung chung mot router.
"""
import json
import threading

from . import ipc, session, users
from .errors import MangoError

DEFAULT_GUI_IPC_HOST = "127.0.0.1"
DEFAULT_GUI_IPC_PORT = 18767


def is_system_session():
    """True neu tien trinh hien tai dang o session 0 (SYSTEM/service)."""
    return session.is_system_session()


def gui_ipc_settings(config):
    """Cau hinh IPC GUI: host/port (mac dinh 127.0.0.1:18767).

    Doc tu config `control.gui_ipc_port` neu co; khong thi dung mac dinh.
    Cong 18767 khac voi IPC MangoMCP 0.14.2 (8767) de khong dung do.
    """
    data = (config.data.get("control", {}) or {})
    try:
        port = int(data.get("gui_ipc_port", DEFAULT_GUI_IPC_PORT))
    except Exception:
        port = DEFAULT_GUI_IPC_PORT
    if port < 1 or port > 65535:
        port = DEFAULT_GUI_IPC_PORT
    host = str(data.get("gui_ipc_host", DEFAULT_GUI_IPC_HOST) or DEFAULT_GUI_IPC_HOST)
    try:
        timeout = int(data.get("login_timeout_seconds", 30))
    except Exception:
        timeout = 30
    timeout = max(5, min(timeout, 300))
    return {"ipc_host": host, "ipc_port": port, "login_timeout_seconds": timeout}


class GuiRouter:
    """Router phia client SYSTEM: giu IPC server + mo GUI agent khi can."""

    def __init__(self, config):
        self.config = config
        settings = gui_ipc_settings(config)
        self.host = settings["ipc_host"]
        self.port = settings["ipc_port"]
        self.login_timeout = settings["login_timeout_seconds"]
        self._router = ipc.ControlRouter(self.host, self.port)
        self._started = False
        self._start_lock = threading.Lock()
        self._launch_info = None

    # ----- Trang thai -----

    def is_connected(self):
        return self._router.is_connected()

    def agent_info(self):
        return self._router.agent_info()

    def launch_info(self):
        return dict(self._launch_info) if self._launch_info else None

    def _start_router(self):
        with self._start_lock:
            if not self._started:
                self._router.start()
                self._started = True

    def stop(self):
        try:
            self._router.stop()
        except Exception:
            pass
        self._started = False

    # ----- Mo GUI agent -----

    def ensure_agent(self, timeout=None):
        """Dam bao GUI agent dang noi ve IPC. Mo neu chua co.

        Tra {"connected": True, "agent": {...}, "method": "console"|"logon",
        "launched": bool}. Loi: NO_SESSION (khong co session, khong co
        tai khoan luu), AGENT_LAUNCH_FAILED, hoac timeout cho agent noi.
        """
        if self.is_connected():
            return {"connected": True, "agent": self.agent_info(),
                    "method": (self._launch_info or {}).get("method", "console"),
                    "launched": False}
        self._start_router()
        timeout = timeout if timeout is not None else self.login_timeout
        config_path = str(self.config.path) if getattr(self.config, "path", None) else ""
        command, cwd = session.gui_agent_command(config_path, self.host, self.port)
        launched = None
        method = None
        sess = session.find_console_session()
        if sess is not None:
            method = "console"
            launched = session.launch_agent(
                sess["session_id"], command, cwd=cwd)
        else:
            # Chua ai dang nhap: dung tai khoan/mat khau DA LUU.
            user_list = self.config.data.get("users", []) or []
            entry = users.get_default(user_list)
            if entry is None or not entry.get("password"):
                raise MangoError(
                    "NO_SESSION",
                    "Chua ai dang nhap tai may va chua co tai khoan/mat khau "
                    "da luu de dang nhap (them bang user_add hoac cai dat "
                    "lai co nhap tai khoan).",
                    retryable=False,
                )
            method = "logon"
            launched = session.launch_as_user(
                entry.get("username"), entry.get("password"), command, cwd=cwd)
        self._launch_info = {"method": method, "launched": launched}
        if not self._router.wait_for_agent(timeout):
            raise MangoError(
                "AGENT_LAUNCH_FAILED",
                f"GUI agent khong noi ve IPC trong {timeout} giay "
                f"(da mo bang {method}, pid={launched.get('pid')}).",
                retryable=True,
            )
        return {"connected": True, "agent": self.agent_info(),
                "method": method, "launched": True}

    # ----- Goi lenh dieu khien qua IPC -----

    def call(self, tool, args=None, timeout=300.0):
        """Gui 1 tool dieu khien sang GUI agent (mo agent neu chua co)."""
        self.ensure_agent()
        return self._router.call(tool, args or {}, timeout=timeout)

    def shutdown_agent(self, timeout=10.0):
        """Bao GUI agent tu thoat."""
        out = self._router.shutdown_agent(timeout=timeout)
        self._launch_info = None
        return out

    def status(self):
        """Trang thai dieu khien (dung cho control_status)."""
        return {
            "system_session": is_system_session(),
            "agent_connected": self.is_connected(),
            "agent": self.agent_info(),
            "launch": self.launch_info(),
            "ipc": {"host": self.host, "port": self.port},
        }


# ----- Singleton theo (host, port) -----

_ROUTERS = {}
_ROUTERS_LOCK = threading.Lock()


def get_gui_router(config):
    """Router dung chung cho mot config (singleton theo host:port)."""
    settings = gui_ipc_settings(config)
    key = (settings["ipc_host"], settings["ipc_port"])
    with _ROUTERS_LOCK:
        router = _ROUTERS.get(key)
        if router is None:
            router = GuiRouter(config)
            _ROUTERS[key] = router
        return router


def reset_gui_router():
    """Xoa singleton (dung cho test)."""
    with _ROUTERS_LOCK:
        _ROUTERS.clear()


def call_control_tool(config, name, args):
    """Goi 1 tool dieu khien qua GUI agent, tra dung dinh dang MCP
    envelope nhu DirectEngine.call_tool (de ServerLink dung chung).

    Chi goi khi dang o session 0 (SYSTEM). Loi tra isError envelope.
    """
    router = get_gui_router(config)
    try:
        result = router.call(name, dict(args or {}))
    except MangoError as exc:
        return {"isError": True, "content": [{
            "type": "text",
            "text": json.dumps(exc.to_dict(), ensure_ascii=False)}]}
    except Exception as exc:
        return {"isError": True, "content": [{
            "type": "text",
            "text": json.dumps({"error": "TOOL_ERROR", "message": str(exc)},
                               ensure_ascii=False)}]}
    return {"content": [{
        "type": "text",
        "text": json.dumps(result, ensure_ascii=False, default=str)}]}
