"""Shell Tunnel (ban 0.11.0, server 0.12.0): SSH server rieng chay cung tien trinh MangoMCP.

Khi client MCP ket noi, agent co them mot kenh ma hoa doc lap khoi tool MCP:
- Shell tuong tac (cmd.exe tren Windows, shell cau hinh tren he khac),
  giu phien, khong phai lenh mot lan nhu tool run_command.
- SFTP chuyen file len/xuong, tao/xoa/doi ten file va thu muc.
- Dang nhap bang dung credential cua client: username = App ID
  (dang mango_...), password = Secret. KHONG dung mat khau chu o day
  (mat khau chu chi mo app cau hinh, theo quy tac cua server).
- Chi mo khi cau hinh tunnel.enabled = true (mac dinh TAT, bat bang
  cong tac trong app cau hinh). Tunnel tu dong boi dong boi trong vai
  giay khi cau hinh doi, khong can khoi dong lai server chinh.
- Moi ket noi, lenh exec, phien SFTP va thao tac file deu ghi vao
  audit.jsonl nhu tool MCP (khong ghi mat khau hay noi dung file).
- Khi che do khoa dang tam ngung (nguoi ngoi may vua mo khoa), shell
  va SFTP bi tu choi voi LOCK_PAUSED, giong tool input/capture.

An toan: tunnel CO TINH CO Y vuot qua scopes va allowlist cua MCP
(Quan tri vien chon toan quyen). Ai co AppID.Secret cua mot client dang bat
va tunnel dang bat thi co toan quyen shell + file cua user chay server.
Host key luu tai <thu muc app>/ssh_host_key, client nen kiem tra
fingerprint lan dau (xem tunnel_info) de chong MITM.
Chay doc lap de test ma khong can khoi dong lai server chinh:
    MANGO_MCP_CONFIG=<duong dan config test> python -m mangomcp.tunnel
"""
import asyncio
import os
import threading
import time

try:
    import asyncssh as _asyncssh
except ImportError:
    _asyncssh = None

SHELL_DEFAULT = "cmd.exe"


def _fingerprint(key):
    try:
        return key.get_fingerprint()
    except Exception:
        return ""


def _to_bytes(data):
    if isinstance(data, str):
        return data.encode()
    return data


async def _process_handler(controller, shell, process):
    """Factory cho asyncssh: shell tuong tac hoac lenh exec.

    process.command is None = shell tuong tac, khac None = exec.
    SFTP khong qua day (asyncssh tu dieu phoi qua sftp_factory)."""
    if controller.is_paused():
        try:
            process.stderr.write("LOCK_PAUSED: agent dang tam ngung, nguoi ngoi may dang dung may.\n")
            await process.stderr.drain()
        except Exception:
            pass
        process.exit(1)
        return
    if process.command is None:
        controller.audit("tunnel_shell", "shell started", ok=True)
        try:
            proc = await asyncio.create_subprocess_exec(
                shell, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT)
        except Exception as exc:
            try:
                process.stderr.write("tunnel shell error: %s\n" % exc)
            except Exception:
                pass
            process.exit(1)
            return

        async def pump_in():
            try:
                while True:
                    data = await process.stdin.read(1024)
                    if not data:
                        break
                    proc.stdin.write(_to_bytes(data))
                    await proc.stdin.drain()
            except Exception:
                pass
            try:
                proc.stdin.close()
            except Exception:
                pass

        pump_task = asyncio.create_task(pump_in())
        try:
            while True:
                chunk = await proc.stdout.read(1024)
                if not chunk:
                    break
                process.stdout.write(chunk.decode(errors="replace"))
        except Exception:
            pass
        try:
            rc = await proc.wait()
        except Exception:
            rc = 1
        pump_task.cancel()
        try:
            await process.stdout.drain()
        except Exception:
            pass
        process.exit(rc if rc is not None else 0)
        return
    controller.audit("tunnel_exec", process.command[:200], ok=True)
    try:
        if os.name == "nt":
            args = [shell, "/c", process.command]
        else:
            args = [shell, "-c", process.command]
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT)
        out, _ = await proc.communicate()
        if out:
            process.stdout.write(out.decode(errors="replace"))
            try:
                await process.stdout.drain()
            except Exception:
                pass
        process.exit(proc.returncode if proc.returncode is not None else 0)
    except Exception as exc:
        try:
            process.stderr.write("tunnel exec error: %s\n" % exc)
        except Exception:
            pass
        process.exit(1)


