"""Test unit cho toolgroups + Router (điều phối machine_call).

Router được test với hub giả (không cần WebSocket thật): kiểm tra đúng
thứ tự kiểm tra quyền và mọi nhánh lỗi, và trường hợp thành công.
"""
import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from mangoserver import toolgroups
from mangoserver.hub import CallError
from mangoserver.mcp_endpoint import Router
from mangoserver.registry import Registry
from mangoserver.store import AuditLog, JsonStore


class TestToolGroups(unittest.TestCase):
    def test_read_tools(self):
        self.assertEqual(toolgroups.tool_group("mango_status"), "read")
        self.assertEqual(toolgroups.tool_group("screenshot"), "read")
        self.assertEqual(toolgroups.tool_group("read_text_file"), "read")

    def test_control_tools(self):
        self.assertEqual(toolgroups.tool_group("mouse_click"), "control")
        self.assertEqual(toolgroups.tool_group("run_command"), "control")
        self.assertEqual(toolgroups.tool_group("desktop_click"), "control")

    def test_files_tools(self):
        self.assertEqual(toolgroups.tool_group("write_text_file"), "files")
        self.assertEqual(toolgroups.tool_group("delete_file"), "files")

    def test_admin_tools(self):
        self.assertEqual(toolgroups.tool_group("control_login"), "admin")
        self.assertEqual(toolgroups.tool_group("user_add"), "admin")
        self.assertEqual(toolgroups.tool_group("auto_logon_enable"), "admin")

    def test_unknown_tool_fails_closed(self):
        # Tool lạ mặc định thuộc nhóm admin (không cho gọi bừa).
        self.assertEqual(toolgroups.tool_group("tool_chua_biet"), "admin")
        self.assertEqual(toolgroups.tool_group(""), "admin")

    def test_token_may_call(self):
        token = {"enabled": True, "machines": ["m1"], "tool_groups": ["read"]}
        ok, _ = toolgroups.token_may_call(token, "m1", "mango_status")
        self.assertTrue(ok)
        ok, reason = toolgroups.token_may_call(token, "m1", "mouse_click")
        self.assertFalse(ok)
        self.assertEqual(reason, "TOOL_GROUP_DENIED")
        ok, reason = toolgroups.token_may_call(token, "m2", "mango_status")
        self.assertFalse(ok)
        self.assertEqual(reason, "MACHINE_NOT_ALLOWED")
        token["enabled"] = False
        ok, reason = toolgroups.token_may_call(token, "m1", "mango_status")
        self.assertFalse(ok)
        self.assertEqual(reason, "AGENT_TOKEN_DISABLED")
        # Token "*" thấy mọi máy.
        token2 = {"enabled": True, "machines": ["*"],
                  "tool_groups": ["read", "control", "files", "admin"]}
        ok, _ = toolgroups.token_may_call(token2, "bat-ky-may-nao", "run_command")
        self.assertTrue(ok)


class FakeHub:
    """Hub giả: giả lập máy online/offline và kết quả gọi."""

    def __init__(self, connected=True, result=None, error=None):
        self._connected = connected
        self.result = result if result is not None else {
            "content": [{"type": "text", "text": "ok"}], "isError": False}
        self.error = error
        self.calls = []

    def is_connected(self, machine_id):
        return self._connected

    async def call(self, machine_id, tool, args, timeout=60):
        self.calls.append((machine_id, tool, args))
        if self.error:
            raise self.error
        return self.result


def _router(connected=True, result=None, error=None):
    tmp = tempfile.mkdtemp()
    store = JsonStore(os.path.join(tmp, "registry.json"), {"machines": {}})
    registry = Registry(store)
    audit = AuditLog(os.path.join(tmp, "audit.jsonl"))
    hub = FakeHub(connected=connected, result=result, error=error)
    return Router(registry, hub, audit), registry, hub, audit


def _token(machines=None, groups=None):
    return {"name": "test-agent", "enabled": True,
            "machines": machines if machines is not None else ["*"],
            "tool_groups": groups if groups is not None else ["read", "control", "files", "admin"]}


