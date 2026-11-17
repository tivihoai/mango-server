"""Test monitor 1.2.0: ping 10s + stats 5 phút + API overview.

Chay: cd ~/workspace/mango-server && .venv/bin/python tests/run_tests.py

LƯU Ý: ICMP (ping) có thể bị chặn trong môi trường sandbox/container
(raw socket "Operation not permitted") — test chỉ assert parse/regex và
hành vi khi ping fail, KHÔNG assert ping loopback thành công. Trên máy
ảo Windows thật (nơi Server chạy), lệnh ping của Windows chạy được với
user thường nên ping sẽ hoạt động.
"""
import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from mangoserver.monitor import (
    MachineMonitor,
    _PING_TIME_RE,
    check_host,
    ping_once,
    tcp_open,
    unwrap_system_info,
)


class FakeRegistry:
    def __init__(self, machines):
        self._machines = machines
        self.sync_calls = []  # (machine_id, hostname) đã gọi sync_name

    def list_public(self):
        return [dict(m) for m in self._machines]

    def sync_name(self, machine_id, hostname):
        """Giả Registry.sync_name thật: đổi tên máy nếu hostname khác."""
        self.sync_calls.append((machine_id, hostname))
        if not isinstance(hostname, str) or not hostname.strip():
            return False
        for m in self._machines:
            if m["machine_id"] == machine_id:
                if m.get("name") == hostname.strip():
                    return False
                m["name"] = hostname.strip()
                return True
        return False


class FakeHub:
    def __init__(self, connected, stats_by_machine=None):
        self._connected = set(connected)
        self._stats = stats_by_machine or {}

    def is_connected(self, machine_id):
        return machine_id in self._connected

    async def call(self, machine_id, tool, args, timeout=60):
        if machine_id not in self._connected:
            from mangoserver.hub import CallError
            raise CallError("MACHINE_OFFLINE", "offline")
        info = self._stats.get(machine_id)
        if info is None:
            from mangoserver.hub import CallError
            raise CallError("CALL_TIMEOUT", "no answer")
        # Tra đúng envelope MCP như client thật.
        return {"content": [{"type": "text", "text": json.dumps(info)}]}


def _machine(machine_id, online=True, status="approved", ip="127.0.0.1"):
    return {
        "machine_id": machine_id, "name": machine_id, "version": "0.14.2",
        "status": status, "online": online, "last_heartbeat": 1700000000,
        "last_ip": ip, "agent_connected": True, "created_at": 1700000000,
        "approved_at": 1700000000, "client_version": "2.1.4",
        "reported_tools": ["system_info"], "desired_scope": None,
        "target_version": None, "upgrade_status": "",
        "upgrade_status_at": 0, "last_seen_scope_at": 0,
    }


class TestUnwrapSystemInfo(unittest.TestCase):
    def test_envelope(self):
        info = {"os": "Windows", "hostname": "may-03", "cpu_percent": 11.0}
        env = {"content": [{"type": "text", "text": json.dumps(info)}]}
        self.assertEqual(unwrap_system_info(env), info)

    def test_plain_dict(self):
        info = {"os": "Windows", "hostname": "may-03"}
        self.assertEqual(unwrap_system_info(info), info)

    def test_garbage(self):
        self.assertIsNone(unwrap_system_info({}))
        self.assertIsNone(unwrap_system_info({"content": []}))
        self.assertIsNone(unwrap_system_info({"content": [{"type": "text", "text": "not json"}]}))
        self.assertIsNone(unwrap_system_info(None))
        self.assertIsNone(unwrap_system_info("hello"))


