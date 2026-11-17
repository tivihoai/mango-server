"""Nhóm tool (tool groups) — phạm vi quyền của token Agent và của Server.

Mỗi tool trên máy client thuộc 1 nhóm:
- "read"    : chỉ đọc, không đổi trạng thái máy (an toàn nhất).
- "control" : điều khiển chuột/bàn phím/màn hình, chạy lệnh, mở app.
- "files"   : ghi/xóa/di chuyển file.
- "admin"   : quản trị máy (đăng nhập/tự đăng nhập, user, registry, khóa).

Token Agent chỉ được gọi machine_call với tool thuộc nhóm mà token có.
Tool lạ (không có trong bảng) mặc định thuộc nhóm "admin" — fail-closed:
muốn gọi tool chưa biết thì token phải có quyền admin.

Bảng này là mặc định của Server. Máy client còn có scope riêng của nó
(server_allowed_tools trong server-client.json) — cả 2 lớp đều phải cho
phép thì lệnh mới chạy (defense in depth).
"""
TOOL_GROUPS = {
    "read": {
        "mango_status", "system_info", "list_processes", "display_inventory",
        "list_windows", "screenshot", "screen_preview", "get_pixel_color",
        "clipboard_get_text", "list_directory", "read_text_file",
        "search_files", "stat_file", "lock_status", "tunnel_info",
        "control_status", "user_list", "auto_logon_status",
        "ui_tree", "ui_find", "ui_get_text", "find_controls",
        "get_control_text", "desktop_status", "desktop_snapshot",
        "desktop_find", "desktop_get", "desktop_list_apps",
        "desktop_list_windows", "desktop_clipboard_get", "find_text_on_screen",
        "read_window_text", "find_color_on_screen", "count_color_on_screen",
        "list_workflows",
    },
    "control": {
        "mouse_move", "mouse_click", "mouse_drag", "mouse_path",
        "mouse_scroll", "keyboard_type", "keyboard_hotkey", "focus_window",
        "wait_for_window", "input_sequence", "clipboard_set_text",
        "ui_click", "ui_set_text", "set_control_text", "click_control",
        "desktop_click", "desktop_double_click", "desktop_right_click",
        "desktop_type", "desktop_set_value", "desktop_clear",
        "desktop_select", "desktop_toggle", "desktop_scroll", "desktop_press",
        "desktop_launch", "desktop_focus_window", "desktop_wait",
        "desktop_clipboard_set", "set_display_resolution",
        "activate_or_launch", "snapshot", "click_label", "multi_click",
        "run_workflow", "save_workflow", "run_saved_workflow",
        "delete_workflow", "set_busy_overlay", "notify_on_screen",
        "wait_for_pixel", "send_keys", "scroll_at", "close_window",
        "set_window_state", "open_path", "launch_application",
        "run_command", "powershell", "kill_process", "terminate_process",
    },
    "files": {
        "write_text_file", "copy_file", "move_file", "delete_file",
    },
    "admin": {
        "registry_get", "registry_set", "control_login", "control_logout",
        "user_add", "user_remove", "user_set_default", "switch_user",
        "auto_logon_enable", "auto_logon_disable",
    },
}

# Tool -> nhóm (tra cứu nhanh). Tool không có trong bảng => "admin".
_TOOL_TO_GROUP = {}
for _group, _tools in TOOL_GROUPS.items():
    for _tool in _tools:
        _TOOL_TO_GROUP[_tool] = _group


def tool_group(tool: str) -> str:
    """Nhóm quyền của 1 tool. Tool lạ => 'admin' (fail-closed)."""
    return _TOOL_TO_GROUP.get(tool or "", "admin")


def token_may_call(token_record, machine_id: str, tool: str):
    """Kiểm tra token Agent có được gọi tool này trên máy này không.

    Trả (allowed: bool, reason: str). Thứ tự kiểm tra:
    1. Token còn bật không.
    2. Token được chạm máy này không (machines == ["*"] hoặc có machine_id).
    3. Tool thuộc nhóm mà token có không.
    """
    if not token_record or not token_record.get("enabled", True):
        return False, "AGENT_TOKEN_DISABLED"
    allowed_machines = token_record.get("machines", [])
    if "*" not in allowed_machines and machine_id not in allowed_machines:
        return False, "MACHINE_NOT_ALLOWED"
    group = tool_group(tool)
    if group not in (token_record.get("tool_groups", []) or []):
        return False, "TOOL_GROUP_DENIED"
    return True, ""
