"""Test system_info mo rong cho dashboard 1.2.0.

Chay: cd ~/workspace/mango-server && .venv/bin/python tests/run_tests.py
(hoac python3 -m pytest tests/test_systeminfo12.py -v)

Cac test chay duoc tren Linux (khong can Windows): WMI tra [] nen
gpu/memory_detail rong; psutil co hay khong thi assert theo dieu kien
(.venv hien tai KHONG co psutil nen disks == [] va memory_note co mat).
"""
import os
import platform
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client-2.0", "client"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from mangoengine import core

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False

NEW_FIELDS = ("cpu_model", "cpu_cores", "cpu_ghz", "cpu_percent",
              "memory_used_gb", "memory_detail", "gpu", "gpu_note", "disks")
DISK_KEYS = ("device", "mountpoint", "filesystem", "total_gb",
             "used_gb", "free_gb", "used_percent")
MEMORY_STICK_KEYS = ("capacity_gb", "speed_mhz", "type", "manufacturer")
GPU_KEYS = ("name", "driver_version", "vram_gb", "usage_percent",
            "temperature_c", "power_w")


class TestSystemInfo12(unittest.TestCase):
    def test_no_exception_with_none_config(self):
        """system_info(config=None) khong nem exception, luon tra dict."""
        info = core.system_info(None)
        self.assertIsInstance(info, dict)

    def test_old_fields_present(self):
        """Cac truong cu van du (tuong thich nguoc)."""
        info = core.system_info(None)
        self.assertIsInstance(info["os"], str)
        self.assertTrue(info["os"])
        self.assertIsInstance(info["hostname"], str)
        self.assertTrue(info["cpu_logical"] is None
                        or isinstance(info["cpu_logical"], int))

    def test_new_fields_present_and_types(self):
        """Cac truong moi ton tai va dung kieu."""
        info = core.system_info(None)
        for field in NEW_FIELDS:
            self.assertIn(field, info, f"Thieu truong moi: {field}")
        self.assertIsInstance(info["cpu_model"], str)
        self.assertIsInstance(info["cpu_cores"], int)
        self.assertTrue(info["cpu_ghz"] is None
                        or isinstance(info["cpu_ghz"], float))
        self.assertIsInstance(info["cpu_percent"], float)
        self.assertIsInstance(info["memory_used_gb"], float)
        self.assertIsInstance(info["memory_detail"], list)
        self.assertIsInstance(info["gpu"], list)
        self.assertIsInstance(info["gpu_note"], str)
        self.assertIsInstance(info["disks"], list)

    def test_cpu_percent_in_range(self):
        info = core.system_info(None)
        self.assertGreaterEqual(info["cpu_percent"], 0.0)
        self.assertLessEqual(info["cpu_percent"], 100.0)

    def test_linux_gpu_empty_and_note_mentions_windows(self):
        """Tren Linux: khong co GPU (WMI chi co tren Windows)."""
        if platform.system() == "Windows":
            self.skipTest("chi chay tren non-Windows")
        info = core.system_info(None)
        self.assertEqual(info["gpu"], [])
        self.assertIn("Windows", info["gpu_note"])

    def test_linux_memory_detail_empty(self):
        if platform.system() == "Windows":
            self.skipTest("chi chay tren non-Windows")
        info = core.system_info(None)
        self.assertEqual(info["memory_detail"], [])

    def test_wmi_query_returns_empty_on_linux(self):
        """Helper _wmi_query khong chay WMI tren Linux, tra [] chu khong nem."""
        if platform.system() == "Windows":
            self.skipTest("chi chay tren non-Windows")
        self.assertEqual(
            core._wmi_query("SELECT Name FROM Win32_Processor"), [])

    def test_smbios_memory_type_map(self):
        """Map SMBIOSMemoryType theo dung spec: 26=DDR4, 34=DDR5, 24=DDR3."""
        mapping = core._SMBIOS_MEMORY_TYPE
        self.assertEqual(mapping[26], "DDR4")
        self.assertEqual(mapping[34], "DDR5")
        self.assertEqual(mapping[24], "DDR3")
        self.assertEqual(mapping[21], "DDR2")
        self.assertEqual(mapping[20], "DDR")

    def test_disks_conditional_on_psutil(self):
        """Co psutil thi co it nhat 1 o; khong co thi [] (khong crash)."""
        info = core.system_info(None)
        if not HAS_PSUTIL:
            self.assertEqual(info["disks"], [])
            return
        self.assertGreaterEqual(len(info["disks"]), 1)
        for disk in info["disks"]:
            for key in DISK_KEYS:
                self.assertIn(key, disk, f"O thieu khoa: {key}")
            self.assertIsInstance(disk["device"], str)
            self.assertIsInstance(disk["mountpoint"], str)
            self.assertIsInstance(disk["filesystem"], str)
            for key in ("total_gb", "used_gb", "free_gb", "used_percent"):
                self.assertIsInstance(disk[key], (int, float))
                self.assertEqual(round(disk[key], 1), disk[key])
            self.assertGreaterEqual(disk["used_percent"], 0.0)
            self.assertLessEqual(disk["used_percent"], 100.0)

    def test_memory_fields_conditional_on_psutil(self):
        """Co psutil thi du so lieu RAM; khong co thi co memory_note."""
        info = core.system_info(None)
        if not HAS_PSUTIL:
            self.assertIn("memory_note", info)
            self.assertEqual(info["memory_used_gb"], 0.0)
            return
        self.assertGreater(info["memory_total_gb"], 0)
        self.assertGreaterEqual(info["memory_used_gb"], 0.0)
        self.assertLessEqual(info["memory_used_gb"],
                             info["memory_total_gb"])
        self.assertGreaterEqual(info["memory_used_percent"], 0.0)
        self.assertLessEqual(info["memory_used_percent"], 100.0)
        self.assertIn("boot_time", info)

    def test_memory_detail_entry_shape(self):
        """Neu co thanh RAM thi moi thanh du 4 khoa, dung kieu."""
        info = core.system_info(None)
        for stick in info["memory_detail"]:
            for key in MEMORY_STICK_KEYS:
                self.assertIn(key, stick, f"Thanh RAM thieu khoa: {key}")
            self.assertIsInstance(stick["capacity_gb"], float)
            self.assertTrue(stick["speed_mhz"] is None
                            or isinstance(stick["speed_mhz"], int))
            self.assertIsInstance(stick["type"], str)
            self.assertIsInstance(stick["manufacturer"], str)

    def test_gpu_entry_shape(self):
        """Neu co GPU thi moi GPU du 6 khoa; temp/power luon None (WMI)."""
        info = core.system_info(None)
        for gpu in info["gpu"]:
            for key in GPU_KEYS:
                self.assertIn(key, gpu, f"GPU thieu khoa: {key}")
            self.assertIsInstance(gpu["name"], str)
            self.assertIsInstance(gpu["driver_version"], str)
            self.assertTrue(gpu["vram_gb"] is None
                            or isinstance(gpu["vram_gb"], float))
            self.assertTrue(gpu["usage_percent"] is None
                            or isinstance(gpu["usage_percent"], float))
            self.assertIsNone(gpu["temperature_c"])
            self.assertIsNone(gpu["power_w"])

    def test_repeated_calls_stable_keys(self):
        """Goi 2 lan lien tiep: tap khoa giong nhau, khong rac them."""
        first = core.system_info(None)
        second = core.system_info(None)
        self.assertEqual(set(first.keys()), set(second.keys()))


