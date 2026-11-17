"""Set admin password + create agent token for a fresh Mango Server install.

Non-interactive replacement for `run_server.py init` (which uses getpass).
Used ONLY by install_server.ps1 during Setup.exe install.

Usage:
  python set_admin.py --data-dir C:\\MangoMCPServer\\data --token-out <file>

Password comes from env var MANGO_ADMIN_PASSWORD (never from argv, so it
does not show in process command lines). Behaviour:
  - If no admin password is set yet: set it from the env var.
  - If one is already set: keep it (upgrade/reinstall path) and do NOT
    overwrite, unless --force is passed.
  - If no agent token exists yet: create one full-access token ("Admin (toan
    quyen)") and write the raw token to --token-out (ONE place, the
    installer GUI shows it once then deletes the file).
  - NEVER prints the password or the token to stdout/stderr/log.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mangoserver.auth import AuthStore
from mangoserver.store import JsonStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Set Mango Server admin password (install-time)")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--token-out", default="")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite an existing admin password")
    args = parser.parse_args()

    data_dir = args.data_dir
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    auth = AuthStore(JsonStore(
        f"{data_dir}/auth.json",
        {"admin_password_sha256": "", "enrollment_tokens": [],
         "agent_tokens": [],
         "settings": {"enrollment_ttl_seconds": 86400}},
    ))

    password = os.environ.get("MANGO_ADMIN_PASSWORD", "")
    if auth.admin_password_set():
        if args.force:
            if len(password) < 4:
                print("ERROR: MANGO_ADMIN_PASSWORD missing or too short (min 4 chars).")
                return 1
            auth.set_admin_password(password)
            print("ADMIN_PASSWORD: replaced existing admin password.")
        else:
            print("ADMIN_PASSWORD: already set, kept existing password.")
    else:
        if len(password) < 4:
            print("ERROR: MANGO_ADMIN_PASSWORD missing or too short (min 4 chars).")
            return 1
        auth.set_admin_password(password)
        print("ADMIN_PASSWORD: set.")

    tokens = auth.list_agent_tokens()
    if tokens:
        print(f"AGENT_TOKEN: already have {len(tokens)} token(s), no new token created.")
        return 0
    rec, token = auth.create_agent_token("Admin (toan quyen)", ["*"],
                                         ["read", "control", "files", "admin"])
    if args.token_out:
        Path(args.token_out).write_text(token, encoding="utf-8")
        print(f"AGENT_TOKEN: created id={rec['id']}, raw token written to token-out file (show once, then delete).")
    else:
        print("AGENT_TOKEN: created but no --token-out given, token NOT shown (create one from the dashboard).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