class TestRouter(unittest.TestCase):
    def _approved_machine(self, registry, mid="m1"):
        registry.enroll("may-01", "0.14.2", "s", mid)
        registry.set_status(mid, "approved", by="admin")
        registry.heartbeat(mid, version="0.14.2")
        return mid

    def test_machine_list_only_visible_machines(self):
        router, registry, hub, _ = _router()
        registry.enroll("may-01", "0.14.2", "s", "m1")
        registry.enroll("may-02", "0.14.2", "s", "m2")
        token = _token(machines=["m1"])
        res = asyncio.run(router.call(token, "machine_list", {}))
        text = res["content"][0]["text"]
        self.assertIn("m1", text)
        self.assertNotIn("m2", text)
        self.assertFalse(res["isError"])

    def test_machine_status_not_found(self):
        router, registry, hub, _ = _router()
        res = asyncio.run(router.call(_token(), "machine_status", {"machine_id": "nope"}))
        self.assertTrue(res["isError"])
        self.assertIn("MACHINE_NOT_FOUND", res["content"][0]["text"])

    def test_machine_call_success_passthrough(self):
        router, registry, hub, _ = _router()
        self._approved_machine(registry)
        res = asyncio.run(router.call(
            _token(), "machine_call",
            {"machine_id": "m1", "tool": "mango_status", "args": {}}))
        self.assertFalse(res["isError"])
        self.assertEqual(hub.calls, [("m1", "mango_status", {})])

    def test_machine_call_tool_group_denied(self):
        router, registry, hub, _ = _router()
        self._approved_machine(registry)
        token = _token(groups=["read"])
        res = asyncio.run(router.call(
            token, "machine_call",
            {"machine_id": "m1", "tool": "run_command", "args": {}}))
        self.assertTrue(res["isError"])
        self.assertIn("TOOL_GROUP_DENIED", res["content"][0]["text"])
        self.assertEqual(hub.calls, [])

    def test_machine_call_machine_not_allowed(self):
        router, registry, hub, _ = _router()
        self._approved_machine(registry)
        token = _token(machines=["m2"])
        res = asyncio.run(router.call(
            token, "machine_call",
            {"machine_id": "m1", "tool": "mango_status", "args": {}}))
        self.assertTrue(res["isError"])
        self.assertIn("MACHINE_NOT_ALLOWED", res["content"][0]["text"])

    def test_machine_call_pending_denied(self):
        router, registry, hub, _ = _router()
        registry.enroll("may-01", "0.14.2", "s", "m1")  # vẫn pending
        registry.heartbeat("m1")
        res = asyncio.run(router.call(
            _token(), "machine_call",
            {"machine_id": "m1", "tool": "mango_status", "args": {}}))
        self.assertTrue(res["isError"])
        self.assertIn("MACHINE_NOT_APPROVED", res["content"][0]["text"])

    def test_machine_call_offline(self):
        router, registry, hub, _ = _router(connected=False)
        self._approved_machine(registry)
        res = asyncio.run(router.call(
            _token(), "machine_call",
            {"machine_id": "m1", "tool": "mango_status", "args": {}}))
        self.assertTrue(res["isError"])
        self.assertIn("MACHINE_OFFLINE", res["content"][0]["text"])

    def test_machine_call_timeout_propagates(self):
        router, registry, hub, _ = _router(
            error=CallError("CALL_TIMEOUT", "het gio"))
        self._approved_machine(registry)
        res = asyncio.run(router.call(
            _token(), "machine_call",
            {"machine_id": "m1", "tool": "mango_status", "args": {}}))
        self.assertTrue(res["isError"])
        self.assertIn("CALL_TIMEOUT", res["content"][0]["text"])

    def test_machine_call_audit_masks_args(self):
        router, registry, hub, audit = _router()
        self._approved_machine(registry)
        asyncio.run(router.call(
            _token(), "machine_call",
            {"machine_id": "m1", "tool": "mango_status",
             "args": {"password": "bi-mat-khong-duoc-ghi"}}))
        entries = audit.read_last(5)
        self.assertTrue(entries)
        blob = str(entries)
        self.assertNotIn("bi-mat-khong-duoc-ghi", blob)

    def test_unknown_tool(self):
        router, registry, hub, _ = _router()
        res = asyncio.run(router.call(_token(), "tool_khong_co", {}))
        self.assertTrue(res["isError"])
        self.assertIn("UNKNOWN_TOOL", res["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
