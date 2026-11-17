"""Điều khiển PC qua agent-desktop CLI (Vercel Labs v1.2.0) — cây UI Automation.

Đây là đường điều khiển mới của MangoMCP 0.13.0, thay thế vòng lặp
"screenshot rồi đoán tọa độ" bằng vòng lặp "snapshot → ref → act":

1. `desktop_snapshot` đọc cây accessibility (UI Automation) của một cửa
   sổ/app, trả JSON kèm ref từng phần tử tương tác (`@<snapshot_id>:e<N>`).
2. Các lệnh sau (`desktop_click`, `desktop_type`, `desktop_set_value`...)
   thao tác theo ref đó, không cần tọa độ chuột, không cần ảnh màn hình.
3. Sau mỗi thao tác, snapshot lại vùng đó để kiểm chứng trạng thái mới.

Quy tắc ref (theo skill agent-desktop):
- Ref chỉ dùng được với đúng snapshot đã sinh ra nó. Sau bất kỳ thay đổi
  giao diện nào, snapshot lại rồi dùng ref mới.
- `STALE_REF`: phần tử đã biến mất — snapshot lại.
- `AMBIGUOUS_TARGET`: có phần tử giống hệt (twin) — không lặp lại ref đó;
  thao tác lên control duy nhất trong cửa sổ, hoặc dùng click theo tọa độ.
- Lỗi mang `disposition.retry == "safe"` (chưa gửi gì đi) mới được thử lại;
  các lỗi khác có thể đã tác động rồi, lặp lại sẽ bấm/gõ hai lần.

Headed (input vật lý) hay headless (ngữ nghĩa):
- Mặc định headless: click/set-value/clear/select/toggle/scroll/press dùng
  lời gọi UI Automation ngữ nghĩa, không di chuột, không cướp focus.
- Các lệnh sau BẮT BUỘC `--headed` trên Windows (headless trả
  `POLICY_DENIED`): `type`, `right-click`, `double-click`, `triple-click`,
  `focus`. Vì vậy các tool tương ứng mặc định `headed=True`.
- `--headed` nghĩa là di chuột/gõ phím thật và có thể cướp foreground:
  chỉ bật khi thật sự cần, không dùng để "chữa" một lỗi headless.

Cách gọi CLI:
- Gọi trực tiếp bằng `subprocess` với args dạng list, KHÔNG qua
  PowerShell (PowerShell đọc `@token` thành toán tử splatting và nuốt
  mất ref). Ref được truyền nguyên vẹn như một phần tử argv.
- Text dài (>200 ký tự) đi qua `--stdin` thay vì argv, tránh vỡ vì
  ký tự đặc biệt và giới hạn độ dài dòng lệnh.
- Mọi lệnh trả một envelope JSON `{version, ok, command, data/error}`.
  Exit code 0 = thành công, 1 = lỗi có cấu trúc (JSON trên stdout),
  2 = lỗi parse đối số (envelope vẫn in ra).

Snapshot có thể rất lớn (cửa sổ phức tạp): module cắt ngắn cây khi JSON
thô vượt ~200KB, đánh dấu `truncated` + `mangomcp_truncated`, giữ nguyên
các ref ở phần cây còn lại.
"""
import json
import os
import re
import subprocess

from .core import require
from .errors import MangoError, invalid_args
from . import overlay

# Vị trí mặc định của binary trên máy đích (đi kèm gói cài đặt 0.13.0,
# xem packaging/build130.ps1). Đổi được qua config `desktop_binary`.
DEFAULT_DESKTOP_BINARY = r"C:\MangoMCP\bin\agent-desktop.exe"

# Snapshot thô vượt ngưỡng này thì cắt ngắn cây trước khi trả về.
MAX_SNAPSHOT_BYTES = 200 * 1024

# Text dài hơn ngưỡng này thì truyền qua --stdin thay vì argv.
LONG_TEXT_STDIN_CHARS = 200

# Giới hạn --stdin của CLI theo từng lệnh (xem cli_args/actions.rs,
# cli_args/system.rs): type 10.000 byte, set-value/clipboard-set 128 KiB.
TYPE_STDIN_LIMIT_BYTES = 10_000
SET_VALUE_STDIN_LIMIT_BYTES = 128 * 1024

