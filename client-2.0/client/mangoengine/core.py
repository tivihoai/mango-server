"""Toàn bộ logic tool của MangoMCP, độc lập với tầng giao vận MCP.

Mỗi hàm trả về dict kết quả hoặc ném MangoError có cấu trúc.
Tầng server (server.py) chỉ làm nhiệm vụ đăng ký và bọc lỗi + audit.
"""
import base64
import io
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from . import backend, lock, overlay
from .errors import MangoError, invalid_args, permission_denied

VERSION = "0.14.2"

# Controller khóa máy do server.main gán; None nghĩa là chưa bật chế độ khóa.
LOCK_CONTROLLER = None

# Controller Shell Tunnel do server.main gán; None nghĩa là tunnel chưa chạy
# (tunnel tắt, asyncssh chưa cài, hoặc server chạy bản cũ không có tunnel).
TUNNEL_CONTROLLER = None

# 0.14.0: Core (session 0) khong co LockController — trang thai khoa live
# nam o Agent. server.py gan LOCK_STATE_PROVIDER = callable tra dict
# lock_status cua Agent (qua IPC __lock_state); None thi dung fallback
# doc tu config ben duoi. Agent khong gan bien nay.
LOCK_STATE_PROVIDER = None

# ----- Phan loai tool (0.14.0): can desktop -> chay trong Agent -----
# Core (session 0, SYSTEM) chi chay tool KHONG can desktop: mango_status,
# system_info, list_processes, file, run_command/powershell, registry,
# terminate/kill process, save/list/delete workflow, tunnel, lock_status.
# Moi tool can desktop (chup man hinh, chuot, ban phim, clipboard,
# UIA/win32, desktop_*, snapshot, overlay, launch app, workflow CHAY)
# deu nam o day: Core chi forward sang Agent qua IPC, chua control_login
# thi bao CONTROL_NOT_ACTIVE. Agent dung chung tap nay de dispatch.
# run_workflow/run_saved_workflow la tool tong hop (co the chua buoc dieu
# khien) nen cung forward sang Agent; save/list/delete workflow chi la
# file nen o lai Core.
CONTROL_TOOLS = frozenset({
    # Man hinh / capture
    "display_inventory", "list_windows", "screenshot", "screen_preview",
    "get_pixel_color", "find_color_on_screen", "count_color_on_screen",
    "wait_for_pixel", "snapshot", "read_window_text", "find_text_on_screen",
    # Chuot / ban phim / input
    "mouse_move", "mouse_click", "mouse_drag", "mouse_path", "mouse_scroll",
    "keyboard_type", "keyboard_hotkey", "send_keys", "scroll_at",
    "focus_window", "wait_for_window", "input_sequence",
    # Clipboard (theo session)
    "clipboard_get_text", "clipboard_set_text",
    # UI Automation / Win32
    "ui_tree", "ui_find", "ui_click", "ui_set_text", "ui_get_text",
    "find_controls", "click_control", "set_control_text", "get_control_text",
    "click_label", "multi_click",
    # Cua so / hien thi / overlay
    "set_display_resolution", "activate_or_launch", "close_window",
    "set_window_state", "open_path", "set_busy_overlay", "notify_on_screen",
    # Mo ung dung (phai mo vao session nguoi dung)
    "launch_application",
    # Workflow chay (co the chua buoc dieu khien)
    "run_workflow", "run_saved_workflow",
    # agent-desktop CLI (0.13.0): 21 tool desktop_*
    "desktop_status", "desktop_snapshot", "desktop_find", "desktop_get",
    "desktop_click", "desktop_double_click", "desktop_right_click",
    "desktop_type", "desktop_set_value", "desktop_clear", "desktop_select",
    "desktop_toggle", "desktop_scroll", "desktop_press", "desktop_launch",
    "desktop_list_apps", "desktop_list_windows", "desktop_focus_window",
    "desktop_wait", "desktop_clipboard_get", "desktop_clipboard_set",
})


def is_control_tool(name):
    """True neu tool can desktop (chay trong Agent, Core chi forward)."""
    return name in CONTROL_TOOLS


def _check_lock_pause():
    """Agent tạm ngưng vì người ngồi máy đã mở khóa tại máy."""
    if LOCK_CONTROLLER is not None and LOCK_CONTROLLER.agent_input_blocked():
        raise lock.lock_paused_error(LOCK_CONTROLLER)


def _check_lock_capture():
    if LOCK_CONTROLLER is not None and LOCK_CONTROLLER.agent_capture_blocked():
        raise lock.lock_paused_error(LOCK_CONTROLLER)
STARTED_AT = time.time()


def require(config, group):
    if group == "input":
        _check_lock_pause()
    if not config.permission(group):
        raise permission_denied(group)
    # Phạm vi quyền riêng của client (bản 0.6.0): client chỉ dùng được
    # các nhóm quyền nằm trong scopes của nó, dù cổng toàn cục đang bật.
    from .config import CURRENT_AUTH
    auth = CURRENT_AUTH.get()
    if auth and auth.get("kind") == "client":
        scopes = auth.get("client", {}).get("scopes", [])
        if group not in scopes:
            raise MangoError(
                "CLIENT_SCOPE_DENIED",
                f"Client '{auth.get('name')}' không có quyền '{group}' trong phạm vi được cấp.",
                detail=f"scopes: {scopes}", retryable=False)


# ---------- Chỉ đọc ----------

