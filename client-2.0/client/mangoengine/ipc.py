"""IPC giua client SYSTEM (session 0) va GUI agent (session nguoi dung)
— Mango Client 2.1. Port tu MangoMCP 0.14.2 ipc.py (da kiem chung).

Giao thuc don gian, chi localhost:
- Moi dong la mot JSON (newline-delimited), toi da 64MB/dong (du cho
  screenshot base64).
- Agent noi vao client SYSTEM, gui hello dau tien:
  {"type": "hello", "pid", "session_id", "username", "version"}.
- Client SYSTEM gui request:
  {"id", "tool", "args", "client": null}.
- Agent tra response:
  {"id", "ok": true, "result": ...} hoac
  {"id", "ok": false, "error": {"code", "message", "detail", "retryable"}}.
- Tool noi bo (khong phai tool dieu khien, Agent tu xu ly):
  "__ping" (kiem tra song), "__lock_state" (trang thai khoa live),
  "__shutdown" (Agent tu thoat, khong noi lai).

Cong mac dinh 18767 — KHAC voi IPC cua MangoMCP 0.14.2 (8767) de khong
dung do khi ca 2 cung chay tren mot may (PC1 van chay MangoMCP 0.14.2).

Bao mat: IPC chi bind localhost. No khong phai ranh gioi chong tien
trinh local; ranh gioi xac thuc that su la Server (token Agent) o client.
"""
import json
import socket
import threading
import time

from .errors import MangoError

DEFAULT_IPC_HOST = "127.0.0.1"
DEFAULT_IPC_PORT = 18767
MAX_LINE_BYTES = 64 * 1024 * 1024
HELLO_TIMEOUT = 10.0
DEFAULT_CALL_TIMEOUT = 300.0

# Tool noi bo Agent tu xu ly (khong phai tool dieu khien).
INTERNAL_TOOLS = frozenset({"__ping", "__lock_state", "__shutdown"})


def control_not_active_error():
    return MangoError(
        "CONTROL_NOT_ACTIVE",
        "Chua bat dieu khien — GUI agent chua noi ve client SYSTEM "
        "(can co console session dang active, hoac tai khoan/mat khau "
        "da luu de dang nhap).",
        retryable=False,
    )


def error_to_dict(exc):
    if isinstance(exc, MangoError):
        return exc.to_dict()
    return {"code": "INTERNAL", "message": str(exc), "detail": "", "retryable": False}


def error_from_dict(data):
    data = data or {}
    return MangoError(
        str(data.get("code") or "IPC_ERROR"),
        str(data.get("message") or "Loi IPC khong ro."),
        detail=str(data.get("detail") or ""),
        retryable=bool(data.get("retryable")),
    )


def _read_line(f, limit=MAX_LINE_BYTES):
    """Doc mot dong JSON (co gioi han do dai)."""
    line = f.readline(limit + 1)
    if not line:
        raise ConnectionError("IPC: ket noi da dong")
    if len(line) > limit or not line.endswith(b"\n"):
        raise MangoError(
            "IPC_MESSAGE_TOO_LARGE",
            "Dong IPC vuot qua gioi han 64MB hoac khong ket thuc bang newline.",
            retryable=False,
        )
    return line


def _send_line(sock, obj):
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    sock.sendall(data)


# ---------------------------------------------------------------------------
# Client SYSTEM: ControlRouter — lang nghe GUI agent noi vao, chuyen tiep
# ---------------------------------------------------------------------------

