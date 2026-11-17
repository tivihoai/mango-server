"""MCP client tối giản (chuẩn library) gọi MangoMCP 0.14.x local qua HTTP.

Chỉ dùng urllib (stdlib) để chạy được trên Python portable của Windows
mà không cần cài thêm gì. Giao thức: Streamable HTTP JSON-RPC, giống
client của Muse (custom.mangomcp): POST JSON-RPC, nhận application/json
hoặc text/event-stream.

Dùng để client 1.0 thực thi tool local khi Server route lệnh tới.
"""
import json
import urllib.error
import urllib.request

from mangoclient import VERSION as CLIENT_VERSION


class LocalMcpError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LocalMcpError("Local MCP endpoint redirected")


class LocalMcpClient:
    def __init__(self, url: str, bearer: str, timeout: int = 45):
        self.url = url
        self.bearer = bearer
        self.timeout = timeout
        # Luon bypass proxy cho MCP local (luon la loopback 127.0.0.1).
        self.opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.ProxyHandler({}))
        self.session = None
        self.protocol = "2025-06-18"
        self._seq = 0

    def _send(self, method, params, notification=False):
        self._seq += 1
        request_id = None if notification else self._seq
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            body["id"] = request_id
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self.protocol,
            "User-Agent": "Mango-Server-Client/" + CLIENT_VERSION,
        }
        if self.bearer:
            headers["Authorization"] = "Bearer " + self.bearer
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                if s := resp.headers.get("Mcp-Session-Id"):
                    self.session = s
                if notification:
                    return None
                return self._read_result(resp, request_id)
        except urllib.error.HTTPError as exc:
            raise LocalMcpError(f"Local MCP HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LocalMcpError(f"Local MCP khong noi duoc: {exc}") from None

    @staticmethod
    def _decode(payload, request_id):
        msg = json.loads(payload)
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            raise LocalMcpError("Local MCP tra JSON-RPC khong hop le")
        if type(msg.get("id")) is not int or msg["id"] != request_id:
            return None
        if "error" in msg:
            err = msg["error"]
            raise LocalMcpError(f"Local MCP loi: {err.get('message', err)}")
        if not isinstance(msg.get("result"), dict):
            raise LocalMcpError("Local MCP khong tra result object")
        return msg["result"]

    def _read_result(self, resp, request_id):
        ctype = resp.headers.get_content_type()
        if ctype == "application/json":
            result = self._decode(resp.read(), request_id)
            if result is None:
                raise LocalMcpError("Local MCP tra sai request id")
            return result
        if ctype != "text/event-stream":
            raise LocalMcpError(f"Local MCP tra content-type khong ho tro: {ctype}")
        data = []
        while True:
            line = resp.readline()
            if not line:
                raise LocalMcpError("Local MCP dong stream truoc khi co ket qua")
            line = line.rstrip(b"\r\n")
            if line.startswith(b"data:"):
                data.append(line[5:].lstrip(b" "))
            elif not line and data:
                result = self._decode(b"\n".join(data), request_id)
                data.clear()
                if result is not None:
                    return result

    def initialize(self):
        result = self._send("initialize", {
            "protocolVersion": self.protocol,
            "capabilities": {},
            "clientInfo": {"name": "mango-server-client", "version": CLIENT_VERSION},
        })
        if isinstance(result.get("protocolVersion"), str):
            self.protocol = result["protocolVersion"]
        self._send("notifications/initialized", {}, notification=True)

    def call_tool(self, name: str, arguments: dict):
        """Gọi 1 tool local. Trả dict result của MCP (content/isError).

        Tự thử initialize() lại khi chưa có session (vd initialize lúc
        khởi động thất bại vì MCP local chưa lên kịp sau reboot) hoặc khi
        session cũ bị Core từ chối (HTTP 400)."""
        if self.session is None:
            self.initialize()
        try:
            return self._send("tools/call",
                              {"name": name, "arguments": arguments or {}})
        except LocalMcpError as exc:
            if "HTTP 400" not in str(exc) or self.session is None:
                raise
            # Session cũ đã hết hạn (Core vừa khởi động lại): bỏ session,
            # initialize lại rồi gọi 1 lần nữa.
            self.session = None
            self.initialize()
            return self._send("tools/call",
                              {"name": name, "arguments": arguments or {}})
