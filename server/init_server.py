"""Init Server 1.0 khong tuong tac (tranh getpass tren SSH).

Dat mat khau quan tri + tao token Agent toan quyen cho quan tri vien.
Mat khau lay tu bien moi truong MANGO_ADMIN_PASSWORD — khong co mat
khau mac dinh. Chay: C:\MangoMCP\python\python.exe init_server.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mangoserver.auth import AuthStore
from mangoserver.store import JsonStore

DATA = r"C:\MangoMCPServer\data"
ADMIN_PW = os.environ.get("MANGO_ADMIN_PASSWORD", "")

auth = AuthStore(JsonStore(
    DATA + r"\auth.json",
    {"admin_password_sha256": "", "enrollment_tokens": [], "agent_tokens": []},
))
if auth.admin_password_set():
    print("Da co mat khau quan tri.")
else:
    if not ADMIN_PW or len(ADMIN_PW) < 4:
        print("CHUA DAT MAT KHAU QUAN TRI: dat bien moi truong "
              "MANGO_ADMIN_PASSWORD (toi thieu 4 ky tu) roi chay lai.")
        raise SystemExit(1)
    auth.set_admin_password(ADMIN_PW)
    print("Da dat mat khau quan tri.")
rec, token = auth.create_agent_token(
    "Admin (toan quyen)", ["*"], ["read", "control", "files", "admin"])
print("TOKEN:")
print(token)
print("TOKEN_ID:", rec["id"])