class ControlRouter:
    """Router dieu khien o client SYSTEM: nhan GUI agent qua IPC.

    Chi mot Agent noi cung luc (Agent moi thay Agent cu). Chi mot request
    xu ly cung luc (Agent xu ly tuan tu); cac lenh goi dong xep hang o
    _call_lock.
    """

    def __init__(self, host=DEFAULT_IPC_HOST, port=DEFAULT_IPC_PORT):
        self.host = host
        self.port = port
        self._listener = None
        self._accept_thread = None
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._conn = None
        self._conn_file = None
        self._agent_info = None
        self._connected = threading.Event()
        self._call_lock = threading.Lock()
        self._next_id = 0
        self._id_lock = threading.Lock()

    # ----- Vong doi -----

    def start(self):
        """Mo socket lang nghe IPC (chi localhost). Goi mot lan."""
        if self._listener is not None:
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        listener.listen(1)
        listener.settimeout(0.5)
        self._listener = listener
        # port=0 (chon ngau nhien, dung cho test) thi ghi lai cong that.
        try:
            self.port = listener.getsockname()[1]
        except Exception:
            pass
        self._stop.clear()
        self._accept_thread = threading.Thread(
            target=self._accept_loop, daemon=True, name="mangoclient-ipc-accept"
        )
        self._accept_thread.start()

    def stop(self):
        self._stop.set()
        self._drop_connection()
        listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.close()
            except Exception:
                pass
        # Cho luong accept thoat han truoc khi tra ve, de cong duoc
        # giai phong sach (tranh EADDRINUSE khi khoi dong lai ngay).
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=2)
            self._accept_thread = None

    def _accept_loop(self):
        while not self._stop.is_set():
            listener = self._listener
            if listener is None:
                break
            try:
                conn, _addr = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._register_connection(conn)

    def _register_connection(self, conn):
        """Doc hello cua Agent moi, thay the ket noi cu (neu co)."""
        try:
            conn.settimeout(HELLO_TIMEOUT)
            f = conn.makefile("rb")
            line = _read_line(f)
            hello = json.loads(line.decode("utf-8"))
            if not isinstance(hello, dict) or hello.get("type") != "hello":
                raise ValueError("hello IPC khong hop le")
            info = {
                "pid": hello.get("pid"),
                "session_id": hello.get("session_id"),
                "username": hello.get("username", ""),
                "version": hello.get("version", ""),
            }
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            return
        with self._state_lock:
            old_conn, old_file = self._conn, self._conn_file
            self._conn = conn
            self._conn_file = f
            self._agent_info = info
            self._connected.set()
        if old_conn is not None:
            try:
                old_conn.close()
            except Exception:
                pass
            try:
                if old_file is not None:
                    old_file.close()
            except Exception:
                pass

    def _drop_connection(self):
        with self._state_lock:
            conn, f = self._conn, self._conn_file
            self._conn = None
            self._conn_file = None
            self._agent_info = None
            self._connected.clear()
        for obj in (f, conn):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass

    def _snapshot(self):
        with self._state_lock:
            return self._conn, self._conn_file

    # ----- Trang thai -----

    def is_connected(self):
        return self._connected.is_set() and self._conn is not None

    def agent_info(self):
        with self._state_lock:
            return dict(self._agent_info) if self._agent_info else None

    def wait_for_agent(self, timeout):
        """Cho Agent noi vao. Tra True neu kip."""
        return self._connected.wait(timeout)

    # ----- Goi lenh -----

    def call(self, tool, args=None, client=None, timeout=DEFAULT_CALL_TIMEOUT):
        """Gui mot lenh dieu khien sang Agent, cho response.

        Chua co Agent noi thi bao CONTROL_NOT_ACTIVE (retryable=false).
        Mat ket noi giua chung thi bao IPC_ERROR (retryable=true).
        """
        if not self.is_connected():
            raise control_not_active_error()
        lock_timeout = min(float(timeout or 0) or DEFAULT_CALL_TIMEOUT, 60.0)
        if not self._call_lock.acquire(timeout=lock_timeout):
            raise MangoError(
                "IPC_BUSY",
                "IPC dang ban (mot lenh dieu khien khac dang chay). Thu lai sau.",
                retryable=True,
            )
        try:
            conn, f = self._snapshot()
            if conn is None or f is None:
                raise control_not_active_error()
            with self._id_lock:
                self._next_id += 1
                req_id = self._next_id
            req = {"id": req_id, "tool": tool, "args": args or {}}
            if client is not None:
                req["client"] = client
            try:
                conn.settimeout(timeout)
                _send_line(conn, req)
                line = _read_line(f)
            except (OSError, ConnectionError, MangoError) as exc:
                self._drop_connection()
                if isinstance(exc, MangoError):
                    raise
                raise MangoError(
                    "IPC_ERROR",
                    f"IPC mat ket noi khi goi {tool}: {exc}",
                    retryable=True,
                )
            try:
                resp = json.loads(line.decode("utf-8"))
            except Exception as exc:
                raise MangoError(
                    "IPC_ERROR",
                    f"IPC tra ve khong phai JSON hop le: {exc}",
                    retryable=True,
                )
            if not isinstance(resp, dict) or resp.get("id") != req_id:
                raise MangoError(
                    "IPC_ERROR",
                    "IPC tra ve sai id hoac sai dinh dang.",
                    retryable=True,
                )
            if resp.get("ok"):
                return resp.get("result")
            raise error_from_dict(resp.get("error"))
        finally:
            self._call_lock.release()

    def shutdown_agent(self, timeout=10.0):
        """Bao Agent tu thoat (__shutdown). Neu Agent khong thoat kip
        (dang ket o tool dai) thi ket thuc tien trinh theo pid.

        Tra {"was_connected", "agent", "exited"}.
        """
        info = self.agent_info()
        was = self.is_connected()
        if not was:
            return {"was_connected": False, "agent": info, "exited": True}
        try:
            self.call("__shutdown", {}, timeout=timeout)
        except Exception:
            pass
        deadline = time.time() + float(timeout)
        while time.time() < deadline and self.is_connected():
            time.sleep(0.1)
        exited = not self.is_connected()
        if not exited:
            pid = (info or {}).get("pid")
            if pid:
                self._terminate_pid(pid)
            self._drop_connection()
            exited = True
        return {"was_connected": True, "agent": info, "exited": exited}

    @staticmethod
    def _terminate_pid(pid):
        """Ket thuc tien trinh theo pid (dung o control_logout)."""
        try:
            import psutil

            psutil.Process(int(pid)).terminate()
            return
        except Exception:
            pass
        try:
            import os

            if os.name == "nt":
                import subprocess

                subprocess.run(
                    ["taskkill", "/F", "/PID", str(int(pid))],
                    capture_output=True,
                    timeout=10,
                )
            else:
                import signal

                os.kill(int(pid), signal.SIGTERM)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# GUI agent: AgentConnection — noi ve client SYSTEM, nhan request
