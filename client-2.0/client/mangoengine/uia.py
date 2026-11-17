"""UI Automation: điều khiển Windows theo TÊN phần tử giao diện, không cần tọa độ.

Đây là kỹ thuật nâng cấp lớn nhất về độ thành thạo: thay vì đoán tọa độ
nút bấm trên ảnh chụp (vỡ ngay khi đổi độ phân giải), bot hỏi thẳng cây
giao diện của ứng dụng: "nút nào tên là Save?", "ô nhập nào tên là
File name?" rồi bấm bằng Invoke Pattern hoặc điền chữ bằng Value
Pattern. Nhanh hơn, chắc hơn, và không phụ thuộc kích thước cửa sổ.

Dùng thư viện `uiautomation` (đã cài trên máy đích cùng comtypes).
Mọi hàm đều tự vô hiệu hóa an toàn khi thư viện không có mặt.
"""

from __future__ import annotations

from collections import deque

from .errors import MangoError

_ua = None
_import_error = None


def _lib():
    global _ua, _import_error
    if _ua is None and _import_error is None:
        try:
            import uiautomation as ua

            _ua = ua
        except Exception as exc:  # pragma: no cover - phụ thuộc máy đích
            _import_error = str(exc)
    if _ua is None:
        raise MangoError(
            "UIA_UNAVAILABLE",
            "Thư viện uiautomation chưa dùng được trên máy này.",
            detail=_import_error or "",
            retryable=False,
        )
    return _ua


_TYPE_ALIASES = {
    "button": "ButtonControl", "edit": "EditControl", "text": "TextControl",
    "window": "WindowControl", "menu": "MenuControl", "menuitem": "MenuItemControl",
    "checkbox": "CheckBoxControl", "radio": "RadioButtonControl",
    "combobox": "ComboBoxControl", "list": "ListControl", "listitem": "ListItemControl",
    "tab": "TabControl", "tabitem": "TabItemControl", "tree": "TreeControl",
    "treeitem": "TreeItemControl", "hyperlink": "HyperlinkControl",
    "image": "ImageControl", "pane": "PaneControl", "toolbar": "ToolBarControl",
    "statusbar": "StatusBarControl", "slider": "SliderControl",
    "progressbar": "ProgressBarControl", "splitbutton": "SplitButtonControl",
    "document": "DocumentControl", "group": "GroupControl", "thumb": "ThumbControl",
    "titlebar": "TitleBarControl", "scrollbar": "ScrollBarControl",
}


