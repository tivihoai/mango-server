"""Test 1.1 — Tương thích MCP (§6.1): dùng client MCP chính thức
(mcp SDK, streamablehttp_client) nối Server thật.

- initialize trả serverInfo version 1.1.0
- ping -> {}
- tools/list có đủ 5 tool (3 cũ + machine_restart + machine_upgrade)
- machine_list gọi được qua SDK
- machine_restart / machine_upgrade kiểm tra quyền admin + máy tồn tại
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
import unittest

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from mangoserver.app import build_app

PORT = 18779
BASE = f"http://127.0.0.1:{PORT}"


class TestMcpCompat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.app = build_app(cls.tmp)
        cls.app.state.auth.set_admin_password("test-admin-password")
        _, cls.boss_token = cls.app.state.auth.create_agent_token(
            "Admin", ["*"], ["read", "control", "files", "admin"])
        _, cls.read_token = cls.app.state.auth.create_agent_token(
            "chi-doc", ["*"], ["read"])
        import uvicorn
        config = uvicorn.Config(cls.app, host="127.0.0.1", port=PORT,
                                log_level="error")
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                r = httpx.get(f"{BASE}/health", timeout=2, trust_env=False)
                if r.status_code == 200:
                    return
            except Exception:
                time.sleep(0.3)
        raise RuntimeError("Server khong khoi dong duoc")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=10)

    def _run(self, coro):
        return asyncio.run(coro)

    def _with_session(self, token, coro_fn):
        async def _run_all():
            url = f"{BASE}/mcp"
            headers = {"Authorization": f"Bearer {token}"}
            async with httpx.AsyncClient(trust_env=False,
                                         headers=headers) as http_client:
                async with streamable_http_client(
                        url, http_client=http_client) as (read, write, _sid):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        return await coro_fn(session)
        return asyncio.run(_run_all())

    def _tool_text(self, result):
        return result.content[0].text

    def test_initialize_server_info_110(self):
        async def _raw():
            url = f"{BASE}/mcp"
            headers = {"Authorization": f"Bearer {self.boss_token}"}
            async with httpx.AsyncClient(trust_env=False,
                                         headers=headers) as http_client:
                async with streamable_http_client(
                        url, http_client=http_client) as (read, write, _sid):
                    async with ClientSession(read, write) as session:
                        res = await session.initialize()
                        return res
        res = asyncio.run(_raw())
        self.assertEqual(res.serverInfo.version, "1.1.0")
        self.assertEqual(res.serverInfo.name, "Mango Server")
        self.assertEqual(res.protocolVersion, "2025-06-18")

    def test_ping_and_tools_list(self):
        async def _check(session):
            await session.send_ping()
            tools = await session.list_tools()
            return [t.name for t in tools.tools]
        names = self._with_session(self.boss_token, _check)
        self.assertEqual(names, ["machine_list", "machine_status",
                                 "machine_call", "machine_restart",
                                 "machine_upgrade"])

    def test_machine_list_via_sdk(self):
        async def _check(session):
            return await session.call_tool("machine_list", {})
        res = self._with_session(self.boss_token, _check)
        self.assertFalse(res.isError)
        payload = json.loads(self._tool_text(res))
        self.assertEqual(payload["machines"], [])

    def test_machine_restart_permission_and_not_found(self):
        async def _check(session):
            # Token chỉ đọc -> bị chặn (nhóm admin).
            r1 = await session.call_tool(
                "machine_restart", {"machine_id": "mango_x", "delay_seconds": 60})
            # Token toàn quyền nhưng máy không tồn tại.
            return r1
        res = self._with_session(self.read_token, _check)
        self.assertTrue(res.isError)
        self.assertIn("TOOL_GROUP_DENIED", self._tool_text(res))

        async def _check2(session):
            return await session.call_tool(
                "machine_restart", {"machine_id": "mango_khong-co",
                                    "delay_seconds": 60})
        res = self._with_session(self.boss_token, _check2)
        self.assertTrue(res.isError)
        self.assertIn("MACHINE_NOT_FOUND", self._tool_text(res))

    def test_machine_upgrade_no_packages(self):
        async def _check(session):
            return await session.call_tool(
                "machine_upgrade", {"machine_id": "mango_khong-co"})
        res = self._with_session(self.boss_token, _check)
        # Máy không tồn tại -> lỗi trước khi kiểm tra kho gói.
        self.assertTrue(res.isError)
        self.assertIn("MACHINE_NOT_FOUND", self._tool_text(res))

        # Tạo máy rồi gọi upgrade khi kho trống -> NO_PACKAGES.
        r = httpx.post(f"{BASE}/api/enroll-request", trust_env=False,
                       json={"machine_name": "PC-sdk"}, timeout=10)
        mid = r.json()["machine_id"]
        async def _check2(session):
            return await session.call_tool("machine_upgrade", {"machine_id": mid})
        res = self._with_session(self.boss_token, _check2)
        self.assertTrue(res.isError)
        self.assertIn("NO_PACKAGES", self._tool_text(res))

    def test_mcp_requires_bearer_via_sdk(self):
        def _flatten(exc):
            parts = [str(exc)]
            if isinstance(exc, BaseExceptionGroup):
                for sub in exc.exceptions:
                    parts.append(_flatten(sub))
            return " | ".join(parts)

        async def _raw():
            url = f"{BASE}/mcp"
            try:
                async with httpx.AsyncClient(trust_env=False) as http_client:
                    async with streamable_http_client(
                            url, http_client=http_client) as (read, write, _sid):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            return "connected"
            except Exception as exc:  # noqa: BLE001 - SDK raise khi 401
                return f"error: {_flatten(exc)}"
        out = asyncio.run(_raw())
        self.assertIn("error", out)
        self.assertIn("401", out)


if __name__ == "__main__":
    unittest.main()