def mango_status(config):
    return {
        "name": "MangoMCP",
        "version": VERSION,
        "hostname": platform.node(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "uptime_seconds": round(time.time() - STARTED_AT, 1),
        "permissions": config.data.get("permissions", {}),
        "clients": [config.client_public(c) for c in config.clients()],
        "overlay": overlay.status(),
        "lock": lock_status(config),
        # 0.10.0: mật khẩu chủ đã đặt chưa, và token chủ cũ có bị
        # vô hiệu hóa không (= đã đặt mật khẩu chủ). Chỉ báo trạng
        # thái, không bao giờ lộ hash hay mật khẩu.
        "master_password_set": bool(str(config.data.get("master_password_sha256", "")).strip()),
        "master_token_retired": bool(str(config.data.get("master_password_sha256", "")).strip()),
        "tunnel": tunnel_status(config),
    }


def tunnel_status(config):
    """Trang thai Shell Tunnel (0.11.0). Tool chi doc, luon dung duoc."""
    if TUNNEL_CONTROLLER is not None:
        return TUNNEL_CONTROLLER.status()
    settings = config.tunnel_settings()
    return {"enabled": settings["enabled"], "running": False,
            "host": settings["host"], "port": settings["port"],
            "shell": settings["shell"], "host_key_fingerprint": "",
            "connections": 0, "started_at": 0, "paused_blocked": False,
            "error": "", "note": "tunnel controller chua chay (server chua bat tunnel)"}


def tunnel_info(config):
    """Huong dan song ve Shell Tunnel (0.11.0) cho agent moi ket noi.

    Tra trang thai truc tiep + cach ket noi SSH/SFTP bang credential
    cua chinh client dang goi (username = App ID, password = Secret).
    Agent doc tool nay la biet ngay co tunnel, khoi can hoi lai."""
    st = tunnel_status(config)
    host = st.get("host") or "127.0.0.1"
    port = st.get("port") or 8768
    return {
        **st,
        "what": "Shell Tunnel: SSH server rieng chay cung tien trinh MangoMCP, "
                "doc lap khoi tool MCP. Qua do agent co shell tuong tac "
                "(cmd.exe tren Windows) + SFTP chuyen file, khong bi "
                "gioi han boi scopes hay allowlist cua MCP.",
        "auth": "SSH username = App ID cua client (dang mango_...), "
                "password = Secret cua client do. KHONG dung mat khau chu.",
        "examples": {
            "ssh_shell": "ssh <AppID>@%s -p %d  (nhap Secret khi hoi password)" % (host, port),
            "sftp": "sftp -P %d <AppID>@%s" % (port, host),
            "scp_upload": "scp -P %d file_local <AppID>@%s:C:/duong/dan/dich" % (port, host),
            "scp_download": "scp -P %d <AppID>@%s:C:/duong/dan/file ./file_local" % (port, host),
        },
        "notes": [
            "Tunnel mac dinh TAT; chi mo khi chu may bat cong tac Shell Tunnel trong app cau hinh.",
            "Moi ket noi, lenh exec, phien SFTP va thao tac file deu ghi vao audit.jsonl.",
            "Khi che do khoa dang tam ngung (nguoi ngoi may vua mo khoa), shell/SFTP bi tu choi voi LOCK_PAUSED.",
            "Lan dau ket noi, kiem tra host key fingerprint o tren de chong MITM; fingerprint doi la phai hoi chu may.",
            "Canh bao: doi IP cua card mang dang chay tunnel se mat ket noi ngay; tranh doi dung card do.",
        ],
    }


def lock_status(config):
    """Trạng thái chế độ khóa máy. Tool chỉ đọc, luôn dùng được kể cả
    khi Agent đang tạm ngưng, để Agent tự biết khi nào khóa lại mà
    không cần tool khóa/mở nào khác.

    0.14.0: LockController chay trong Agent (can desktop). Core hoi trang
    thai live cua Agent qua LOCK_STATE_PROVIDER (IPC __lock_state);
    khong co Agent thi bao theo config (state "off")."""
    if LOCK_CONTROLLER is not None:
        return LOCK_CONTROLLER.status()
    if LOCK_STATE_PROVIDER is not None:
        try:
            state = LOCK_STATE_PROVIDER()
            if isinstance(state, dict) and state:
                return state
        except Exception:
            pass
    lock_cfg = config.data.get("lock", {}) or {}
    return {"enabled": bool(lock_cfg.get("enabled", False)), "state": "off",
            "password_set": bool(lock_cfg.get("password_sha256")),
            "pause_minutes": lock_cfg.get("pause_minutes", 15),
            "screen_mode": lock_cfg.get("screen_mode", "monitor_off"),
            "agent_input_blocked": False, "agent_capture_blocked": False,
            "note": "lock controller chưa chạy (chạy trong Agent khi control bật)"}


_SMBIOS_MEMORY_TYPE = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5"}


def _wmi_query_comtypes(query):
    """WMI qua comtypes (nhanh). Tra [] neu loi."""
    try:
        import comtypes.client
    except ImportError:
        return []
    try:
        svc = comtypes.client.CoGetObject(r"winmgmts:\\\\.\\root\\cimv2")
        rows = []
        for item in svc.ExecQuery(query):
            try:
                row = {}
                for prop in item.Properties_:
                    try:
                        row[prop.Name] = prop.Value
                    except Exception:
                        continue
                rows.append(row)
            except Exception:
                continue
        return rows
    except Exception:
        return []


def _wmi_query_powershell(query):
    """WMI qua PowerShell Get-CimInstance (fallback khi comtypes that bai).

    Ly do: tien trinh client chay SYSTEM o session 0 co the da khoi tao
    COM theo kieu khac nen CoGetObject that bai (kiem chung PC3 16/11/2026:
    cung code comtypes chay duoc trong python.exe moi nhung tra [] trong
    tien trinh client). PowerShell Get-CimInstance chay doc lap nen khong
    bi anh huong. Lay dung field trong SELECT roi ConvertTo-Json de parse.
    Tra [] neu PowerShell khong co/loi/timeout."""
    try:
        import json as _json
        import re as _re
        m = _re.match(r"\s*SELECT\s+(.+?)\s+FROM\s+(\S+)",
                      query, _re.IGNORECASE)
        if not m:
            return []
        fields = ", ".join(f.strip() for f in m.group(1).split(",")
                           if f.strip())
        if not fields:
            return []
        ps = ("Get-CimInstance -Query '" + query.replace("'", "''") + "' "
              "| Select-Object " + fields + " | ConvertTo-Json -Compress")
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=25)
        text = (out.stdout or "").strip()
        if not text:
            return []
        data = _json.loads(text)
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        return []
    except Exception:
        return []


def _wmi_query(query):
    """Chạy một truy vấn WMI, trả list dict (mỗi dict là một hàng kết quả).

    Chỉ chạy trên Windows; mọi lỗi (không có comtypes, không nối được WMI,
    class không tồn tại...) đều trả [] thay vì ném ra ngoài, vì
    system_info là best-effort và poller dashboard gọi mỗi 5 phút.
    Không import comtypes ở đầu file để Linux không bị ảnh hưởng.

    Thử comtypes trước (nhanh); nếu trả rỗng thì thử PowerShell
    Get-CimInstance (chậm hơn nhưng độc lập với trạng thái COM của
    tiến trình client). Xem _wmi_query_powershell để biết lý do.

    LƯU Ý comtypes 1.4.17: `comtypes.client.GetObject` KHÔNG còn tồn tại
    (gọi là AttributeError) — phải dùng `CoGetObject`. Property của đối
    tượng WMI phải đọc qua `item.Properties_` (đọc trực tiếp `item.Name`
    cũng lỗi AttributeError vì comtypes không map được tên).
    Đã kiểm chứng trên PC3 ngày 16/11/2026.
    """
    if platform.system() != "Windows":
        return []
    rows = _wmi_query_comtypes(query)
    if rows:
        return rows
    return _wmi_query_powershell(query)


def _wmi_gpu_usage():
    """% GPU dùng chung cho mọi GPU (float) hoặc None nếu không lấy được.

    Dùng Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine: chỉ lấy
    các engine 3D (Name chứa "engtype_3D") rồi lấy trung bình
    UtilizationPercentage. Class này không gắn engine với từng card nên
    máy nhiều GPU vẫn chỉ có một con số chung — ghi rõ trong comment,
    muốn tách từng card phải dùng SDK hãng/DXGI (ngoài phạm vi WMI).
    """
    try:
        rows = _wmi_query(
            "SELECT Name, UtilizationPercentage "
            "FROM Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine")
        values = []
        for row in rows:
            name = str(row.get("Name") or "")
            if "engtype_3D" not in name:
                continue
            pct = row.get("UtilizationPercentage")
            # WMI trả UtilizationPercentage dạng chuỗi ('0') trên VMware;
            # chấp nhận cả số lẫn chuỗi số, bỏ qua giá trị không parse được.
            if isinstance(pct, str):
                try:
                    pct = float(pct)
                except (TypeError, ValueError):
                    continue
            if isinstance(pct, (int, float)) and not isinstance(pct, bool):
                values.append(float(pct))
        if not values:
            return None
        return round(min(sum(values) / len(values), 100.0), 1)
    except Exception:
        return None


