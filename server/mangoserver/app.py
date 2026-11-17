"""Lắp ráp Mango Server 1.0: 1 tiến trình uvicorn, 1 cổng (mặc định 8443).

- POST /mcp        : MCP endpoint (Streamable HTTP JSON-RPC) cho Agent AI.
- WS   /ws        : WebSocket cho máy client (enrollment xong mới nối).
- GET  /dashboard : Bảng điều khiển web (đăng nhập mật khẩu quản trị).
- /api/*          : API của dashboard (+ /api/enroll public cho máy mới).
- GET  /health    : kiểm tra sống (không cần xác thực).

Chạy local bằng HTTP — TLS do Cloudflare Tunnel lo ở ngoài (máy ảo).
"""
import asyncio
import json
import time
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocketDisconnect

from . import VERSION
from .auth import AuthStore
from .dashboard import Sessions, dashboard_page, make_dashboard_routes, redirect_root
from .hub import MachineHub
from .monitor import MachineMonitor
from .mcp_endpoint import AuthFailLimiter, Router, make_mcp_handler
from .packages import PackageStore, compare_versions
from .registry import Registry
from .store import AuditLog, JsonStore


def build_app(data_dir, version: str = VERSION,
              host: str = "127.0.0.1", port: int = 8443):
    """Tạo Starlette app. `data_dir` chứa registry.json, auth.json,
    audit.jsonl, packages.json + thư mục packages/. Gọi 1 lần lúc khởi
    động Server. `host`/`port`/`data_dir` được lưu vào app.state để
    /api/config trả đúng (§1.4)."""
    data_dir = str(data_dir)
    registry_store = JsonStore(f"{data_dir}/registry.json", {"machines": {}})
    auth_store_raw = JsonStore(f"{data_dir}/auth.json", {
        "admin_password_sha256": "",
        "enrollment_tokens": [],
        "agent_tokens": [],
        "settings": {"enrollment_ttl_seconds": 86400},
    })
    packages_store = JsonStore(f"{data_dir}/packages.json", {"packages": {}})
    audit = AuditLog(f"{data_dir}/audit.jsonl")
    registry = Registry(registry_store)
    auth = AuthStore(auth_store_raw)
    hub = MachineHub()
    packages = PackageStore(packages_store, f"{data_dir}/packages")
    # Monitor 1.2.0: ping 10s + stats 5 phút cho dashboard mới.
    monitor = MachineMonitor(registry, hub, audit)
    router = Router(registry, hub, audit, packages=packages)
    limiter = AuthFailLimiter()
    enroll_limiter = AuthFailLimiter(max_failures=5, window_seconds=60, block_seconds=300)
    # Giới hạn riêng cho enroll bằng URL (§3.1): tối đa 5 lần thất bại /
    # 10 phút / IP, chặn 10 phút.
    enroll_request_limiter = AuthFailLimiter(max_failures=5, window_seconds=600,
                                             block_seconds=600)
    sessions = Sessions()

    mcp_handler = make_mcp_handler(auth, router, limiter)
    dash = make_dashboard_routes()

    async def health(request):
        return JSONResponse({"status": "ok", "version": version,
                             "server": "Mango Server"})

    async def ws_handler(websocket):
        await websocket.accept()
        machine_id = None
        try:
            # Message đầu tiên phải là auth, chờ tối đa 10s.
            first = await asyncio.wait_for(websocket.receive_text(), timeout=10)
            try:
                msg = json.loads(first)
            except Exception:
                await websocket.send_text(json.dumps(
                    {"type": "error", "error": "AUTH_INVALID"}))
                await websocket.close(code=4401)
                return
            if msg.get("type") != "auth":
                await websocket.send_text(json.dumps(
                    {"type": "error", "error": "AUTH_REQUIRED"}))
                await websocket.close(code=4401)
                return
            machine_id = str(msg.get("machine_id", ""))
            secret = str(msg.get("secret", ""))
            rec = registry.verify_machine(machine_id, secret)
            if rec is None:
                audit.append("ws.auth_failed", machine_id=machine_id, ok=False,
                             error_code="BAD_MACHINE_CREDENTIAL")
                await websocket.send_text(json.dumps(
                    {"type": "error", "error": "BAD_MACHINE_CREDENTIAL"}))
                await websocket.close(code=4401)
                return
            await hub.register(machine_id, websocket)
            client_ip = websocket.client.host if websocket.client else ""
            audit.append("ws.connected", machine_id=machine_id, ok=True)
            await websocket.send_text(json.dumps(
                {"type": "welcome", "machine_id": machine_id,
                 "status": rec.get("status")}))
            while True:
                try:
                    raw = await websocket.receive_text()
                except WebSocketDisconnect:
                    break
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                mtype = msg.get("type")
                if mtype == "heartbeat":
                    registry.heartbeat(
                        machine_id,
                        version=str(msg.get("version", "")),
                        agent_connected=bool(msg.get("agent_connected", False)),
                        ip=client_ip)
                    # Nấc 2 (§2.2): client 1.1 báo thêm client_version +
                    # allowed_tools; client 1.0 không gửi -> giữ nguyên.
                    registry.update_reported(
                        machine_id,
                        client_version=msg.get("client_version"),
                        allowed_tools=msg.get("allowed_tools"))
                    rec = registry.get(machine_id) or {}
                    ack = {"type": "heartbeat_ack",
                           "server_time": int(time.time())}
                    # desired_scope: chỉ gửi khi đã đặt VÀ khác reported.
                    desired = rec.get("desired_scope")
                    reported = list(rec.get("reported_tools") or [])
                    ack["desired_scope"] = (list(desired) if desired is not None
                                            and list(desired) != reported else None)
                    # upgrade: chỉ khi đã đặt target_version và có gói
                    # mới hơn bản client đang chạy (§4.2).
                    upgrade = None
                    target = rec.get("target_version")
                    client_version = str(rec.get("client_version") or "")
                    if target:
                        pkg = packages.get(target)
                        if (pkg is not None
                                and compare_versions(target, client_version) > 0):
                            upgrade = {
                                "version": pkg["version"],
                                "sha256": pkg.get("sha256", ""),
                                "size": int(pkg.get("size", 0)),
                                "requires_restart": bool(pkg.get("requires_restart", False)),
                            }
                    ack["upgrade"] = upgrade
                    # Client vừa chạy lại với đúng bản đích -> xong nâng cấp.
                    if (target and client_version
                            and compare_versions(target, client_version) == 0):
                        registry.set_target_version(machine_id, None)
                        registry.set_upgrade_status(machine_id, "done")
                    await websocket.send_text(json.dumps(ack))
                elif mtype == "upgrade_status":
                    # Client báo tiến độ nâng cấp (§4.2): downloading /
                    # applying / done / failed.
                    status = str(msg.get("status", ""))
                    version = str(msg.get("version", ""))
                    if registry.set_upgrade_status(machine_id, status):
                        audit.append("ws.upgrade_status", machine_id=machine_id,
                                     version=version, status=status, ok=True)
                elif mtype == "result":
                    hub.handle_result(msg)
                elif mtype == "bye":
                    break
        except asyncio.TimeoutError:
            try:
                await websocket.close(code=4401)
            except Exception:
                pass
        except Exception:
            pass
        finally:
            if machine_id:
                await hub.unregister(machine_id, websocket)
                audit.append("ws.disconnected", machine_id=machine_id, ok=True)

    app = Starlette(routes=[
        Route("/", redirect_root),
        Route("/health", health, methods=["GET"]),
        Route("/mcp", mcp_handler, methods=["POST"]),
        Route("/dashboard", dashboard_page, methods=["GET"]),
        Route("/api/login", dash["login"], methods=["POST"]),
        Route("/api/logout", dash["logout"], methods=["POST"]),
        Route("/api/status", dash["status"], methods=["GET"]),
        Route("/api/config", dash["config"], methods=["GET"]),
        Route("/api/config/change-password", dash["config_change_password"],
              methods=["POST"]),
        Route("/api/config/enrollment-ttl", dash["config_enrollment_ttl"],
              methods=["POST"]),
        Route("/api/machines", dash["machines"], methods=["GET"]),
        Route("/api/machines/overview", dash["overview"], methods=["GET"]),
        Route("/api/machines/scan-now", dash["scan_now"], methods=["POST"]),
        # Route cụ thể phải đứng TRƯỚC /api/machines/{machine_id}/{action}
        # (Starlette khớp theo thứ tự; route {action} sẽ nuốt "scope",
        # "upgrade", "restart", "call", "admin" nếu đứng trước).
        Route("/api/machines/{machine_id}/scope", dash["machine_scope_get"],
              methods=["GET"]),
        Route("/api/machines/{machine_id}/scope", dash["machine_scope_set"],
              methods=["POST"]),
        Route("/api/machines/{machine_id}/upgrade", dash["machine_upgrade"],
              methods=["POST"]),
        Route("/api/machines/{machine_id}/restart", dash["machine_restart"],
              methods=["POST"]),
        Route("/api/machines/{machine_id}/call", dash["machine_call"],
              methods=["POST"]),
        Route("/api/machines/{machine_id}/admin", dash["machine_admin"],
              methods=["POST"]),
        Route("/api/machines/{machine_id}/{action}", dash["machine_action"],
              methods=["POST"]),
        Route("/api/enrollment", dash["enrollment_list"], methods=["GET"]),
        Route("/api/enrollment", dash["enrollment_create"], methods=["POST"]),
        Route("/api/enrollment/revoke", dash["enrollment_revoke"], methods=["POST"]),
        Route("/api/agent-tokens", dash["agent_token_list"], methods=["GET"]),
        Route("/api/agent-tokens", dash["agent_token_create"], methods=["POST"]),
        Route("/api/agent-tokens/{token_id}/{action}", dash["agent_token_action"],
              methods=["POST"]),
        Route("/api/audit", dash["audit_list"], methods=["GET"]),
        Route("/api/packages", dash["packages_list"], methods=["GET"]),
        Route("/api/packages", dash["packages_upload"], methods=["POST"]),
        Route("/api/packages/{version}", dash["packages_delete"],
              methods=["DELETE"]),
        Route("/api/packages/{version}/download", dash["packages_download"],
              methods=["GET"]),
        Route("/api/enroll", dash["enroll"], methods=["POST"]),
        Route("/api/enroll-request", dash["enroll_request"], methods=["POST"]),
        WebSocketRoute("/ws", ws_handler),
    ], lifespan=_lifespan)
    app.state.version = version
    app.state.started_at = time.time()
    app.state.server_host = host
    app.state.server_port = port
    app.state.data_dir = data_dir
    app.state.registry = registry
    app.state.auth = auth
    app.state.audit = audit
    app.state.hub = hub
    app.state.monitor = monitor
    app.state.packages = packages
    app.state.router = router
    app.state.limiter = limiter
    app.state.enroll_limiter = enroll_limiter
    app.state.enroll_request_limiter = enroll_request_limiter
    app.state.sessions = sessions
    return app


@asynccontextmanager
async def _lifespan(app):
    """Khởi động/dừng monitor 1.2.0 cùng Server (Starlette >= 1.0 chỉ còn
    cách lifespan, không còn add_event_handler/on_startup)."""
    monitor = app.state.monitor
    await monitor.start()
    try:
        yield
    finally:
        await monitor.stop()
