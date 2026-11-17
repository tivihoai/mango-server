"""Tự áp dụng gói nâng cấp client (1.1, §4.3).

Nguyên tắc: tiến trình client hiện tại KHÔNG tự ghi đè code của chính
nó (file đang chạy, có thể bị khóa trên Windows). Nó chỉ:
1. Ghi script áp dụng (update_apply.bat trên Windows, update_apply.sh
   trên Linux) vào thư mục tạm.
2. Chạy script đó detached (nền, tách khỏi tiến trình client).
3. Thoát ngay để script chờ client chết hẳn rồi mới copy đè.

Script chờ tiến trình client cũ thoát (vòng lặp kiểm tra PID, timeout
30 giây), copy đè staging -> client_dir, rồi chạy lại client (qua
Scheduled Task MangoServerClient nếu task tồn tại, ngược lại chạy trực
tiếp lệnh khởi động lại đã cho). Nếu requires_restart thì cuối script
chạy shutdown /r /t 60.

KHÔNG chạy shutdown thật trong test: test chỉ kiểm tra nội dung file
script + mock subprocess.Popen, không gọi apply_update() thật trên máy
đang chạy.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WAIT_TIMEOUT_SECONDS = 30


def _quote_win(path: str) -> str:
    return '"' + str(path).replace('"', '""') + '"'


def render_update_script(staging_dir, client_dir, restart_client_cmd,
                         requires_restart, pid, windows=True):
    """Sinh nội dung script áp dụng. Trả (tên file, nội dung).

    Tách riêng khỏi apply_update() để test được nội dung .bat/.sh mà
    không cần chạy thật.
    """
    staging = str(staging_dir)
    target = str(client_dir)
    cmd = restart_client_cmd or ""
    if windows:
        lines = [
            "@echo off",
            "setlocal EnableDelayedExpansion",
            f"set \"STAGING={staging}\"",
            f"set \"TARGET={target}\"",
            f"set \"PID={pid}\"",
            "set /a WAITED=0",
            ":WAITLOOP",
            f"tasklist /FI \"PID eq {pid}\" 2>nul | findstr /I \"{pid}\" >nul",
            "if %ERRORLEVEL%==0 (",
            "  if !WAITED! GEQ 30 goto APPLY",
            "  timeout /t 1 /nobreak >nul",
            "  set /a WAITED+=1",
            "  goto WAITLOOP",
            ")",
            ":APPLY",
            "robocopy \"%STAGING%\" \"%TARGET%\" /E /IS /IT /NFL /NDL /NJH /NJS",
            "if %ERRORLEVEL% GEQ 8 exit /b %ERRORLEVEL%",
            "rem Thu Task 2.x (MangoClient) truoc, roi Task 1.x (MangoServerClient).",
            "schtasks /query /tn MangoClient >nul 2>&1",
            "if %ERRORLEVEL%==0 (",
            "  schtasks /run /tn MangoClient",
            ") else (",
            "  schtasks /query /tn MangoServerClient >nul 2>&1",
            "  if %ERRORLEVEL%==0 (",
            "    schtasks /run /tn MangoServerClient",
            "  ) else (",
        ]
        if cmd:
            lines.append(f"  start \"\" /B {cmd}")
        else:
            lines.append(f"  start \"\" /B python {_quote_win(str(Path(target) / 'run_client.py'))}")
        lines.append("  )")
        lines.append(")")
        if requires_restart:
            lines.append("shutdown /r /t 60 /c \"Mango Client da nang cap, khoi dong lai may\"")
        lines.append("exit /b 0")
        return "update_apply.bat", "\r\n".join(lines) + "\r\n"
    # Linux (chỉ để test local): tương đương bằng shell.
    lines = [
        "#!/bin/sh",
        f"STAGING={staging!r}",
        f"TARGET={target!r}",
        f"PID={pid}",
        "WAITED=0",
        f"while kill -0 $PID 2>/dev/null; do",
        "  if [ \"$WAITED\" -ge 30 ]; then break; fi",
        "  sleep 1",
        "  WAITED=$((WAITED + 1))",
        "done",
        "cp -r \"$STAGING/.\" \"$TARGET/\"",
    ]
    if cmd:
        lines.append(f"{cmd} &")
    else:
        lines.append(f"python3 {_quote_win(str(Path(target) / 'run_client.py'))} &")
    if requires_restart:
        # Ghi chú rõ: trên Linux thật, dòng dưới mới reboot máy.
        lines.append("# requires_restart=true: khoi dong lai may sau khi ap dung")
        lines.append("shutdown -r +1 \"Mango Client da nang cap, khoi dong lai may\"")
    lines.append("exit 0")
    return "update_apply.sh", "\n".join(lines) + "\n"


def apply_update(staging_dir, client_dir, restart_client_cmd,
                 requires_restart, windows=None):
    """Tạo script áp dụng, chạy detached, trả đường dẫn script.

    Người gọi (agent) thoát ngay sau khi hàm này trả về để script chờ
    tiến trình client chết rồi mới copy đè. `windows=None` = tự nhận
    theo hệ điều hành; test có thể ép True/False.
    """
    if windows is None:
        windows = os.name == "nt"
    pid = os.getpid()
    name, content = render_update_script(
        staging_dir, client_dir, restart_client_cmd, requires_restart,
        pid, windows=windows)
    script_path = Path(tempfile.gettempdir()) / name
    script_path.write_text(content, encoding="utf-8")
    if windows:
        # DETACHED_PROCESS (0x08) + CREATE_NEW_PROCESS_GROUP (0x200):
        # script sống độc lập sau khi client thoát.
        flags = 0x08 | 0x200
        subprocess.Popen(["cmd", "/c", "start", "", "/B", str(script_path)],
                         creationflags=flags,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL,
                         close_fds=True)
    else:
        os.chmod(script_path, 0o755)
        subprocess.Popen(["/bin/sh", str(script_path)],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
    return str(script_path)


def default_restart_cmd(client_dir, config_path):
    """Lệnh chạy lại client trực tiếp (khi không có Scheduled Task)."""
    python = sys.executable or "python"
    return (f"{_quote_win(python)} "
            f"{_quote_win(str(Path(client_dir) / 'run_client.py'))} "
            f"--config {_quote_win(str(config_path))}")