class _Server(_asyncssh.SSHServer if _asyncssh is not None else object):
    """Xac thuc SSH + theo doi ket noi. Session/SFTP lay qua factory."""

    def __init__(self, controller):
        self.controller = controller

    def connection_made(self, conn):
        self.controller.conn_opened(conn)

    def connection_lost(self, exc):
        self.controller.conn_closed()

    def password_auth_supported(self):
        return True

    def publickey_auth_supported(self):
        return False

    def kbdint_auth_supported(self):
        return False

    def validate_password(self, username, password):
        record = self.controller.config_getter().authenticate_tunnel(username, password)
        if record is None:
            self.controller.audit("tunnel_auth", "failed login for %s" % username, ok=False)
            return False
        self.controller.audit("tunnel_auth", "login ok: %s (%s)" % (username, record.get("name", "")),
                              ok=True)
        return True

    def session_requested(self):
        return True


def _make_sftp_factory(controller):
    import asyncssh

    def _p(path):
        if isinstance(path, bytes):
            return path.decode(errors="replace")
        return str(path)

    class AuditedSFTP(asyncssh.SFTPServer):
        def open(self, path, pflags, attrs):
            controller.audit("tunnel_sftp_open", _p(path), ok=True)
            return super().open(path, pflags, attrs)

        def remove(self, path):
            controller.audit("tunnel_sftp_remove", _p(path), ok=True)
            return super().remove(path)

        def rename(self, oldpath, newpath):
            controller.audit("tunnel_sftp_rename", "%s -> %s" % (_p(oldpath), _p(newpath)), ok=True)
            return super().rename(oldpath, newpath)

        def mkdir(self, path, attrs):
            controller.audit("tunnel_sftp_mkdir", _p(path), ok=True)
            return super().mkdir(path, attrs)

        def rmdir(self, path):
            controller.audit("tunnel_sftp_rmdir", _p(path), ok=True)
            return super().rmdir(path)

    class _PausedSFTP(asyncssh.SFTPServer):
        """Tu choi moi thao tac SFTP khi dang tam ngung, bang loi sach."""

        def _refuse(self, *args, **kwargs):
            raise asyncssh.SFTPError(asyncssh.FX_PERMISSION_DENIED, "LOCK_PAUSED")

        open = _refuse
        open56 = _refuse
        stat = _refuse
        lstat = _refuse
        fstat = _refuse
        setstat = _refuse
        lsetstat = _refuse
        fsetstat = _refuse
        realpath = _refuse
        scandir = _refuse
        mkdir = _refuse
        rmdir = _refuse
        remove = _refuse
        rename = _refuse
        posix_rename = _refuse
        readlink = _refuse
        symlink = _refuse
        link = _refuse
        statvfs = _refuse
        read = _refuse
        write = _refuse

    def factory(chan):
        if controller.is_paused():
            controller.audit("tunnel_sftp", "rejected: LOCK_PAUSED", ok=False)
            # Khong tra ve None khi paused: asyncssh dung thang gia tri
            # factory tra ve lam handler ma khong kiem tra None, nen None
            # gay crash NoneType o moi thao tac thay vi loi tu choi sach.
            return _PausedSFTP(chan)
        controller.audit("tunnel_sftp", "session started", ok=True)
        return AuditedSFTP(chan)

    return factory