def _info(c) -> dict:
    try:
        r = c.BoundingRectangle
        rect = [r.left, r.top, r.right - r.left, r.bottom - r.top]
        center = [(r.left + r.right) // 2, (r.top + r.bottom) // 2]
    except Exception:
        rect, center = [0, 0, 0, 0], [0, 0]
    return {
        "name": c.Name or "",
        "control_type": c.ControlTypeName,
        "automation_id": c.AutomationId or "",
        "class_name": c.ClassName or "",
        "rect": rect,
        "center": center,
        "enabled": bool(c.IsEnabled),
        "offscreen": bool(c.IsOffscreen),
    }


def _root(window_title: str | None):
    ua = _lib()
    root = ua.GetRootControl()
    if not window_title:
        return root
    for child in root.GetChildren():
        if window_title.lower() in (child.Name or "").lower():
            return child
    raise MangoError("WINDOW_NOT_FOUND", f"Không thấy cửa sổ chứa '{window_title}'.", retryable=True)


def _walk(root, max_depth: int, max_nodes: int):
    queue = deque([(root, 0)])
    seen = 0
    while queue:
        node, depth = queue.popleft()
        seen += 1
        if seen > max_nodes:
            return
        yield node, depth
        if depth < max_depth:
            try:
                for ch in node.GetChildren():
                    queue.append((ch, depth + 1))
            except Exception:
                pass


def _type_of(friendly: str | None) -> str | None:
    if not friendly:
        return None
    return _TYPE_ALIASES.get(friendly.lower().replace("control", ""), friendly)


def find(name: str, control_type: str | None = None, window_title: str | None = None,
         max_results: int = 10) -> list[dict]:
    root = _root(window_title)
    want = _type_of(control_type)
    out = []
    for node, _depth in _walk(root, max_depth=14, max_nodes=4000):
        try:
            if name.lower() in (node.Name or "").lower():
                if want and node.ControlTypeName != want:
                    continue
                out.append(_info(node))
                if len(out) >= max_results:
                    break
        except Exception:
            continue
    return out


def _find_one(name, control_type, window_title):
    ua = _lib()
    root = _root(window_title)
    want = _type_of(control_type)
    for node, _depth in _walk(root, max_depth=14, max_nodes=4000):
        try:
            if name.lower() in (node.Name or "").lower():
                if want and node.ControlTypeName != want:
                    continue
                return node
        except Exception:
            continue
    raise MangoError("ELEMENT_NOT_FOUND",
                     f"Không thấy phần tử tên chứa '{name}'"
                     + (f" (loại {control_type})" if control_type else "") + ".",
                     retryable=True)


def click(name: str, control_type: str | None = None, window_title: str | None = None) -> dict:
    node = _find_one(name, control_type, window_title)
    info = _info(node)
    # Ưu tiên Invoke Pattern: bấm "trong hệ thống", không cần di chuột thật
    try:
        pattern = node.GetInvokePattern()
        if pattern:
            pattern.Invoke()
            return {**info, "method": "invoke"}
    except Exception:
        pass
    try:
        pattern = node.GetTogglePattern()
        if pattern:
            pattern.Toggle()
            return {**info, "method": "toggle"}
    except Exception:
        pass
    node.Click()  # phương án cuối: bấm chuột thật vào tâm phần tử
    return {**info, "method": "mouse"}


def set_text(name: str, text: str, control_type: str | None = None,
             window_title: str | None = None) -> dict:
    node = _find_one(name, control_type, window_title)
    info = _info(node)
    try:
        pattern = node.GetValuePattern()
        if pattern:
            pattern.SetValue(text)
            return {**info, "method": "value_pattern"}
    except Exception:
        pass
    # Dự phòng: bấm vào ô rồi chọn hết + gõ (qua backend của MangoMCP)
    from . import backend

    node.Click()
    backend.hotkey(["ctrl", "a"])
    backend.keyboard_type(text)
    return {**info, "method": "type_fallback"}


def get_text(name: str, control_type: str | None = None,
             window_title: str | None = None) -> dict:
    node = _find_one(name, control_type, window_title)
    info = _info(node)
    value = None
    try:
        pattern = node.GetValuePattern()
        if pattern:
            value = pattern.Value
    except Exception:
        pass
    if value is None:
        try:
            legacy = node.GetLegacyIAccessiblePattern()
            if legacy:
                value = legacy.Value
        except Exception:
            pass
    return {**info, "value": value if value is not None else (node.Name or "")}


def tree(window_title: str | None = None, max_depth: int = 3, max_items: int = 120) -> dict:
    root = _root(window_title)
    items: list[dict] = []
    for node, depth in _walk(root, max_depth=max_depth, max_nodes=max_items):
        entry = _info(node)
        entry["depth"] = depth
        items.append(entry)
        if len(items) >= max_items:
            break
    return {"root": _info(root), "items": items, "count": len(items)}


# ---------------- Snapshot phần tử tương tác + đọc chữ (bản 0.5.0) ----------------
# Học từ CursorTouch Windows-MCP (Snapshot gắn nhãn số cho phần tử) và
# sshh12 windows-computer-use-mcp (đọc chữ cửa sổ bằng UIA, rẻ hơn ảnh chụp).

_INTERACTABLE = {
    "ButtonControl", "EditControl", "MenuItemControl", "CheckBoxControl",
    "RadioButtonControl", "ComboBoxControl", "ListItemControl", "TabItemControl",
    "HyperlinkControl", "SplitButtonControl", "TreeItemControl", "DocumentControl",
    "SliderControl", "DataItemControl", "MenuControl", "SpinnerControl",
}


def _foreground_control():
    ua = _lib()
    import ctypes

    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if hwnd:
        try:
            return ua.ControlFromHandle(hwnd)
        except Exception:
            pass
    return ua.GetRootControl()


def interactives(window_title: str | None = None, limit: int = 150) -> dict:
    """Liệt kê các phần tử tương tác được của một cửa sổ kèm nhãn số.

    Nhãn là số thứ tự ổn định trong lần chụp này; dùng click_label để bấm
    lại đúng phần tử (server sẽ kiểm chứng lại vị trí trước khi bấm,
    chống bấm trượt khi giao diện đã thay đổi - bài học "stale frame")."""
    root = _root(window_title) if window_title else _foreground_control()
    elements = []
    for node, _depth in _walk(root, max_depth=8, max_nodes=2500):
        try:
            if node.ControlTypeName not in _INTERACTABLE:
                continue
            info = _info(node)
            if info["rect"][2] <= 0 or info["rect"][3] <= 0 or info["offscreen"]:
                continue
            info["label"] = len(elements) + 1
            elements.append(info)
            if len(elements) >= limit:
                break
        except Exception:
            continue
    return {"window": _info(root), "elements": elements}


def focused_info() -> dict:
    ua = _lib()
    try:
        el = ua.GetFocusedElement()
        return _info(el) if el else {}
    except Exception:
        return {}


def window_text(window_title: str, max_chars: int = 6000) -> dict:
    """Đọc toàn bộ chữ đọc được trong một cửa sổ qua UI Automation.

    Rẻ và nhanh hơn chụp ảnh rất nhiều: lấy giá trị các ô nhập/tài liệu
    và mọi nhãn chữ tĩnh, khử trùng lặp, giữ thứ tự xuất hiện."""
    root = _root(window_title)
    lines: list[str] = []
    seen = set()
    for node, _depth in _walk(root, max_depth=10, max_nodes=3000):
        try:
            text = None
            if node.ControlTypeName in ("EditControl", "DocumentControl", "ComboBoxControl"):
                try:
                    vp = node.GetValuePattern()
                    if vp and vp.Value:
                        text = vp.Value
                except Exception:
                    pass
            if text is None and node.ControlTypeName == "TextControl" and node.Name:
                text = node.Name
            if text:
                for part in str(text).splitlines():
                    part = part.strip()
                    if part and part not in seen:
                        seen.add(part)
                        lines.append(part)
        except Exception:
            continue
    joined = "\n".join(lines)
    return {"window": _info(root), "text": joined[:max_chars], "lines": len(lines),
            "truncated": len(joined) > max_chars}