class TestSystemInfoWmiParsing(unittest.TestCase):
    """Parse dữ liệu WMI mẫu bằng cách mock
    core._wmi_query. Chạy được trên Linux vì không đụng WMI thật."""

    PC3_CPU = [
        {"DeviceID": "CPU0", "Name": "Intel(R) Core(TM) i7-8750H CPU @ 2.20GHz",
         "NumberOfCores": 1, "NumberOfLogicalProcessors": 1, "MaxClockSpeed": 2208},
        {"DeviceID": "CPU1", "Name": "Intel(R) Core(TM) i7-8750H CPU @ 2.20GHz",
         "NumberOfCores": 1, "NumberOfLogicalProcessors": 1, "MaxClockSpeed": 2208},
    ]
    PC3_GPU = [
        {"DeviceID": "VideoController1", "Name": "VMware SVGA 3D",
         "DriverVersion": "9.17.11.3", "AdapterRAM": -1048576},
    ]
    PC3_GPU_USAGE = [
        {"Name": "pid_2628_luid_0x00000000_0x00009B48_phys_0_eng_0_engtype_3D",
         "UtilizationPercentage": "0"},
        {"Name": "pid_2628_luid_0x00000000_0x00009B48_phys_0_eng_1_engtype_VM3DEngineInternal",
         "UtilizationPercentage": "0"},
    ]
    PC3_RAM = [
        {"Capacity": "2147483648", "Manufacturer": "VMware Virtual RAM",
         "SMBIOSMemoryType": 3, "Speed": None},
    ]

    def _fake_wmi(self, query):
        if "Win32_Processor" in query:
            return list(self.PC3_CPU)
        if "Win32_VideoController" in query:
            return list(self.PC3_GPU)
        if "GPUEngine" in query:
            return list(self.PC3_GPU_USAGE)
        if "Win32_PhysicalMemory" in query:
            return list(self.PC3_RAM)
        return []

    def test_cpu_name_cores_ghz_from_wmi(self):
        """Tên CPU thật từ WMI (không phải platform.processor()),
        cộng nhân qua các hàng, xung từ MaxClockSpeed."""
        orig = core._wmi_query
        core._wmi_query = self._fake_wmi
        try:
            info = core.system_info(None)
        finally:
            core._wmi_query = orig
        self.assertEqual(info["cpu_model"],
                         "Intel(R) Core(TM) i7-8750H CPU @ 2.20GHz")
        self.assertNotIn("Intel64 Family", info["cpu_model"])
        self.assertEqual(info["cpu_cores"], 2)  # 2 hàng x 1 nhân
        self.assertEqual(info["cpu_ghz"], 2.21)  # 2208 MHz

    def test_gpu_vram_negative_adapter_ram(self):
        """AdapterRAM âm (tràn 32-bit, VMware) -> đổi không dấu -> ~4GB."""
        orig = core._wmi_query
        core._wmi_query = self._fake_wmi
        try:
            info = core.system_info(None)
        finally:
            core._wmi_query = orig
        self.assertEqual(len(info["gpu"]), 1)
        gpu = info["gpu"][0]
        self.assertEqual(gpu["name"], "VMware SVGA 3D")
        self.assertEqual(gpu["driver_version"], "9.17.11.3")
        # -1048576 & 0xFFFFFFFF = 4293918720 byte ~ 4.0 GB
        self.assertIsNotNone(gpu["vram_gb"])
        self.assertAlmostEqual(gpu["vram_gb"], 4.0, places=1)

    def test_gpu_usage_string_percentage(self):
        """UtilizationPercentage dạng chuỗi ('0') vẫn parse được."""
        orig = core._wmi_query
        core._wmi_query = self._fake_wmi
        try:
            info = core.system_info(None)
        finally:
            core._wmi_query = orig
        gpu = info["gpu"][0]
        self.assertEqual(gpu["usage_percent"], 0.0)
        self.assertEqual(info["gpu_note"], "")

    def test_memory_detail_from_wmi(self):
        """Thanh RAM từ WMI: dung lượng 2GB, hãng VMware, type lạ -> Unknown."""
        orig = core._wmi_query
        core._wmi_query = self._fake_wmi
        try:
            info = core.system_info(None)
        finally:
            core._wmi_query = orig
        self.assertEqual(len(info["memory_detail"]), 1)
        stick = info["memory_detail"][0]
        self.assertEqual(stick["capacity_gb"], 2.0)
        self.assertEqual(stick["manufacturer"], "VMware Virtual RAM")
        self.assertIsNone(stick["speed_mhz"])
        self.assertEqual(stick["type"], "Unknown")  # SMBIOS type 3 ko có trong map

    def test_wmi_query_uses_cogetobject_not_getobject(self):
        """Hồi quy lỗi 2.1.5: _wmi_query phải dùng CoGetObject (comtypes
        1.4.17 không còn GetObject). Kiểm tra source, vì trên Linux hàm
        trả [] sớm nên không chạy được nhánh Windows."""
        import inspect
        src = inspect.getsource(core._wmi_query_comtypes)
        self.assertIn("CoGetObject", src)
        self.assertNotIn("GetObject(", src.replace("CoGetObject(", ""))

    def test_wmi_query_falls_back_to_powershell(self):
        """comtypes trả rỗng -> _wmi_query dùng PowerShell fallback."""
        orig_ct = core._wmi_query_comtypes
        orig_ps = core._wmi_query_powershell
        ps_rows = [{"Name": "Intel(R) Core(TM) i7-8750H CPU @ 2.20GHz",
                    "NumberOfCores": 1, "MaxClockSpeed": 2208}]
        core._wmi_query_comtypes = lambda q: []
        core._wmi_query_powershell = lambda q: list(ps_rows)
        try:
            # _wmi_query tra [] som tren Linux (platform != Windows) nen
            # goi truc tiep logic fallback bang cach mock platform.
            import platform as _plat
            orig_system = _plat.system
            _plat.system = lambda: "Windows"
            try:
                self.assertEqual(
                    core._wmi_query("SELECT Name FROM Win32_Processor"),
                    ps_rows)
            finally:
                _plat.system = orig_system
        finally:
            core._wmi_query_comtypes = orig_ct
            core._wmi_query_powershell = orig_ps

    def test_wmi_query_comtypes_wins_when_it_works(self):
        """comtypes có dữ liệu thì không gọi PowerShell."""
        orig_ct = core._wmi_query_comtypes
        orig_ps = core._wmi_query_powershell
        ct_rows = [{"Name": "CPU-A"}]
        calls = []
        core._wmi_query_comtypes = lambda q: list(ct_rows)
        core._wmi_query_powershell = lambda q: calls.append(q) or []
        try:
            import platform as _plat
            orig_system = _plat.system
            _plat.system = lambda: "Windows"
            try:
                self.assertEqual(
                    core._wmi_query("SELECT Name FROM Win32_Processor"),
                    ct_rows)
            finally:
                _plat.system = orig_system
        finally:
            core._wmi_query_comtypes = orig_ct
            core._wmi_query_powershell = orig_ps
        self.assertEqual(calls, [])

    def test_wmi_query_powershell_parses_select_json(self):
        """_wmi_query_powershell: parse JSON từ PowerShell (1 object và
        list), bỏ qua stdout rỗng, sai cú pháp query -> []."""
        import subprocess as _sp
        import json as _json

        class FakeProc:
            def __init__(self, stdout):
                self.stdout = stdout
                self.stderr = ""
                self.returncode = 0

        orig_run = _sp.run
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            # Gia lap PowerShell tra JSON cho CPU (list) va GPU (1 object).
            if "Win32_Processor" in cmd[-1]:
                out = _json.dumps([
                    {"Name": "Intel(R) Core(TM) i7-8750H CPU @ 2.20GHz",
                     "NumberOfCores": 1, "MaxClockSpeed": 2208}])
            elif "Win32_VideoController" in cmd[-1]:
                out = _json.dumps({"Name": "VMware SVGA 3D",
                                   "DriverVersion": "9.17.11.3",
                                   "AdapterRAM": 4293918720})
            else:
                out = ""
            return FakeProc(out)

        _sp.run = fake_run
        try:
            rows = core._wmi_query_powershell(
                "SELECT Name, NumberOfCores, MaxClockSpeed "
                "FROM Win32_Processor")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["Name"],
                             "Intel(R) Core(TM) i7-8750H CPU @ 2.20GHz")
            self.assertEqual(rows[0]["MaxClockSpeed"], 2208)
            # 1 object (không phải list) -> bọc thành list 1 phần tử.
            rows = core._wmi_query_powershell(
                "SELECT Name, DriverVersion, AdapterRAM "
                "FROM Win32_VideoController")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["AdapterRAM"], 4293918720)
            # Query không parse được -> [] (không chạy PowerShell).
            self.assertEqual(core._wmi_query_powershell("SELECT"), [])
            self.assertEqual(core._wmi_query_powershell(""), [])
            # Lệnh PowerShell phải chứa Select-Object đúng field.
            self.assertIn("Select-Object", seen["cmd"][-1])
        finally:
            _sp.run = orig_run


if __name__ == "__main__":
    unittest.main()