def system_info(config):
    # config không dùng (giữ tham số để tương thích dispatch) nên
    # config=None vẫn chạy được.
    info = {
        "os": platform.platform(),
        "hostname": platform.node(),
        "user": os.environ.get("USERNAME") or os.environ.get("USER") or "",
        "cpu_logical": os.cpu_count(),
        # --- Trường mới cho dashboard 1.2.0, tất cả best-effort ---
        "cpu_model": platform.processor() or "",
        "cpu_cores": os.cpu_count() or 0,
        "cpu_ghz": None,
        "cpu_percent": 0.0,
        "memory_used_gb": 0.0,
        "memory_detail": [],
        "gpu": [],
        "gpu_note": "GPU info requires Windows (WMI)",
        "disks": [],
    }
    # CPU: WMI cho tên/nhân/xung chính xác hơn platform.processor().
    # Máy ảo có thể có nhiều hàng Win32_Processor (mỗi vCPU một hàng,
    # mỗi hàng NumberOfCores=1) nên CỘNG số nhân qua tất cả các hàng
    # thay vì chỉ lấy hàng đầu (PC3: 2 hàng x 1 nhân = 2 nhân).
    try:
        total_cores = 0
        total_logical = 0
        wmi_name = ""
        for row in _wmi_query(
                "SELECT Name, NumberOfCores, NumberOfLogicalProcessors, "
                "MaxClockSpeed FROM Win32_Processor"):
            name = str(row.get("Name") or "").strip()
            # Tên WMI (vd 'Intel(R) Core(TM) i7-8750H...') luôn đúng hơn
            # platform.processor() (chỉ ra 'Intel64 Family 6...').
            if name and not wmi_name:
                wmi_name = name
            cores = row.get("NumberOfCores")
            if isinstance(cores, int) and not isinstance(cores, bool) and cores > 0:
                total_cores += cores
            logical = row.get("NumberOfLogicalProcessors")
            if isinstance(logical, int) and not isinstance(logical, bool) and logical > 0:
                total_logical += logical
            mhz = row.get("MaxClockSpeed")
            if isinstance(mhz, (int, float)) and not isinstance(mhz, bool) and mhz > 0:
                info["cpu_ghz"] = round(float(mhz) / 1000, 2)
        if total_cores > 0:
            info["cpu_cores"] = total_cores
        if total_logical > 0:
            # Số nhân logic dùng để dashboard hiển thị, giữ cpu_cores là
            # số nhân vật lý; nếu WMI không cho NumberOfCores thì dùng
            # số logic làm số nhân (trường hợp máy chỉ báo logic).
            if total_cores <= 0:
                info["cpu_cores"] = total_logical
        if wmi_name:
            info["cpu_model"] = wmi_name
    except Exception:
        pass
    # RAM từng thanh (Windows/WMI); Linux hoặc không lấy được thì [].
    try:
        for row in _wmi_query(
                "SELECT Capacity, Speed, SMBIOSMemoryType, Manufacturer "
                "FROM Win32_PhysicalMemory"):
            try:
                cap_gb = round(float(row.get("Capacity") or 0) / (1024 ** 3), 2)
            except (TypeError, ValueError):
                cap_gb = 0.0
            speed = row.get("Speed")
            mem_type = row.get("SMBIOSMemoryType")
            info["memory_detail"].append({
                "capacity_gb": cap_gb,
                "speed_mhz": int(speed) if isinstance(speed, int)
                             and not isinstance(speed, bool) else None,
                "type": _SMBIOS_MEMORY_TYPE.get(mem_type, "Unknown")
                        if isinstance(mem_type, int) else "Unknown",
                "manufacturer": str(row.get("Manufacturer") or "").strip(),
            })
    except Exception:
        info["memory_detail"] = []
    # GPU (Windows/WMI). temperature_c và power_w LUÔN None: WMI không có
    # hai số này, muốn có phải dùng SDK hãng (NVML/ADL) — ngoài phạm vi.
    try:
        gpu_rows = _wmi_query(
            "SELECT Name, DriverVersion, AdapterRAM FROM Win32_VideoController")
        usage = _wmi_gpu_usage() if gpu_rows else None
        for row in gpu_rows:
            name = str(row.get("Name") or "").strip()
            if not name:
                continue
            ram = row.get("AdapterRAM")
            vram = None
            # AdapterRAM là byte, có thể None hoặc tràn số 32-bit: chỉ tin
            # giá trị trong khoảng hợp lý (0..64GB), còn lại coi là không có.
            # VMware SVGA trả AdapterRAM ÂM (vd -1048576 ~ 4GB) do tràn
            # số nguyên có dấu 32-bit -> đổi sang không dấu trước khi kiểm tra.
            if isinstance(ram, int) and not isinstance(ram, bool) and ram < 0:
                ram = ram & 0xFFFFFFFF
            if (isinstance(ram, (int, float)) and not isinstance(ram, bool)
                    and 0 < ram <= 64 * (1024 ** 3)):
                vram = round(float(ram) / (1024 ** 3), 2)
            info["gpu"].append({
                "name": name,
                "driver_version": str(row.get("DriverVersion") or ""),
                "vram_gb": vram,
                "usage_percent": usage,
                "temperature_c": None,
                "power_w": None,
            })
        if info["gpu"]:
            if usage is not None:
                info["gpu_note"] = ""
            else:
                info["gpu_note"] = ("gpu_usage_unavailable "
                                    "(can WMI perf counters)")
        elif platform.system() == "Windows":
            info["gpu_note"] = "no GPU detected via WMI"
    except Exception:
        info["gpu"] = []
    try:
        import psutil
        vm = psutil.virtual_memory()
        info["memory_total_gb"] = round(vm.total / (1024 ** 3), 2)
        info["memory_used_percent"] = vm.percent
        info["memory_used_gb"] = round(vm.used / (1024 ** 3), 2)
        info["boot_time"] = psutil.boot_time()
        try:
            info["cpu_percent"] = float(psutil.cpu_percent(interval=0.1))
        except Exception:
            pass
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except Exception:
                continue  # ổ lỗi thì bỏ qua, không làm đổ cả hàm
            info["disks"].append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "filesystem": part.fstype,
                "total_gb": round(usage.total / (1024 ** 3), 1),
                "used_gb": round(usage.used / (1024 ** 3), 1),
                "free_gb": round(usage.free / (1024 ** 3), 1),
                "used_percent": round(usage.percent, 1),
            })
    except ImportError:
        info["memory_note"] = "cài thêm psutil để có số liệu bộ nhớ và boot time"
    except Exception:
        pass
    return info


