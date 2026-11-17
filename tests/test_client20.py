"""Test Client 2.0 — DirectEngine (goi thang engine trong process).

Chay: cd ~/workspace/mango-server && .venv/bin/python tests/run_tests.py
(hoac python3 -m pytest tests/test_client20.py -v)
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client-2.0", "client"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from mangoengine.config import Config as EngineConfig
from mangoengine.direct_engine import DirectEngine, build_dispatch_table


def _test_config():
    """Config test toi thieu (khong can Windows)."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    data = {
        "permissions": {"input": True, "files_read": True,
                        "files_write": True, "clipboard": False,
                        "admin": True},
        "launch_allowlist": ["notepad"],
        "lock": {"enabled": False, "screen_mode": "visible",
                 "pause_minutes": 15, "password_sha256": ""},
        "tunnel": {"enabled": False, "port": 8768},
        "users": [],
        "clients": [],
        "desktop_binary": "",
        "audit_log": "",
    }
    with open(path, "w") as f:
        json.dump(data, f)
    return EngineConfig.load_from(path)


class TestDirectEngine(unittest.TestCase):
    def setUp(self):
        self.cfg = _test_config()
        self.eng = DirectEngine(self.cfg)

    def test_dispatch_covers_all_100_server_tools(self):
        """DirectEngine phai goi du 100 tool cua Server."""
        from mangoserver.toolgroups import TOOL_GROUPS
        table = build_dispatch_table()
        all_tools = []
        for tools in TOOL_GROUPS.values():
            all_tools.extend(tools)
        self.assertEqual(len(all_tools), 100)
        missing = [t for t in all_tools if t not in table]
        self.assertEqual(missing, [], f"Thieu tool: {missing}")

    def test_control_tools_all_have_impl(self):
        """67 CONTROL_TOOLS phai co ham thuc thi (fail-fast nhu agent)."""
        from mangoengine import core
        table = build_dispatch_table()
        for name in sorted(core.CONTROL_TOOLS):
            self.assertIn(name, table, f"Thieu CONTROL_TOOL: {name}")
        self.assertEqual(len(core.CONTROL_TOOLS), 67)

    def test_call_tool_returns_mcp_envelope(self):
        """call_tool tra dung dinh dang MCP envelope de ServerLink dung."""
        r = self.eng.call_tool("mango_status", {})
        self.assertIn("content", r)
        self.assertNotIn("isError", r)
        text = r["content"][0]["text"]
        info = json.loads(text)
        self.assertEqual(info["name"], "MangoMCP")

    def test_call_unknown_tool_returns_is_error(self):
        """Tool la tra isError thay vi nem exception ra ngoai."""
        r = self.eng.call_tool("khong_co_tool_nay_xyz", {})
        self.assertTrue(r.get("isError"))

    def test_server_tools_present(self):
        """11 tool cau hinh tu server.py phai co trong dispatch."""
        table = build_dispatch_table()
        for name in ["auto_logon_status", "auto_logon_enable",
                     "auto_logon_disable", "user_list", "user_add",
                     "user_remove", "user_set_default", "switch_user",
                     "control_login", "control_logout", "control_status"]:
            self.assertIn(name, table, f"Thieu tool cau hinh: {name}")

    def test_control_status_is_internal(self):
        """control_status 2.1 tra trang thai noi bo (khong can Core/Agent)."""
        r = self.eng.call_tool("control_status", {})
        info = json.loads(r["content"][0]["text"])
        self.assertTrue(info.get("control_active"))
        self.assertEqual(info.get("core_version"), "2.1.9")

    def test_user_list_empty(self):
        """user_list tra danh sach rong khi chua co user."""
        r = self.eng.call_tool("user_list", {})
        info = json.loads(r["content"][0]["text"])
        self.assertEqual(info.get("users"), [])

    def test_initialize_is_noop(self):
        """initialize() khong can bat tay (tuong thich LocalMcpClient)."""
        self.assertTrue(self.eng.initialize())

    def test_list_tools_sorted(self):
        """list_tools tra danh sach da sap xep."""
        tools = self.eng.list_tools()
        self.assertEqual(tools, sorted(tools))
        self.assertGreaterEqual(len(tools), 100)


if __name__ == "__main__":
    unittest.main()
