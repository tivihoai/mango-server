#!/usr/bin/env python3
"""GUI agent cua Mango Client 2.1 — tien trinh thuong tru trong session
nguoi dung, chay cac tool dieu khien (CONTROL_TOOLS) thay cho client
SYSTEM o session 0 (khong co desktop).

Client SYSTEM (chay luc khoi dong bang SYSTEM) mo tien trinh nay vao
console session (WTSQueryUserToken) hoac bang tai khoan/mat khau da luu
(LogonUser) khi can dieu khien. Agent noi ve IPC cua client SYSTEM
(127.0.0.1:18767) va phuc vu lenh dieu khien cho toi khi nhan __shutdown
hoac bi tat. Chay an (pythonw.exe, khong cua so); log ghi ra gui_agent.log.

Su dung (chi chay tren Windows, do client SYSTEM mo):
  pythonw gui_agent.py --config C:\\MangoClient\\server-client.json
      --ipc-host 127.0.0.1 --ipc-port 18767
"""
import argparse
import getpass
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mangoengine import core, desktop
from mangoengine.config import CURRENT_AUTH, Config as EngineConfig
from mangoengine.errors import MangoError
from mangoengine.ipc import AgentConnection

VERSION = "2.1.7"


def _log_path(config):
    try:
        base = config.base_dir
    except Exception:
        base = Path.cwd()
    return Path(base) / "gui_agent.log"


def _make_log(log_path):
    def log(msg):
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
        try:
            print(line, flush=True)
        except Exception:
            pass
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
    return log


def build_control_dispatch():
    """Bang tool dieu khien GUI agent phu trach: CONTROL_TOOLS -> ham."""
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


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Mango Client GUI agent {VERSION}")
    parser.add_argument("--config", required=True,
                        help="Duong dan server-client.json")
    parser.add_argument("--ipc-host", default="127.0.0.1")
    parser.add_argument("--ipc-port", type=int, default=18767)
    args = parser.parse_args()

    config = EngineConfig.load_from(args.config)
    log = _make_log(_log_path(config))
    try:
        current = getpass.getuser()
    except Exception:
        current = ""
    try:
        session_id = int(os.environ.get("SESSIONNAME", "") or 0)
    except Exception:
        session_id = 0
    # Session id that: lay tu win32ts neu co (chinh xac hon bien moi truong).
    try:
        import win32ts

        session_id = int(win32ts.WTS_CURRENT_SESSION)
    except Exception:
        pass

    dispatch = build_control_dispatch()
    control_lock = threading.Lock()
    log(f"GUI agent {VERSION} khoi dong: user={current} session={session_id} "
        f"ipc={args.ipc_host}:{args.ipc_port} tool={len(dispatch)}.")

    def handler(req):
        tool = req.get("tool")
        req_id = req.get("id")
        if tool == "__ping":
            return {"id": req_id, "ok": True,
                    "result": {"ok": True, "username": current}}, False
        if tool == "__lock_state":
            locked = False
            try:
                if core.LOCK_CONTROLLER is not None:
                    locked = bool(core.LOCK_CONTROLLER.agent_input_blocked())
            except Exception:
                locked = False
            return {"id": req_id, "ok": True,
                    "result": {"locked": locked, "username": current}}, False
        if tool == "__shutdown":
            log("Nhan __shutdown — thoat.")
            return {"id": req_id, "ok": True,
                    "result": {"shutdown": True}}, True
        fn = dispatch.get(tool)
        if fn is None:
            err = MangoError("UNKNOWN_TOOL",
                             f"GUI agent: khong co tool '{tool}'",
                             retryable=False)
            return {"id": req_id, "ok": False, "error": err.to_dict()}, False
        token = CURRENT_AUTH.set(None)
        try:
            with control_lock:
                result = fn(config, **(req.get("args") or {}))
            return {"id": req_id, "ok": True, "result": result}, False
        except MangoError as exc:
            return {"id": req_id, "ok": False, "error": exc.to_dict()}, False
        except Exception as exc:
            return {"id": req_id, "ok": False,
                    "error": {"code": "TOOL_ERROR", "message": str(exc),
                              "detail": "", "retryable": False}}, False
        finally:
            CURRENT_AUTH.reset(token)

    hello = {"type": "hello", "pid": os.getpid(),
             "session_id": session_id, "username": current,
             "version": VERSION}
    conn = AgentConnection(args.ipc_host, args.ipc_port, hello, on_log=log)
    try:
        outcome = conn.serve(handler)
    except KeyboardInterrupt:
        log("Nhan Ctrl+C, dang dung...")
        outcome = "stopped"
    log(f"GUI agent dung ({outcome}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
