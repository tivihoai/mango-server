"""Test Client 2.1 — chay SYSTEM o session 0 + GUI agent + doi mat khau.

Chay: cd ~/workspace/mango-server && .venv/bin/python tests/run_tests.py
(hoac python3 -m pytest tests/test_client21.py -v)

Cac test chay duoc tren Linux (khong can Windows): session/GUI agent
bao PLATFORM_UNSUPPORTED hoac tra trang thai "khong co session" thay vi
nem loi lung tung; tool doi mat khau chi thao tac tren config (khong
cham registry tren Linux, chi ghi canh bao).
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
from mangoengine.errors import MangoError


def _load_mangoclient21():
    """Load goi mangoclient 2.1 tu duong dan file ro rang.

    `mangoclient` ton tai o ca client/ (1.1.5) va client-2.0/client (2.1);
    sys.modules co the dang giu ban 1.1.5 do test khac import truoc. Nap
    ban 2.1 bang importlib theo duong dan file de kiem tra dung code.
    Tra (package, config_module).
    """
    import importlib.util
    base = os.path.join(os.path.dirname(__file__), "..", "client-2.0",
                        "client", "mangoclient")
    spec = importlib.util.spec_from_file_location(
        "mangoclient21", os.path.join(base, "__init__.py"))
    pkg = importlib.util.module_from_spec(spec)
    sys.modules["mangoclient21"] = pkg
    spec.loader.exec_module(pkg)
    # config.py lam "from mangoclient import VERSION" — chi ten do sang
    # goi 2.1 trong luc nap, roi khoi phuc ngay.
    old = sys.modules.get("mangoclient")
    sys.modules["mangoclient"] = pkg
    try:
        spec2 = importlib.util.spec_from_file_location(
            "mangoclient21.config", os.path.join(base, "config.py"))
        cfg_mod = importlib.util.module_from_spec(spec2)
        sys.modules["mangoclient21.config"] = cfg_mod
        spec2.loader.exec_module(cfg_mod)
    finally:
        if old is None:
            sys.modules.pop("mangoclient", None)
        else:
            sys.modules["mangoclient"] = old
    return pkg, cfg_mod


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


def _call(eng, tool, args=None):
    r = eng.call_tool(tool, args or {})
    assert "content" in r, f"{tool} khong tra envelope: {r}"
    return json.loads(r["content"][0]["text"]), bool(r.get("isError"))


class TestConfigSetUserPassword(unittest.TestCase):
    def setUp(self):
        self.cfg = _test_config()
        self.eng = DirectEngine(self.cfg)

    def test_tool_in_dispatch_and_scope(self):
        """config_set_user_password phai co trong dispatch + scope mac dinh."""
        table = build_dispatch_table()
        self.assertIn("config_set_user_password", table)
        _pkg, cfg_mod = _load_mangoclient21()
        self.assertIn("config_set_user_password",
                      cfg_mod.DEFAULT_ALLOWED_TOOLS)
        self.assertEqual(len(cfg_mod.DEFAULT_ALLOWED_TOOLS), 101)

    def test_set_password_updates_config(self):
        """Doi mat khau: config luu mat khau moi, ket qua KHONG tra password."""
        _call(self.eng, "user_add", {"username": "admin", "password": "old-pass"})
        info, is_err = _call(self.eng, "config_set_user_password",
                             {"username": "admin", "password": "new-pass-123"})
        self.assertFalse(is_err, info)
        self.assertEqual(info.get("username"), "admin")
        self.assertTrue(info.get("updated"))
        self.assertNotIn("new-pass-123", json.dumps(info))
        self.assertNotIn("old-pass", json.dumps(info))
        # Doc lai tu file: mat khau moi da luu.
        fresh = EngineConfig.load_from(str(self.cfg.path))
        entry = fresh.data["users"][0]
        self.assertEqual(entry.get("password"), "new-pass-123")

    def test_set_password_by_index(self):
        """Doi mat khau bang index (khong can username)."""
        _call(self.eng, "user_add", {"username": "admin", "password": "p1"})
        _call(self.eng, "user_add", {"username": "user2", "password": "p2"})
        info, is_err = _call(self.eng, "config_set_user_password",
                             {"index": 1, "password": "p2-moi"})
        self.assertFalse(is_err, info)
        self.assertEqual(info.get("username"), "user2")
        fresh = EngineConfig.load_from(str(self.cfg.path))
        self.assertEqual(fresh.data["users"][1].get("password"), "p2-moi")

    def test_set_password_rejects_empty(self):
        """Mat khau moi trong bi tu choi."""
        _call(self.eng, "user_add", {"username": "admin", "password": "p1"})
        _info, is_err = _call(self.eng, "config_set_user_password",
                              {"username": "admin", "password": ""})
        self.assertTrue(is_err)

    def test_set_password_unknown_user(self):
        """User khong co trong danh sach bi tu choi."""
        _info, is_err = _call(self.eng, "config_set_user_password",
                              {"username": "khong-co", "password": "x"})
        self.assertTrue(is_err)

    def test_set_password_needs_identifier(self):
        """Thieu ca username va index bi tu choi."""
        _info, is_err = _call(self.eng, "config_set_user_password",
                              {"password": "x"})
        self.assertTrue(is_err)

    def test_users_set_password_unit(self):
        """users.set_password: doi dung user, khong doi thu tu."""
        from mangoengine import users
        lst = []
        users.add(lst, "admin", "p1")
        users.add(lst, "user2", "p2")
        out = users.set_password(lst, username="user2", password="p2-moi")
        self.assertEqual(out["username"], "user2")
        self.assertFalse(out["is_default"])
        self.assertEqual(lst[1]["password"], "p2-moi")
        self.assertEqual(lst[0]["username"], "admin")  # thu tu khong doi
        with self.assertRaises(MangoError):
            users.set_password(lst, username="user2", password="")
        with self.assertRaises(MangoError):
            users.set_password(lst, username="khong-co", password="x")


class TestSessionModule(unittest.TestCase):
    def test_no_console_session_on_linux(self):
        """Tren Linux: khong co console session, khong phai session 0."""
        from mangoengine import session
        self.assertIsNone(session.find_console_session())
        self.assertIsNone(session.current_session_id())
        self.assertFalse(session.is_system_session())

    def test_launch_agent_unsupported_on_linux(self):
        """launch_agent tren Linux bao PLATFORM_UNSUPPORTED."""
        from mangoengine import session
        with self.assertRaises(MangoError) as ctx:
            session.launch_agent(1, "echo hi")
        self.assertEqual(ctx.exception.code, "PLATFORM_UNSUPPORTED")

    def test_launch_as_user_unsupported_on_linux(self):
        """launch_as_user tren Linux bao PLATFORM_UNSUPPORTED."""
        from mangoengine import session
        with self.assertRaises(MangoError) as ctx:
            session.launch_as_user("admin", "pass", "echo hi")
        self.assertEqual(ctx.exception.code, "PLATFORM_UNSUPPORTED")

    def test_gui_agent_command_builds(self):
        """Lenh chay GUI agent duoc xay dung dung (khong can chay that)."""
        from mangoengine import session
        cmd, cwd = session.gui_agent_command("/tmp/x/server-client.json",
                                             "127.0.0.1", 18767)
        self.assertIn("gui_agent.py", cmd)
        self.assertIn("--ipc-port", cmd)
        self.assertIn("18767", cmd)
        self.assertIn("server-client.json", cmd)


class TestGuiRouter(unittest.TestCase):
    def setUp(self):
        self.cfg = _test_config()
        from mangoengine import gui
        gui.reset_gui_router()

    def test_ipc_defaults(self):
        """Cong IPC GUI mac dinh 18767 (khac 8767 cua MangoMCP)."""
        from mangoengine import gui
        st = gui.gui_ipc_settings(self.cfg)
        self.assertEqual(st["ipc_host"], "127.0.0.1")
        self.assertEqual(st["ipc_port"], 18767)

    def test_not_system_session_on_linux(self):
        """Tren Linux: khong phai session 0 nen khong dinh tuyen IPC."""
        from mangoengine import gui
        self.assertFalse(gui.is_system_session())

    def test_router_not_connected_initially(self):
        """Router moi tao chua noi GUI agent."""
        from mangoengine import gui
        router = gui.get_gui_router(self.cfg)
        self.assertFalse(router.is_connected())
        self.assertIsNone(router.agent_info())

    def test_router_singleton(self):
        """get_gui_router tra cung mot router cho cung config."""
        from mangoengine import gui
        r1 = gui.get_gui_router(self.cfg)
        r2 = gui.get_gui_router(self.cfg)
        self.assertIs(r1, r2)

    def test_ensure_agent_no_session_no_user(self):
        """Khong session, khong user luu -> NO_SESSION (khong treo)."""
        from mangoengine import gui
        router = gui.get_gui_router(self.cfg)
        with self.assertRaises(MangoError) as ctx:
            router.ensure_agent(timeout=1)
        self.assertEqual(ctx.exception.code, "NO_SESSION")


class TestVersion21(unittest.TestCase):
    def setUp(self):
        self.cfg = _test_config()
        self.eng = DirectEngine(self.cfg)

    def test_control_status_reports_210(self):
        """control_status 2.1 bao ban 2.1.9."""
        info, is_err = _call(self.eng, "control_status", {})
        self.assertFalse(is_err, info)
        self.assertEqual(info.get("core_version"), "2.1.9")
        self.assertEqual(info.get("client_version"), "2.1.9")

    def test_client_version_is_210(self):
        """VERSION cua client la 2.1.9."""
        pkg, _cfg_mod = _load_mangoclient21()
        self.assertEqual(pkg.VERSION, "2.1.9")

    def test_dispatch_still_covers_100_server_tools(self):
        """Van du 100 tool Server + them config_set_user_password."""
        from mangoserver.toolgroups import TOOL_GROUPS
        table = build_dispatch_table()
        all_tools = []
        for tools in TOOL_GROUPS.values():
            all_tools.extend(tools)
        self.assertEqual(len(all_tools), 100)
        missing = [t for t in all_tools if t not in table]
        self.assertEqual(missing, [], f"Thieu tool: {missing}")
        self.assertIn("config_set_user_password", table)
        self.assertGreaterEqual(len(table), 101)

    def test_control_login_user_session(self):
        """control_login o session nguoi dung (Linux): da bat, khong can Agent."""
        info, is_err = _call(self.eng, "control_login", {})
        self.assertFalse(is_err, info)
        self.assertTrue(info.get("control_active"))

    def test_control_logout_user_session(self):
        """control_logout o session nguoi dung: no-op, dieu khien van bat."""
        info, is_err = _call(self.eng, "control_logout", {})
        self.assertFalse(is_err, info)
        self.assertTrue(info.get("control_active"))

    def test_ipc_port_differs_from_mangomcp(self):
        """IPC 2.1 (18767) khac IPC MangoMCP 0.14.2 (8767) — khong dung do."""
        from mangoengine.ipc import DEFAULT_IPC_PORT
        self.assertEqual(DEFAULT_IPC_PORT, 18767)
        self.assertNotEqual(DEFAULT_IPC_PORT, 8767)


if __name__ == "__main__":
    unittest.main()