_REF_RE = re.compile(r"^@[^:\s]+:e\d+$")

_SURFACES = {
    "window", "focused", "menu", "menubar", "sheet", "popover", "alert",
    "desktop", "taskbar", "system-tray", "quick-settings",
    "notification-center", "toolbar", "dock", "spotlight",
    "menu-bar-extras", "system-tray-overflow", "start-menu",
    "action-center",
}

# Lệnh chỉ đọc: timeout của subprocess cũng an toàn để thử lại.
_READ_ONLY_COMMANDS = {
    "snapshot", "find", "get", "is", "screenshot", "list-surfaces",
    "list-windows", "list-apps", "list-displays", "status", "permissions",
    "version", "clipboard-get", "wait",
}


def _binary_path(config):
    """Đường dẫn binary agent-desktop: config `desktop_binary` hoặc mặc định."""
    getter = getattr(config, "desktop_binary", None)
    if callable(getter):
        path = getter()
    else:
        data = getattr(config, "data", None) or {}
        path = data.get("desktop_binary", "")
    path = str(path or "").strip()
    return path or DEFAULT_DESKTOP_BINARY


def _check_ref(ref):
    if not isinstance(ref, str) or not _REF_RE.match(ref):
        raise invalid_args(
            f"Ref không hợp lệ: {ref!r}. Ref phải có dạng @<snapshot_id>:e<N>, "
            "lấy từ desktop_snapshot/desktop_find của cùng một snapshot.")
    return ref


def _check_surface(surface):
    if surface not in _SURFACES:
        raise invalid_args(
            f"Surface không hợp lệ: {surface!r}. Chọn một trong: "
            + ", ".join(sorted(_SURFACES)) + ".")
    return surface


def _check_direction(direction):
    if direction not in ("up", "down", "left", "right"):
        raise invalid_args(
            f"Hướng cuộn không hợp lệ: {direction!r}. Chọn up/down/left/right.")
    return direction


def _check_property(prop):
    if prop not in ("text", "value", "title", "bounds", "role", "states"):
        raise invalid_args(
            f"Property không hợp lệ: {prop!r}. Chọn text/value/title/bounds/role/states.")
    return prop


def _stdin_or_arg(text, limit_bytes):
    """Quyết định truyền text qua --stdin hay argv.

    Trả (use_stdin, text). Text vượt giới hạn byte của CLI thì báo lỗi
    rõ ràng thay vì để CLI cắt ngắn lặng lẽ."""
    if text is None:
        raise invalid_args("Thiếu text cần truyền.")
    encoded = text.encode("utf-8")
    if len(encoded) > limit_bytes:
        raise invalid_args(
            f"Text dài {len(encoded)} byte, vượt giới hạn {limit_bytes} byte "
            "của --stdin. Chia nhỏ text rồi gửi từng phần.")
    return len(text) > LONG_TEXT_STDIN_CHARS, text


# ---------------- Cắt ngắn cây snapshot ----------------

def _prune_tree(node, budget):
    """Cắt bớt cây snapshot cho vừa ngân sách byte (ước lượng).

    Giữ nguyên các nút con đầu tiên còn vừa ngân sách; nút con đầu tiên
    không vừa thì giữ lại bản cắt ngắn của nó, các nút sau bị bỏ hẳn.
    Nút bị cắt mang `subtree_truncated: true` và `children_count` gốc.
    Trả (node_moi, so_byte_uoc_luong)."""
    if not isinstance(node, dict):
        return node, 0
    children = list(node.get("children") or [])
    base = {k: v for k, v in node.items() if k != "children"}
    base_size = len(json.dumps(base, ensure_ascii=False))
    if not children:
        return dict(base), base_size
    out = dict(base)
    kept = []
    used = base_size + len('"children":[]')
    cut = False
    for child in children:
        if cut:
            continue
        child_size = len(json.dumps(child, ensure_ascii=False))
        if used + child_size <= budget:
            kept.append(child)
            used += child_size + 1
        else:
            # Nút con đầu tiên không vừa: giữ lại bản cắt ngắn của nó,
            # các nút sau bị bỏ hẳn (đánh dấu bằng subtree_truncated).
            pruned, psize = _prune_tree(child, max(budget - used, 0))
            kept.append(pruned)
            used += psize + 1
            cut = True
    out["children"] = kept
    if cut or len(kept) < len(children):
        out["subtree_truncated"] = True
        out["children_count"] = len(children)
    return out, used