def list_processes(config, limit: int = 50):
    try:
        import psutil
        rows = []
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                mem = proc.info["memory_info"].rss if proc.info.get("memory_info") else 0
                rows.append({"pid": proc.info["pid"], "name": proc.info["name"],
                             "memory_mb": round(mem / (1024 * 1024), 1)})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        rows.sort(key=lambda r: r["memory_mb"], reverse=True)
        return {"processes": rows[:limit]}
    except ImportError:
        out = subprocess.run(["ps", "-eo", "pid,comm,rss", "--sort=-rss"],
                             capture_output=True, text=True, timeout=10)
        lines = out.stdout.strip().splitlines()[1:1 + limit]
        rows = []
        for line in lines:
            parts = line.split(None, 2)
            if len(parts) == 3:
                rows.append({"pid": int(parts[0]), "name": parts[1],
                             "memory_mb": round(int(parts[2]) / 1024, 1)})
        return {"processes": rows, "source": "ps (thiếu psutil)"}


def display_inventory(config):
    return backend.display_info()


def list_windows(config):
    return {"windows": backend.list_windows()}


def _image_result(img, label):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"label": label, "mime_type": "image/png",
            "base64": base64.b64encode(buf.getvalue()).decode(),
            "width": img.width, "height": img.height}


def screenshot(config):
    _check_lock_capture()
    return _image_result(backend.screenshot_image(), "screenshot")


def screen_preview(config, region: list = None, scale: float = 0.5, jpeg_quality: int = 58):
    _check_lock_capture()
    img = backend.screenshot_image()
    if region:
        img = img.crop(tuple(region))
    if scale != 1.0:
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=jpeg_quality)
    return {"mime_type": "image/jpeg",
            "base64": base64.b64encode(buf.getvalue()).decode(),
            "width": img.width, "height": img.height}


def get_pixel_color(config, x: int, y: int):
    """Vòng phản hồi kín: bot tự đọc màu tại một điểm để biết mình làm đúng chưa."""
    _check_lock_capture()
    img = backend.screenshot_image()
    if not (0 <= x < img.width and 0 <= y < img.height):
        raise invalid_args(f"điểm ({x},{y}) nằm ngoài màn hình {img.width}x{img.height}")
    rgb = img.getpixel((x, y))[:3]
    return {"x": x, "y": y, "rgb": list(rgb), "hex": "#%02x%02x%02x" % rgb}


# ---------- Input (cổng quyền input) ----------

def mouse_move(config, x: int, y: int):
    require(config, "input")
    backend.mouse_move(x, y)
    return {"ok": True, "position": [x, y]}


def mouse_click(config, x: int = None, y: int = None, button: str = "left", clicks: int = 1):
    overlay.pulse()
    require(config, "input")
    backend.mouse_click(x, y, button, clicks)
    return {"ok": True}


def mouse_drag(config, from_x: int, from_y: int, to_x: int, to_y: int, duration_seconds: float = 0.5, button: str = "left"):
    overlay.pulse()
    require(config, "input")
    steps = max(2, int(duration_seconds * 30))
    points = []
    for i in range(steps + 1):
        t = i / steps
        points.append([round(from_x + (to_x - from_x) * t),
                       round(from_y + (to_y - from_y) * t)])
    backend.mouse_path(points, duration_seconds, button)
    return {"ok": True}


def mouse_path(config, points: list, total_duration_seconds: float = 1.0, button: str = "left"):
    require(config, "input")
    backend.mouse_path(points, total_duration_seconds, button)
    return {"ok": True, "points": len(points)}


def mouse_scroll(config, clicks: int):
    require(config, "input")
    backend.mouse_scroll(clicks)
    return {"ok": True}


def keyboard_type(config, text: str, interval_seconds: float = 0.005):
    overlay.pulse()
    require(config, "input")
    backend.type_text(text, interval_seconds)
    return {"ok": True, "characters": len(text)}


def keyboard_hotkey(config, keys: list):
    require(config, "input")
    backend.hotkey(keys)
    return {"ok": True}


def focus_window(config, title_contains: str):
    require(config, "input")
    return backend.focus_window(title_contains)


def wait_for_window(config, title_contains: str, timeout_seconds: float = 10.0, must_be_active: bool = False):
    require(config, "input")
    started = time.time()
    attempts = 0
    while time.time() - started <= timeout_seconds:
        attempts += 1
        try:
            for w in backend.list_windows():
                if title_contains.lower() in w["title"].lower():
                    if not must_be_active or w["active"]:
                        return {"found": True, "title": w["title"],
                                "elapsed_seconds": round(time.time() - started, 2),
                                "attempts": attempts}
        except MangoError:
            raise
        except Exception:
            pass
        time.sleep(0.25)
    return {"found": False, "elapsed_seconds": round(time.time() - started, 2),
            "attempts": attempts}


def input_sequence(config, actions: list, step_delay_ms: int = 20, dry_run: bool = False):
    overlay.pulse()
    """Chạy một chùm hành động trong một lần gọi để giảm vòng lặp mạng.

    Định dạng mỗi hành động là một object có trường "type":
      {"type": "click", "x": 100, "y": 200, "button": "left", "clicks": 1}
      {"type": "move", "x": 100, "y": 200}
      {"type": "drag", "from_x": 0, "from_y": 0, "to_x": 10, "to_y": 10, "duration_seconds": 0.4}
      {"type": "path", "points": [[0,0],[10,10]], "total_duration_seconds": 1.0}
      {"type": "type", "text": "xin chào"}
      {"type": "hotkey", "keys": ["ctrl", "s"]}
      {"type": "scroll", "clicks": -3}
      {"type": "focus", "title_contains": "Paint"}
      {"type": "wait_window", "title_contains": "Paint", "timeout_seconds": 5}
      {"type": "sleep", "seconds": 0.5}
    Kết quả trả về theo từng bước, một bước lỗi không làm đổ cả chùm
    trừ khi hành động đó đặt "stop_on_error": true.
    """
    require(config, "input")
    if not isinstance(actions, list) or not actions:
        raise invalid_args("actions phải là một mảng khác rỗng")
    if len(actions) > 500:
        raise invalid_args("tối đa 500 hành động trong một lần gọi")
    results = []
    stopped = False
    for idx, action in enumerate(actions):
        if stopped:
            results.append({"index": idx, "ok": False, "skipped": True})
            continue
        try:
            if dry_run:
                _validate_action(action)
                results.append({"index": idx, "ok": True, "dry_run": True})
            else:
                _run_action(config, action)
                results.append({"index": idx, "ok": True})
        except MangoError as exc:
            results.append({"index": idx, "ok": False, "error": exc.to_dict()})
            if action.get("stop_on_error"):
                stopped = True
        except Exception as exc:  # lỗi không lường trước vẫn phải có cấu trúc
            results.append({"index": idx, "ok": False,
                            "error": {"code": "INTERNAL", "message": str(exc),
                                      "detail": "", "retryable": False}})
            if action.get("stop_on_error"):
                stopped = True
        if step_delay_ms:
            time.sleep(step_delay_ms / 1000)
    return {"total": len(actions),
            "succeeded": sum(1 for r in results if r["ok"]),
            "results": results}


def _validate_action(action):
    known = {"click", "move", "drag", "path", "type", "hotkey", "scroll",
             "focus", "wait_window", "sleep"}
    if action.get("type") not in known:
        raise invalid_args(f"type không hợp lệ: {action.get('type')!r}, hợp lệ: {sorted(known)}")


