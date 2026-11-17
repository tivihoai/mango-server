"""Dashboard web của Mango Server 1.0.

Một trang HTML duy nhất tại /dashboard (không dùng thư viện ngoài, chỉ
fetch API). Đăng nhập bằng mật khẩu quản trị Server, phiên lưu bằng
cookie HttpOnly (ms_session), hết hạn sau 12 giờ.

Dashboard cho Quản trị viên:
- Xem danh sách máy (tên, trạng thái duyệt, online/offline, bản).
- Bấm vào máy: xem chi tiết, duyệt/từ chối/thu hồi/xóa, xoay secret,
  gửi 1 lệnh tool, gửi lệnh quản trị (disconnect/status).
- Tạo/thu hồi mã đăng ký (enrollment) và token Agent.
- Xem nhật ký (metadata) và trạng thái Server.
- KHÔNG hiện mật khẩu Windows hay secret máy (2 thứ đó không có trên
  Server; secret máy/token chỉ hiện ĐÚNG 1 lần lúc tạo).

Mọi API (trừ /api/login và /api/enroll) đều yêu cầu session hợp lệ.
"""
import hashlib
import json
import os
import time

from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)

from .security import new_token

SESSION_TTL_SECONDS = 12 * 3600  # phiên dashboard hết hạn sau 12 giờ
MAX_PACKAGE_BYTES = 200 * 1024 * 1024  # gói client tối đa 200MB (§4.4)


class Sessions:
    """Phiên đăng nhập dashboard, lưu trong bộ nhớ (Server restart thì
    đăng nhập lại — chấp nhận được ở 1.0)."""

    def __init__(self):
        self._sessions = {}  # session_id -> created_ts

    def create(self) -> str:
        sid = new_token(24)
        self._sessions[sid] = time.time()
        return sid

    def valid(self, sid: str) -> bool:
        if not sid:
            return False
        created = self._sessions.get(sid)
        if created is None:
            return False
        if time.time() - created > SESSION_TTL_SECONDS:
            del self._sessions[sid]
            return False
        return True

    def destroy(self, sid: str) -> None:
        self._sessions.pop(sid, None)


def _session_id(request) -> str:
    return request.cookies.get("ms_session", "")


def _need_auth(request):
    """Trả None nếu session hợp lệ, ngược lại trả JSONResponse 401."""
    sessions = request.app.state.sessions
    if sessions.valid(_session_id(request)):
        return None
    return JSONResponse({"error": "unauthorized",
                         "message": "Dang nhap bang mat khau quan tri truoc"},
                        status_code=401)


def _json_ok(payload, status_code: int = 200):
    return JSONResponse(payload, status_code=status_code)


def _json_err(message: str, status_code: int = 400):
    return JSONResponse({"error": message}, status_code=status_code)


