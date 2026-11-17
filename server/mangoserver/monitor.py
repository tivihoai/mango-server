"""Giám sát máy client cho dashboard 1.2.0 (theo mẫu AgentPCManagement).

Hai nhịp riêng, đúng yêu cầu của Quản trị viên (16/11/2026):
- Ping mỗi 10 giây: ping ICMP tới IP cuối của máy (last_ip) + kiểm tra
  cổng SSH 22 và RDP 3389 có mở không (kết nối TCP, timeout ngắn).
- Stats mỗi 5 phút: gọi tool `system_info` của máy đang online qua hub
  (WebSocket) để lấy CPU/RAM/GPU/ổ đĩa, lưu lại để dashboard hiện.

State chỉ giữ trong bộ nhớ (mất khi Server restart — chấp nhận được ở
1.2.0; lịch sử quét đầy đủ dạng DB chưa làm). Không ghi secret hay
mật khẩu vào state.

Ping dùng lệnh `ping` có sẵn của hệ điều hành (Windows/Linux), không cần
cài thêm tool ngoài; kiểm tra cổng dùng socket TCP thuần của Python.
"""
import asyncio
import re
import socket
import subprocess
import time

PING_INTERVAL_SECONDS = 10
STATS_INTERVAL_SECONDS = 300
PING_TIMEOUT_SECONDS = 5
PORT_TIMEOUT_SECONDS = 1.0
STATS_CALL_TIMEOUT_SECONDS = 15
MAX_HISTORY = 50

_PING_TIME_RE = re.compile(r"time[=<]\s*([\d.]+)\s*ms", re.IGNORECASE)


def ping_once(ip: str, timeout: float = PING_TIMEOUT_SECONDS):
    """Ping 1 lần tới IP, trả ms (float) hoặc None nếu không tới được.

    Dùng lệnh ping của hệ điều hành (có sẵn, không cần cài thêm).
    Chạy đồng bộ — caller phải gọi qua asyncio.to_thread để không chặn
    event loop của Server.
    """
    if not ip:
        return None
    try:
        import platform
        if platform.system() == "Windows":
            cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip]
        else:
            cmd = ["ping", "-c", "1", "-W", str(max(1, int(timeout))), ip]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout + 2)
        out = (proc.stdout or "") + (proc.stderr or "")
        m = _PING_TIME_RE.search(out)
        if m:
            return round(float(m.group(1)), 1)
        # Ping trả 0 nhưng không có time=... (vd: đích không tới được
        # nhưng ping vẫn exit 0 trên một số hệ thống) -> coi là fail.
        return None
    except Exception:
        return None


def tcp_open(ip: str, port: int, timeout: float = PORT_TIMEOUT_SECONDS) -> bool:
    """Kiểm tra cổng TCP có mở không (kết nối thử, timeout ngắn)."""
    if not ip:
        return False
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False


def check_host(ip: str):
    """Kiểm tra 1 host: ping + cổng 22 + cổng 3389. Trả dict kết quả.
    Chạy đồng bộ (dùng qua asyncio.to_thread)."""
    ms = ping_once(ip)
    return {
        "ping_ms": ms,
        "ping_ok": ms is not None,
        "ssh_open": tcp_open(ip, 22),
        "rdp_open": tcp_open(ip, 3389),
    }


def unwrap_system_info(result):
    """Lấy dict system_info từ kết quả hub.call.

    hub.call trả đúng envelope MCP của client:
    {"content": [{"type": "text", "text": "<json system_info>"}]}.
    Phòng thủ: nếu result đã là dict system_info (có hostname) thì
    dùng luôn; nếu không parse được thì trả None.
    """
    if not isinstance(result, dict):
        return None
    if "hostname" in result and "os" in result:
        return result
    try:
        content = result.get("content") or []
        if content and isinstance(content[0], dict):
            text = content[0].get("text", "")
            parsed = __import__("json").loads(text)
            if isinstance(parsed, dict):
                return parsed
    except Exception:
        return None
    return None