def _run_action(config, action):
    _validate_action(action)
    t = action["type"]
    if t == "click":
        backend.mouse_click(action.get("x"), action.get("y"),
                            action.get("button", "left"), action.get("clicks", 1))
    elif t == "move":
        backend.mouse_move(action["x"], action["y"])
    elif t == "drag":
        mouse_drag(config, action["from_x"], action["from_y"],
                   action["to_x"], action["to_y"], action.get("duration_seconds", 0.5))
    elif t == "path":
        backend.mouse_path(action["points"], action.get("total_duration_seconds", 1.0))
    elif t == "type":
        backend.type_text(action["text"], action.get("interval_seconds", 0.005))
    elif t == "hotkey":
        backend.hotkey(action["keys"])
    elif t == "scroll":
        backend.mouse_scroll(action["clicks"])
    elif t == "focus":
        backend.focus_window(action["title_contains"])
    elif t == "wait_window":
        res = wait_for_window(config, action["title_contains"],
                              action.get("timeout_seconds", 10.0))
        if not res["found"]:
            raise MangoError("WINDOW_NOT_FOUND", "Hết thời gian chờ cửa sổ.",
                             retryable=True)
    elif t == "sleep":
        time.sleep(float(action["seconds"]))


# ---------- Clipboard (nhóm quyền riêng) ----------

def clipboard_get_text(config):
    require(config, "clipboard")
    return {"text": backend.clipboard_get()}


def clipboard_set_text(config, text: str):
    require(config, "clipboard")
    return backend.clipboard_set(text)


# ---------- File (đọc và ghi là hai nhóm quyền tách nhau) ----------

def list_directory(config, path: str = ".", limit: int = 200):
    require(config, "files_read")
    p = Path(path)
    if not p.is_dir():
        raise MangoError("NOT_A_DIRECTORY", f"Không phải thư mục: {path}", retryable=False)
    rows = []
    for entry in sorted(p.iterdir(), key=lambda e: e.name.lower())[:limit]:
        try:
            st = entry.stat()
            rows.append({"name": entry.name, "path": str(entry),
                         "is_directory": entry.is_dir(), "size": st.st_size,
                         "modified": st.st_mtime})
        except OSError:
            continue
    return {"entries": rows}


def read_text_file(config, path: str, max_characters: int = 100000):
    require(config, "files_read")
    text = Path(path).read_text(encoding="utf-8", errors="strict")
    return {"path": path, "text": text[:max_characters],
            "truncated": len(text) > max_characters}


def write_text_file(config, path: str, content: str, overwrite: bool = False):
    require(config, "files_write")
    p = Path(path)
    if p.exists() and not overwrite:
        raise MangoError("ALREADY_EXISTS",
                         "File đã tồn tại. Đặt overwrite=true nếu muốn ghi đè.",
                         retryable=False)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(p), "bytes": p.stat().st_size}


def search_files(config, path: str, pattern: str = "*", max_results: int = 200):
    require(config, "files_read")
    base = Path(path)
    found = []
    scanned = 0
    for entry in base.rglob(pattern):
        scanned += 1
        if scanned > 20000:
            break
        found.append(str(entry))
        if len(found) >= max_results:
            break
    return {"matches": found, "scanned": scanned}


# ---------- Admin và mở ứng dụng ----------

def launch_application(config, executable: str, args: list = None, cwd: str = None):
    """App trong allowlist chỉ cần quyền input, ngoài allowlist cần admin.

    Cách phân tầng này tránh việc mở một app vô hại như Paint cũng bị
    chặn bởi cổng admin như ở thế hệ bot trước.
    """
    name = Path(executable).name.lower()
    if name in config.launch_allowlist():
        require(config, "input")
        gate = "allowlist"
    else:
        require(config, "admin")
        gate = "admin"
    proc = subprocess.Popen([executable] + list(args or []), cwd=cwd)
    return {"ok": True, "pid": proc.pid, "gate": gate}


def run_command(config, command: str, timeout_seconds: int = 60, shell: str = "powershell"):
    require(config, "admin")
    if platform.system() == "Windows" and shell == "powershell":
        argv = ["powershell", "-NoProfile", "-Command", command]
    else:
        argv = ["/bin/sh", "-c", command]
    try:
        out = subprocess.run(argv, capture_output=True, text=True,
                             timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        raise MangoError("COMMAND_TIMEOUT", f"Lệnh chạy quá {timeout_seconds} giây.",
                         retryable=True)
    return {"returncode": out.returncode,
            "stdout": out.stdout[-20000:], "stderr": out.stderr[-5000:]}


def terminate_process(config, pid: int):
    require(config, "admin")
    try:
        import psutil
        psutil.Process(pid).terminate()
    except ImportError:
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True, timeout=10)
        else:
            os.kill(pid, 15)
    return {"ok": True, "pid": pid}


# ---------- Phân tích màn hình (bản 0.2.0): vòng phản hồi mạnh hơn ----------

def _match(rgb, target, tolerance):
    return all(abs(int(a) - int(b)) <= tolerance for a, b in zip(rgb[:3], target[:3]))


def _region_of(img, region):
    if not region:
        return img, 0, 0
    x, y, w, h = region
    return img.crop((x, y, x + w, y + h)), x, y


def find_color_on_screen(config, rgb: list, region: list = None,
                         tolerance: int = 0, max_points: int = 50):
    """Tìm các điểm có màu cho trước trên màn hình.

    Dùng để bot tự định vị vật thể theo màu thay vì đoán tọa độ.
    """
    _check_lock_capture()
    img = backend.screenshot_image().convert("RGB")
    sub, ox, oy = _region_of(img, region)
    points = []
    px = sub.load()
    for yy in range(sub.height):
        for xx in range(sub.width):
            if _match(px[xx, yy], rgb, tolerance):
                points.append([xx + ox, yy + oy])
                if len(points) >= max_points:
                    return {"found": True, "points": points, "truncated": True}
    return {"found": bool(points), "points": points, "truncated": False}


def count_color_on_screen(config, rgb: list, region: list = None, tolerance: int = 0):
    """Đếm số pixel có màu cho trước: thước đo khách quan để nghiệm thu thao tác tô."""
    _check_lock_capture()
    img = backend.screenshot_image().convert("RGB")
    sub, _ox, _oy = _region_of(img, region)
    data = sub.getdata()
    count = sum(1 for p in data if _match(p, rgb, tolerance))
    return {"count": count, "region_pixels": len(data),
            "percent": round(100.0 * count / max(len(data), 1), 3)}


def wait_for_pixel(config, x: int, y: int, rgb: list, timeout_seconds: float = 10.0,
                   tolerance: int = 0):
    """Chờ tới khi một điểm trên màn hình đạt màu mong muốn (hoặc hết giờ).

    Đây là cách chờ giao diện sẵn sàng đúng nghĩa thay vì ngủ cố định:
    ví dụ chờ cửa sổ vẽ xong, chờ tô màu hoàn tất, chờ hộp thoại hiện.
    """
    require(config, "input")
    started = time.time()
    attempts = 0
    last = None
    while time.time() - started <= timeout_seconds:
        attempts += 1
        img = backend.screenshot_image()
        if 0 <= x < img.width and 0 <= y < img.height:
            last = list(img.getpixel((x, y))[:3])
            if _match(last, rgb, tolerance):
                return {"matched": True, "elapsed_seconds": round(time.time() - started, 2),
                        "attempts": attempts, "rgb": last}
        time.sleep(0.2)
    return {"matched": False, "elapsed_seconds": round(time.time() - started, 2),
            "attempts": attempts, "rgb": last}


