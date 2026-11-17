"""Agent client 1.1: nối máy ra Mango Server bằng WebSocket.

Luồng chạy:
1. Nếu chưa enroll: tự enroll bằng URL (POST /api/enroll-request, §3.2)
   — không dừng hỏi mã; --enroll-token vẫn được ưu tiên nếu có.
2. Mở WebSocket tới Server, xác thực bằng machine_id + secret.
3. Gửi heartbeat ~30s (kèm bản local, Agent có đang nối không,
   client_version + allowed_tools — §2.2).
4. Nhận heartbeat_ack có desired_scope (khác reported thì áp dụng ngay:
   ghi server-client.json + cập nhật allowed_tools trong bộ nhớ, không
   cần khởi động lại) hoặc upgrade (xem §4).
5. Nhận {"type":"call"}: kiểm tra tool có trong scope riêng của máy rồi
   thực thi qua MCP loopback local, trả kết quả về Server.
6. Nâng cấp tự động (§4): nhận upgrade_available / upgrade trong
   heartbeat_ack -> tải zip từ Server đã cấu hình (Bearer credential
   máy), kiểm tra SHA-256, giải nén vào staging, gửi upgrade_status
   applying, áp dụng qua updater rồi thoát để updater chạy lại client.
7. Khởi động lại máy (§4.5): nhận admin/restart_machine -> lên lịch
   shutdown của hệ điều hành sau delay_seconds (không qua tool scope).
8. Rớt nối: tự nối lại với backoff 5s -> 10s -> 30s -> 60s. Credential bị
   thu hồi (BAD_MACHINE_CREDENTIAL) thì dừng và báo rõ (cần enroll lại).

KHÔNG BAO GIỜ gửi mật khẩu Windows / mật khẩu chủ lên Server. Client
không hỏi, không hiện hộp thoại khi áp dụng scope/upgrade/restart — tự
áp dụng và ghi log tại chỗ (§4.6).
"""
import asyncio
import hashlib
import json
import math
import os
import platform
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import websockets

from mangoclient import VERSION as CLIENT_VERSION
from mangoclient.updater import apply_update, default_restart_cmd

BACKOFF_SECONDS = [5, 10, 30, 60, 60, 60]
USER_AGENT = f"Mango-Server-Client/{CLIENT_VERSION}"


def log(msg: str):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _post_json(url: str, payload: dict):
    """POST JSON, trả dict đã parse. Lỗi HTTP/mạng -> RuntimeError."""
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise RuntimeError(f"POST {url} that bai (HTTP {exc.code}): {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Khong noi duoc Server ({url}): {exc}") from None


def _save_credential(config, data, machine_name: str):
    config.data["machine_id"] = data["machine_id"]
    config.data["machine_secret"] = data["secret"]
    if machine_name:
        config.data["machine_name"] = machine_name
    config.save()
    log(f"Enroll xong: machine_id={data['machine_id']}, trang thai={data.get('status')}")


def enroll(config, enrollment_token: str, machine_name: str, version: str = ""):
    """Đổi mã đăng ký lấy credential máy bền vững (1.0, giữ nguyên)."""
    if not enrollment_token:
        raise ValueError("Thieu ma dang ky (enrollment token)")
    data = _post_json(config.server_enroll_url, {
        "enrollment_token": enrollment_token,
        "machine_name": machine_name or config.data.get("machine_name", ""),
        "version": version,
    })
    if not data.get("ok"):
        raise RuntimeError(f"Enroll that bai: {data.get('error', 'unknown')}")
    _save_credential(config, data, machine_name)
    return data


def enroll_by_url(config, machine_name: str, version: str = ""):
    """Enroll bằng URL (1.1, §3.2): POST /api/enroll-request, không cần
    mã đăng ký tay. Máy mới chỉ ở trạng thái pending cho tới khi Quản trị viên
    duyệt trên dashboard — chưa điều khiển được."""
    data = _post_json(config.server_enroll_request_url, {
        "machine_name": machine_name or config.data.get("machine_name", ""),
        "version": version,
        "client_version": config.client_version,
        "allowed_tools": sorted(config.allowed_tools),
    })
    if not data.get("ok"):
        raise RuntimeError(f"Enroll bang URL that bai: {data.get('error', 'unknown')}")
    _save_credential(config, data, machine_name)
    return data


