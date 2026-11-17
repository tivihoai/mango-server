#!/usr/bin/env python3
"""Mango Server 1.2 — chạy Server trên máy ảo (thư mục C:\\MangoMCPServer\\).

Sử dụng (chạy từ thư mục server/):
  # 1. Khởi tạo lần đầu: đặt mật khẩu quản trị + tạo token Agent của Quản trị viên
  python run_server.py init --data-dir ./data
  # 2. Chạy Server (cổng mặc định 8443, HTTP local — TLS do Cloudflare lo)
  python run_server.py start --data-dir ./data --host 127.0.0.1 --port 8443
  # 3. Tạo mã đăng ký cho máy mới (in ra màn hình 1 lần)
  python run_server.py enroll-token --data-dir ./data --label "may-01"

Lệnh init hỏi mật khẩu quản trị (gõ 2 lần, không hiện trên màn hình) rồi
tạo token Agent toàn quyền cho Quản trị viên (in ra 1 lần — lưu lại ngay).
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mangoserver import VERSION
from mangoserver.auth import AuthStore
from mangoserver.store import JsonStore


def _auth_store(data_dir: str) -> AuthStore:
    raw = JsonStore(f"{data_dir}/auth.json", {
        "admin_password_sha256": "",
        "enrollment_tokens": [],
        "agent_tokens": [],
        "settings": {"enrollment_ttl_seconds": 86400},
    })
    return AuthStore(raw)


def cmd_init(args) -> int:
    auth = _auth_store(args.data_dir)
    if auth.admin_password_set():
        print("Da co mat khau quan tri. Muon doi thi dung dashboard hoac xoa hash trong auth.json.")
    else:
        pw1 = getpass.getpass("Mat khau quan tri Server (nhap, khong hien): ")
        pw2 = getpass.getpass("Nhap lai mat khau quan tri: ")
        if pw1 != pw2:
            print("Hai lan nhap khac nhau. Huy.")
            return 1
        auth.set_admin_password(pw1)
        print("Da dat mat khau quan tri.")
    rec, token = auth.create_agent_token("Admin (toan quyen)", ["*"],
                                         ["read", "control", "files", "admin"])
    print()
    print("Token Agent toan quyen cua quan tri vien (CHI HIEN 1 LAN NAY — luu lai ngay):")
    print(token)
    print()
    print("Ghi chu: token nay goi duoc moi may + moi nhom tool. Giu kin nhu mat khau.")
    return 0


def cmd_enroll_token(args) -> int:
    auth = _auth_store(args.data_dir)
    token = auth.create_enrollment_token(args.label or "")
    ttl = auth.get_enrollment_ttl()
    hours = ttl / 3600
    print(f"Ma dang ky (CHI HIEN 1 LAN NAY, han {ttl} giay (~{hours:g} gio) — dua cho may moi):")
    print(token)
    return 0


def cmd_start(args) -> int:
    import uvicorn
    from mangoserver.app import build_app

    auth = _auth_store(args.data_dir)
    if not auth.admin_password_set():
        print("CHUA DAT MAT KHAU QUAN TRI. Chay lenh init truoc:")
        print("  python run_server.py init --data-dir", args.data_dir)
        return 1
    app = build_app(args.data_dir, VERSION, host=args.host, port=args.port)
    print(f"Mango Server {VERSION} — dang chay tai http://{args.host}:{args.port}")
    print("  MCP endpoint : POST /mcp")
    print("  WebSocket    : /ws")
    print("  Dashboard    : /dashboard")
    print("Nhan Ctrl+C de dung.")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Mango Server 1.2")
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="Dat mat khau quan tri + tao token quan tri vien")
    p_init.add_argument("--data-dir", default="./data")
    p_init.set_defaults(func=cmd_init)
    p_tok = sub.add_parser("enroll-token", help="Tao ma dang ky cho may moi")
    p_tok.add_argument("--data-dir", default="./data")
    p_tok.add_argument("--label", default="")
    p_tok.set_defaults(func=cmd_enroll_token)
    p_run = sub.add_parser("start", help="Chay Server")
    p_run.add_argument("--data-dir", default="./data")
    p_run.add_argument("--host", default="127.0.0.1")
    p_run.add_argument("--port", type=int, default=8443)
    p_run.set_defaults(func=cmd_start)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