class TestPingHelpers(unittest.TestCase):
    def test_ping_time_regex_windows(self):
        self.assertEqual(_PING_TIME_RE.search("time=1ms").group(1), "1")
        self.assertEqual(_PING_TIME_RE.search("time<1ms").group(1), "1")
        self.assertEqual(
            _PING_TIME_RE.search("Reply from 1.2.3.4: bytes=32 time=12ms TTL=64").group(1),
            "12")

    def test_ping_time_regex_linux(self):
        m = _PING_TIME_RE.search(
            "64 bytes from 127.0.0.1: icmp_seq=1 ttl=64 time=0.042 ms")
        self.assertEqual(m.group(1), "0.042")
        self.assertIsNone(_PING_TIME_RE.search("100% packet loss"))

    def test_ping_empty_and_invalid_ip(self):
        self.assertIsNone(ping_once("", timeout=1))
        self.assertIsNone(ping_once(None, timeout=1))
        # IP sai định dạng: ping lỗi ngay, không treo.
        self.assertIsNone(ping_once("999.999.999.999", timeout=2))

    def test_tcp_closed_port(self):
        # Cổng 59999 trên loopback gần như chắc chắn đóng.
        self.assertFalse(tcp_open("127.0.0.1", 59999, timeout=1))
        self.assertFalse(tcp_open("", 22, timeout=1))

    def test_check_host_shape(self):
        # Chỉ assert hình dạng + cổng đóng (TCP chạy được trong sandbox);
        # ping_ok có thể False nếu ICMP bị chặn ở môi trường test.
        res = check_host("127.0.0.1")
        self.assertIn("ping_ms", res)
        self.assertIn("ping_ok", res)
        self.assertIsInstance(res["ping_ok"], bool)
        self.assertFalse(res["ssh_open"])
        self.assertFalse(res["rdp_open"])

    def test_check_host_empty(self):
        res = check_host("")
        self.assertFalse(res["ping_ok"])
        self.assertIsNone(res["ping_ms"])
        self.assertFalse(res["ssh_open"])
        self.assertFalse(res["rdp_open"])