class TunnelController:
    """Chay SSH server trong mot luong rieng, tu dong boi theo config."""

    def __init__(self, config_getter, lock_getter, audit_fn):
        self.config_getter = config_getter
        self.lock_getter = lock_getter
        self.audit_fn = audit_fn
        self._lock = threading.Lock()
        self._connections = 0
        self._running = False
        self._host = ""
        self._port = 0
        self._fingerprint = ""
        self._started_at = 0
        self._error = ""
        self._stop = threading.Event()
        self._thread = None

    # ----- API dung chung voi core/server -----

    def audit(self, tool, detail, ok=True):
        try:
            self.audit_fn(tool, detail, ok)
        except Exception:
            pass

    def is_paused(self):
        try:
            ctl = self.lock_getter() if self.lock_getter else None
            return bool(ctl is not None and ctl.agent_input_blocked())
        except Exception:
            return False

    def conn_opened(self, conn):
        with self._lock:
            self._connections += 1

    def conn_closed(self):
        with self._lock:
            self._connections = max(0, self._connections - 1)

    def status(self):
        cfg = {}
        try:
            cfg = self.config_getter().tunnel_settings()
        except Exception:
            pass
        with self._lock:
            return {
                "enabled": bool(cfg.get("enabled", False)),
                "running": self._running,
                "host": self._host,
                "port": self._port,
                "shell": cfg.get("shell", SHELL_DEFAULT),
                "host_key_fingerprint": self._fingerprint,
                "connections": self._connections,
                "started_at": self._started_at,
                "paused_blocked": self.is_paused(),
                "error": self._error,
            }

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._manager, daemon=True,
                                        name="mangomcp-tunnel")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    # ----- Vong quan ly trong luong rieng -----

    def _manager(self):
        try:
            import asyncssh
        except Exception as exc:
            with self._lock:
                self._error = "asyncssh chua cai: %s" % exc
            return
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        server = None
        current = None
        try:
            while not self._stop.is_set():
                try:
                    cfg = self.config_getter().tunnel_settings()
                except Exception as exc:
                    with self._lock:
                        self._error = "doc config loi: %s" % exc
                    loop.run_until_complete(asyncio.sleep(5))
                    continue
                desired = None
                if cfg.get("enabled"):
                    desired = (str(cfg.get("host", "127.0.0.1")),
                               int(cfg.get("port", 8768)),
                               str(cfg.get("shell", SHELL_DEFAULT)))
                if desired is not None and (server is None or current != desired):
                    if server is not None:
                        server.close()
                        loop.run_until_complete(server.wait_closed())
                        server = None
                    try:
                        key = self._load_or_create_host_key(asyncssh)
                        server = loop.run_until_complete(asyncssh.create_server(
                            lambda: _Server(self),
                            desired[0], desired[1],
                            server_host_keys=[key],
                            process_factory=lambda process: _process_handler(self, desired[2], process),
                            sftp_factory=_make_sftp_factory(self),
                        ))
                        current = desired
                        with self._lock:
                            self._running = True
                            self._host, self._port = desired[0], desired[1]
                            self._fingerprint = _fingerprint(key)
                            self._started_at = time.time()
                            self._error = ""
                        self.audit("tunnel_start", "SSH/SFTP listening %s:%d" % (desired[0], desired[1]), ok=True)
                    except Exception as exc:
                        with self._lock:
                            self._error = "khong mo duoc tunnel: %s" % exc
                        server = None
                        current = None
                elif desired is None and server is not None:
                    server.close()
                    loop.run_until_complete(server.wait_closed())
                    server = None
                    current = None
                    with self._lock:
                        self._running = False
                        self._host, self._port = "", 0
                    self.audit("tunnel_stop", "tunnel da tat theo cau hinh", ok=True)
                loop.run_until_complete(asyncio.sleep(2))
        finally:
            try:
                if server is not None:
                    server.close()
                    loop.run_until_complete(server.wait_closed())
            except Exception:
                pass
            try:
                loop.close()
            except Exception:
                pass
            with self._lock:
                self._running = False

    def _load_or_create_host_key(self, asyncssh):
        from pathlib import Path
        base = Path(self.config_getter().base_dir)
        key_path = base / "ssh_host_key"
        if key_path.exists():
            return asyncssh.read_private_key(str(key_path))
        key = asyncssh.generate_private_key("ssh-ed25519")
        try:
            key.write_private_key(str(key_path))
        except Exception:
            priv = key.export_private_key()
            if isinstance(priv, bytes):
                key_path.write_bytes(priv)
            else:
                key_path.write_text(priv, encoding="utf-8")
        try:
            pub_path = base / "ssh_host_key.pub"
            pub = key.export_public_key()
            if isinstance(pub, bytes):
                pub = pub.decode()
            pub_path.write_text(pub, encoding="utf-8")
        except Exception:
            pass
        return key


def run_standalone():
    """Chay tunnel doc lap (test, khong can khoi dong lai server chinh)."""
    import sys
    from .audit import write_audit
    from .config import Config
    config = Config.load()
    controller = TunnelController(
        lambda: config, lambda: None,
        lambda name, detail, ok=True: write_audit(config, name, detail, ok=ok))
    controller.start()
    print("tunnel standalone: dang chay, bam Ctrl+C de dung", flush=True)
    try:
        while True:
            time.sleep(1)
            st = controller.status()
            if st["error"]:
                print("tunnel error:", st["error"], flush=True)
                break
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
        print("tunnel standalone: da dung", flush=True)


if __name__ == "__main__":
    run_standalone()