class MachineMonitor:
    """Giữ trạng thái ping + stats của từng máy, chạy 2 vòng lặp nền."""

    def __init__(self, registry, hub, audit=None,
                 ping_interval: int = PING_INTERVAL_SECONDS,
                 stats_interval: int = STATS_INTERVAL_SECONDS):
        self.registry = registry
        self.hub = hub
        self.audit = audit
        self.ping_interval = ping_interval
        self.stats_interval = stats_interval
        self.state = {}  # machine_id -> ping/stats
        self.last_scan_at = 0
        self.last_stats_at = 0
        self.scan_count = 0
        self.history = []  # [{at, total, online, ssh_open, rdp_open, avg_ping_ms}]
        self._tasks = []
        self._scan_lock = asyncio.Lock()
        self._running = False

    # ----- State -----
    def _ensure(self, machine_id: str):
        return self.state.setdefault(machine_id, {
            "ping_ms": None, "ping_ok": False,
            "ssh_open": False, "rdp_open": False, "ping_at": 0,
            "stats": None, "stats_at": 0, "stats_error": "",
        })

    def get(self, machine_id: str):
        return self.state.get(machine_id)

    # ----- Vòng lặp nền -----
    async def start(self):
        if self._running:
            return
        self._running = True
        self._tasks = [
            asyncio.create_task(self._ping_loop()),
            asyncio.create_task(self._stats_loop()),
        ]

    async def stop(self):
        self._running = False
        for t in self._tasks:
            t.cancel()
        self._tasks = []

    async def _ping_loop(self):
        while self._running:
            try:
                await self._ping_pass()
            except Exception:
                pass
            await asyncio.sleep(self.ping_interval)

    async def _stats_loop(self):
        # Chạy 1 lần ngay sau khi khởi động để dashboard sớm có số liệu.
        await asyncio.sleep(5)
        while self._running:
            try:
                await self._stats_pass()
            except Exception:
                pass
            await asyncio.sleep(self.stats_interval)

    async def scan_now(self):
        """Quét ngay 1 lượt (ping + stats) — nút "Quét ngay" gọi tới."""
        async with self._scan_lock:
            await self._ping_pass()
            await self._stats_pass()
        return self.overview()

    # ----- 1 lượt ping (10s) -----
    async def _ping_pass(self):
        machines = self.registry.list_public()
        now = int(time.time())
        checks = {}
        for m in machines:
            ip = (m.get("last_ip") or "").strip()
            if ip:
                checks[m["machine_id"]] = await asyncio.to_thread(check_host, ip)
            else:
                checks[m["machine_id"]] = {
                    "ping_ms": None, "ping_ok": False,
                    "ssh_open": False, "rdp_open": False,
                }
        pings = []
        for m in machines:
            st = self._ensure(m["machine_id"])
            c = checks[m["machine_id"]]
            st.update({"ping_ms": c["ping_ms"], "ping_ok": c["ping_ok"],
                       "ssh_open": c["ssh_open"], "rdp_open": c["rdp_open"],
                       "ping_at": now})
            if c["ping_ms"] is not None:
                pings.append(c["ping_ms"])
        self.last_scan_at = now
        self.scan_count += 1
        total = len(machines)
        online = sum(1 for m in machines if m["online"])
        self.history.append({
            "at": now, "total": total, "online": online,
            "ssh_open": sum(1 for m in machines
                            if self.state.get(m["machine_id"], {}).get("ssh_open")),
            "rdp_open": sum(1 for m in machines
                            if self.state.get(m["machine_id"], {}).get("rdp_open")),
            "avg_ping_ms": (round(sum(pings) / len(pings), 1) if pings else None),
        })
        del self.history[:-MAX_HISTORY]

    # ----- 1 lượt stats (5 phút) -----
    async def _stats_pass(self):
        machines = self.registry.list_public()
        targets = [m for m in machines
                   if m["online"] and m["status"] == "approved"
                   and self.hub.is_connected(m["machine_id"])]
        if not targets:
            return
        results = await asyncio.gather(
            *(self._fetch_stats(m["machine_id"]) for m in targets),
            return_exceptions=True)
        now = int(time.time())
        for m, res in zip(targets, results):
            st = self._ensure(m["machine_id"])
            if isinstance(res, Exception):
                st["stats_error"] = str(res)[:200]
                # Giữ stats cũ nếu lần này lỗi (không xóa số liệu tốt).
                continue
            info = unwrap_system_info(res)
            if info is None:
                st["stats_error"] = "system_info tra ve khong doc duoc"
                continue
            # Đồng bộ tên máy theo hostname thực tế (dashboard 1.2.x):
            # tên Windows đổi (vd DESKTOP-XXXXXXX -> may-03) thì dashboard
            # hiện tên mới ngay lượt quét sau, không cần enroll lại.
            # sync_name tự bỏ qua hostname rỗng/không đổi/không tìm thấy máy.
            host = info.get("hostname")
            if isinstance(host, str) and host.strip():
                try:
                    self.registry.sync_name(m["machine_id"], host.strip())
                except Exception:
                    pass
            st["stats"] = info
            st["stats_at"] = now
            st["stats_error"] = ""
        self.last_stats_at = now

    async def _fetch_stats(self, machine_id: str):
        from .hub import CallError
        try:
            return await self.hub.call(machine_id, "system_info", {},
                                       timeout=STATS_CALL_TIMEOUT_SECONDS)
        except CallError as exc:
            raise RuntimeError(f"{exc.code}: {exc.message}")
        except Exception as exc:
            raise RuntimeError(str(exc))

    # ----- Dữ liệu cho API/dashboard -----
    def overview(self):
        machines = self.registry.list_public()
        rows = []
        for m in machines:
            st = self.state.get(m["machine_id"], {})
            row = dict(m)
            row.update({
                "ping_ms": st.get("ping_ms"),
                "ping_ok": bool(st.get("ping_ok", False)),
                "ssh_open": bool(st.get("ssh_open", False)),
                "rdp_open": bool(st.get("rdp_open", False)),
                "ping_at": st.get("ping_at", 0),
                "stats": st.get("stats"),
                "stats_at": st.get("stats_at", 0),
                "stats_error": st.get("stats_error", ""),
            })
            rows.append(row)
        total = len(rows)
        online = sum(1 for r in rows if r["online"])
        return {
            "machines": rows,
            "counts": {
                "total": total,
                "online": online,
                "offline": total - online,
                "ssh_open": sum(1 for r in rows if r["ssh_open"]),
                "rdp_open": sum(1 for r in rows if r["rdp_open"]),
                "pending": sum(1 for r in rows if r["status"] == "pending"),
            },
            "last_scan_at": self.last_scan_at,
            "last_stats_at": self.last_stats_at,
            "scan_count": self.scan_count,
            "history": list(self.history),
        }
