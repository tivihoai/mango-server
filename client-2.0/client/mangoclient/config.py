"""Cấu hình client 1.1 (file server-client.json).

File này nằm cạnh MangoMCP (vd C:\\MangoMCP\\server-client.json), RIÊNG
với config.json của MangoMCP 0.14.x để không đụng cấu hình cũ.

KHÔNG BAO GIỜ ghi mật khẩu Windows / mật khẩu chủ vào file này.
Local MCP Bearer (client secret của MangoMCP trên máy) đọc từ biến môi
trường MANGO_LOCAL_BEARER lúc chạy, không lưu vào file.
"""
import json
import os
from pathlib import Path

from mangoclient import VERSION as CLIENT_VERSION

# Tool Server được phép gọi trên máy này (mặc định 2.1.1: ĐẦY ĐỦ 100 tool
# của MangoMCP 0.14.2 + config_set_user_password (doi mat khau user da
# luu) = 101 tool — y chang điều khiển trực tiếp trên máy, gồm cả
# chạy lệnh, ghi file, bấm/chuột, đổi user/auto-logon. Chủ máy thu hẹp
# bằng cách sửa file server-client.json hoặc đặt scope trên dashboard).
DEFAULT_ALLOWED_TOOLS = [
    "activate_or_launch", "auto_logon_disable", "auto_logon_enable",
    "auto_logon_status", "click_control", "click_label",
    "clipboard_get_text", "clipboard_set_text", "close_window",
    "config_set_user_password",
    "control_login", "control_logout", "control_status", "copy_file",
    "count_color_on_screen", "delete_file", "delete_workflow",
    "desktop_clear", "desktop_click", "desktop_clipboard_get",
    "desktop_clipboard_set", "desktop_double_click", "desktop_find",
    "desktop_focus_window", "desktop_get", "desktop_launch",
    "desktop_list_apps", "desktop_list_windows", "desktop_press",
    "desktop_right_click", "desktop_scroll", "desktop_select",
    "desktop_set_value", "desktop_snapshot", "desktop_status",
    "desktop_toggle", "desktop_type", "desktop_wait",
    "display_inventory", "find_color_on_screen", "find_controls",
    "find_text_on_screen", "focus_window", "get_control_text",
    "get_pixel_color", "input_sequence", "keyboard_hotkey",
    "keyboard_type", "kill_process", "launch_application",
    "list_directory", "list_processes", "list_windows", "list_workflows",
    "lock_status", "mango_status", "mouse_click", "mouse_drag",
    "mouse_move", "mouse_path", "mouse_scroll", "move_file",
    "multi_click", "notify_on_screen", "open_path", "powershell",
    "read_text_file", "read_window_text", "registry_get", "registry_set",
    "run_command", "run_saved_workflow", "run_workflow", "save_workflow",
    "screen_preview", "screenshot", "scroll_at", "search_files",
    "send_keys", "set_busy_overlay", "set_control_text",
    "set_display_resolution", "set_window_state", "snapshot", "stat_file",
    "switch_user", "system_info", "terminate_process", "tunnel_info",
    "ui_click", "ui_find", "ui_get_text", "ui_set_text", "ui_tree",
    "user_add", "user_list", "user_remove", "user_set_default",
    "wait_for_pixel", "wait_for_window", "write_text_file",
]

DEFAULT_CONFIG = {
    # 2.1.9: server_host mac dinh DE TRONG — khong con host mac dinh cua
    # rieng ai nua. Installer luon ghi host tuong minh vao
    # server-client.json (ban chuan truyen -ServerHost, ban CustomHost lay
    # host nguoi cai nhap); neu file cau hinh thieu host thi client bao
    # loi ro rang chu khong tu noi ve mot Server mac dinh nao.
    "server_host": "",
    "server_port": 8443,
    "use_tls": True,
    "machine_name": "",
    "machine_id": "",
    "machine_secret": "",
    "client_version": CLIENT_VERSION,
    "server_allowed_tools": list(DEFAULT_ALLOWED_TOOLS),
    "local_mcp_url": "http://127.0.0.1:8766/mcp",
    "local_bearer_env": "MANGO_LOCAL_BEARER",
    "heartbeat_seconds": 30,
    "call_timeout_seconds": 60,
}


class ClientConfig:
    def __init__(self, path):
        self.path = Path(path)
        self.data = self._load()

    def _load(self):
        try:
            if self.path.exists():
                raw = self.path.read_text(encoding="utf-8-sig")
                if raw.strip():
                    data = json.loads(raw)
                    merged = dict(DEFAULT_CONFIG)
                    merged.update(data)
                    return merged
        except Exception:
            pass
        return dict(DEFAULT_CONFIG)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, self.path)

    @property
    def enrolled(self) -> bool:
        return bool(self.data.get("machine_id")) and bool(self.data.get("machine_secret"))

    @property
    def server_ws_url(self) -> str:
        scheme = "wss" if self.data.get("use_tls", True) else "ws"
        return f"{scheme}://{self.data['server_host']}:{self.data['server_port']}/ws"

    @property
    def server_enroll_url(self) -> str:
        scheme = "https" if self.data.get("use_tls", True) else "http"
        return f"{scheme}://{self.data['server_host']}:{self.data['server_port']}/api/enroll"

    @property
    def server_enroll_request_url(self) -> str:
        """URL enroll bằng URL (1.1, §3.2): không cần mã đăng ký tay."""
        scheme = "https" if self.data.get("use_tls", True) else "http"
        return f"{scheme}://{self.data['server_host']}:{self.data['server_port']}/api/enroll-request"

    def server_package_download_url(self, version: str) -> str:
        """URL tải gói nâng cấp client (1.1, §4.2)."""
        scheme = "https" if self.data.get("use_tls", True) else "http"
        return (f"{scheme}://{self.data['server_host']}:"
                f"{self.data['server_port']}/api/packages/{version}/download")

    @property
    def client_version(self) -> str:
        # Bản đang CHẠY (code) mới là sự thật — file server-client.json có
        # thể còn ghi bản cũ (vd sau khi nâng cấp mà chưa lưu lại file),
        # báo bản cũ sẽ làm Server gửi lệnh nâng cấp lặp vô hạn (1.1.3).
        return CLIENT_VERSION

    @property
    def allowed_tools(self):
        return set(self.data.get("server_allowed_tools", []) or [])

    def local_bearer(self) -> str:
        """Bearer cho MCP local: đọc từ biến môi trường, không lưu file."""
        env_name = self.data.get("local_bearer_env", "MANGO_LOCAL_BEARER")
        return os.environ.get(env_name, "")