# ---------------------------------------------------------------------------

class AgentConnection:
    """Ket noi IPC phia GUI agent: noi ve client SYSTEM, gui hello.

    Rot ket noi thi tu noi lai (backoff tang dan) cho toi khi client len
    lai — tru khi nhan __shutdown (thoat han, khong noi lai).
    """

    def __init__(self, host, port, hello, on_log=None):
        self.host = host
        self.port = port
        self.hello = hello
        self._on_log = on_log or (lambda msg: None)
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def serve(self, handler):
        """Vong lap phuc vu. handler(request_dict) -> (response_dict, should_exit).

        Tra "shutdown" khi nhan __shutdown, "stopped" khi stop() duoc goi.
        """
        delay = 1.0
        while not self._stop.is_set():
            try:
                sock = socket.create_connection((self.host, self.port), timeout=10)
            except OSError as exc:
                self._on_log(f"IPC: chua noi duoc client SYSTEM ({self.host}:{self.port}): {exc}")
                self._sleep_or_stop(delay)
                delay = min(delay * 2, 30.0)
                continue
            try:
                _send_line(sock, self.hello)
                self._on_log(f"IPC: da noi client SYSTEM, hello pid={self.hello.get('pid')}")
                delay = 1.0
                f = sock.makefile("rb")
                while not self._stop.is_set():
                    line = _read_line(f)
                    req = json.loads(line.decode("utf-8"))
                    resp, should_exit = handler(req)
                    _send_line(sock, resp)
                    if should_exit:
                        return "shutdown"
            except (OSError, ConnectionError, MangoError, ValueError, KeyError) as exc:
                self._on_log(f"IPC: mat ket noi / loi doc: {exc}; se noi lai")
            finally:
                try:
                    sock.close()
                except Exception:
                    pass
            if not self._stop.is_set():
                self._sleep_or_stop(delay)
                delay = min(delay * 2, 30.0)
        return "stopped"

    def _sleep_or_stop(self, seconds):
        self._stop.wait(seconds)
