#!/usr/bin/env python3
"""Chay Mango Client 2.0 (gop sau): 1 chuong trinh duy nhat, engine goi
truc tiep trong process — khong con MangoMCP Core/Agent rieng, khong
con goi HTTP qua localhost:8766, khong con MANGO_LOCAL_BEARER.

Su dung (tren may Windows, Python portable):
  python run_client.py --config C:\\MangoClient\\server-client.json
  # Ghi de dia chi Server bang URL (phuc vu bo cai):
  python run_client.py --config ... --server-url https://your-server.example.com:8443
  # Cac lan sau (da enroll): chi can chay, khong can ma nua
  python run_client.py --config C:\\MangoClient\\server-client.json

Enroll bang URL chi tao may o trang thai pending — Quan tri vien duyet tren
dashboard thi may moi noi duoc, chua duyet thi client van chay va cho.
Nhan Ctrl+C de dung.
"""
import argparse
import asyncio
import json
import os
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mangoclient import VERSION as CLIENT_VERSION
from mangoclient.agent import ServerLink, enroll, enroll_by_url, log
from mangoclient.config import ClientConfig
from mangoengine.config import Config as EngineConfig
from mangoengine.direct_engine import DirectEngine


def apply_server_url(cfg, url: str):
    """Ghi de server_host/server_port/use_tls tu URL (vd
    https://host:port). Khong co cong trong URL thi giu cong cu."""
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"URL Server khong hop le: {url}")
    cfg.data["server_host"] = parsed.hostname
    if parsed.port:
        cfg.data["server_port"] = parsed.port
    cfg.data["use_tls"] = parsed.scheme == "https"
    cfg.save()
    return cfg


def _local_mcp_version(local):
    """Doc ban engine local (best-effort) de gui kem khi enroll."""
    try:
        status = local.call_tool("mango_status", {})
        text = status.get("content", [{}])[0].get("text", "{}")
        return str(json.loads(text).get("version", ""))
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Mango Client {CLIENT_VERSION}")
    parser.add_argument("--config", required=True,
                        help="Duong dan server-client.json")
    parser.add_argument("--enroll-token", default="",
                        help="Ma dang ky (chi can luc enroll lan dau; uu tien hon enroll bang URL)")
    parser.add_argument("--machine-name", default="",
                        help="Ten may (mac dinh: ten may Windows)")
    parser.add_argument("--server-url", default="",
                        help="URL Server dang https://host:port (ghi de server_host/port/use_tls)")
    parser.add_argument("--log-file", default="",
                        help="Ghi log ra file nay thay vi stdout (de chay an bang pythonw.exe "
                             "khong cua so van co log; mac dinh: client.log canh file config)")
    args = parser.parse_args()

    # 2.1: chay an bang pythonw.exe (Task SYSTEM, khong cua so) thi stdout
    # khong co noi den — chuyen huong ra file log ngay tu dau.
    if args.log_file:
        log_path = Path(args.log_file)
    else:
        log_path = Path(args.config).resolve().parent / "client.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _log_fh = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = _log_fh
        sys.stderr = _log_fh
    except Exception as exc:
        print(f"Canh bao: khong mo duoc file log {log_path} ({exc}).")

    cfg = ClientConfig(args.config)
    if args.server_url:
        try:
            apply_server_url(cfg, args.server_url)
        except ValueError as exc:
            print(f"{exc}")
            return 1
    if not cfg.data.get("machine_name") and args.machine_name:
        cfg.data["machine_name"] = args.machine_name
    if not cfg.data.get("machine_name"):
        cfg.data["machine_name"] = os.environ.get("COMPUTERNAME", "PC")
        cfg.save()

    # Client 2.0: engine chay trong cung process, khong can Bearer local.
    # Engine Config doc cung file server-client.json (1 file duy nhat).
    engine_cfg = EngineConfig.load_from(args.config)
    local = DirectEngine(engine_cfg)
    try:
        local.initialize()
    except Exception as exc:
        print(f"Canh bao: khong khoi dong duoc engine ({exc}).")
    if not cfg.enrolled:
        token = args.enroll_token or os.environ.get("MANGO_ENROLL_TOKEN", "")
        local_version = _local_mcp_version(local)
        try:
            if token:
                enroll(cfg, token, cfg.data.get("machine_name", ""), local_version)
            else:
                # Tu enroll bang URL, khong dung hoi ma.
                enroll_by_url(cfg, cfg.data.get("machine_name", ""), local_version)
        except Exception as exc:
            print(f"Enroll that bai: {exc}")
            return 1
    log(f"Client {CLIENT_VERSION} khoi dong: may={cfg.data.get('machine_name')} "
        f"({cfg.data.get('machine_id')}), server={cfg.data['server_host']}:"
        f"{cfg.data['server_port']}, tool Server duoc goi: "
        f"{len(cfg.allowed_tools)} tool.")
    link = ServerLink(cfg, local,
                      heartbeat_seconds=int(cfg.data.get("heartbeat_seconds", 30)),
                      call_timeout=int(cfg.data.get("call_timeout_seconds", 60)))
    try:
        asyncio.run(link.run_forever())
    except KeyboardInterrupt:
        print("\nNhan Ctrl+C, dang dung...")
        link.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