# ---------- Input tiện ích (bản 0.2.0) ----------

def send_keys(config, keys: str):
    overlay.pulse()
    """Gửi tổ hợp phím dạng chữ: "ctrl+s", "alt+f4", "enter", "ctrl+shift+esc".

    Tiện hơn keyboard_hotkey vì gọi bằng một chuỗi duy nhất trong các
    chuỗi hành động và kịch bản tự động.
    """
    require(config, "input")
    parts = [p.strip().lower() for p in keys.split("+") if p.strip()]
    if not parts:
        raise invalid_args("keys rỗng, ví dụ hợp lệ: 'ctrl+s'")
    backend.hotkey(parts)
    return {"ok": True, "keys": parts}


def scroll_at(config, x: int, y: int, clicks: int):
    require(config, "input")
    backend.mouse_move(x, y)
    backend.mouse_scroll(clicks)
    return {"ok": True}


def close_window(config, title_contains: str):
    require(config, "input")
    return backend.close_window(title_contains)


def set_window_state(config, title_contains: str, state: str = None,
                     x: int = None, y: int = None, width: int = None, height: int = None):
    require(config, "input")
    return backend.set_window_state(title_contains, state, x, y, width, height)


def open_path(config, path: str):
    require(config, "input")
    return backend.open_path(path)


# ---------- File nâng cao (bản 0.2.0) ----------

def stat_file(config, path: str):
    require(config, "files_read")
    p = Path(path)
    if not p.exists():
        raise MangoError("NOT_FOUND", f"Không tồn tại: {path}", retryable=False)
    st = p.stat()
    return {"path": str(p), "is_directory": p.is_dir(), "size": st.st_size,
            "modified": st.st_mtime}