def make_dashboard_routes():
    """Trả dict các handler API. Dùng closure lấy state từ request.app."""
    from .auth import make_machine_credential
    from .hub import CallError
    from .security import summarize_args

    async def login(request):
        try:
            body = await request.json()
        except Exception:
            return _json_err("Yeu cau khong hop le", 400)
        auth = request.app.state.auth
        if auth.verify_admin_password(str(body.get("password", ""))):
            sid = request.app.state.sessions.create()
            resp = _json_ok({"ok": True})
            resp.set_cookie("ms_session", sid, httponly=True, samesite="lax",
                            path="/", max_age=SESSION_TTL_SECONDS)
            request.app.state.audit.append("dashboard.login", actor="admin", ok=True)
            return resp
        request.app.state.audit.append("dashboard.login", actor="admin", ok=False,
                                       error_code="WRONG_PASSWORD")
        return _json_err("Mat khau khong dung", 401)

    async def logout(request):
        request.app.state.sessions.destroy(_session_id(request))
        resp = _json_ok({"ok": True})
        resp.delete_cookie("ms_session", path="/")
        return resp

    async def status(request):
        err = _need_auth(request)
        if err:
            return err
        st = request.app.state
        return _json_ok({
            "version": st.version,
            "uptime_seconds": int(time.time() - st.started_at),
            "machines_total": len(st.registry.list_public()),
            "machines_online": sum(
                1 for m in st.registry.list_public() if m["online"]),
            "machines_pending": sum(
                1 for m in st.registry.list_public() if m["status"] == "pending"),
            "ws_connected": len(st.hub.connected_machines()),
            "admin_password_set": st.auth.admin_password_set(),
        })

    async def machines(request):
        err = _need_auth(request)
        if err:
            return err
        return _json_ok({"machines": request.app.state.registry.list_public()})

    # ----- Dashboard 1.2.0 (mẫu AgentPCManagement) -----
    async def overview(request):
        """Tổng quan gộp cho dashboard mới: registry + ping (10s) + stats
        (5 phút) của từng máy. Frontend poll mỗi 10s; stats chỉ đổi khi
        monitor chạy lượt 5 phút (server cache, không gọi máy liên tục)."""
        err = _need_auth(request)
        if err:
            return err
        monitor = getattr(request.app.state, "monitor", None)
        if monitor is None:
            return _json_ok({"machines": request.app.state.registry.list_public(),
                             "counts": {"total": 0, "online": 0, "offline": 0,
                                        "ssh_open": 0, "rdp_open": 0, "pending": 0},
                             "last_scan_at": 0, "last_stats_at": 0,
                             "scan_count": 0, "history": []})
        return _json_ok(monitor.overview())

    async def scan_now(request):
        """Nút "Quét ngay": chạy 1 lượt ping + stats ngay (không chờ nhịp
        10s/5 phút). Chạy nền để không chặn request quá lâu."""
        err = _need_auth(request)
        if err:
            return err
        monitor = getattr(request.app.state, "monitor", None)
        if monitor is None:
            return _json_err("Monitor chua chay", 503)
        import asyncio
        asyncio.create_task(monitor.scan_now())
        request.app.state.audit.append("dashboard.scan_now", actor="admin",
                                       ok=True)
        return _json_ok({"ok": True, "message": "Dang quet, tai lai sau vai giay"})

    async def machine_action(request):
        err = _need_auth(request)
        if err:
            return err
        machine_id = request.path_params["machine_id"]
        action = request.path_params["action"]
        st = request.app.state
        if action in ("approve", "reject", "revoke"):
            status = {"approve": "approved", "reject": "rejected",
                      "revoke": "revoked"}[action]
            ok = st.registry.set_status(machine_id, status, by="admin")
            if not ok:
                return _json_err("Khong tim thay may", 404)
            if action == "revoke":
                await st.hub.send_admin(machine_id, "disconnect",
                                        "Credential da bi thu hoi")
            st.audit.append(f"dashboard.machine_{action}", actor="admin",
                            machine_id=machine_id, ok=True)
            return _json_ok({"ok": True, "machine": st.registry.public(st.registry.get(machine_id))})
        if action == "delete":
            ok = st.registry.delete(machine_id)
            if not ok:
                return _json_err("Khong tim thay may", 404)
            await st.hub.send_admin(machine_id, "disconnect", "May da bi xoa")
            st.audit.append("dashboard.machine_delete", actor="admin",
                            machine_id=machine_id, ok=True)
            return _json_ok({"ok": True})
        if action == "rotate-secret":
            machine_id_new, secret = make_machine_credential()
            rec = st.registry.get(machine_id)
            if rec is None:
                return _json_err("Khong tim thay may", 404)
            # Giữ nguyên machine_id, chỉ xoay secret.
            st.registry.rotate_secret(machine_id, secret)
            await st.hub.send_admin(machine_id, "disconnect",
                                    "Secret da xoay, hay noi lai bang secret moi")
            st.audit.append("dashboard.machine_rotate_secret", actor="admin",
                            machine_id=machine_id, ok=True)
            # Secret chỉ trả 1 lần này, dashboard phải hiện rồi quên.
            return _json_ok({"ok": True, "machine_id": machine_id, "secret": secret})
        return _json_err("Hanh dong khong hop le", 400)

    async def machine_call(request):
        err = _need_auth(request)
        if err:
            return err
        machine_id = request.path_params["machine_id"]
        try:
            body = await request.json()
        except Exception:
            return _json_err("Yeu cau khong hop le", 400)
        tool = str(body.get("tool", ""))
        args = body.get("args", {}) or {}
        st = request.app.state
        rec = st.registry.get(machine_id)
        if rec is None:
            return _json_err("Khong tim thay may", 404)
        if rec.get("status") != "approved":
            return _json_err(f"May chua duoc duyet (trang thai: {rec.get('status')})", 403)
        if not st.hub.is_connected(machine_id) or not st.registry.is_online(rec):
            return _json_err("May khong online", 503)
        try:
            result = await st.hub.call(machine_id, tool, args)
        except CallError as exc:
            st.audit.append("dashboard.machine_call", actor="admin:dashboard",
                            machine_id=machine_id, tool=tool, ok=False,
                            error_code=exc.code,
                            args=summarize_args(args))
            return _json_err(f"{exc.code}: {exc.message}", 502)
        st.audit.append("dashboard.machine_call", actor="admin:dashboard",
                        machine_id=machine_id, tool=tool, ok=True,
                        args=summarize_args(args))
        return _json_ok({"ok": True, "result": result})

    async def machine_admin(request):
        err = _need_auth(request)
        if err:
            return err
        machine_id = request.path_params["machine_id"]
        try:
            body = await request.json()
        except Exception:
            return _json_err("Yeu cau khong hop le", 400)
        action = str(body.get("action", ""))
        if action not in ("disconnect", "status"):
            return _json_err("Hanh dong khong hop le", 400)
        sent = await request.app.state.hub.send_admin(
            machine_id, action, str(body.get("message", "")))
        return _json_ok({"ok": sent})

    async def enrollment_list(request):
        err = _need_auth(request)
        if err:
            return err
        return _json_ok({"tokens": request.app.state.auth.list_enrollment_tokens()})

    async def enrollment_create(request):
        err = _need_auth(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        label = str(body.get("label", ""))
        token = request.app.state.auth.create_enrollment_token(label)
        request.app.state.audit.append("dashboard.enrollment_create",
                                       actor="admin", label=label, ok=True)
        # Mã chỉ hiện 1 lần này.
        return _json_ok({"ok": True, "token": token,
                         "expires_in_seconds": request.app.state.auth.get_enrollment_ttl()})

    async def enrollment_revoke(request):
        err = _need_auth(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            return _json_err("Yeu cau khong hop le", 400)
        ok = request.app.state.auth.revoke_enrollment_token(
            str(body.get("token_sha256", "")))
        return _json_ok({"ok": ok})

    async def agent_token_list(request):
        err = _need_auth(request)
        if err:
            return err
        return _json_ok({"tokens": request.app.state.auth.list_agent_tokens()})

    async def agent_token_create(request):
        err = _need_auth(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            return _json_err("Yeu cau khong hop le", 400)
        name = str(body.get("name", "agent"))
        machines = body.get("machines", ["*"])
        groups = body.get("tool_groups", ["read"])
        if not isinstance(machines, list) or not isinstance(groups, list):
            return _json_err("machines va tool_groups phai la danh sach", 400)
        rec, token = request.app.state.auth.create_agent_token(name, machines, groups)
        request.app.state.audit.append("dashboard.agent_token_create",
                                       actor="admin", name=name, ok=True)
        # Token chỉ hiện 1 lần này.
        return _json_ok({"ok": True, "token": token,
                         "record": request.app.state.auth.list_agent_tokens()[-1]})

    async def agent_token_action(request):
        err = _need_auth(request)
        if err:
            return err
        token_id = request.path_params["token_id"]
        action = request.path_params["action"]
        auth = request.app.state.auth
        if action == "enable":
            ok = auth.set_agent_token_enabled(token_id, True)
        elif action == "disable":
            ok = auth.set_agent_token_enabled(token_id, False)
        elif action == "delete":
            ok = auth.delete_agent_token(token_id)
        else:
            return _json_err("Hanh dong khong hop le", 400)
        return _json_ok({"ok": ok})

    async def audit_list(request):
        err = _need_auth(request)
        if err:
            return err
        try:
            limit = int(request.query_params.get("limit", "200"))
        except ValueError:
            limit = 200
        return _json_ok({"entries": request.app.state.audit.read_last(max(1, min(limit, 500)))})

    async def enroll(request):
        """Máy mới dùng mã đăng ký để đổi lấy credential bền vững.
        Public (không cần session) nhưng bị giới hạn tốc độ theo IP.
        Trả {machine_id, secret} — secret chỉ hiện 1 lần này."""
        st = request.app.state
        client_ip = request.client.host if request.client else "unknown"
        if st.enroll_limiter.is_blocked(client_ip):
            return _json_err("Qua nhieu lan thu, thu lai sau", 429)
        try:
            body = await request.json()
        except Exception:
            return _json_err("Yeu cau khong hop le", 400)
        token = str(body.get("enrollment_token", ""))
        name = str(body.get("machine_name", ""))
        version = str(body.get("version", ""))
        rec = st.auth.consume_enrollment_token(token)
        if rec is None:
            st.enroll_limiter.record_failure(client_ip)
            st.audit.append("enroll.failed", actor="enroll", ok=False,
                            error_code="INVALID_ENROLLMENT_TOKEN")
            return _json_err("Ma dang ky khong hop le, het han hoac da dung", 401)
        machine_id, secret = make_machine_credential()
        st.registry.enroll(name or machine_id, version, secret, machine_id)
        st.audit.append("enroll.ok", actor="enroll", machine_id=machine_id,
                        machine_name=name, ok=True)
        return _json_ok({"ok": True, "machine_id": machine_id, "secret": secret,
                         "status": "pending",
                         "note": "May dang o trang thai cho duyet. Quan tri vien duyet tren dashboard thi moi dieu khien duoc."})

    # ----- Nấc 1 (§1.2): Tab Cấu hình -----
    async def config(request):
        err = _need_auth(request)
        if err:
            return err
        st = request.app.state
        machines = st.registry.list_public()
        return _json_ok({
            "version": st.version,
            "host": getattr(st, "server_host", "127.0.0.1"),
            "port": getattr(st, "server_port", 8443),
            "data_dir": getattr(st, "data_dir", ""),
            "uptime_seconds": int(time.time() - st.started_at),
            "started_at": int(st.started_at),
            "machines_total": len(machines),
            "machines_online": sum(1 for m in machines if m["online"]),
            "machines_pending": sum(1 for m in machines if m["status"] == "pending"),
            "agent_tokens_total": len(st.auth.list_agent_tokens()),
            "enrollment_ttl_seconds": st.auth.get_enrollment_ttl(),
            "admin_password_set": st.auth.admin_password_set(),
        })

    async def config_change_password(request):
        err = _need_auth(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            return _json_err("Yeu cau khong hop le", 400)
        st = request.app.state
        current = str(body.get("current_password", ""))
        new = str(body.get("new_password", ""))
        if not st.auth.verify_admin_password(current):
            st.audit.append("dashboard.config_password", actor="admin",
                            ok=False, error_code="WRONG_PASSWORD")
            return _json_err("Mat khau hien tai khong dung", 401)
        try:
            st.auth.set_admin_password(new)
        except ValueError as exc:
            return _json_err(str(exc), 400)
        st.audit.append("dashboard.config_password", actor="admin", ok=True)
        return _json_ok({"ok": True})

    async def config_enrollment_ttl(request):
        err = _need_auth(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            return _json_err("Yeu cau khong hop le", 400)
        st = request.app.state
        try:
            seconds = int(body.get("seconds"))
        except (TypeError, ValueError):
            return _json_err("seconds phai la so nguyen", 400)
        try:
            st.auth.set_enrollment_ttl(seconds)
        except ValueError as exc:
            return _json_err(str(exc), 400)
        st.audit.append("dashboard.config_enrollment_ttl", actor="admin",
                        enrollment_ttl_seconds=st.auth.get_enrollment_ttl(), ok=True)
        return _json_ok({"ok": True,
                         "enrollment_ttl_seconds": st.auth.get_enrollment_ttl()})

    # ----- Nấc 2 (§2.3): API scope máy -----
    async def machine_scope_get(request):
        err = _need_auth(request)
        if err:
            return err
        machine_id = request.path_params["machine_id"]
        rec = request.app.state.registry.get(machine_id)
        if rec is None:
            return _json_err("Khong tim thay may", 404)
        reported = list(rec.get("reported_tools") or [])
        desired = rec.get("desired_scope")
        return _json_ok({
            "machine_id": machine_id,
            "reported_tools": reported,
            "reported_at": rec.get("last_seen_scope_at", 0),
            "desired_scope": desired,
            "effective_scope": desired if desired is not None else reported,
        })

    async def machine_scope_set(request):
        err = _need_auth(request)
        if err:
            return err
        machine_id = request.path_params["machine_id"]
        try:
            body = await request.json()
        except Exception:
            return _json_err("Yeu cau khong hop le", 400)
        if "desired_scope" not in body:
            return _json_err("Thieu desired_scope", 400)
        st = request.app.state
        try:
            ok = st.registry.set_desired_scope(machine_id, body.get("desired_scope"))
        except ValueError as exc:
            return _json_err(str(exc), 400)
        if not ok:
            return _json_err("Khong tim thay may", 404)
        sent = await st.hub.send_apply_scope(machine_id, body.get("desired_scope"))
        st.audit.append("dashboard.machine_set_scope", actor="admin",
                        machine_id=machine_id, sent=sent, ok=True)
        return _json_ok({"ok": True, "sent": sent,
                         "machine": st.registry.public(st.registry.get(machine_id))})

    # ----- Nâng cấp + khởi động lại máy (§4.2, §4.5) -----
    async def machine_upgrade(request):
        from .mcp_endpoint import apply_upgrade_target
        err = _need_auth(request)
        if err:
            return err
        machine_id = request.path_params["machine_id"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        st = request.app.state
        target = (body or {}).get("target_version") or None
        ok, res = await apply_upgrade_target(
            st.registry, st.hub, st.packages, machine_id, target)
        if not ok:
            status = 404 if res["error"] in ("MACHINE_NOT_FOUND", "PACKAGE_NOT_FOUND") else 400
            return _json_err(f"{res['error']}: {res['message']}", status)
        st.audit.append("dashboard.machine_upgrade", actor="admin",
                        machine_id=machine_id,
                        target_version=res["target_version"],
                        sent=res["sent"], ok=True)
        return _json_ok({"ok": True, "target_version": res["target_version"],
                         "sent": res["sent"]})

    async def machine_restart(request):
        err = _need_auth(request)
        if err:
            return err
        machine_id = request.path_params["machine_id"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            delay = int((body or {}).get("delay_seconds", 60))
        except (TypeError, ValueError):
            return _json_err("delay_seconds phai la so nguyen", 400)
        if not 0 <= delay <= 3600:
            return _json_err("delay_seconds phai tu 0 den 3600", 400)
        st = request.app.state
        if st.registry.get(machine_id) is None:
            return _json_err("Khong tim thay may", 404)
        sent = await st.hub.send_restart(machine_id, delay)
        st.audit.append("dashboard.machine_restart", actor="admin",
                        machine_id=machine_id, delay_seconds=delay,
                        sent=sent, ok=True)
        return _json_ok({"ok": True, "sent": sent})

    # ----- Kho gói client (§4.4) -----
    async def packages_list(request):
        err = _need_auth(request)
        if err:
            return err
        return _json_ok({"packages": request.app.state.packages.list()})

    async def packages_upload(request):
        err = _need_auth(request)
        if err:
            return err
        st = request.app.state
        try:
            form = await request.form()
        except Exception:
            return _json_err("Yeu cau khong hop le (can multipart/form-data)", 400)
        version = str(form.get("version", "") or "").strip()
        note = str(form.get("note", "") or "")
        requires_restart = str(form.get("requires_restart", "false")).lower() in (
            "true", "1", "yes")
        upload = form.get("file")
        if not version:
            return _json_err("Thieu version", 400)
        if upload is None or not hasattr(upload, "read"):
            return _json_err("Thieu file zip", 400)
        filename = str(getattr(upload, "filename", "") or "")
        if (".." in filename or "/" in filename or "\\" in filename
                or not filename):
            return _json_err("Ten file khong hop le", 400)
        if not filename.lower().endswith(".zip"):
            return _json_err("File goi phai la .zip", 400)
        packages_dir = st.packages.packages_dir
        packages_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = packages_dir / (filename + ".tmp")
        sha = hashlib.sha256()
        size = 0
        try:
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_PACKAGE_BYTES:
                        raise ValueError("File vuot qua 200MB")
                    sha.update(chunk)
                    f.write(chunk)
        except ValueError as exc:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return _json_err(str(exc), 413)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return _json_err("Khong doc duoc file upload", 400)
        dest = packages_dir / filename
        os.replace(tmp_path, dest)
        record = {
            "version": version,
            "filename": filename,
            "sha256": sha.hexdigest(),
            "size": size,
            "requires_restart": requires_restart,
            "created_at": int(time.time()),
            "note": note,
        }
        st.packages.add(record)
        st.audit.append("dashboard.package_upload", actor="admin",
                        version=version, size=size, ok=True)
        return _json_ok({"ok": True, "package": record})

    async def packages_delete(request):
        err = _need_auth(request)
        if err:
            return err
        version = request.path_params["version"]
        st = request.app.state
        if st.registry.machines_with_target(version):
            return _json_err(
                "Goi dang la target_version cua 1 may, khong xoa duoc", 409)
        if not st.packages.delete(version):
            return _json_err("Khong tim thay goi", 404)
        st.audit.append("dashboard.package_delete", actor="admin",
                        version=version, ok=True)
        return _json_ok({"ok": True})

    async def packages_download(request):
        """Tải gói client. KHÔNG cần session dashboard; xác thực bằng
        credential máy: Authorization: Bearer <machine_id>.<secret>."""
        st = request.app.state
        version = request.path_params["version"]
        auth_header = request.headers.get("authorization", "")
        machine_id, secret = "", ""
        if auth_header.lower().startswith("bearer "):
            bearer = auth_header[7:].strip()
            if "." in bearer:
                machine_id, secret = bearer.split(".", 1)
        rec = st.registry.verify_machine(machine_id, secret) if machine_id else None
        if rec is None:
            st.audit.append("package.download", machine_id=machine_id,
                            version=version, ok=False,
                            error_code="BAD_MACHINE_CREDENTIAL")
            return _json_err("Credential may khong hop le", 401)
        path = st.packages.file_path(version)
        if path is None or not path.exists():
            st.audit.append("package.download", machine_id=machine_id,
                            version=version, ok=False, error_code="PACKAGE_NOT_FOUND")
            return _json_err("Khong tim thay goi", 404)
        st.audit.append("package.download", machine_id=machine_id,
                        version=version, ok=True)
        return FileResponse(str(path), media_type="application/zip",
                            filename=path.name)

    # ----- Enroll bằng URL (§3.1) -----
    async def enroll_request(request):
        """Máy mới xin enroll bằng URL (public, không cần mã đăng ký).
        Giới hạn tốc độ riêng: tối đa 5 lần thất bại / 10 phút / IP,
        chặn 10 phút (dùng lại AuthFailLimiter). Máy tạo ra ở trạng thái
        pending — Quản trị viên duyệt trên dashboard thì mới điều khiển được.
        Secret chỉ trả 1 lần này."""
        st = request.app.state
        client_ip = request.client.host if request.client else "unknown"
        if st.enroll_request_limiter.is_blocked(client_ip):
            st.audit.append("enroll_request.failed", actor="enroll_request",
                            ok=False, error_code="RATE_LIMITED")
            return _json_err("Qua nhieu lan thu, thu lai sau", 429)

        def _fail(message, status_code=400):
            st.enroll_request_limiter.record_failure(client_ip)
            st.audit.append("enroll_request.failed", actor="enroll_request",
                            ok=False, error_code="BAD_REQUEST")
            return _json_err(message, status_code)

        try:
            body = await request.json()
        except Exception:
            return _fail("Yeu cau khong hop le")
        if not isinstance(body, dict):
            return _fail("Yeu cau khong hop le")
        name_raw = body.get("machine_name")
        if not isinstance(name_raw, str) or not name_raw.strip():
            return _fail("Thieu machine_name")
        name = name_raw.strip()
        version = str(body.get("version", "") or "")
        client_version = body.get("client_version")
        allowed_tools = body.get("allowed_tools")
        if client_version is not None and not isinstance(client_version, str):
            return _fail("client_version phai la chuoi")
        if allowed_tools is not None and (
                not isinstance(allowed_tools, list)
                or any(not isinstance(t, str) for t in allowed_tools)):
            return _fail("allowed_tools phai la danh sach chuoi")
        machine_id, secret = make_machine_credential()
        st.registry.enroll(name, version, secret, machine_id)
        st.registry.update_reported(machine_id, client_version, allowed_tools)
        st.audit.append("enroll_request.ok", actor="enroll_request",
                        machine_id=machine_id, machine_name=name, ok=True)
        return _json_ok({"ok": True, "machine_id": machine_id, "secret": secret,
                         "status": "pending",
                         "note": "May dang o trang thai cho duyet. Quan tri vien duyet tren dashboard thi moi dieu khien duoc."})

    return {
        "login": login, "logout": logout, "status": status,
        "machines": machines, "machine_action": machine_action,
        "overview": overview, "scan_now": scan_now,
        "machine_call": machine_call, "machine_admin": machine_admin,
        "enrollment_list": enrollment_list, "enrollment_create": enrollment_create,
        "enrollment_revoke": enrollment_revoke,
        "agent_token_list": agent_token_list, "agent_token_create": agent_token_create,
        "agent_token_action": agent_token_action, "audit_list": audit_list,
        "enroll": enroll,
        "config": config, "config_change_password": config_change_password,
        "config_enrollment_ttl": config_enrollment_ttl,
        "machine_scope_get": machine_scope_get,
        "machine_scope_set": machine_scope_set,
        "machine_upgrade": machine_upgrade, "machine_restart": machine_restart,
        "packages_list": packages_list, "packages_upload": packages_upload,
        "packages_delete": packages_delete, "packages_download": packages_download,
        "enroll_request": enroll_request,
    }


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mango Server — Quản lý máy</title>
<link rel="icon" type="image/png" href="data:image/png;base64,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">
<style>
:root{--bg:#0b1220;--panel:#111c2e;--panel2:#16233a;--line:#243449;--text:#e2e8f0;--muted:#94a3b8;--green:#22c55e;--red:#ef4444;--amber:#f59e0b;--blue:#3b82f6}
*{box-sizing:border-box}
body{font-family:system-ui,Arial,sans-serif;margin:0;background:var(--bg);color:var(--text)}
header{background:#0f172a;border-bottom:1px solid var(--line);padding:10px 18px;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
header h1{font-size:20px;margin:0}
header h1 img{width:32px;height:32px;border-radius:7px;vertical-align:-9px;margin-right:2px}
header .sub{color:var(--muted);font-size:13px;margin-top:2px}
header .right{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
header .clock{color:var(--muted);font-size:13px;margin-right:6px}
main{max-width:1560px;margin:0 auto;padding:14px 16px 30px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:14px}
button{padding:7px 13px;border-radius:7px;border:1px solid #475569;background:#1e293b;color:var(--text);cursor:pointer}
button:hover{border-color:#64748b}
button.primary{background:#14532d;border-color:#14532d;color:#fff}
button.danger{border-color:#b91c1c;color:#fca5a5}
button.active{background:#1d4ed8;border-color:#1d4ed8;color:#fff}
input,select,textarea{padding:7px 9px;border:1px solid #475569;border-radius:7px;background:#0f172a;color:var(--text);width:100%;margin:4px 0}
input[type=checkbox]{width:auto}
table{width:100%;border-collapse:collapse;min-width:1180px}
th,td{border-bottom:1px solid var(--line);padding:8px 9px;text-align:left;font-size:13px;vertical-align:top}
th{color:var(--muted);font-weight:600;white-space:nowrap;position:sticky;top:0;background:var(--panel)}
tbody tr:hover{background:#1a2942}
tbody tr{cursor:pointer}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;background:#334155;color:#e2e8f0}
.badge.online,.badge.approved{background:#14532d;color:#bbf7d0}
.badge.offline,.badge.rejected,.badge.revoked{background:#7f1d1d;color:#fecaca}
.badge.pending{background:#713f12;color:#fde68a}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:middle}
.dot.on{background:var(--green)}.dot.off{background:var(--red)}
.muted{color:var(--muted);font-size:12px}
.small{font-size:12px;color:var(--muted);line-height:1.45}
.big{font-size:24px;font-weight:700;line-height:1.1}
.bar{height:7px;border-radius:4px;background:#334155;overflow:hidden;margin:4px 0}
.bar>i{display:block;height:100%;background:var(--green)}
.bar>i.warn{background:var(--amber)}.bar>i.bad{background:var(--red)}
.cards{display:grid;grid-template-columns:repeat(7,1fr);gap:10px;margin-bottom:14px}
.cards .card{margin:0;padding:12px 14px}
.cards .lbl{color:var(--muted);font-size:12px;margin-top:3px}
.tabs{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:14px}
.tabs button{border:none;background:none;font-weight:600;padding:9px 13px;color:var(--muted)}
.tabs button.active{color:#fff;border-bottom:2px solid #3b82f6;border-radius:0}
.tabs button:hover{color:#fff}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.toolbar input,.toolbar select{width:auto;margin:0}
.toolbar .grow{flex:1;min-width:180px}
pre{background:#020617;color:#e5e7eb;padding:10px;border-radius:8px;overflow:auto;font-size:12px}
.hidden{display:none}
code{background:#1e293b;padding:1px 5px;border-radius:4px;font-size:12px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.machine-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px}
.machine-cards .card{margin:0}
.ok{color:var(--green)}.bad{color:var(--red)}.warn{color:var(--amber)}
.scrollx{overflow-x:auto}
@media (max-width:1200px){.cards{grid-template-columns:repeat(4,1fr)}}
@media (max-width:760px){.cards{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <div>
    <h1><img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAIAAABt+uBvAAAhPElEQVR42s19aZRl1XXet/e5976hqrqqq+cZegAaaBBCgBgkLSQrimWEFVuDJVvySqQkdryWpziOHSdZXhnseK3YS/mTwfGyLeMIQyRZeEkkCmJoAWaSJRpBAz1Az3N1V9fwpnvO/vLj3Hvfq+pGkqtF4VrvR1e/+4a7zx6+/e2hZGzVjfhb/pD8Qa4CAMgbPi8ECMr3ugaEAJTyH+i/pxDE93ktCAiEIgKCFBH5295sgjfrR974ngkAVMj3vkMA0hcKK6ETkEJqP8AXkEu7jTdPQBc9Ty2/tLBQjUsRukAMUFE1UgiZr9sCoPgvyt9lARFipdlJYVhEXx0WrqaCWubj3fsAT5AXkSMX/gmuPrz2zRdQdDR6EUWQufcjBrHy+u/3o2CS9JaMurtuw3CDJ8+KBeH3MqwF+CDFW/MjxYM615UIKNEy3uh1ohAVEGGWoSvZ+zaM/8Hv1n/8gwTEuVLog4Hi764PGgxk3yP0yNxXyNwYB5TBhwb2GHISSEZ09Kb6sh9p4Ceun339G90vPaCiDLkU/vuH4qAX1UmXnrKQ0YBNUecKq4xxIERExHILXYOINiVbmzQ2JiPbayM7hmqre90VO9qjW5oP/ok9t1cBMSvlW70tL1FSiyigQikUwv4hU0v/rfN8qqhaz3zPaqvckmvqw9c0GpuybKUkIwkQQq83u/SWztjNowcfmHrpGKe9DoFVNCgE/RZrUP9wROSN0aOVnq5EMRx8LUs3NOd+ROFnQ7YmXX/XyNjN9XTcicI8mXf9TLfXXNu7/E7Uhof335fZ5OSunsIG5Kulp/8hWFmyQA87VxwXSIcXeIEBwymc0dxDFgMFIqCIIJ8Ny98ztOFTY8m4+C59y4t5JIlfcnl3xXV5Y002+XJj/9POsX0C07vbWnO0QU18azWI3w8uy4C7ra6pzKoI7aU/EitvRkCIip/xqz80suEfjoWu5dMU7VrW7I1f55ddw7SRTe6rH9np2udgNddIJh4556eYLhEa+3IppM9LV6IFm5j8ABKcd4Yy4GIGbmAg6IhKaNno27P1nx71bcIMibRX39xdcb10Z+undqXn97veDCQFalKTzuHexGOzSVNpKLxb4Z6l7+8vTUzJJTgg+T5Bff6V7COgQmtQ5KJl2kEz1Ln240tJYeiF4eWtzXeBHDrwSDL1uhjEZdA6SBgT5w7+77P5+ZAMKW3gQwWADaTBXPQoVvgguUicukjKM1dkEubCQi2im0BEfcuP3txobqn72XY+fllr20+6k88OH35SSWgGVzp5b7XR5OTXps88PpsOOVqRA4sIGcMCIOhjCr4FPkjekJe4qA0WPnguJupHtygpMMjYtQ1o3htb39n6DxoHHszOvCSuEQOfADAyMBt1555tH7pnMq0nZEkPDGb8/c/iYFq7gHvVH4b/oegAuSC8SB4fgwsxkGcN+lFAjAiaarbaWdpsb7m7dvih2qndok0hi1s3AMjGkrOPd/b/lwmBQAkEAAIVzPkSxakUhmwLTlkX6oOk8q8ESFZfTSAg5YKQxjlgOqp/FXHE+vlnFjob70ynDjZOvsCkGfGEGZ2KDMG3ePTPp44/MC1OJQVCQaEwogOIiJIFXCQHYZFBdAHO6BJNzEQE0fKjxDgYlQZhDudYH0WUoJaXCwRQNQmt+up0aM3Iq/dRajATARIkNWWX55/tHv3iZGuPT4YVEhEowUI9CZN+xi6gEFZhUZHFdtIDxkZU5GYplsH4zb6CDNgko08VMmqdqjTqfshPj+5YxdNJveOaNTXPHjonw8Su2YknZ1uv9iBIRhwtGp3MAaIRVAkHfpc5oFEWYmWXkmrEYBbjswwqi4gCVnzFSjpUCiGgqgjViahCYJRA+DTLl4/pDVvlur/Xm37m7NEmD06Hg63Ogbx1IO9MeKi5IaWBxhLIm2AeW8JShTnXwwphwkUzscp2JBo2C61hYSwk52IQEgoFVUWRJGLQ2aB5rlBJUhlp6tIVQ+HKFfqrP9/cfMXky83Wg891XjzbOZkjBNR0aCzL1JBbMFqUqEXcPaC5hTvjXP2t9EnmRdE31QdJP3JXxlUpUT/JIgBSGSkuhyR1rSDdXLOm275Jbtqa3HS5u3qNrh9z9dF6d0X2+2tm7gc+uJm/+msj/ljr+FH3/EH/1L7w7dfCsdMBZiMJ0zR4b/BmVkpDWEENEQVA2hzrk4XjaVlI2Qc2mH9LX2U4ICNBjM+q4jRJdDaga27TuuSjt9Y/cqPcsJ5Z0yAOnggwpK3a0KGxy/9o/Uc+ffyr2yf31PIZoAdn8Dh5Th59Jdz/jD3yoj8/GUYyS2A+DzBqIPqp/KCAymgAgRbptPztYc3CBVTIpv9t5tXOHB1EoYmaS6d6evn65Jc/WPuZmzE+Dnigx2AkNSapFPEu6dVH7t/4E3cff2jpzFEESjBGhJMaMsDk5SPy3x4Nn38sn5ryS7MQck+jBBMDREVIWoz3lUsqfyW5EAEtiLTngLFJVY0TERURUChCp3CS1tJppszcL91V+/zP1e7cIQ0ybwO+uFoFKpE4REKvlBdHrrr23CvNfEoA1fgsGMRywHPlmP3ojfix67Oj52XXYcsSTVxJkRnmqpIMkLVafdlFEVBl0lJ5yBhBNX4NOieJpvXkbJ7u2JLe94vZZ9+XNEnfIgBVuAsKDMWJS/LS6FVXTe2t5TMCrbyvCDTSr0GsgzXj+MTtyapl2cOvsN2TRkor+CW9gN9WQCvCatGqGoQQIqAWacAAr0BHceKy5Gw3+egdyc5/nd1+hfgpMiBxfW272LsSAhWV+OYXy29UxKmELkI7/PwH8NBv1C9bk076NK0l4pQuOuR5jAIJg4QLcqA3T0CUC5j2Ipc3BZxqpud67pc+lN7/i9loamFWElfcssTC4RuqppSiEci85LYInhSoQlXy87h5Gx/7t413XJlN9JI0dRLVpf8yIayIttSFFVcvIVllRTkXgZZKOE2zdDJ3//zu9HM/m4aOWRDnUAbkwg7lDTwbCVfEGyuIkeqFwhIIF5qQJshbsmaJf/BfZDddVTuXuyR1dFLyuix54dJNL6IGocA+BU6zCMPoNM2Ssz330+9O/vOnU9+isvwAElbBy4v1HZSsttDAEiiwJE8jziopNo3aRaTK0JVlw+GBX8m2bEinLUkSRy18kWjpdKI6yqJp0GAkE4vOgw5J5qZCctP27A//ccO6lCqIwCBCFdAPlGXKNG3OwRaCKQ0Zc7gRcXOLBTRAFb4ta8bz+34hawwnuTpxSlX8oG06b4qJsQ9ei2BIdc6Lawzrn3ym1kxpXpwAJkbAer+6/dd+9vp/R7GSiyjzfypssEbCMnGxytuaKEL70RW3vPum/7F/eAOsx76rF4LOST4rN1zJ3/9kfSZPXOpiWhNlRBpJEgsT1yXU5ksrIBROXZbO9JLfvDu9ZqvlLbriPosguzKfXufPC2xO286APy7erB8Q57HaqNOPi29ar2IOicgFAEDi1E/JZ+/Uu27JJntJ4YwuXoxbDKAYw3y0EUUiLnUtJtdsTf/oM5nmdFKSMtFImK+19g0zr43PHINLqqy6qgdVvAiSdM/Y1VumXq2FdqEfEDFAdaWf2W5TV0y8AI3hTWLIi2EvZsqa8B2bsnueDj6nwkBIpTaywFRjoRpUhQohRMS5LuTXP5g2hkhfOcO+GXa0PqtNyGATDHFBrYMVrOo3wVhUl1ySjmbUZE5RZODmnYhv84pN/p/cmc70NE0UWuSpP1Cp6s3ipEXU6UxIrt6oP/F2sRadDhDDRbyTBHA0yiDFFfMjQgYqicWba8kESlHWBpz1CqVlJDAJGmLazAJdiQjb+OX3y+qVSZfRW1eH5RYRBw32CKiqai/gp25NGiMSvJbkXuEZo5hySaAipEEiS8qSMgZJWIGCQGeIryPjlTARCfnJoQ0ekOALihZCVa+Jd6lp1ChVUd/DmjXy8VuzmVyTxIkOlLYXL4qhAKYUQJgDjWH58NsSdKlRMggwggaSIZC6onXktdFtM42VzndJgAZj8SBhpBnMzEzj+xvisyTUd48svXbP+HU3Ht9JmJCgGdBNanmtGbJGL2mYOhKkiZBd/OxtrjGceChUypDHxRRQnw52qi2v121Mrl4LdoJjEKMYhTGpFwWBZOX0oRtOPPXI+ruma0s19GAijNdEGQFGGsREYMIQ/auQGnpHRq98efnb7zj44EjnHKAxfHnNOrXhv1z/od/d9guvj15O50SoZgmCdMINm8KtV7npkKirBLRAJVoooxjzAFVxEnxy82XiUvquFA6ogL+RWVcCprUN514B7ZFNd7/34AMj7XPmMrXAuS6tNEuBwAQabKqx4qXl77zj4F81e1OmacEjiEBkorbsj9d+fK80jtTX3HnuWy5YzXJYHoItGU43/uhrePEpCSJOYVywBi2UtKeDGEQgCie3bxGYFzLWo0qwN5C5mxFuw8QLSv/Yxh9/3+tfbnbOmqtLDFICYaxwMDFzDOUNWSsdG86nhrrngqsVWQgsQLPQOp8tXRPONTn9I+eevPXUt1yvk9GDZobGeR1e2vpSXUIrAXpzu00Wq6oRw08w1JtuzcbhduI6NTitqHOyYD8LGGhmlGXL2xNXTL78wPbPfvDVz4+2T3nNhEGhRPTQ3V5SbyVDQ+2TTIaAAPNEAhGYL6O+Jr51aOn2l8Zu+M19fzCUzy5rnam3p5K8VWWnmMWtS92Vq3XXHmmqmKjQdFE1KPJzEG9YMp6dvfy6Z8aW5EGlwIgCQEUjyotUXoRyEFcLndTn/3fbp390z+eXtE95VyOLdEND720nHn9yw93v3/+FZmeCUrRURdQsNIM66x1ZctWzq3/kg/vvH+2d9ZKIBQQfkBZ9HUAwZHV923p+61VxLqo6uKA4nyxUfaLx0IAx67z3zFMjUwwmAitLzewTniVeFkGMNGloHVm6/bHNH71z/30j7dMhyWAGwCTbdGYXRB/e/In37v/z4dYpwll05KqEiPmzzbXPrX//e1//8njruE/qKb3A0G/jqMrZeNtGhUROkbQFxqOFAUUrkycEouGs7gwWhF5oYia0IhiZwUzMxEzpxYIwOAte6uvPvHTjoa8/fPnHzjdXutAFEqEK4ZOhTaefv/7Yww9v+5lWfTzJu6oqKMrr6ntnGuvXzhwenznstebMlBbRohQPEYoQyHn1KnWpGFVEFr+BylgyX06hFSiUqDoXps6sWJ84eZNrY93Z3QB2XvaRd79+/9jsGe+yWCgKSXPT6V0isnPzx7edeT4JXZYFCpBiPSEJBc3mfkz5uYQAARuW+tEGejMx5SC5EEJo4dl8+WliIj5mi6SZATSLFEOsCLHKbhmrrkV52Hquse7Mizccfmjn5k9ONVckoRtUjYRZng5vPPXd649/88nNH+4kNbGeRRwe3UzMQgmSJdgkSYvERhSSx4phjA9LoIguXIMuhe4AIJrqTNqclSykqVdn0EAxAUVMIiEMgwRJoEqV4NIigSTFQjdpbji7+8ZDX31088cm6yvSvBNxNc06rrF2Yvd79t57Ynjj+caqNHTLmbHCl5V8mFnECnMIKwbjcIalQ/CsUjwuahQDjOLccOPM2PjD45vejSPLzh1LQw4ExNyqIgNV88wdGdtCYOXM0Yh0CvKUlifN9WdfArFz2yfes+8vxlonc1dTmoB50rzs9PNp6D2x5RO37/nCku7ZUnHZH7EjFBQZaDUp8jskjmN1eoqoDpbMFklAsWcFidr77vjsTf/0A9PP/6NTj9Y7rSyEmIOj6N1JfJLN1Ifv2/CTQvzO3/za8u6RihkTABZ6bmj92ZcE8sSWT9y+9wtj7ZNeawqjhZ421p150Uv21GV3v3fPPTXrFuk8GclKYcmHSSkzK+hWShiuF+iVWGCH0CVoUJFLkVOzjfbU+vz0ePtU2ummwQRQBFgczZHgXN2WrJ89dHx44/Ell609uy9nqiWoI6HCnhteN/EiyG9u/ti799+3tH0qd1mEQLk21kzsfmXZje10tNadojHEPFatzwgAQp+ar7oTzSABDZcVZ7X4GkQKvM96+eRXn/n7ycH/9K7jPHWq7nuIXRfREYuAwVR7teGtZ19sZ0PfWXvn3hVvv+LoU103pGBkBEgKQ1eH1k28RLNvbv2pd+27d7x1sucaSpDBayoiEaVTJEhaYKPonkU19Nq10ZPjWxXFp9O4pGnd0dOKifkltjdfQAJQxGAis+00n9j78Ey+PaSUjmTQomcMg2ywt8bUxAhPvmfyxJPbPuZCvuX4c91kSEqqmKQgdFxz7cRuAo9v++S79tw7Nnsyd/XI7joRWoDRymhupNAIdaE7Ux9/7rK7hvKpLPRiRmIhhHroplMxiReoLLqTJongfVPar+wPLx+0mzZaOxet+pVZVOpBiAWApmi2z7775Xsev+qnA3XbiWe6rqlk2XMFYegljfVnXhLKE1s/efve/zU2eyJISmEI3oIHTSxo8CRj2E9CbyYbe3rLh6889vjlZ75rmsaGe5LalOaphjHO33HRwzwgJI0O1pkJX/su4WjGMoZEGytmbRFZjECPNOvNvuuVe19fddO+NbfXfNtiG16FlIJ1XHPdmRdvPPBXj2/9+GR9hZoHpKIKFHCFn0bq/Ux9+TPbfvLqozsvO/1Sx43kWutqrSdZT2u0bLIjGrEXFigjXTAEqvjyEEKm9pUXXGcWQ+imoZuFbup7Gb3S5tHmQgbJss70Hbvv2b/ixr2rbq6HGSsjTNQjpXWS5rpT31k7uefw8h1J6LA/t4Cq8diZnW8sf3rL3VcfeWzjmZe7yZDQYLGSQYX53M63LRmsJi0iYcaqAkRjM7MXDtvnD6358LtWTsxapjZZH39w84fv3vMXO448kbuacKAJnsFrmnan79j9J09s/zQQth17ppMOx4GLEv4xSFbvzVIkFNWOgiEqgDIJ+pc2vm/ziW+tO/1iuzYqRZwqkh4VtnM931KFv5QS68KS1b5SKE2M8JYifO5RTrYsFbNAoeSSGpwWpKqBAWYxX1ULJmmtN3PH7nv2r7xl36pb6r0ZQoRW6ZKC0FgCCCx5a5pJUSyxIE4hS1sn86SuoZvl7ciCxwTECc61MNmiK6oEsrCqRrIg+QycKABjsDDk9JVvn/z6l4/84vt6vWlJHG449HCgdrWm5TiFoBhais3nhqzWnblt9z1PX/MzKtx8/Nk8bYpZ3CYBCi1I2RETkZ5UvccGUSEZJHXAgeU7Tg2v3nH0qSxvxzqiKo+dx2TL6rG0Ri4s0i9Eg2iDbQUQUozm/VDCf/dwY+/ppmu4jiS5iZFigSRNGOsRAExIoxnN5+LqnZnbdn9h7+qb9615R9qbNghpMQkFYuUexiIaxiKsFHkwaUF9b7Y+/qe3/NYf3Pg7T235UBJ6BpgZNOw/g043inHhywUWXNWY4/fESGON+cQ5/1sPpk4goUgJol+JJb74CGSVdAsZNMla52578Z7XV71z39rbsrwVg3QEPALQCFJpBfo0ChlYzIiRQJ7Xu1NNtrN8Kr5xIAHsPiEIZGF3uohOuj8yy361PlguWJr5Lz4nX9mRfPjaTrdFVwzgGOOMgJC0oEnQbKChwIIm9e70O7/7+aeu/RTNthx7ppMOEWQw0EgTIy3QYknNaAEMIJ0IxQ3NnvrId/7rgVXXvXPfV3NNQFMBvTx/LKoPhYPfeZGQ9AWpjcVhLktpv72zcdWtV2DZkEgkHwWiUS+8y5ZNHVp59lWvNSltFWAQrfWmb/3unz6341Nqtv7k84j1RZiwH9oQrGgcYnTesRHAhtpnV08edHkeXGZk6nBqWl85obXEM1TNNovaQCXzVv+IUAwh2LCGXYfk3m9zRTKrnZm0O511Z7PuTNaZSttTQ61zr62//fCK67PQVvMRJcSHl7Tenbl2z1cOrbo+iBMzqcI+CwIoWo8WZD4RLDpvqgvijGJGC0yd7ToqR86iJiVIxGLioKo5aHAQDBpdTmCoddoPfGXfr6+d3iTlKFlRZ4eSy8+88tc7fvobV37q9tf/8opDT+Sali1l5iVJ8q7rzQZJSBPAGCfyowtRg1gIIVKWKkKxEIwATejJYHSBFOXjr7m8a5oFMwrfAkaRA2Kq/oMIRo+mC7uOugf3D6XNWkdruav1tJ4nDZ80OtnISPv06PTRb6x//8urb3GWzyVqDBCRtJpH0xjVKbDo9iNACKCHGZgLAmnCEOfCASSKdpsPvYpUzazydItaWY24JpSNQlKutYl6YDBIsC/uSj+6I1dSyn0uAih9Lx269sjjv+F/Zd3pV7zLZN4kQzGVy4pNLcoBjL5ZRNRB42VaEGagWTHPaxhOw7NHsheOuqbLzbPkYxe59NxPjeaulABgNGPDhSf265Gzbs2w71q/wSI2b9Q6U2/b93+CZiZOWfb9IPpzaJVaFqjJhERRp6UFI00oSlGz2FAT20WUIqCm+uCeWrtjjcR8Oe8KAnALsLOFtr/0dWf+QKGAZqyJnTjHZw+rS5lbhXxY/lO7yZCXJDJ90YhIGI2MykIzQ9ESHCNC5PIp8bmINENRjIcFwAKROJ6fkS/uQk0tBIv1yPJOFy+bv3Ax0gVFM9I8nz1YxJoYqQp7KbqBAmgwo1n5fGwasviISLlw0VEENCGVjMMXRggiUKJQlfCGRsqvvpy8clyaLphZ/+z6nbmLZ2IYmA6bA6+FoFGFu0/AfNzSV7nKflgTIJQuNDbCuHiJBZoBpoUIWDRcxWstKD1FQKpZ8akM8D4Bu7n80XOZi0jS2K/Hl9OQi0N3VOIYjPcDnohCigOPT2sn10RYRph+1aYYEpI55ypGGMsGqrJvwYyMYzMCQmmwgGAQiAWYKUVJeN/M/FderT++H0tcbh7KubkRF4IVLxEozs0/ONjLZYnwfAuzXcZ5Pw64XilpCRQ+qd+zSFJhKiCFIdD7fstmWa2VkMdDUpqY0QgztW43l889nsEbDLTB0Wzpn+iiRrGq6NLf2tFfICAKH9gLlV1ZaWd6AcgsXmuEQST46IUZvNJACQYEjxBif6KLNQNSGESUQAi2rObvfaH+zX0ylvqQRxIq1gvlUnZO/jB80OAp9ZNYkhShihXGUhTXAVhR9mA1kWPVTbjgtYCGcIK4EUAFDqHQCpqFUMzDBs/gaag5Hp1xv7Mzq8MYDIFCE1WyKrHIwhL6SyDtB6N7f9ai2N0T/XLNoe5gZiV7LyBUKLFZNdIXLKsQIs53Z4ZXmKoLPQIqJW40K9pnLUix48RAqOVgHshx1/3cY37vKVdXbz5G97mhY6GjCMkPSX1Y7d4SKYakgsmyIdYdfWC5bAqgxNyp38RIgdBEE9+dGN10ePX12w48WvRZh5hPwGK3EcRI+jxWU8yCMYSAkaZ85Tud+752YsyFkFtRIyk7JNnv6KfEDTtvPifNsj1hTlRDv8uLAD25YUmoJwzlgLsaNLIzxfAgQRHSKC7vnBtZd3DTbdv2PjRy/iShYmCI5BqUoiFHCIATisS6mIEeTWeHzye//NVa0u4geAlW0ACDkK16LCrdIfMzwNhiwXJRBinbV4bYKD0nHSI04r3IE4okvntuePXr62/Zuu//jbQmfFKP5+4QS22x9OgL30+K90IYJQt5MH7mLxuHz6DhvAVG6Mz5maMtLh/EAY8sVfsNB+hFoag6XLMSCFLNqVpUvBjeC9Qs6rtTI6uOrr9p62sPj0yfDC6LJDIpsQQiBM3UgpAkJeQaP4JhWcP/y0eWPPRystR5n1sBNweWnsjgJObiNZJDQYs9mkUyWHYrFNt7BMEw1uCVy733wYnEopX0VQ+gUFQsnxpedWTdOy4/+ORIa8Kn9bK8pQDEPErGX0MPDApzoNIbMd7gbz5w6o+f5Hgt5J4IccpFqvUhxeg8Ksp+scN8xG0Dq6WkbH8T9IJcvoTrRkO3qGRJf0ixXEOqwU8PrTi29rpNh/56ePa0T+rVMKYoIaZksTMJdMELLbostTA6JP9+55Lfe6i1NAnBM7aKVpGUhTO0uckQF2v7i1SlYOFc7FM2ftAHrhlmM7FuKObfylU5Zfu9Wbs+cmLNNeuO/M3Q7JngGsKC2o+LhQDV0JNyNDFOK3rCMYzW8W++MfwfdqZjiTcfLHBQOv3vQ4WaQBkzNupi5WJVOkW5IIrFMxcSjZo5Jb1Chagyo2I2TCzMjKwanj61ZPpUSBtxfwcHGV1wdngZQ74SBoiGkAcZS9Wz88++nN/3aG0s8ZYbLaasg9tgWVYYBVQOdE4vWm1+Xi42sGszblsiRDDbdcEqKpEmsXOoYNEJSPCOYi6jStkjx2K+0ozOff22X0o701sPPG2B5sOKhh04Vf+5e8PD+84sTS14YzC1cg9X/KjqzDj4qyzUwn5omzg5eHhmzJztP5ucaydLaqE3sKxLqn1e8XzFyrlgg2hgtXMHNLvzqf8OWo+u4WxFw//FM81/9YAdmZTxpOtzo5kaL0Zvxrqlzv1bCotc1fheqDqAqCU8cIbffN199Hrfbknqyp48lrEPjGVEqTbtcNC+JMBd8erXG6m4JfXdJ/W3H5n40jNpvdcdS/I8p1h04UWoij2b89cryLx1c4vmpH8ArloCE7Hfeyz7wFWhmYS2F+eqnD9WteIEjlaLXyoQZQYRNFJkQ/WD55I/fHjofz7tzkzPjKaBNJ/HaQdU0gErRk7jmASoxMD8SrH+U99CDZrfPRSMQ4l9+7D7zP31P/tEd6zup7px0KWI24UlWaFJnsW+n5pjvU7A7T6V/tl3kj9/Pj06IcOpjSXmc0OpOP2dSQVM1UJIhR5BxGglFdMPo1isMF8t15yXiPWVm8FzLLMv7dLTreZ//ED31o1ddcgDgjGYwBATpMRJlkjiCIV5OTyd7nzdfe3l9NHX0tPnw1ASltbMPEMovNVcvFoubxX2KZQ4V9T31nIpy27lkv90TVHVkLhOCNXO1iInSlI37TVL5L1Xhh/bLm9ba2tH8pGMqeRTo+u8ueTMsVNtd+Cc++4JffqAPH8yOzoJhDBSQ4pgxmAUg9jAztaYl1P6BGXZeVTMscWnys2oUq1ZE3krBFT1e1DneMQSOkuiVJ3uqYkbqWFpk6MNNlP4Rr0dtDXZOd+S6Q58oIKNJGQONDLExhdD2RlSgay5Rd2B4IXyr7OU/V3lzrfKnS+eBnH+0ugCXusFT1ls+FIRcQhEbhpiRwqoIqJIhE4YC2oWE2+LalJM519wbxftpyuHEqrFsvJWLv2X+ZkHL2Bd+2euIC0AgRCkYmm1jQpkKCtpcXnCYNV/zh0q+npE4MK/QME32IReJa6LJqB5C7cv2NTS3zIR085BoyQHQCXns0n9tUR9HCzK/rLjAovHv0Iy55D6pEv5lwMGvcGCrez/A4AkO9KgTqnbAAAAAElFTkSuQmCC" alt="Mango" width="32" height="32"> Mango Server — Quản lý máy</h1>
    <div class="sub">Theo dõi realtime PC client · Ping / SSH / RDP · <span id="subStats">—</span></div>
  </div>
  <div class="right">
    <span class="clock" id="clock">—</span>
    <button class="primary" onclick="doScanNow()">Quét ngay</button>
    <button onclick="showTab('enroll')">+ Thêm máy</button>
    <button onclick="showTab('config')">Cài đặt</button>
    <button onclick="doLogout()">Đăng xuất</button>
  </div>
</header>
<main>
<div id="loginBox" class="card hidden">
  <h2>Đăng nhập quản trị</h2>
  <p class="muted">Nhập mật khẩu quản trị Server (Quản trị viên đặt lúc cài Server).</p>
  <input id="pw" type="password" placeholder="Mật khẩu quản trị" onkeydown="if(event.key==='Enter')doLogin()">
  <button class="primary" onclick="doLogin()">Đăng nhập</button>
  <p id="loginErr" style="color:#fca5a5"></p>
</div>
<div id="app" class="hidden">
  <div class="cards" id="overviewCards">
    <div class="card"><div class="big" id="vTotal">—</div><div class="lbl">Tổng máy</div></div>
    <div class="card"><div class="big ok" id="vOnline">—</div><div class="lbl">Đang bật</div></div>
    <div class="card"><div class="big bad" id="vOffline">—</div><div class="lbl">Offline</div></div>
    <div class="card"><div class="big" id="vSsh">—</div><div class="lbl">SSH 22 mở</div></div>
    <div class="card"><div class="big" id="vRdp">—</div><div class="lbl">RDP 3389 mở</div></div>
    <div class="card"><div class="big" style="font-size:17px" id="vLastScan">—</div><div class="lbl">Lần quét cuối</div></div>
    <div class="card"><div class="big" style="font-size:17px" id="vHistory">—</div><div class="lbl">Lịch sử quét</div></div>
  </div>

  <div class="toolbar card">
    <input id="q" class="grow" placeholder="Tìm tên / IP..." oninput="renderTable()">
    <select id="fStatus" onchange="renderTable()">
      <option value="all">Tất cả</option>
      <option value="online">Đang bật</option>
      <option value="offline">Offline</option>
      <option value="pending">Chờ duyệt</option>
    </select>
    <span class="muted" id="refreshNote">Tự làm mới mỗi 10 giây</span>
    <button id="viewTableBtn" class="active" onclick="setView('table')">Bảng</button>
    <button id="viewCardsBtn" onclick="setView('cards')">Thẻ</button>
    <span class="muted" id="updatedAt"></span>
  </div>

  <div class="tabs card" style="padding:4px 10px">
    <button data-tab="dashboard" class="active" onclick="showTab('dashboard')">Dashboard</button>
    <button data-tab="report" onclick="showTab('report')">Báo cáo</button>
    <button data-tab="logs" onclick="showTab('logs')">Logs máy</button>
    <button data-tab="audit" onclick="showTab('audit')">Nhật ký thao tác</button>
    <button data-tab="enroll" onclick="showTab('enroll')">Mã đăng ký</button>
    <button data-tab="tokens" onclick="showTab('tokens')">Token Agent</button>
    <button data-tab="config" onclick="showTab('config')">Cấu hình</button>
  </div>

  <div id="tab-dashboard">
    <div id="tableWrap" class="card scrollx" style="padding:6px 10px">
      <table>
        <thead><tr>
          <th>#</th><th>Máy</th><th>IP</th><th>Trạng thái</th><th>Ping</th><th>SSH</th><th>RDP</th>
          <th>CPU</th><th>RAM</th><th>GPU</th><th>Ổ đĩa</th>
        </tr></thead>
        <tbody id="machineRows"><tr><td colspan="11" class="muted">Đang tải...</td></tr></tbody>
      </table>
    </div>
    <div id="cardsWrap" class="machine-cards hidden"></div>
    <div id="machineDetail" class="card hidden"></div>
  </div>

  <div id="tab-report" class="card hidden"><h2>Báo cáo</h2><div id="reportBody" class="muted">Chưa có dữ liệu.</div></div>

  <div id="tab-logs" class="card hidden">
    <h2>Logs máy</h2>
    <select id="logMachine" onchange="loadMachineLogs()"></select>
    <button onclick="loadMachineLogs()">Tải lại</button>
    <pre id="logList">Chọn máy để xem log.</pre>
  </div>

  <div id="tab-audit" class="card hidden">
    <h2>Nhật ký thao tác (chỉ metadata, không ghi tham số đầy đủ)</h2>
    <button onclick="loadAudit()">Tải lại</button>
    <pre id="auditOut"></pre>
  </div>

  <div id="tab-enroll" class="card hidden">
    <h2>Mã đăng ký (dùng 1 lần)</h2>
    <p class="muted" id="enrollTtlNote">Hạn mã đăng ký: xem ở tab Cấu hình.</p>
    <input id="enrollLabel" placeholder="Ghi chú (vd: may-01)">
    <button class="primary" onclick="createEnroll()">Tạo mã mới</button>
    <pre id="enrollOut" class="hidden"></pre>
    <div id="enrollList"></div>
  </div>

  <div id="tab-tokens" class="card hidden">
    <h2>Token Agent</h2>
    <input id="tokName" placeholder="Tên Agent (vd: Muse)">
    <input id="tokMachines" placeholder="Máy được chạm: * hoặc machine_id, cách nhau bằng dấu phẩy">
    <input id="tokGroups" placeholder="Nhóm tool: read,control,files,admin (cách nhau bằng dấu phẩy)">
    <button class="primary" onclick="createToken()">Tạo token mới</button>
    <pre id="tokOut" class="hidden"></pre>
    <div id="tokList"></div>
  </div>

  <div id="tab-config" class="card hidden">
    <h2>Cấu hình Server</h2>
    <h3>Thông tin Server (chỉ xem)</h3>
    <pre id="configOut"></pre>
    <h3>Hạn mã đăng ký</h3>
    <p class="muted">Mã đăng ký hết hạn sau số giây này (60..2592000, mặc định 86400 = 24 giờ).</p>
    <input id="ttlSeconds" type="number" placeholder="Số giây (vd: 86400)">
    <button class="primary" onclick="setTtl()">Đổi hạn mã đăng ký</button>
    <h3>Đổi mật khẩu quản trị</h3>
    <input id="pwCurrent" type="password" placeholder="Mật khẩu hiện tại">
    <input id="pwNew1" type="password" placeholder="Mật khẩu mới (tối thiểu 4 ký tự)">
    <input id="pwNew2" type="password" placeholder="Nhập lại mật khẩu mới">
    <button class="primary" onclick="changePassword()">Đổi mật khẩu</button>
    <p id="configMsg" style="color:#fca5a5"></p>
    <h3>Gói Client (nâng cấp từ xa)</h3>
    <p class="muted">Upload file zip gói client rồi bấm "Nâng cấp" trong chi tiết máy.</p>
    <input id="pkgVersion" placeholder="Phiên bản (vd: 2.1.4)">
    <input id="pkgNote" placeholder="Ghi chú (không bắt buộc)">
    <label><input id="pkgRestart" type="checkbox" style="width:auto"> Cần khởi động lại máy sau khi nâng cấp</label>
    <input id="pkgFile" type="file" accept=".zip">
    <button class="primary" onclick="uploadPackage()">Upload gói</button>
    <div id="pkgList"></div>
  </div>
</div>
</main>
<script>
let OV=null, VIEW='table', REFRESH_TIMER=null;
async function api(path, opts={}){
  const r = await fetch(path, {headers:{'Content-Type':'application/json'}, ...opts});
  const t = await r.json().catch(()=>({}));
  if(r.status===401){ showLogin(); throw new Error('Chưa đăng nhập'); }
  if(!r.ok) throw new Error(t.error||('HTTP '+r.status));
  return t;
}
function showLogin(){ document.getElementById('loginBox').classList.remove('hidden'); document.getElementById('app').classList.add('hidden'); if(REFRESH_TIMER){clearInterval(REFRESH_TIMER);REFRESH_TIMER=null;} }
function showApp(){ document.getElementById('loginBox').classList.add('hidden'); document.getElementById('app').classList.remove('hidden'); }
async function doLogin(){
  const pw=document.getElementById('pw').value;
  try{ await api('/api/login',{method:'POST',body:JSON.stringify({password:pw})}); document.getElementById('loginErr').textContent=''; showApp(); startAutoRefresh(); loadAll(); }
  catch(e){ document.getElementById('loginErr').textContent='Mật khẩu không đúng.'; }
}
async function doLogout(){ try{await api('/api/logout',{method:'POST',body:'{}'});}catch(e){} showLogin(); }
function startAutoRefresh(){ if(REFRESH_TIMER) clearInterval(REFRESH_TIMER); REFRESH_TIMER=setInterval(()=>{ loadOverview(); }, 10000); }
function tickClock(){ const d=new Date(); const p=n=>String(n).padStart(2,'0'); document.getElementById('clock').textContent=p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds())+' '+p(d.getDate())+'/'+p(d.getMonth()+1)+'/'+d.getFullYear(); }
setInterval(tickClock,1000); tickClock();
function fmtTime(ts){ if(!ts) return '—'; const d=new Date(ts*1000); const p=n=>String(n).padStart(2,'0'); return p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds())+' '+p(d.getDate())+'/'+p(d.getMonth()+1)+'/'+d.getFullYear(); }
function fmtClock(ts){ if(!ts) return '—'; const d=new Date(ts*1000); const p=n=>String(n).padStart(2,'0'); return p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds()); }
function esc(s){ return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function barCls(p){ return p>=90?'bad':(p>=70?'warn':''); }
function bar(p){ p=Math.max(0,Math.min(100,p||0)); return `<div class="bar"><i class="${barCls(p)}" style="width:${p}%"></i></div>`; }
function showTab(name){
  document.querySelectorAll('.tabs button[data-tab]').forEach(b=>b.classList.toggle('active', b.dataset.tab===name));
  ['dashboard','report','logs','audit','enroll','tokens','config'].forEach(t=>document.getElementById('tab-'+t).classList.toggle('hidden', t!==name));
  if(name==='dashboard') loadOverview();
  if(name==='report') renderReport();
  if(name==='logs') loadMachineLogs();
  if(name==='audit') loadAudit();
  if(name==='enroll') loadEnroll();
  if(name==='tokens') loadTokens();
  if(name==='config') loadConfig();
}
function loadAll(){ loadOverview(); loadEnroll(); loadTokens(); loadAudit(); loadConfig(); }
async function loadOverview(){
  try{
    const d=await api('/api/machines/overview');
    OV=d;
    const c=d.counts||{};
    document.getElementById('vTotal').textContent=c.total??'—';
    document.getElementById('vOnline').textContent=c.online??'—';
    document.getElementById('vOffline').textContent=c.offline??'—';
    document.getElementById('vSsh').textContent=c.ssh_open??'—';
    document.getElementById('vRdp').textContent=c.rdp_open??'—';
    document.getElementById('vLastScan').textContent=fmtClock(d.last_scan_at);
    document.getElementById('vHistory').textContent=(d.scan_count||0)+' lần quét';
    document.getElementById('subStats').textContent='Tổng '+(c.total||0)+' máy · '+(c.online||0)+' đang bật · '+(c.offline||0)+' offline';
    document.getElementById('updatedAt').textContent='Cập nhật: '+fmtClock(d.last_scan_at)+' · Stats: '+fmtClock(d.last_stats_at);
    renderTable();
    const sel=document.getElementById('logMachine');
    if(sel && sel.options.length===0) fillLogMachines();
  }catch(e){ /* giữ dữ liệu cũ khi lỗi mạng thoáng qua */ }
}
function filteredMachines(){
  if(!OV) return [];
  const q=(document.getElementById('q').value||'').toLowerCase();
  const f=document.getElementById('fStatus').value;
  return (OV.machines||[]).filter(m=>{
    if(f==='online' && !m.online) return false;
    if(f==='offline' && m.online) return false;
    if(f==='pending' && m.status!=='pending') return false;
    if(q){
      const s=((m.name||'')+' '+(m.machine_id||'')+' '+(m.last_ip||'')+' '+((m.stats&&m.stats.hostname)||'')).toLowerCase();
      if(!s.includes(q)) return false;
    }
    return true;
  });
}
function cpuCell(m){
  const s=m.stats;
  if(!s) return '<span class="muted">—</span>';
  const pct=(s.cpu_percent??null);
  const model=s.cpu_model||s.cpu||'';
  const cores=s.cpu_cores||s.cpu_logical||'';
  const ghz=s.cpu_ghz? (Number(s.cpu_ghz).toFixed(1)+' GHz') : '';
  const sub=[model, cores? (cores+' nhân'):'', ghz].filter(Boolean).join(' · ');
  return `<b>${pct===null||pct===undefined?'—':Number(pct).toFixed(0)+'%'}</b>${pct!==null&&pct!==undefined?bar(pct):''}<div class="small">${esc(sub)||'—'}</div>`;
}
function ramCell(m){
  const s=m.stats;
  if(!s || s.memory_total_gb===undefined) return '<span class="muted">—</span>';
  const total=Number(s.memory_total_gb||0);
  const pct=s.memory_used_percent!==undefined? Number(s.memory_used_percent) : 0;
  const used=(s.memory_used_gb!==undefined)? Number(s.memory_used_gb||0) : (total*pct/100);
  let detail='';
  if(Array.isArray(s.memory_detail) && s.memory_detail.length){
    const kinds={};
    s.memory_detail.forEach(d=>{ const k=(d.type||'RAM')+'-'+(d.speed_mhz||'?'); kinds[k]=(kinds[k]||0)+1; });
    detail=Object.entries(kinds).map(([k,n])=>k+' · '+n+' thanh').join('; ');
  }
  return `<b>${used.toFixed(1)} / ${total.toFixed(1)} GB</b>${bar(pct)}<div class="small">${esc(detail)||'—'}</div>`;
}
function gpuCell(m){
  const s=m.stats;
  if(!s || !Array.isArray(s.gpu) || !s.gpu.length) return '<span class="muted">—</span>';
  return s.gpu.map(g=>{
    const pct=g.usage_percent;
    const vram=g.vram_gb? ('VRAM '+Number(g.vram_gb).toFixed(1)+' GB') : '';
    const temp=g.temperature_c!==null&&g.temperature_c!==undefined? (Number(g.temperature_c).toFixed(0)+'°C') : '';
    const pw=g.power_w!==null&&g.power_w!==undefined? (Number(g.power_w).toFixed(1)+' W') : '';
    const sub=[g.driver_version?('drv '+g.driver_version):'', vram, temp, pw].filter(Boolean).join(' · ');
    return `<b>${pct===null||pct===undefined?'—':Number(pct).toFixed(0)+'%'}</b>${pct!==null&&pct!==undefined?bar(pct):''}<div class="small">${esc(g.name||'')}${sub?' · '+esc(sub):''}</div>`;
  }).join('');
}
function diskCell(m){
  const s=m.stats;
  if(!s || !Array.isArray(s.disks) || !s.disks.length) return '<span class="muted">—</span>';
  return s.disks.map(d=>{
    const label=(d.mountpoint||d.device||'').replace('\\','');
    return `<div><b>${esc(label)}: ${Number(d.used_gb||0).toFixed(0)}/${Number(d.total_gb||0).toFixed(0)} GB (${Number(d.used_percent||0).toFixed(0)}%)</b>${bar(d.used_percent||0)}</div>`;
  }).join('');
}
function machineNameCell(m){
  const s=m.stats||{};
  const sub=[s.hostname||'', s.user||''].filter(Boolean).join(' · ');
  return `<b>${esc(m.name||m.machine_id)}</b><div class="small">${esc(sub)}${m.client_version?' · v'+esc(m.client_version):''}</div>`;
}
function renderTable(){
  const rows=filteredMachines();
  const tb=document.getElementById('machineRows');
  if(!rows.length){ tb.innerHTML='<tr><td colspan="11" class="muted">Không có máy nào khớp bộ lọc.</td></tr>'; }
  else{
    tb.innerHTML=rows.map((m,i)=>{
      const st=m.online?'<span class="dot on"></span>Đang bật':'<span class="dot off"></span>Offline';
      const ping=m.ping_ms===null||m.ping_ms===undefined?'<span class="muted">—</span>':('<b class="'+(m.ping_ms<50?'ok':(m.ping_ms<200?'warn':'bad'))+'">'+m.ping_ms+' ms</b>');
      return `<tr onclick="showMachine('${esc(m.machine_id)}')">
        <td>${i+1}</td><td>${machineNameCell(m)}</td><td>${esc(m.last_ip||'—')}</td>
        <td>${st}<br><span class="badge ${esc(m.status)}">${esc(m.status)}</span></td>
        <td>${ping}</td>
        <td>${m.ssh_open?'<span class="ok">Mở</span>':'<span class="muted">Đóng</span>'}</td>
        <td>${m.rdp_open?'<span class="ok">Mở</span>':'<span class="muted">Đóng</span>'}</td>
        <td>${cpuCell(m)}</td><td>${ramCell(m)}</td><td>${gpuCell(m)}</td><td>${diskCell(m)}</td>
      </tr>`;
    }).join('');
  }
  renderCardsView(rows);
}
function renderCardsView(rows){
  const w=document.getElementById('cardsWrap');
  if(VIEW!=='cards'){ return; }
  if(!rows.length){ w.innerHTML='<div class="card muted">Không có máy nào khớp bộ lọc.</div>'; return; }
  w.innerHTML=rows.map(m=>{
    const st=m.online?'<span class="dot on"></span>Đang bật':'<span class="dot off"></span>Offline';
    return `<div class="card" onclick="showMachine('${esc(m.machine_id)}')" style="cursor:pointer">
      <b>${esc(m.name||m.machine_id)}</b> <span class="badge ${esc(m.status)}">${esc(m.status)}</span>
      <div class="small">${esc(m.last_ip||'—')} · ${st} · Ping ${m.ping_ms??'—'} ms · SSH ${m.ssh_open?'Mở':'Đóng'} · RDP ${m.rdp_open?'Mở':'Đóng'}</div>
      <div style="margin-top:8px"><div class="small">CPU</div>${cpuCell(m)}</div>
      <div style="margin-top:6px"><div class="small">RAM</div>${ramCell(m)}</div>
      <div style="margin-top:6px"><div class="small">GPU</div>${gpuCell(m)}</div>
      <div style="margin-top:6px"><div class="small">Ổ đĩa</div>${diskCell(m)}</div>
    </div>`;
  }).join('');
}
function setView(v){
  VIEW=v;
  document.getElementById('viewTableBtn').classList.toggle('active', v==='table');
  document.getElementById('viewCardsBtn').classList.toggle('active', v==='cards');
  document.getElementById('tableWrap').classList.toggle('hidden', v!=='table');
  document.getElementById('cardsWrap').classList.toggle('hidden', v!=='cards');
  renderTable();
}
async function doScanNow(){
  try{ await api('/api/machines/scan-now',{method:'POST',body:'{}'}); document.getElementById('updatedAt').textContent='Đang quét...'; setTimeout(loadOverview, 4000); }
  catch(e){ alert('Lỗi: '+e.message); }
}
function renderReport(){
  const el=document.getElementById('reportBody');
  if(!OV){ el.textContent='Chưa có dữ liệu.'; return; }
  const rows=OV.machines||[];
  const totRam=rows.reduce((a,m)=>a+Number((m.stats&&m.stats.memory_total_gb)||0),0);
  const totDisk=rows.reduce((a,m)=>a+((m.stats&&m.stats.disks||[]).reduce((x,d)=>x+Number(d.total_gb||0),0)),0);
  const usedDisk=rows.reduce((a,m)=>a+((m.stats&&m.stats.disks||[]).reduce((x,d)=>x+Number(d.used_gb||0),0)),0);
  const avgCpu=rows.length? (rows.reduce((a,m)=>a+Number((m.stats&&m.stats.cpu_percent)||0),0)/rows.length):0;
  const byCpu=[...rows].sort((a,b)=>Number((b.stats&&b.stats.cpu_percent)||0)-Number((a.stats&&a.stats.cpu_percent)||0)).slice(0,5);
  const byDisk=[...rows].sort((a,b)=>{ const pa=Math.max(0,...((a.stats&&a.stats.disks||[]).map(d=>Number(d.used_percent||0)))); const pb=Math.max(0,...((b.stats&&b.stats.disks||[]).map(d=>Number(d.used_percent||0)))); return pb-pa; }).slice(0,5);
  const issues=rows.filter(m=>!m.online || ((m.stats&&m.stats.disks||[]).some(d=>Number(d.used_percent||0)>=90)) || Number((m.stats&&m.stats.cpu_percent)||0)>=90);
  el.innerHTML=`<div class="grid2">
    <div class="card"><div class="big">${rows.length}</div><div class="lbl">Tổng máy · ${(OV.counts&&OV.counts.online)||0} đang bật · ${(OV.counts&&OV.counts.offline)||0} offline</div>
    <div class="small" style="margin-top:8px">Tổng RAM: ${totRam.toFixed(1)} GB · Tổng ổ đĩa: ${totDisk.toFixed(0)} GB (đã dùng ${usedDisk.toFixed(0)} GB) · CPU trung bình: ${avgCpu.toFixed(1)}%</div></div>
    <div class="card"><div class="big" style="color:${issues.length?'#f59e0b':'#22c55e'}">${issues.length}</div><div class="lbl">Máy cần chú ý (offline / ổ đĩa ≥90% / CPU ≥90%)</div>
    <div class="small" style="margin-top:8px">${issues.length? issues.map(m=>esc(m.name||m.machine_id)).join(', ') : 'Không có.'}</div></div>
  </div>
  <div class="grid2" style="margin-top:12px">
    <div class="card"><h3>Top CPU</h3>${byCpu.map(m=>`<div>${esc(m.name||m.machine_id)} — <b>${Number((m.stats&&m.stats.cpu_percent)||0).toFixed(0)}%</b></div>`).join('')||'<div class="muted">—</div>'}</div>
    <div class="card"><h3>Top ổ đĩa đầy</h3>${byDisk.map(m=>{ const p=Math.max(0,...((m.stats&&m.stats.disks||[]).map(d=>Number(d.used_percent||0)))); return `<div>${esc(m.name||m.machine_id)} — <b>${p.toFixed(0)}%</b></div>`; }).join('')||'<div class="muted">—</div>'}</div>
  </div>
  <p class="muted">Số liệu stats cập nhật mỗi 5 phút (lần cuối: ${fmtTime(OV.last_stats_at)}); ping cập nhật mỗi 10 giây (lần cuối: ${fmtTime(OV.last_scan_at)}).</p>`;
}
function fillLogMachines(){
  const sel=document.getElementById('logMachine');
  sel.innerHTML=(OV.machines||[]).map(m=>`<option value="${esc(m.machine_id)}">${esc(m.name||m.machine_id)}</option>`).join('');
  if(sel.options.length) loadMachineLogs();
}
async function loadMachineLogs(){
  const sel=document.getElementById('logMachine');
  const id=sel.value; if(!id) return;
  try{
    const d=await api('/api/audit?limit=500');
    const rows=(d.entries||[]).filter(e=>e.machine_id===id);
    document.getElementById('logList').textContent=rows.length? rows.map(e=>JSON.stringify(e)).join('\n') : 'Chưa có log cho máy này.';
  }catch(e){ document.getElementById('logList').textContent='Lỗi: '+e.message; }
}
async function showMachine(id){
  if(!OV) return;
  const m=(OV.machines||[]).find(x=>x.machine_id===id); if(!m) return;
  const el=document.getElementById('machineDetail');
  el.classList.remove('hidden');
  el.innerHTML=`<h3>${esc(m.name)} <code>${esc(m.machine_id)}</code></h3>
  <p class="muted">Bản Client: <b>${esc(m.client_version||'(chưa báo)')}</b> • Bản MangoMCP trên máy: <b>${esc(m.version||'(chưa báo)')}</b> • Agent nối: <b>${m.agent_connected?'có':'không'}</b> • IP: ${esc(m.last_ip||'—')} • Ping: ${m.ping_ms??'—'} ms • SSH: ${m.ssh_open?'Mở':'Đóng'} • RDP: ${m.rdp_open?'Mở':'Đóng'}</p>
  <p class="muted">Stats lúc: ${fmtTime(m.stats_at)}${m.stats_error? ' • Lỗi stats: '+esc(m.stats_error):''}</p>
  <pre>${esc(JSON.stringify(m.stats||{},null,2))}</pre>
  <button onclick="machineAct('${esc(id)}','approve')">Duyệt</button>
  <button onclick="machineAct('${esc(id)}','reject')">Từ chối</button>
  <button onclick="machineAct('${esc(id)}','revoke')" class="danger">Thu hồi</button>
  <button onclick="rotateSecret('${esc(id)}')">Xoay secret</button>
  <button onclick="machineAct('${esc(id)}','delete')" class="danger">Xóa máy</button>
  <h4>Scope (scope thật: ${(m.reported_tools||[]).join(', ')||'(chưa báo)'})</h4>
  <p class="muted">Scope mong muốn (để trống = chưa đặt, dùng scope thật). Nhập JSON, vd: ["mango_status","screenshot"] — [] = cấm hết.</p>
  <textarea id="scopeInput" rows="2" placeholder='["mango_status","screenshot"]'>${esc(m.desired_scope?JSON.stringify(m.desired_scope):'')}</textarea>
  <button class="primary" onclick="setScope('${esc(id)}')">Đặt scope</button>
  <span id="scopeMsg" class="muted"></span>
  <h4>Nâng cấp client</h4>
  <p class="muted">Bản đích hiện tại: ${esc(m.target_version||'(chưa đặt)')} • Trạng thái nâng cấp: ${esc(m.upgrade_status||'(chưa có)')}</p>
  <input id="upgradeVersion" placeholder="Bản đích (để trống = mới nhất)">
  <button class="primary" onclick="doUpgrade('${esc(id)}')">Nâng cấp</button>
  <h4>Khởi động lại máy</h4>
  <input id="restartDelay" type="number" value="60" placeholder="Trễ (giây, 0..3600)">
  <button onclick="doRestart('${esc(id)}')">Khởi động lại máy</button>
  <span id="restartMsg" class="muted"></span>
  <h4>Gửi 1 lệnh tool</h4>
  <input id="callTool" placeholder="Tên tool (vd: mango_status)">
  <textarea id="callArgs" rows="2" placeholder='Tham số JSON (vd: {})'></textarea>
  <button class="primary" onclick="callTool('${esc(id)}')">Gửi lệnh</button>
  <pre id="callOut" class="hidden"></pre>`;
  el.scrollIntoView({behavior:'smooth', block:'nearest'});
}
async function machineAct(id, action){
  if(action==='delete' && !confirm('Xóa máy này khỏi Server?')) return;
  await api('/api/machines/'+id+'/'+action,{method:'POST',body:'{}'}); loadOverview(); showMachine(id);
}
async function rotateSecret(id){
  const r=await api('/api/machines/'+id+'/rotate-secret',{method:'POST',body:'{}'});
  alert('Secret mới (chỉ hiện 1 lần này, lưu lại ngay):\n'+r.secret);
  loadOverview();
}
async function callTool(id){
  const tool=document.getElementById('callTool').value.trim();
  let args={}; try{ args=JSON.parse(document.getElementById('callArgs').value||'{}'); }catch(e){ alert('Tham số không phải JSON hợp lệ'); return; }
  const out=document.getElementById('callOut'); out.classList.remove('hidden');
  try{ const r=await api('/api/machines/'+id+'/call',{method:'POST',body:JSON.stringify({tool,args})}); out.textContent=JSON.stringify(r.result,null,2); }
  catch(e){ out.textContent='Lỗi: '+e.message; }
  loadOverview();
}
async function loadEnroll(){
  try{ const d=await api('/api/enrollment');
    document.getElementById('enrollList').innerHTML='<table><tr><th>Ghi chú</th><th>Tạo lúc</th><th>Hết hạn</th><th>Đã dùng</th><th>Dùng bởi</th></tr>'+
    d.tokens.map(t=>`<tr><td>${esc(t.label||'')}</td><td>${new Date(t.created_at*1000).toLocaleString()}</td><td>${new Date(t.expires_at*1000).toLocaleString()}</td><td>${t.used?'rồi':'chưa'}${t.expired?' (hết hạn)':''}</td><td>${esc(t.used_by||'')}</td></tr>`).join('')+'</table>';
  }catch(e){}
}
async function createEnroll(){
  const label=document.getElementById('enrollLabel').value;
  const r=await api('/api/enrollment',{method:'POST',body:JSON.stringify({label})});
  const out=document.getElementById('enrollOut'); out.classList.remove('hidden');
  out.textContent='Mã đăng ký (chỉ hiện 1 lần này, đưa cho máy mới, hạn '+r.expires_in_seconds+' giây):\n'+r.token;
  loadEnroll();
}
async function loadTokens(){
  try{ const d=await api('/api/agent-tokens');
    document.getElementById('tokList').innerHTML='<table><tr><th>Tên</th><th>ID</th><th>Máy</th><th>Nhóm tool</th><th>Bật</th><th></th></tr>'+
    d.tokens.map(t=>`<tr><td>${esc(t.name)}</td><td><code>${esc(t.id)}</code></td><td>${esc(t.machines.join(','))}</td><td>${esc(t.tool_groups.join(','))}</td><td>${t.enabled?'có':'không'}</td>
    <td><button onclick="tokAct('${esc(t.id)}','${t.enabled?'disable':'enable'}')">${t.enabled?'Tắt':'Bật'}</button>
    <button onclick="tokAct('${esc(t.id)}','delete')" class="danger">Xóa</button></td></tr>`).join('')+'</table>';
  }catch(e){}
}
async function createToken(){
  const name=document.getElementById('tokName').value||'agent';
  const machines=document.getElementById('tokMachines').value.split(',').map(s=>s.trim()).filter(Boolean);
  const groups=document.getElementById('tokGroups').value.split(',').map(s=>s.trim()).filter(Boolean);
  const r=await api('/api/agent-tokens',{method:'POST',body:JSON.stringify({name,machines:machines.length?machines:['*'],tool_groups:groups.length?groups:['read']})});
  const out=document.getElementById('tokOut'); out.classList.remove('hidden');
  out.textContent='Token Agent mới (chỉ hiện 1 lần này, lưu lại ngay):\n'+r.token;
  loadTokens();
}
async function tokAct(id, action){
  if(action==='delete' && !confirm('Xóa token này?')) return;
  await api('/api/agent-tokens/'+id+'/'+action,{method:'POST',body:'{}'}); loadTokens();
}
async function loadConfig(){
  try{ const c=await api('/api/config');
    document.getElementById('configOut').textContent=JSON.stringify(c,null,2);
    document.getElementById('ttlSeconds').value=c.enrollment_ttl_seconds;
    const el=document.getElementById('enrollTtlNote'); if(el) el.textContent='Hạn mã đăng ký hiện tại: '+c.enrollment_ttl_seconds+' giây.';
    loadPackages();
  }catch(e){}
}
async function setTtl(){
  const seconds=parseInt(document.getElementById('ttlSeconds').value,10);
  const msg=document.getElementById('configMsg');
  try{ const r=await api('/api/config/enrollment-ttl',{method:'POST',body:JSON.stringify({seconds})}); msg.style.color='#22c55e'; msg.textContent='Đã đổi hạn mã đăng ký: '+r.enrollment_ttl_seconds+' giây.'; loadConfig(); }
  catch(e){ msg.style.color='#fca5a5'; msg.textContent='Lỗi: '+e.message; }
}
async function changePassword(){
  const cur=document.getElementById('pwCurrent').value;
  const n1=document.getElementById('pwNew1').value, n2=document.getElementById('pwNew2').value;
  const msg=document.getElementById('configMsg');
  if(n1!==n2){ msg.style.color='#fca5a5'; msg.textContent='Hai lần nhập mật khẩu mới khác nhau.'; return; }
  try{ await api('/api/config/change-password',{method:'POST',body:JSON.stringify({current_password:cur,new_password:n1})}); msg.style.color='#22c55e'; msg.textContent='Đã đổi mật khẩu quản trị.'; }
  catch(e){ msg.style.color='#fca5a5'; msg.textContent='Lỗi: '+e.message; }
}
async function loadPackages(){
  try{ const d=await api('/api/packages');
    document.getElementById('pkgList').innerHTML='<table><tr><th>Phiên bản</th><th>File</th><th>Kích thước</th><th>SHA-256</th><th>Khởi động lại</th><th>Ghi chú</th><th></th></tr>'+
    d.packages.map(p=>`<tr><td>${esc(p.version)}</td><td>${esc(p.filename)}</td><td>${p.size}</td><td><code>${esc(String(p.sha256).slice(0,16))}…</code></td><td>${p.requires_restart?'có':'không'}</td><td>${esc(p.note||'')}</td><td><button onclick="deletePackage('${esc(p.version)}')" class="danger">Xóa</button></td></tr>`).join('')+'</table>';
  }catch(e){}
}
async function uploadPackage(){
  const version=document.getElementById('pkgVersion').value.trim();
  const file=document.getElementById('pkgFile').files[0];
  if(!version||!file){ alert('Nhập phiên bản và chọn file zip.'); return; }
  const fd=new FormData();
  fd.append('version',version); fd.append('note',document.getElementById('pkgNote').value);
  fd.append('requires_restart',document.getElementById('pkgRestart').checked?'true':'false');
  fd.append('file',file);
  const r=await fetch('/api/packages',{method:'POST',body:fd});
  if(!r.ok){ const t=await r.json().catch(()=>({})); alert('Upload lỗi: '+(t.error||r.status)); return; }
  alert('Đã upload gói '+version+'.'); loadPackages();
}
async function deletePackage(version){
  if(!confirm('Xóa gói '+version+'?')) return;
  try{ await api('/api/packages/'+encodeURIComponent(version),{method:'DELETE'}); loadPackages(); }
  catch(e){ alert('Lỗi: '+e.message); }
}
async function setScope(id){
  let scope; try{ scope=JSON.parse(document.getElementById('scopeInput').value||'null'); }catch(e){ alert('Scope không phải JSON hợp lệ'); return; }
  if(scope===null){ alert('Nhập danh sách tool JSON (vd: ["mango_status"]) hoặc [] để cấm hết.'); return; }
  const msg=document.getElementById('scopeMsg');
  try{ const r=await api('/api/machines/'+id+'/scope',{method:'POST',body:JSON.stringify({desired_scope:scope})}); msg.textContent='Đã đặt scope'+(r.sent?' (đã gửi tới máy ngay).':' (máy offline, sẽ áp dụng khi nối lại).'); loadOverview(); }
  catch(e){ msg.textContent='Lỗi: '+e.message; }
}
async function doUpgrade(id){
  const v=document.getElementById('upgradeVersion').value.trim();
  try{ const r=await api('/api/machines/'+id+'/upgrade',{method:'POST',body:JSON.stringify({target_version:v||null})}); alert('Đã đặt bản đích '+r.target_version+(r.sent?' (đã gửi tới máy ngay).':' (máy offline, sẽ nhận khi nối lại).')); showMachine(id); }
  catch(e){ alert('Lỗi: '+e.message); }
}
async function doRestart(id){
  const delay=parseInt(document.getElementById('restartDelay').value||'60',10);
  if(!confirm('Khởi động lại máy sau '+delay+' giây?')) return;
  const msg=document.getElementById('restartMsg');
  try{ const r=await api('/api/machines/'+id+'/restart',{method:'POST',body:JSON.stringify({delay_seconds:delay})}); msg.textContent=r.sent?'Đã gửi lệnh khởi động lại.':'Máy offline, chưa gửi được.'; }
  catch(e){ msg.textContent='Lỗi: '+e.message; }
}
async function loadAudit(){
  try{ const d=await api('/api/audit?limit=200');
    document.getElementById('auditOut').textContent=d.entries.map(e=>JSON.stringify(e)).join('\n');
  }catch(e){}
}
(async()=>{ try{ await api('/api/status'); showApp(); startAutoRefresh(); loadAll(); }catch(e){ showLogin(); } })();
</script>
</body>
</html>

"""


def dashboard_page(request):
    return HTMLResponse(DASHBOARD_HTML)


def redirect_root(request):
    return RedirectResponse("/dashboard")