def _truncate_snapshot(data, raw_bytes):
    """Cắt ngắn cây của một snapshot quá lớn, đánh dấu rõ ràng."""
    if not isinstance(data, dict) or not isinstance(data.get("tree"), dict):
        return data
    out = dict(data)
    pruned, _used = _prune_tree(data["tree"], MAX_SNAPSHOT_BYTES)
    out["tree"] = pruned
    out["truncated"] = True
    out["mangomcp_truncated"] = True
    out["mangomcp_original_bytes"] = raw_bytes
    return out


# ---------------- Chạy CLI ----------------

def run_desktop(config, args, timeout_ms=30000, stdin_text=None, headed=False):
    """Chạy một lệnh agent-desktop, trả `data` của envelope JSON.

    `args`: list argv sau tên binary, ví dụ ["snapshot", "--app", "Notepad"].
    `timeout_ms`: deadline của chính lệnh CLI; subprocess được cộng thêm
    15 giây ân hạn để CLI kịp trả envelope lỗi thay vì bị giết ngang.
    `stdin_text`: text truyền qua stdin khi lệnh có cờ --stdin.
    `headed`: thêm cờ global --headed (input vật lý, có thể cướp focus).
    Lỗi CLI (ok=false) được chuyển thành MangoError giữ nguyên mã lỗi
    của agent-desktop (STALE_REF, AMBIGUOUS_TARGET, POLICY_DENIED...),
    `retryable` theo `disposition.retry == "safe"`."""
    binary = _binary_path(config)
    if not os.path.isfile(binary):
        raise MangoError(
            "DESKTOP_UNAVAILABLE",
            "Chưa có agent-desktop trên máy này: không thấy file "
            f"{binary}. Cài lại gói MangoMCP 0.13.0 (kèm bin\\agent-desktop.exe) "
            "rồi thử lại.",
            detail=f"desktop_binary: {binary}",
            retryable=False,
        )
    command = args[0] if args else ""
    argv = [binary]
    if headed:
        argv.append("--headed")
    argv.extend(str(a) for a in args)
    sub_timeout = max(float(timeout_ms or 0), 1000.0) / 1000.0 + 15.0
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            argv, input=stdin_text, capture_output=True, text=True,
            encoding="utf-8", timeout=sub_timeout, **kwargs)
    except subprocess.TimeoutExpired:
        raise MangoError(
            "DESKTOP_TIMEOUT",
            f"Lệnh agent-desktop '{command}' quá {timeout_ms}ms mà chưa trả kết quả.",
            detail=" ".join(argv[1:]),
            retryable=command in _READ_ONLY_COMMANDS,
        )
    except FileNotFoundError:
        raise MangoError(
            "DESKTOP_UNAVAILABLE",
            f"Không chạy được agent-desktop tại {binary} (file vừa biến mất).",
            detail=f"desktop_binary: {binary}",
            retryable=False,
        )
    except OSError as exc:
        raise MangoError("DESKTOP_UNAVAILABLE",
                         f"Không chạy được agent-desktop: {exc}",
                         detail=f"desktop_binary: {binary}", retryable=False)
    stdout = proc.stdout or ""
    if not stdout.strip():
        raise MangoError(
            "DESKTOP_BAD_OUTPUT",
            f"agent-desktop '{command}' không trả JSON (exit {proc.returncode}).",
            detail=(proc.stderr or "")[:500],
            retryable=command in _READ_ONLY_COMMANDS,
        )
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise MangoError(
            "DESKTOP_BAD_OUTPUT",
            f"agent-desktop '{command}' trả stdout không phải JSON: {exc}",
            detail=stdout[:500],
            retryable=command in _READ_ONLY_COMMANDS,
        )
    if not isinstance(envelope, dict) or "ok" not in envelope:
        raise MangoError(
            "DESKTOP_BAD_OUTPUT",
            f"agent-desktop '{command}' trả JSON không đúng envelope.",
            detail=stdout[:500],
            retryable=command in _READ_ONLY_COMMANDS,
        )
    if envelope.get("ok"):
        data = envelope.get("data")
        if command == "snapshot" and len(stdout.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            data = _truncate_snapshot(data, len(stdout.encode("utf-8")))
        return data
    err = envelope.get("error") or {}
    code = str(err.get("code") or "DESKTOP_ERROR")
    message = str(err.get("message") or f"agent-desktop '{command}' thất bại.")
    suggestion = str(err.get("suggestion") or "")
    disposition = err.get("disposition") or {}
    detail = suggestion
    if err.get("details"):
        detail = (detail + " | details: "
                  + json.dumps(err["details"], ensure_ascii=False)[:500]).strip(" |")
    raise MangoError(
        code, message, detail=detail,
        retryable=disposition.get("retry") == "safe",
    )


def _ref_timeout_args(ref, timeout_ms):
    return [_check_ref(ref), "--timeout-ms", str(int(timeout_ms))]


# ---------------- Chỉ đọc: trạng thái, danh sách ----------------

def desktop_status(config):
    """Trạng thái agent-desktop: nền tảng, quyền, các surface hỗ trợ.

    Tool chỉ đọc, luôn dùng được (kể cả khi binary chưa có thì báo
    DESKTOP_UNAVAILABLE rõ ràng thay vì sập)."""
    return run_desktop(config, ["status"], timeout_ms=10000)


def desktop_list_apps(config, app: str = None, timeout_ms: int = 5000):
    """Liệt kê các ứng dụng đang chạy (để lấy tên cho snapshot/launch)."""
    args = ["list-apps"]
    if app:
        args += ["--app", app]
    args += ["--timeout-ms", str(int(timeout_ms))]
    return run_desktop(config, args, timeout_ms=timeout_ms)


def desktop_list_windows(config, app: str = None, timeout_ms: int = 5000):
    """Liệt kê các cửa sổ đang mở (id, tiêu đề, app chủ)."""
    args = ["list-windows"]
    if app:
        args += ["--app", app]
    args += ["--timeout-ms", str(int(timeout_ms))]
    return run_desktop(config, args, timeout_ms=timeout_ms)


# ---------------- Quan sát: snapshot / find / get ----------------

def desktop_snapshot(config, app: str = None, window_id: str = None,
                     surface: str = "window", skeleton: bool = False,
                     compact: bool = False, interactive: bool = False,
                     max_depth: int = 10, root: str = None,
                     timeout_ms: int = 3000, include_bounds: bool = False):
    """Đọc cây giao diện (UI Automation) của một app/cửa sổ/surface.

    Đây là "mắt" mới của MangoMCP: thay cho chụp ảnh rồi đoán tọa độ,
    snapshot trả JSON cây phần tử kèm ref (`@<snapshot_id>:e<N>`) để các
    lệnh sau thao tác theo ref. Bắt đầu bằng `--skeleton -i --compact`
    để có bản đồ nông, rồi khoan vào một vùng bằng `root` (ref của vùng
    đó). `surface`: window (mặc định), focused, menu, sheet, alert,
    desktop, taskbar... Cây quá ~200KB sẽ bị cắt ngắn và đánh dấu
    `truncated` + `mangomcp_truncated`. Chỉ kiểm tra khóa chụp ảnh
    (như screenshot), không cần nhóm quyền input."""
    from .core import _check_lock_capture
    _check_lock_capture()
    args = ["snapshot"]
    if app:
        args += ["--app", app]
    if window_id:
        args += ["--window-id", window_id]
    args += ["--surface", _check_surface(surface)]
    if skeleton:
        args.append("--skeleton")
    if compact:
        args.append("--compact")
    if interactive:
        args.append("-i")
    if include_bounds:
        args.append("--include-bounds")
    args += ["--max-depth", str(int(max_depth))]
    if root:
        args += ["--root", _check_ref(root)]
    args += ["--timeout-ms", str(int(timeout_ms))]
    return run_desktop(config, args, timeout_ms=timeout_ms)


def desktop_find(config, role: str = None, name: str = None, value: str = None,
                 text: str = None, description: str = None,
                 native_id: str = None, exact: bool = False,
                 app: str = None, window_id: str = None,
                 surface: str = "window", root: str = None,
                 timeout_ms: int = 5000, limit: int = None,
                 first: bool = False, count: bool = False):
    """Tìm phần tử trong cây giao diện theo role/tên/giá trị/chữ.

    Dùng khi đã biết cần tìm gì (vd nút tên "Open"). `first` trả match
    đầu tiên, `count` chỉ trả số lượng, `limit` giới hạn số match.
    `root` giới hạn tìm trong cây con của một ref. Chỉ kiểm tra khóa
    chụp ảnh (như screenshot), không cần nhóm quyền input."""
    from .core import _check_lock_capture
    _check_lock_capture()
    if sum([bool(first), bool(count), limit is not None]) > 1:
        raise invalid_args("first, count và limit loại trừ lẫn nhau: chỉ dùng một.")
    args = ["find"]
    if app:
        args += ["--app", app]
    if window_id:
        args += ["--window-id", window_id]
    args += ["--surface", _check_surface(surface)]
    if role:
        args += ["--role", role]
    if name:
        args += ["--name", name]
    if value:
        args += ["--value", value]
    if text:
        args += ["--text", text]
    if description:
        args += ["--description", description]
    if native_id:
        args += ["--native-id", native_id]
    if exact:
        args.append("--exact")
    if root:
        args += ["--root", _check_ref(root)]
    args += ["--timeout-ms", str(int(timeout_ms))]
    if first:
        args.append("--first")
    elif count:
        args.append("--count")
    elif limit is not None:
        args += ["--limit", str(int(limit))]
    return run_desktop(config, args, timeout_ms=timeout_ms)


def desktop_get(config, ref: str, property: str = "text"):
    """Đọc một thuộc tính của phần tử theo ref: text/value/title/bounds/
    role/states. Dùng để kiểm chứng sau một thao tác (vd đọc lại text
    của ô vừa điền). Chỉ kiểm tra khóa chụp ảnh, không cần quyền input."""
    from .core import _check_lock_capture
    _check_lock_capture()
    args = ["get", _check_ref(ref), "--property", _check_property(property)]
    return run_desktop(config, args, timeout_ms=5000)


# ---------------- Thao tác theo ref ----------------

def desktop_click(config, ref: str, timeout_ms: int = 5000, headed: bool = False):
    """Bấm một phần tử theo ref, bằng lời gọi UI Automation ngữ nghĩa
    (headless mặc định: không di chuột, không cướp focus)."""
    require(config, "input")
    overlay.pulse()
    return run_desktop(config, ["click"] + _ref_timeout_args(ref, timeout_ms),
                       timeout_ms=timeout_ms, headed=headed)


def desktop_double_click(config, ref: str, timeout_ms: int = 5000,
                         headed: bool = True):
    """Bấm đúp một phần tử theo ref. Trên Windows lệnh này bắt buộc
    --headed (input vật lý) nên mặc định headed=True; headless trả
    POLICY_DENIED."""
    require(config, "input")
    overlay.pulse()
    return run_desktop(config, ["double-click"] + _ref_timeout_args(ref, timeout_ms),
                       timeout_ms=timeout_ms, headed=headed)


def desktop_right_click(config, ref: str, timeout_ms: int = 5000,
                        headed: bool = True):
    """Bấm chuột phải một phần tử theo ref (mở menu ngữ cảnh). Trên
    Windows lệnh này bắt buộc --headed nên mặc định headed=True."""
    require(config, "input")
    overlay.pulse()
    return run_desktop(config, ["right-click"] + _ref_timeout_args(ref, timeout_ms),
                       timeout_ms=timeout_ms, headed=headed)


def desktop_type(config, ref: str, text: str, timeout_ms: int = None,
                 interval_ms: int = None, headed: bool = True):
    """Gõ chữ vào một phần tử theo ref, bằng keystroke thật (SendInput).

    Trên Windows lệnh này bắt buộc --headed nên mặc định headed=True.
    Text dài >200 ký tự đi qua --stdin (tối đa 10.000 byte). Sau khi gõ,
    kiểm chứng bằng desktop_get vì có trường không đọc lại được lựa chọn
    Text (kết quả delivered_unverified)."""
    require(config, "input")
    overlay.pulse()
    use_stdin, text = _stdin_or_arg(text, TYPE_STDIN_LIMIT_BYTES)
    args = ["type", _check_ref(ref)]
    if use_stdin:
        args.append("--stdin")
    else:
        args.append(text)
    if timeout_ms is not None:
        args += ["--timeout-ms", str(int(timeout_ms))]
    if interval_ms is not None:
        args += ["--interval-ms", str(int(interval_ms))]
    return run_desktop(config, args,
                       timeout_ms=timeout_ms or 30000,
                       stdin_text=text if use_stdin else None,
                       headed=headed)


def desktop_set_value(config, ref: str, value: str, timeout_ms: int = 5000,
                      headed: bool = False):
    """Đặt giá trị cho một phần tử theo ref (ô nhập, dropdown...), bằng
    Value Pattern ngữ nghĩa — tức thì, không gõ từng phím. Ưu tiên dùng
    lệnh này thay cho desktop_type khi chỉ cần điền chữ. Value dài
    >200 ký tự đi qua --stdin (tối đa 128 KiB)."""
    require(config, "input")
    overlay.pulse()
    use_stdin, value = _stdin_or_arg(value, SET_VALUE_STDIN_LIMIT_BYTES)
    args = ["set-value", _check_ref(ref)]
    if use_stdin:
        args.append("--stdin")
    else:
        args.append(value)
    args += ["--timeout-ms", str(int(timeout_ms))]
    return run_desktop(config, args, timeout_ms=timeout_ms,
                       stdin_text=value if use_stdin else None,
                       headed=headed)


def desktop_clear(config, ref: str, timeout_ms: int = 5000,
                  headed: bool = False):
    """Xóa giá trị của một phần tử theo ref (đặt thành chuỗi rỗng)."""
    require(config, "input")
    overlay.pulse()
    return run_desktop(config, ["clear"] + _ref_timeout_args(ref, timeout_ms),
                       timeout_ms=timeout_ms, headed=headed)


def desktop_select(config, ref: str, value: str, timeout_ms: int = 5000,
                   headed: bool = False):
    """Chọn một mục trong list/dropdown theo ref (value là tên mục)."""
    require(config, "input")
    overlay.pulse()
    return run_desktop(config,
                       ["select", _check_ref(ref), value,
                        "--timeout-ms", str(int(timeout_ms))],
                       timeout_ms=timeout_ms, headed=headed)


def desktop_toggle(config, ref: str, timeout_ms: int = 5000,
                   headed: bool = False):
    """Bật/tắt một checkbox hoặc switch theo ref."""
    require(config, "input")
    overlay.pulse()
    return run_desktop(config, ["toggle"] + _ref_timeout_args(ref, timeout_ms),
                       timeout_ms=timeout_ms, headed=headed)


def desktop_scroll(config, ref: str, direction: str = "down", amount: int = 3,
                   timeout_ms: int = 5000, headed: bool = False):
    """Cuộn tại một phần tử theo ref. direction: up/down/left/right."""
    require(config, "input")
    overlay.pulse()
    args = ["scroll", _check_ref(ref), "--direction", _check_direction(direction),
            "--amount", str(int(amount)), "--timeout-ms", str(int(timeout_ms))]
    return run_desktop(config, args, timeout_ms=timeout_ms, headed=headed)


# ---------------- Bàn phím, app, cửa sổ, chờ ----------------

def desktop_press(config, combo: str, app: str = None, force: bool = False,
                  headed: bool = False):
    """Nhấn một tổ hợp phím (vd "return", "escape", "ctrl+c", "ctrl+s").

    Không ghi tắt shell nguy hiểm (alt+f4, win+l, win+d, alt+tab, win+r,
    win+e, ctrl+shift+esc...) trừ khi force=True. `app` gửi phím tới
    process đó mà không focus nó (headless); kèm --headed thì focus
    cửa sổ của app trước."""
    require(config, "input")
    overlay.pulse()
    if not combo or not str(combo).strip():
        raise invalid_args("combo trống: ví dụ 'return', 'escape', 'ctrl+c'.")
    args = ["press", str(combo)]
    if app:
        args += ["--app", app]
    if force:
        args.append("--force")
    return run_desktop(config, args, timeout_ms=10000, headed=headed)


def desktop_launch(config, app: str, args: list = None,
                   timeout_ms: int = 30000, activate: bool = False):
    """Mở một ứng dụng bằng agent-desktop (tên bare như "notepad", hoặc
    đường dẫn tuyệt đối). App trong allowlist chỉ cần quyền input, ngoài
    allowlist cần admin — cùng luật với launch_application."""
    from pathlib import Path
    name = Path(app).name.lower()
    if name in config.launch_allowlist():
        require(config, "input")
    else:
        require(config, "admin")
    overlay.pulse()
    cli_args = ["launch", app, "--timeout", str(int(timeout_ms))]
    for a in (args or []):
        cli_args += ["--arg", str(a)]
    if activate:
        cli_args.append("--activate")
    return run_desktop(config, cli_args, timeout_ms=timeout_ms)


def desktop_focus_window(config, window_id: str = None, app: str = None,
                         title: str = None, headed: bool = True):
    """Đưa một cửa sổ lên trước (theo window-id, tên app hoặc tiêu đề).
    Mặc định headed=True vì focus là thao tác lấy foreground."""
    require(config, "input")
    overlay.pulse()
    if not (window_id or app or title):
        raise invalid_args("Cần ít nhất một trong: window_id, app, title.")
    args = ["focus-window"]
    if window_id:
        args += ["--window-id", window_id]
    if app:
        args += ["--app", app]
    if title:
        args += ["--title", title]
    return run_desktop(config, args, timeout_ms=10000, headed=headed)


def desktop_wait(config, ms: int = None, element: str = None, window: str = None,
                 text: str = None, event: str = None, menu: bool = False,
                 menu_closed: bool = False, timeout_ms: int = 30000,
                 app: str = None):
    """Chờ một điều kiện thay vì ngủ cố định: ms (chờ N ms), element (ref
    xuất hiện), window (tiêu đề cửa sổ xuất hiện), text (chữ xuất hiện
    trong cây), event (window-opened/window-closed/app-launched/
    app-terminated/focus-changed/surface-appeared/surface-dismissed),
    menu/menu_closed (menu mở/đóng). Chỉ dùng một chế độ mỗi lần gọi."""
    require(config, "input")
    modes = [bool(ms is not None), bool(element), bool(window), bool(text),
             bool(event), bool(menu), bool(menu_closed)]
    if sum(modes) != 1:
        raise invalid_args(
            "desktop_wait cần đúng một chế độ: ms, element, window, text, "
            "event, menu hoặc menu_closed.")
    args = ["wait"]
    if ms is not None:
        args.append(str(int(ms)))
    if element:
        args += ["--element", _check_ref(element)]
    if window:
        args += ["--window", window]
    if text:
        args += ["--text", text]
    if event:
        args += ["--event", event]
    if menu:
        args.append("--menu")
    if menu_closed:
        args.append("--menu-closed")
    if ms is None:
        args += ["--timeout", str(int(timeout_ms))]
    if app:
        args += ["--app", app]
    return run_desktop(config, args, timeout_ms=timeout_ms)


# ---------------- Clipboard ----------------

def desktop_clipboard_get(config, format: str = "text"):
    """Đọc clipboard qua agent-desktop. format: text (mặc định) hoặc auto.
    Nhóm quyền clipboard riêng (mặc định tắt), như clipboard_get_text."""
    require(config, "clipboard")
    if format not in ("text", "auto"):
        raise invalid_args(
            f"format clipboard không hỗ trợ: {format!r}. Chỉ text/auto "
            "(image/file-urls cần truyền file nhị phân, chưa hỗ trợ qua MCP).")
    return run_desktop(config, ["clipboard-get", "--format", format],
                       timeout_ms=10000)


def desktop_clipboard_set(config, text: str):
    """Ghi text vào clipboard qua agent-desktop. Text dài >200 ký tự đi
    qua --stdin (tối đa 128 KiB). Nhóm quyền clipboard riêng."""
    require(config, "clipboard")
    use_stdin, text = _stdin_or_arg(text, SET_VALUE_STDIN_LIMIT_BYTES)
    args = ["clipboard-set"]
    if use_stdin:
        args.append("--stdin")
    else:
        args.append(text)
    return run_desktop(config, args, timeout_ms=10000,
                       stdin_text=text if use_stdin else None)