def copy_file(config, source: str, destination: str, overwrite: bool = False):
    require(config, "files_write")
    import shutil
    dst = Path(destination)
    if dst.exists() and not overwrite:
        raise MangoError("ALREADY_EXISTS", "Đích đã tồn tại. Đặt overwrite=true để ghi đè.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return {"ok": True, "destination": str(dst), "bytes": dst.stat().st_size}


def move_file(config, source: str, destination: str, overwrite: bool = False):
    require(config, "files_write")
    import shutil
    dst = Path(destination)
    if dst.exists() and not overwrite:
        raise MangoError("ALREADY_EXISTS", "Đích đã tồn tại. Đặt overwrite=true để ghi đè.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(source, destination)
    return {"ok": True, "destination": str(dst)}


def delete_file(config, path: str):
    require(config, "files_write")
    p = Path(path)
    if not p.exists():
        raise MangoError("NOT_FOUND", f"Không tồn tại: {path}", retryable=False)
    if p.is_dir():
        raise MangoError("IS_DIRECTORY", "Đây là thư mục; bản MVP chỉ xóa file.", retryable=False)
    p.unlink()
    return {"ok": True, "deleted": str(p)}


# ---------- Lớp phủ hiển thị trên màn hình (bản 0.3.0) ----------

def set_busy_overlay(config, active: bool, message: str = ""):
    """Bật/tắt khung viền xanh và banner "Bot đang sử dụng máy" trên màn hình.

    Bật thủ công khi bắt đầu một phiên điều khiển dài để người ngồi trước
    máy biết không nên đụng vào chuột/phím; tắt khi xong. Ngoài ra overlay
    cũng tự sáng trong vài giây mỗi khi có tool thao tác chạy.
    """
    require(config, "input")
    return overlay.set_busy(active, message)


def notify_on_screen(config, text: str, seconds: int = 5):
    """Hiện một thông báo ngắn ở cuối màn hình máy Windows trong vài giây."""
    require(config, "input")
    return overlay.notify(text, seconds)


# ---------- UI Automation + điều khiển Win32 + hiển thị (bản 0.4.0) ----------

def ui_tree(config, window_title: str = None, max_depth: int = 3, max_items: int = 120):
    """Xem cây phần tử giao diện của một cửa sổ (hoặc cả desktop).

    Đây là cách "nhìn" giao diện chính xác nhất: tên, loại, vị trí của
    từng nút bấm/ô nhập. Dùng trước khi ui_click/ui_set_text để biết
    tên phần tử cần thao tác."""
    require(config, "input")
    from . import uia
    return uia.tree(window_title, max_depth, max_items)


def ui_find(config, name: str, control_type: str = None, window_title: str = None,
            max_results: int = 10):
    """Tìm phần tử giao diện theo tên (không phân biệt hoa thường, khớp một phần).

    control_type có thể dùng tên thân thiện: button, edit, text, menuitem,
    checkbox, combobox, listitem, tabitem, window..."""
    require(config, "input")
    from . import uia
    return {"matches": uia.find(name, control_type, window_title, max_results)}


def ui_click(config, name: str, control_type: str = None, window_title: str = None):
    """Bấm một phần tử theo tên, ưu tiên Invoke Pattern (không cần chuột)."""
    require(config, "input")
    from . import uia
    overlay.pulse()
    return uia.click(name, control_type, window_title)


def ui_set_text(config, name: str, text: str, control_type: str = None,
                window_title: str = None):
    """Điền chữ vào một ô nhập theo tên, ưu tiên Value Pattern (tức thì)."""
    require(config, "input")
    from . import uia
    overlay.pulse()
    return uia.set_text(name, text, control_type, window_title)


def ui_get_text(config, name: str, control_type: str = None, window_title: str = None):
    """Đọc giá trị/nội dung của một phần tử theo tên."""
    require(config, "input")
    from . import uia
    return uia.get_text(name, control_type, window_title)


def find_controls(config, window_title: str, text_contains: str = None,
                  class_name: str = None, limit: int = 100):
    """Liệt kê các control Win32 con của một cửa sổ (handle, lớp, chữ, vị trí).

    Handle lấy được dùng tiếp với click_control/set_control_text. Cách này
    nhẹ và cực nhanh cho các ứng dụng Windows cổ điển và hộp thoại."""
    require(config, "input")
    hwnd, _title = backend._find_hwnd(window_title)
    rows = backend.enum_child_controls(hwnd)
    if text_contains:
        rows = [r for r in rows if text_contains.lower() in r["text"].lower()]
    if class_name:
        rows = [r for r in rows if class_name.lower() in r["class_name"].lower()]
    return {"controls": rows[:limit], "count": len(rows)}


def click_control(config, handle: int):
    """Bấm một control bằng handle (BM_CLICK): không chuột, không tọa độ."""
    require(config, "input")
    overlay.pulse()
    return backend.click_control(handle)


def set_control_text(config, handle: int, text: str):
    """Đặt chữ vào control bằng handle (WM_SETTEXT): tức thì."""
    require(config, "input")
    overlay.pulse()
    return backend.set_control_text(handle, text)


def get_control_text(config, handle: int):
    require(config, "input")
    return backend.get_control_text(handle)


def set_display_resolution(config, width: int, height: int):
    """Đổi (ghim) độ phân giải màn hình chính.

    Ghim độ phân giải trước các phiên thao tác theo tọa độ để giao diện
    không bị "trôi" khi kích thước hiển thị thay đổi giữa chừng."""
    require(config, "input")
    return backend.set_display_resolution(width, height)


def activate_or_launch(config, title_contains: str, executable: str,
                       timeout_seconds: float = 10.0):
    """Có cửa sổ rồi thì đưa lên trước, chưa có thì mở app và chờ sẵn sàng.

    Gộp 3 thao tác thường đi cùng nhau thành một lần gọi."""
    require(config, "input")
    overlay.pulse()
    found = [w for w in backend.list_windows() if title_contains.lower() in w["title"].lower()]
    if found:
        backend.focus_window(title_contains)
        return {"action": "focused", "title": found[0]["title"]}
    launched = launch_application(config, executable)
    waited = wait_for_window(config, title_contains, timeout_seconds)
    if waited.get("found"):
        backend.focus_window(title_contains)
    return {"action": "launched", "launch": launched, "window": waited}


# ---------- Snapshot có nhãn + OCR + hệ thống + Workflow (bản 0.5.0) ----------
# Học từ CursorTouch Windows-MCP (Snapshot/PowerShell/Process/Registry),
# sshh12 windows-computer-use-mcp (đọc chữ cửa sổ, OCR sẵn của Windows,
# chống thao tác trên "khung hình cũ"), Open Interpreter (lưu quy trình
# thành kỹ năng tái sử dụng) và n8n (workflow nhiều bước có retry/on_error
# và biến truyền giữa các bước).

_SNAPSHOT = {"elements": [], "window": {}, "taken_at": 0.0}


def snapshot(config, annotate: bool = True, window_title: str = None, max_width: int = 1280):
    """Chụp trạng thái màn hình: ảnh + danh sách phần tử tương tác có nhãn số.

    Một lần gọi thay cho chụp ảnh + đoán tọa độ: mỗi phần tử (nút bấm, ô
    nhập, mục menu...) có label, tên, loại và tọa độ tâm. Dùng click_label
    để bấm theo nhãn. annotate=true vẽ khung + số nhãn lên ảnh trả về."""
    _check_lock_capture()
    require(config, "input")
    import base64
    import io
    import time as _time

    from . import uia
    img = backend.screenshot_image()
    orig_w, orig_h = img.size
    scale = 1.0
    if orig_w > max_width:
        scale = max_width / orig_w
        img = img.resize((max_width, int(orig_h * scale)))
    data = uia.interactives(window_title)
    elements = data["elements"]
    if annotate and elements:
        from PIL import ImageDraw

        draw = ImageDraw.Draw(img)
        for el in elements:
            x, y, w, h = el["rect"]
            box = [x * scale, y * scale, (x + w) * scale, (y + h) * scale]
            draw.rectangle(box, outline=(46, 204, 113), width=2)
            draw.rectangle([box[0], box[1], box[0] + 22, box[1] + 13], fill=(220, 40, 40))
            draw.text((box[0] + 3, box[1] + 2), str(el["label"]), fill=(255, 255, 255))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=72)
    _SNAPSHOT["elements"] = elements
    _SNAPSHOT["window"] = data["window"]
    _SNAPSHOT["taken_at"] = _time.time()
    return {
        "image_base64": base64.b64encode(buf.getvalue()).decode(),
        "image_size": [img.size[0], img.size[1]],
        "screen_size": [orig_w, orig_h],
        "scale": round(scale, 4),
        "window": data["window"],
        "focused": uia.focused_info(),
        "elements": elements,
        "note": "Tọa độ center/rect là tọa độ màn hình thật. Nhân tọa độ trên ảnh với 1/scale nếu cần đổi từ ảnh về màn hình.",
    }


def _revalidate(element):
    """Tìm lại phần tử của snapshot theo tên+loại để lấy vị trí hiện tại."""
    from . import uia

    matches = uia.find(element["name"], element["control_type"],
                       _SNAPSHOT["window"].get("name") or None, max_results=5)
    for m in matches:
        return m
    return None


def click_label(config, label: int):
    """Bấm phần tử theo nhãn của lần snapshot gần nhất.

    Trước khi bấm, server tìm lại phần tử theo tên/loại: còn đó thì bấm
    vào vị trí HIỆN TẠI (ưu tiên Invoke), mất rồi thì báo SNAPSHOT_STALE
    thay vì bấm bừa vào tọa độ cũ (bài học stale frame của wcum)."""
    require(config, "input")
    overlay.pulse()
    element = next((e for e in _SNAPSHOT["elements"] if e["label"] == int(label)), None)
    if element is None:
        raise MangoError("SNAPSHOT_STALE",
                         f"Chưa có snapshot nào chứa nhãn {label}. Hãy gọi snapshot trước.",
                         retryable=True)
    fresh = _revalidate(element) if element["name"] else None
    if element["name"] and fresh is None:
        raise MangoError("SNAPSHOT_STALE",
                         f"Phần tử '{element['name']}' không còn trên màn hình. Hãy snapshot lại.",
                         retryable=True)
    if fresh is not None:
        from . import uia
        try:
            result = uia.click(element["name"], element["control_type"],
                               _SNAPSHOT["window"].get("name") or None)
            return {"label": label, **result}
        except MangoError:
            pass
        cx, cy = fresh["center"]
    else:
        cx, cy = element["center"]
    backend.mouse_click(cx, cy)
    return {"label": label, "name": element["name"], "method": "mouse", "center": [cx, cy]}


def multi_click(config, labels: list, press_ctrl: bool = True):
    """Bấm nhiều phần tử theo nhãn trong một lần gọi (chọn nhiều mục).

    press_ctrl=true giữ Ctrl khi bấm (chọn rời rạc kiểu Explorer);
    false thì bấm lần lượt bình thường. Học từ Windows-MCP MultiSelect."""
    require(config, "input")
    overlay.pulse()
    done = []
    if press_ctrl:
        backend.key_down("ctrl")
    try:
        for label in labels:
            element = next((e for e in _SNAPSHOT["elements"] if e["label"] == int(label)), None)
            if element is None:
                raise MangoError("SNAPSHOT_STALE", f"Nhãn {label} không có trong snapshot gần nhất.",
                                 retryable=True)
            cx, cy = element["center"]
            backend.mouse_click(cx, cy)
            done.append(label)
    finally:
        if press_ctrl:
            backend.key_up("ctrl")
    return {"ok": True, "clicked": done, "press_ctrl": press_ctrl}


def read_window_text(config, window_title: str, use_ocr: bool = False):
    """Đọc chữ trong một cửa sổ bằng UI Automation (nhanh, không cần ảnh).

    use_ocr=true và UIA không đọc được chữ (app vẽ chữ lên canvas) thì
    dự phòng bằng OCR trên đúng vùng cửa sổ."""
    require(config, "input")
    from . import uia
    result = uia.window_text(window_title)
    if use_ocr and not result["text"]:
        hwnd, _t = backend._find_hwnd(window_title)
        import ctypes
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        img = backend.screenshot_image().crop((rect.left, rect.top, rect.right, rect.bottom))
        words = backend.ocr_image(img, rect.left, rect.top)
        result["text"] = " ".join(w["t"] for w in words)
        result["source"] = "ocr"
        result["words"] = len(words)
    else:
        result["source"] = "uia"
    return result


def find_text_on_screen(config, text: str):
    """Tìm vị trí một đoạn chữ trên màn hình bằng OCR có sẵn của Windows.

    Trả tọa độ tâm của cụm từ khớp để bấm vào — cứu cánh cho các ứng
    dụng vẽ chữ lên canvas mà UI Automation không đọc được."""
    require(config, "input")
    words = backend.ocr_image(backend.screenshot_image())
    query = [w.lower() for w in text.split() if w]
    matches = []
    lowered = [w["t"].lower().strip(".,:;!?\"'") for w in words]
    for i in range(0, len(words) - len(query) + 1):
        if lowered[i:i + len(query)] == query:
            group = words[i:i + len(query)]
            x0 = min(w["x"] for w in group)
            y0 = min(w["y"] for w in group)
            x1 = max(w["x"] + w["w"] for w in group)
            y1 = max(w["y"] + w["h"] for w in group)
            matches.append({"text": " ".join(w["t"] for w in group),
                            "rect": [x0, y0, x1 - x0, y1 - y0],
                            "center": [(x0 + x1) // 2, (y0 + y1) // 2]})
    return {"matches": matches, "words_scanned": len(words)}


def powershell(config, command: str, timeout_seconds: float = 60.0):
    """Chạy lệnh PowerShell trên máy đích (cổng quyền admin).

    Là giao diện quản trị sâu của Windows: dịch vụ, mạng, người dùng,
    tác vụ nền... Chỉ chạy khi nhóm quyền admin được bật ở máy đích."""
    require(config, "admin")
    overlay.pulse()
    return backend.run_powershell(command, timeout_seconds)


def list_processes(config, name_filter: str = None, limit: int = 50):
    """Liệt kê tiến trình đang chạy (tên, PID, bộ nhớ)."""
    require(config, "input")
    return backend.list_processes(name_filter, limit)


def kill_process(config, pid: int = None, name: str = None):
    """Kết thúc một tiến trình theo PID hoặc tên (cổng quyền admin)."""
    require(config, "admin")
    return backend.kill_process(pid, name)


def registry_get(config, path: str, name: str = None):
    """Đọc registry: một giá trị cụ thể, hoặc liệt kê cả khóa khi name trống.

    path dạng 'HKCU\\Software\\...' hoặc 'HKLM\\SOFTWARE\\...'."""
    require(config, "input")
    return backend.registry_get(path, name)


def registry_set(config, path: str, name: str, value, reg_type: str = "SZ"):
    """Ghi một giá trị registry (cổng quyền admin).

    reg_type: SZ, EXPAND_SZ, MULTI_SZ, DWORD, QWORD, BINARY."""
    require(config, "admin")
    return backend.registry_set(path, name, value, reg_type)


# ----- Thư viện workflow: quy trình lưu sẵn, chạy lại nguyên khối -----

_WORKFLOW_DIR = Path(__file__).resolve().parent.parent / "workflows"
_WORKFLOW_BLOCKED = {"run_workflow", "run_saved_workflow", "save_workflow", "delete_workflow"}


def _workflow_path(name: str) -> Path:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_ ").strip()
    if not safe:
        raise MangoError("INVALID_ARGUMENT", "Tên workflow không hợp lệ.")
    return _WORKFLOW_DIR / f"{safe}.json"


def _substitute_prev(value, prev_json: str):
    if isinstance(value, str):
        return value.replace("{{prev}}", prev_json)
    if isinstance(value, list):
        return [_substitute_prev(v, prev_json) for v in value]
    if isinstance(value, dict):
        return {k: _substitute_prev(v, prev_json) for k, v in value.items()}
    return value


def run_workflow(config, steps: list):
    """Chạy một chuỗi bước ngay trên server trong MỘT lần gọi.

    Mỗi bước: {"tool": tên tool, "args": {...}, "retries": 0,
    "on_error": "stop"|"continue"}. Trong args, chuỗi "{{prev}}" được
    thay bằng kết quả JSON của bước liền trước. Trả bản ghi từng bước
    như execution log của n8n: bước nào xong, bước nào lỗi, thử mấy lần."""
    require(config, "input")
    overlay.pulse()
    import json as _json
    import time as _time

    results = []
    prev = None
    ok_all = True
    for idx, step in enumerate(steps):
        tool_name = step.get("tool", "")
        args = step.get("args", {}) or {}
        retries = int(step.get("retries", 0))
        on_error = step.get("on_error", "stop")
        fn = globals().get(tool_name)
        if tool_name in _WORKFLOW_BLOCKED or not callable(fn):
            entry = {"step": idx + 1, "tool": tool_name, "ok": False,
                     "error": "TOOL_NOT_ALLOWED_OR_UNKNOWN"}
            results.append(entry)
            ok_all = False
            if on_error == "stop":
                break
            continue
        if prev is not None:
            args = _substitute_prev(args, _json.dumps(prev, ensure_ascii=False)[:1500])
        attempts, last_error, value = 0, None, None
        while attempts <= retries:
            attempts += 1
            try:
                value = fn(config, **args)
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001 - ghi vào execution log
                last_error = str(getattr(exc, "message", exc))[:300]
                if attempts <= retries:
                    _time.sleep(0.5)
        if last_error is None:
            prev = value
            results.append({"step": idx + 1, "tool": tool_name, "ok": True,
                            "attempts": attempts,
                            "result": _json.dumps(value, ensure_ascii=False, default=str)[:400]})
        else:
            ok_all = False
            results.append({"step": idx + 1, "tool": tool_name, "ok": False,
                            "attempts": attempts, "error": last_error})
            if on_error == "stop":
                break
    return {"ok": ok_all, "steps": results, "completed": len(results)}


def save_workflow(config, name: str, steps: list, description: str = ""):
    """Lưu một workflow đặt tên lên máy đích để chạy lại nhiều lần.

    Như "teach mode" của Open Interpreter và template của n8n: quy trình
    nào làm thành công một lần thì lưu lại, lần sau gọi nguyên khối."""
    require(config, "files_write")
    _WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
    path = _workflow_path(name)
    import json as _json
    path.write_text(_json.dumps({"name": name, "description": description, "steps": steps},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "name": name, "steps": len(steps), "path": str(path)}


def list_workflows(config):
    require(config, "input")
    out = []
    if _WORKFLOW_DIR.exists():
        import json as _json
        for f in sorted(_WORKFLOW_DIR.glob("*.json")):
            try:
                data = _json.loads(f.read_text(encoding="utf-8"))
                out.append({"name": data.get("name", f.stem),
                            "description": data.get("description", ""),
                            "steps": len(data.get("steps", []))})
            except Exception:
                continue
    return {"workflows": out, "count": len(out)}


def run_saved_workflow(config, name: str):
    """Chạy một workflow đã lưu bằng save_workflow."""
    require(config, "input")
    path = _workflow_path(name)
    if not path.exists():
        raise MangoError("NOT_FOUND", f"Chưa có workflow tên '{name}'.", retryable=False)
    import json as _json
    data = _json.loads(path.read_text(encoding="utf-8"))
    return run_workflow(config, data.get("steps", []))


def delete_workflow(config, name: str):
    require(config, "files_write")
    path = _workflow_path(name)
    if path.exists():
        path.unlink()
    return {"ok": True, "name": name}
