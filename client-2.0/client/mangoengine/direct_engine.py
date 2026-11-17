"""DirectEngine — goi thang engine MangoMCP trong cung process (Client 2.0).

Thay the LocalMcpClient (HTTP toi 127.0.0.1:8766). Cung phuong thuc
call_tool(name, args) de ServerLink khong phai doi, nhung goi thang ham
core/desktop trong process thay vi qua HTTP + IPC.

Phan quyen 2 lop:
- Server scope (allowed_tools) do ServerLink kiem tra truoc khi goi.
- Cong quyen may (config.permission) do core.require() kiem tra trong ham.
- CURRENT_AUTH de None (khong co client MCP nao) nen khong bi gioi han
  scope client; chi con cong toan cuc + chan khi khoa tam ngung.
"""

import threading

from mangoengine import core, desktop, gui, server_tools
from mangoengine.config import CURRENT_AUTH


def build_dispatch_table():
    """Bang dispatch cho ca 100 tool: ten -> ham (core/desktop/server).

    Tai dung y tu agent.build_dispatch_table() (fail-fast neu thieu ham),
    mo rong cho ca 100 tool chu khong chi CONTROL_TOOLS.
    """
    table = {}
    missing = []
    # 89 tool trong core/desktop: 22 dang ky truc tiep + 67 CONTROL_TOOLS.
    # Lay tat ca ham public trong core + desktop co ten khop tool.
    candidates = set()
    for mod in (core, desktop):
        for name in dir(mod):
            if not name.startswith("_"):
                candidates.add(name)
    # Chi lay nhung ten la tool that (co trong CONTROL_TOOLS hoac la ham
    # tool dang ky truc tiep). De don gian: lay tat ca ham co the goi duoc
    # trong core/desktop, ServerLink da gioi han bang allowed_tools.
    for name in sorted(candidates):
        fn = getattr(core, name, None) or getattr(desktop, name, None)
        if callable(fn):
            table[name] = fn
    # 11 tool cau hinh tu server.py (auto_logon_*, user_*, switch_user,
    # control_*): them tu server_tools.
    for name in dir(server_tools):
        if not name.startswith("_"):
            fn = getattr(server_tools, name)
            if callable(fn):
                table[name] = fn
    # Kiem tra CONTROL_TOOLS phai du (fail-fast nhu agent).
    for name in sorted(core.CONTROL_TOOLS):
        fn = getattr(core, name, None) or getattr(desktop, name, None)
        if fn is None:
            missing.append(name)
    if missing:
        raise RuntimeError(
            "DirectEngine: thieu ham thuc thi cho tool: %s" % ", ".join(missing)
        )
    return table


class DirectEngine:
    """Engine goi truc tiep trong process."""

    def __init__(self, config):
        self.config = config
        self._table = build_dispatch_table()
        # Lock tuan tu cho tool dieu khien (thay _call_lock cua IPC cu):
        # 1 lenh dieu khien chay cung luc, tranh 2 thao tac chuot/phim
        # chong cheo nhau.
        self._control_lock = threading.Lock()

    def initialize(self):
        """Tuong thich LocalMcpClient.initialize(): khong can bat tay."""
        return True

    def list_tools(self):
        """Ten cac tool co the goi (de ServerLink bao cao)."""
        return sorted(self._table.keys())

    def call_tool(self, name, args):
        """Goi tool bang ten, tra ket qua dang MCP envelope.

        Tra ve dung dinh dang LocalMcpClient tra ({"content": [{"text":
        "<json>"}]}) de ServerLink + Server khong phai doi gi. Loi tra
        {"isError": True, ...} de execute_call nhan ra.
        """
        import json

        from mangoengine.errors import MangoError

        fn = self._table.get(name)
        if fn is None:
            return {"isError": True, "content": [{
                "type": "text",
                "text": json.dumps({"error": "UNKNOWN_TOOL",
                                    "message": "DirectEngine: khong co tool '%s'" % name},
                                   ensure_ascii=False)}]}
        args = dict(args or {})
        # Client 2.1 chay bang SYSTEM o session 0 (khong co desktop):
        # tool dieu khien (CONTROL_TOOLS) chuyen sang GUI agent qua IPC.
        # Dang o session nguoi dung thi chay truc tiep nhu 2.0.
        if name in core.CONTROL_TOOLS and gui.is_system_session():
            return gui.call_control_tool(self.config, name, args)
        # Dat CURRENT_AUTH = None: khong co client MCP, chi ap cong
        # quyen toan cuc trong core.require() + chan khi khoa tam ngung.
        token = CURRENT_AUTH.set(None)
        try:
            if name in core.CONTROL_TOOLS:
                with self._control_lock:
                    result = fn(self.config, **args)
            else:
                result = fn(self.config, **args)
        except MangoError as exc:
            return {"isError": True, "content": [{
                "type": "text",
                "text": json.dumps(exc.to_dict(), ensure_ascii=False)}]}
        except Exception as exc:
            return {"isError": True, "content": [{
                "type": "text",
                "text": json.dumps({"error": "TOOL_ERROR", "message": str(exc)},
                                   ensure_ascii=False)}]}
        finally:
            CURRENT_AUTH.reset(token)
        return {"content": [{
            "type": "text",
            "text": json.dumps(result, ensure_ascii=False, default=str)}]}