def download_package(config, version: str, expected_sha256: str, dest_path):
    """Tải zip gói nâng cấp từ đúng Server đã cấu hình (§4.2).

    Xác thực bằng credential máy (Bearer <machine_id>.<secret>). Kiểm
    tra SHA-256 sau khi tải; sai hash -> RuntimeError, không áp dụng.
    Trả số byte đã tải.
    """
    url = config.server_package_download_url(version)
    mid = config.data.get("machine_id", "")
    secret = config.data.get("machine_secret", "")
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {mid}.{secret}",
                      "User-Agent": USER_AGENT}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Tai goi {version} that bai (HTTP {exc.code})") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Khong tai duoc goi {version}: {exc}") from None
    actual = hashlib.sha256(raw).hexdigest()
    if expected_sha256 and actual.lower() != expected_sha256.lower():
        raise RuntimeError(
            f"SHA-256 goi {version} khong khop (nhan {actual[:16]}..., "
            f"mong doi {expected_sha256[:16]}...) — khong ap dung")
    Path(dest_path).write_bytes(raw)
    return len(raw)


class ServerLink:
    """Vòng lặp nối WebSocket tới Server. `local` là đối tượng có method
    call_tool(name, args) -> dict (mặc định: LocalMcpClient tới 0.14.x)."""

    def __init__(self, config, local, heartbeat_seconds: int = 30,
                 call_timeout: int = 60):
        self.config = config
        self.local = local
        self.heartbeat_seconds = heartbeat_seconds
        self.call_timeout = call_timeout
        self.version = ""
        self.agent_connected = False
        self._stop = False
        self._fail_count = 0
        self._ws = None
        self._upgrading_version = None
        self._upgrade_applied = False

    def stop(self):
        self._stop = True

    def refresh_local_status(self):
        """Đọc version + agent_connected từ MCP local (best-effort)."""
        try:
            status = self.local.call_tool("mango_status", {})
            text = status.get("content", [{}])[0].get("text", "{}")
            info = json.loads(text)
            self.version = str(info.get("version", ""))
        except Exception:
            self.version = ""
        try:
            ctrl = self.local.call_tool("control_status", {})
            text = ctrl.get("content", [{}])[0].get("text", "{}")
            info = json.loads(text)
            self.agent_connected = bool(info.get("control_active", False))
        except Exception:
            self.agent_connected = False

    # -- Heartbeat mở rộng (§2.2) -------------------------------------
    def build_heartbeat(self):
        return {
            "type": "heartbeat",
            "version": self.version,
            "agent_connected": self.agent_connected,
            "client_version": self.config.client_version,
            "allowed_tools": sorted(self.config.allowed_tools),
        }

    def apply_desired_scope(self, scope):
        """Áp dụng scope Quản trị viên đặt: ghi server-client.json + cập nhật bộ
        nhớ ngay, không cần khởi động lại. Trả True nếu đã áp dụng."""
        if not isinstance(scope, list):
            return False
        cleaned = [str(t) for t in scope if isinstance(t, str) and t.strip()]
        if cleaned == sorted(self.config.allowed_tools):
            return False  # đã đúng scope rồi, không ghi lại
        self.config.data["server_allowed_tools"] = cleaned
        self.config.save()
        log(f"Ap dung scope moi tu Server: {len(cleaned)} tool "
            f"({', '.join(cleaned[:5])}{'...' if len(cleaned) > 5 else ''})")
        return True

    # -- upgrade_status (§4.2, best-effort) ----------------------------
    async def send_upgrade_status(self, ws, version, status, detail=""):
        if ws is None:
            return
        try:
            await ws.send(json.dumps({
                "type": "upgrade_status", "version": version,
                "status": status, "detail": str(detail)[:500],
            }))
        except Exception as exc:
            log(f"Khong gui duoc upgrade_status {status}: {exc}")

    # -- Nâng cấp tự động (§4.2, §4.3) ---------------------------------
    def _client_dir(self):
        return Path(__file__).resolve().parent.parent

    async def _handle_upgrade(self, info, ws):
        """Xử lý 1 lệnh nâng cấp. Trả True nếu đã áp dụng + client cần
        thoát ngay (updater sẽ chạy lại client); False nếu không."""
        if not isinstance(info, dict):
            return False
        version = str(info.get("version", "") or "")
        sha256 = str(info.get("sha256", "") or "")
        requires_restart = bool(info.get("requires_restart", False))
        if not version or version == self.config.client_version:
            return False  # đã đúng bản, hoặc lệnh thiếu version
        if self._upgrading_version == version:
            return False  # đang tải/áp dụng bản này rồi
        self._upgrading_version = version
        log(f"Nang cap len client {version} (requires_restart={requires_restart})")
        await self.send_upgrade_status(ws, version, "downloading")
        tmpdir = Path(tempfile.mkdtemp(prefix="mango-upgrade-"))
        try:
            zip_path = tmpdir / f"client-{version}.zip"
            size = await asyncio.to_thread(
                download_package, self.config, version, sha256, zip_path)
            log(f"Da tai goi {version} ({size} byte), SHA-256 khop")
            staging = tmpdir / "staging"
            staging.mkdir(exist_ok=True)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(staging)
            await self.send_upgrade_status(ws, version, "applying")
            restart_cmd = default_restart_cmd(self._client_dir(), self.config.path)
            script = apply_update(staging, self._client_dir(), restart_cmd,
                                  requires_restart)
            log(f"Da ghi updater {script}; client thoat de ap dung ban {version}")
            self._upgrade_applied = True
            return True
        except Exception as exc:
            log(f"Nang cap {version} THAT BAI: {exc}")
            await self.send_upgrade_status(ws, version, "failed", str(exc))
            self._upgrading_version = None
            return False

    async def _apply_heartbeat_ack(self, msg, ws):
        """Xử lý heartbeat_ack: desired_scope + upgrade (§2.2, §4.2)."""
        scope = msg.get("desired_scope")
        if scope is not None:
            self.apply_desired_scope(scope)
        upgrade = msg.get("upgrade")
        if isinstance(upgrade, dict) and upgrade.get("version"):
            return await self._handle_upgrade(upgrade, ws)
        return False

    # -- Khởi động lại máy (§4.5) --------------------------------------
    @staticmethod
    def restart_command(delay_seconds: int, windows=None):
        """Lệnh restart của hệ điều hành. `windows=None` = tự nhận."""
        delay = max(0, int(delay_seconds))
        if windows is None:
            windows = platform.system() == "Windows"
        if windows:
            return ["shutdown", "/r", "/t", str(delay)]
        minutes = math.ceil(delay / 60) if delay > 0 else 0
        return ["shutdown", "-r", f"+{minutes}"]

    def restart_machine(self, delay_seconds: int, windows=None):
        """Lên lịch khởi động lại máy (không qua tool scope). Trả lệnh
        đã chạy. Ghi log rõ để tra cứu sau (§4.6)."""
        cmd = self.restart_command(delay_seconds, windows=windows)
        log(f"Lenh khoi dong lai may tu Server: {' '.join(cmd)}")
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL)
        return cmd

    async def execute_call(self, tool: str, args: dict):
        """Thực thi 1 lệnh từ Server. Kiểm tra scope riêng của máy trước,
        rồi gọi MCP local. Trả (ok, result_dict)."""
        if tool not in self.config.allowed_tools:
            return False, {"error": "SERVER_SCOPE_DENIED",
                           "message": f"May khong cho Server goi tool {tool}"}
        try:
            result = await asyncio.to_thread(self.local.call_tool, tool, args or {})
        except Exception as exc:
            return False, {"error": "LOCAL_MCP_ERROR", "message": str(exc)[:500]}
        if isinstance(result, dict) and result.get("isError"):
            return False, {"error": "LOCAL_TOOL_ERROR", "message": str(result)[:500]}
        return True, result

    async def _heartbeat_loop(self, ws):
        while not self._stop:
            try:
                await ws.send(json.dumps(self.build_heartbeat()))
            except Exception:
                return
            await asyncio.sleep(self.heartbeat_seconds)

    async def _run_once(self):
        """1 lần nối: xác thực, heartbeat, xử lý lệnh tới khi rớt."""
        url = self.config.server_ws_url
        mid = self.config.data.get("machine_id", "")
        secret = self.config.data.get("machine_secret", "")
        log(f"Noi toi Server: {url}")
        async with websockets.connect(url, max_size=10 * 1024 * 1024) as ws:
            self._ws = ws
            await ws.send(json.dumps({"type": "auth", "machine_id": mid, "secret": secret}))
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
            except asyncio.TimeoutError:
                raise RuntimeError("Server khong tra loi xac thuc trong 10s")
            msg = json.loads(raw)
            if msg.get("type") == "error":
                raise _AuthError(str(msg.get("error", "AUTH_FAILED")))
            if msg.get("type") != "welcome":
                raise RuntimeError(f"Server tra message la: {msg.get('type')}")
            log(f"Da noi Server. Trang thai may: {msg.get('status')}")
            self._fail_count = 0
            hb = asyncio.create_task(self._heartbeat_loop(ws))
            try:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    mtype = msg.get("type")
                    if mtype == "call":
                        call_id = msg.get("call_id")
                        tool = str(msg.get("tool", ""))
                        args = msg.get("args", {}) or {}
                        ok, result = await self.execute_call(tool, args)
                        try:
                            await ws.send(json.dumps({
                                "type": "result", "call_id": call_id,
                                "ok": ok,
                                "result": result if ok else {},
                                "error": "" if ok else str(result.get("message", "")),
                                "error_code": "" if ok else str(result.get("error", "")),
                            }))
                        except Exception:
                            return
                    elif mtype == "admin":
                        action = msg.get("action", "")
                        log(f"Lenh quan tri tu Server: {action}")
                        if action == "disconnect":
                            return
                        elif action == "status":
                            try:
                                await ws.send(json.dumps(self.build_heartbeat()))
                            except Exception:
                                return
                        elif action == "apply_scope":
                            self.apply_desired_scope(msg.get("scope"))
                        elif action == "restart_machine":
                            delay = msg.get("delay_seconds", 60)
                            try:
                                delay = int(delay)
                            except (TypeError, ValueError):
                                delay = 60
                            await self.send_upgrade_status(
                                ws, self.config.client_version, "restarting",
                                f"Khoi dong lai may sau {delay}s theo lenh Server")
                            self.restart_machine(delay)
                    elif mtype == "upgrade_available":
                        if await self._handle_upgrade(msg, ws):
                            self._stop = True
                            return
                    elif mtype == "heartbeat_ack":
                        if await self._apply_heartbeat_ack(msg, ws):
                            self._stop = True
                            return
            finally:
                hb.cancel()
                self._ws = None

    async def run_forever(self):
        """Chạy mãi: nối -> rớt -> backoff -> nối lại. Dừng khi credential
        bị thu hồi, gọi stop(), hoặc đã áp dụng nâng cấp (updater chạy
        lại client mới)."""
        await asyncio.to_thread(self.refresh_local_status)
        while not self._stop:
            try:
                await self._run_once()
                if self._stop:
                    break
                log("Mat noi Server, se noi lai...")
            except _AuthError as exc:
                log(f"XAC THUC THAT BAI ({exc}). Credential co the bi thu hoi — "
                    "can enroll lai (xoa machine_id/secret trong server-client.json "
                    "roi chay lai voi ma dang ky moi).")
                return
            except Exception as exc:
                log(f"Loi ket noi: {exc}")
            if self._stop:
                break
            idx = min(self._fail_count, len(BACKOFF_SECONDS) - 1)
            wait = BACKOFF_SECONDS[idx]
            self._fail_count += 1
            log(f"Noi lai sau {wait}s (lan thu {self._fail_count})...")
            await asyncio.sleep(wait)
        if self._upgrade_applied:
            log("Client thoat de updater ap dung ban moi.")
        else:
            log("Client dung.")


class _AuthError(RuntimeError):
    pass