class TestMonitorOverview(unittest.TestCase):
    def test_overview_merges_ping_and_counts(self):
        reg = FakeRegistry([
            _machine("m1", online=True, ip="127.0.0.1"),
            _machine("m2", online=False, status="approved", ip=""),
            _machine("m3", online=False, status="pending", ip=""),
        ])
        mon = MachineMonitor(reg, FakeHub([]))
        # Gia lap 1 lượt ping: m1 co ping, m2/m3 khong.
        mon.state["m1"] = {"ping_ms": 1.0, "ping_ok": True, "ssh_open": True,
                           "rdp_open": False, "ping_at": 1700000100,
                           "stats": {"hostname": "may-01", "cpu_percent": 5.0},
                           "stats_at": 1700000100, "stats_error": ""}
        ov = mon.overview()
        self.assertEqual(ov["counts"]["total"], 3)
        self.assertEqual(ov["counts"]["online"], 1)
        self.assertEqual(ov["counts"]["offline"], 2)
        self.assertEqual(ov["counts"]["ssh_open"], 1)
        self.assertEqual(ov["counts"]["rdp_open"], 0)
        self.assertEqual(ov["counts"]["pending"], 1)
        by_id = {r["machine_id"]: r for r in ov["machines"]}
        self.assertEqual(by_id["m1"]["ping_ms"], 1.0)
        self.assertTrue(by_id["m1"]["ssh_open"])
        self.assertEqual(by_id["m1"]["stats"]["hostname"], "may-01")
        self.assertIsNone(by_id["m2"]["ping_ms"])
        self.assertIsNone(by_id["m2"]["stats"])

    def test_ping_pass_updates_state(self):
        # Máy không có IP: ping bỏ qua nhưng lượt quét vẫn ghi nhận.
        reg = FakeRegistry([_machine("m1", online=True, ip="")])
        mon = MachineMonitor(reg, FakeHub([]))
        asyncio.run(mon._ping_pass())
        st = mon.get("m1")
        self.assertFalse(st["ping_ok"])
        self.assertIsNone(st["ping_ms"])
        self.assertGreater(st["ping_at"], 0)
        self.assertGreater(mon.scan_count, 0)
        self.assertGreater(mon.last_scan_at, 0)
        self.assertEqual(len(mon.history), 1)
        self.assertEqual(mon.history[0]["total"], 1)

    def test_stats_pass_stores_envelope(self):
        info = {"os": "Windows", "hostname": "may-03", "cpu_percent": 11.0,
                "memory_total_gb": 2.0, "disks": [], "gpu": []}
        reg = FakeRegistry([_machine("m1", online=True, ip="127.0.0.1")])
        mon = MachineMonitor(reg, FakeHub(["m1"], {"m1": info}))
        asyncio.run(mon._stats_pass())
        st = mon.get("m1")
        self.assertEqual(st["stats"], info)
        self.assertEqual(st["stats_error"], "")
        self.assertGreater(mon.last_stats_at, 0)

    def test_stats_pass_keeps_old_stats_on_error(self):
        old = {"os": "Windows", "hostname": "may-03"}
        reg = FakeRegistry([_machine("m1", online=True, ip="127.0.0.1")])
        mon = MachineMonitor(reg, FakeHub(["m1"], {}))  # hub tra loi timeout
        mon.state["m1"] = {"ping_ms": 1.0, "ping_ok": True, "ssh_open": False,
                           "rdp_open": False, "ping_at": 1,
                           "stats": old, "stats_at": 100, "stats_error": ""}
        asyncio.run(mon._stats_pass())
        st = mon.get("m1")
        self.assertEqual(st["stats"], old)  # giữ stats cũ
        self.assertTrue(st["stats_error"])  # nhưng ghi lỗi

    def test_stats_pass_skips_offline_and_pending(self):
        reg = FakeRegistry([
            _machine("m1", online=False, ip="127.0.0.1"),
            _machine("m2", online=True, status="pending", ip="127.0.0.1"),
        ])
        mon = MachineMonitor(reg, FakeHub(["m1", "m2"], {
            "m1": {"hostname": "A"}, "m2": {"hostname": "B"}}))
        asyncio.run(mon._stats_pass())
        self.assertIsNone(mon.get("m1"))
        self.assertIsNone(mon.get("m2"))

    def test_stats_pass_syncs_name_from_hostname(self):
        """Tên Windows đổi (DESKTOP-EXAMPLE01 -> may-03): _stats_pass gọi
        sync_name và tên trong registry đổi ngay, overview hiện tên mới."""
        m = _machine("m1", online=True, ip="127.0.0.1")
        m["name"] = "DESKTOP-EXAMPLE01"
        reg = FakeRegistry([m])
        info = {"os": "Windows", "hostname": "may-03", "cpu_percent": 11.0}
        mon = MachineMonitor(reg, FakeHub(["m1"], {"m1": info}))
        asyncio.run(mon._stats_pass())
        self.assertEqual(reg.sync_calls, [("m1", "may-03")])
        self.assertEqual(reg._machines[0]["name"], "may-03")
        ov = mon.overview()
        self.assertEqual(ov["machines"][0]["name"], "may-03")

    def test_stats_pass_no_rename_when_hostname_same_or_empty(self):
        """Hostname trùng tên hiện tại hoặc rỗng: không gọi đổi tên."""
        m1 = _machine("m1", online=True, ip="127.0.0.1")
        m1["name"] = "may-03"
        m2 = _machine("m2", online=True, ip="127.0.0.1")
        m2["name"] = "may-02"
        reg = FakeRegistry([m1, m2])
        mon = MachineMonitor(reg, FakeHub(["m1", "m2"], {
            "m1": {"os": "Windows", "hostname": "may-03"},
            "m2": {"os": "Windows", "hostname": ""},
        }))
        asyncio.run(mon._stats_pass())
        # m1: hostname trùng -> sync_name vẫn được gọi nhưng trả False,
        # tên không đổi. m2: hostname rỗng -> monitor không gọi sync_name.
        self.assertEqual(reg.sync_calls, [("m1", "may-03")])
        self.assertEqual(reg._machines[0]["name"], "may-03")
        self.assertEqual(reg._machines[1]["name"], "may-02")


if __name__ == "__main__":
    unittest.main()
