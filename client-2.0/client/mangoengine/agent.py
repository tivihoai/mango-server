"""Tien trinh Agent (MangoMCP 0.14.0): chay trong session nguoi dung.

Nhan lenh dieu khien tu Core qua IPC (127.0.0.1:8767) va chay cac tool
can desktop: screenshot, mouse, keyboard, input_sequence, desktop_*,
uia, lock overlay. Khong mo cong MCP/SSH — chi Core moi tiep xuc ben ngoai.

Khoi dong bang 2 duong:
- Task Logon "MangoMCP-Agent" (khi Quan tri vien dang nhap, Agent tu chay), hoac
- Core mo theo yeu cau (control_login -> session.launch_agent).

Agent tu noi lai IPC neu rot (Core khoi dong lai). Nhan __shutdown
thi tu thoat (khong noi lai) — dung o control_logout.
"""
import json
import os
import sys
import threading
import time
import traceback

from . import core, desktop, ipc, lock, overlay
from .config import CURRENT_AUTH, Config
from .errors import MangoError

CONFIG = Config.load()


def _log_path():
    try:
        return CONFIG.audit_log_path().parent / "agent.log"
    except Exception:
        return None


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        path = _log_path()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


def build_dispatch_table():
    """Bang tool dieu khien Agent phu trach: ten -> ham (core/desktop).

    Dung chung CONTROL_TOOLS voi Core (server.py forward dung ten nay).
    """
    table = {}
    missing = []
    for name in sorted(core.CONTROL_TOOLS):
        fn = getattr(core, name, None) or getattr(desktop, name, None)
        if fn is None:
            missing.append(name)
        else:
            table[name] = fn
    if missing:
        raise RuntimeError(f"tool dieu khien khong tim thay ham: {missing}")
    return table


def _to_jsonable(value):
    """Ep ket qua ve kieu JSON duoc (phong ham tra object la)."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


class Agent:
    """Agent dieu khien: giu LockController + overlay + dispatch IPC."""

    def __init__(self, config=None):
        self.config = config or CONFIG
        self.dispatch = build_dispatch_table()
        self.lock_controller = None
        self._shutdown = threading.Event()
        # Agent: trang thai khoa luon doc tu LockController local, KHONG
        # qua LOCK_STATE_PROVIDER (provider do hoi Agent qua IPC — dung
        # o day se de quy vo han). Core moi gan provider nay.
        core.LOCK_STATE_PROVIDER = None

    # ----- Khoi dong/tat -----

    def start_lock(self):
        """Khoi dong overlay + LockController trong session nay (nhu
        server.py cu lam). Loi o day khong duoc lam sap Agent."""
        try:
            log(f"overlay: {overlay.start(self.config)}")
        except Exception as exc:
            log(f"overlay start error: {exc}")
        try:
            ctrl = lock.LockController(adapter=lock.make_adapter())
            ctrl.on_event = lambda event, detail="": self._audit_lock(event, detail)
            core.LOCK_CONTROLLER = ctrl
            ctrl.sync_from_config(self.config)
            ctrl.start(lambda: self.config)
            self.lock_controller = ctrl
            log(f"lock: {ctrl.status()}")
        except Exception as exc:
            log(f"lock start error: {exc}")

    def _audit_lock(self, event, detail=""):
        try:
            from .audit import write_audit

            write_audit(self.config, f"lock_{event}", detail, ok=True)
        except Exception:
            pass

    def stop_lock(self):
        if self.lock_controller is not None:
            try:
                self.lock_controller.stop()
            except Exception:
                pass
            self.lock_controller = None
        core.LOCK_CONTROLLER = None

    # ----- Xu ly mot request IPC -----

    def handle(self, request):
        """Xu ly mot request IPC. Tra (response_dict, should_exit)."""
        req_id = request.get("id")
        tool = request.get("tool", "")
        args = request.get("args") or {}
        if not isinstance(args, dict):
            return (
                {"id": req_id, "ok": False,
                 "error": {"code": "INVALID_ARGUMENTS", "message": "args phai la object.",
                           "detail": "", "retryable": False}},
                False,
            )
        if tool == "__ping":
            return {"id": req_id, "ok": True, "result": {"ok": True}}, False
        if tool == "__lock_state":
            try:
                result = core.lock_status(self.config)
            except Exception as exc:
                result = {"enabled": False, "state": "off", "error": str(exc)}
            return {"id": req_id, "ok": True, "result": result}, False
        if tool == "__shutdown":
            self._shutdown.set()
            return (
                {"id": req_id, "ok": True, "result": {"shutdown": True}},
                True,
            )
        fn = self.dispatch.get(tool)
        if fn is None:
            return (
                {"id": req_id, "ok": False,
                 "error": {"code": "UNKNOWN_TOOL",
                           "message": f"Agent khong co tool '{tool}'.",
                           "detail": "", "retryable": False}},
                False,
            )
        # Ap scope cua client goi (Core gui kem trong request), giong
        # require() o server cu: master/khong co client thi khong gioi
        # han scope, chi kiem tra cong quyen toan cuc trong config.
        client = request.get("client") or {}
        token = None
        if isinstance(client, dict) and client.get("scopes") is not None:
            token = CURRENT_AUTH.set(
                {"kind": "client", "name": client.get("name", ""),
                 "client": {"scopes": list(client.get("scopes", []))}}
            )
        try:
            result = fn(self.config, **args)
            return {"id": req_id, "ok": True, "result": _to_jsonable(result)}, False
        except MangoError as exc:
            return {"id": req_id, "ok": False, "error": exc.to_dict()}, False
        except Exception as exc:
            err = MangoError("INTERNAL", str(exc), detail=traceback.format_exc()[-500:],
                             retryable=False)
            return {"id": req_id, "ok": False, "error": err.to_dict()}, False
        finally:
            if token is not None:
                CURRENT_AUTH.reset(token)

    # ----- Vong doi -----

    def run(self):
        """Chay Agent: lock/overlay + noi IPC + phuc vu toi khi shutdown."""
        from .config import watch_config

        try:
            watch_config(self.config)
        except Exception as exc:
            log(f"config watch error: {exc}")
        self.start_lock()
        settings = self.config.control_settings()
        hello = {
            "type": "hello",
            "pid": os.getpid(),
            "session_id": None,
            "username": os.environ.get("USERNAME") or os.environ.get("USER") or "",
            "version": core.VERSION,
        }
        # Session id lay tu env (control_login truyen kem) neu co.
        try:
            sid = os.environ.get("MANGO_MCP_SESSION_ID")
            if sid:
                hello["session_id"] = int(sid)
        except Exception:
            pass
        conn = ipc.AgentConnection(
            settings["ipc_host"], settings["ipc_port"], hello, on_log=log
        )
        log(f"agent {core.VERSION} khoi dong, IPC {settings['ipc_host']}:{settings['ipc_port']}")
        try:
            outcome = conn.serve(self.handle)
            log(f"agent dung: {outcome}")
            return 0 if outcome == "shutdown" else 0
        finally:
            self.stop_lock()


def main():
    agent = Agent(CONFIG)
    try:
        return agent.run()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
