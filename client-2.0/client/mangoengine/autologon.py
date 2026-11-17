"""Tu dong dang nhap Windows (auto-logon) cho MangoMCP 0.14.2.

Yeu cau goc (Quan tri vien, 8/11/2026): app phai TU DANG NHAP vao Windows khi
can dieu khien ("luc nao dieu khien thi dang nhap thong qua MCP").
Ban 0.14.0/0.14.1 chi mo Agent vao session DANG CO SAN (control_login
tra NO_SESSION neu chua ai dang nhap) — do la hieu sai yeu cau. Ban nay
sua lai: Core co them tool quan ly auto-logon cua Windows.

Co che: Windows tu dang nhap bang khoa registry Winlogon:
  HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon
    AutoAdminLogon   = "1" / "0"
    DefaultUserName  = ten tai khoan
    DefaultPassword  = mat khau
    DefaultDomainName = ten may / domain
Core chay bang SYSTEM nen ghi duoc HKLM. Tool nay la tool CAU HINH
(chay tai Core), KHONG phai tool dieu khien — dung duoc ngay ca khi
chua co console session.

CANH BAO BAO MAT (doc ky truoc khi bat):
- DefaultPassword luu MAT KHAU DANG CHU THUONG (plaintext) trong
  registry — do la cach Windows auto-logon hoat dong, khong co cach
  nao khac. Ai co quyen admin tren may deu doc duoc mat khau nay.
- Mat khau KHONG BAO GIO duoc: tra ve qua get_status(), ghi vao
  audit log (audit.summarize_args che khoa password), luu vao
  config.json, hay gui qua MCP. No chi ton tai trong registry.
- Khi bat auto-logon, ai ngoi truoc may cung dung duoc desktop sau
  khi bat may (khong can mat khau). Chi bat khi Quan tri vien chap nhan
  danh doi nay.
- Auto-logon mat khau TRONG da duoc chung minh KHONG chay duoc
  (test reboot 8/11 ~11:12: may dung o man hinh dang nhap). enable()
  tu choi mat khau trong.
- Mat khau duoc dat bang script deploy/enable-auto-logon.ps1 (chay
  tai may, hoi bang Read-Host -AsSecureString, khong hien, khong
  roi khoi may) hoac bang tool auto_logon_enable (mat khau chi di
  qua kenh MCP da xac thuc AppID.Secret).

Tren may khong phai Windows (dev/Linux), module van import duoc;
cac ham bao PLATFORM_UNSUPPORTED (giong session.py).
"""
import os
import socket

from .errors import MangoError, invalid_args, platform_unsupported

try:
    import winreg

    _WINREG_AVAILABLE = True
except ImportError:  # Linux/dev: khong co winreg
    winreg = None
    _WINREG_AVAILABLE = False

WINLOGON_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"


def _require_winreg():
    if not _WINREG_AVAILABLE:
        raise platform_unsupported(
            "auto-logon Windows",
            "Can winreg (chi co tren Windows) de doc/ghi khoa Winlogon.",
        )


def default_domain():
    """Ten may mac dinh cho DefaultDomainName (COMPUTERNAME / hostname)."""
    return os.environ.get("COMPUTERNAME") or socket.gethostname() or ""


def _open_key(access):
    """Mo khoa Winlogon (None neu chua ton tai). Chi dung doc."""
    try:
        return winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, WINLOGON_KEY, 0, access)
    except OSError:
        return None


def _read_str(key, name):
    """Doc mot gia tri REG_SZ (None neu thieu / loi)."""
    try:
        value, _type = winreg.QueryValueEx(key, name)
        return str(value) if value is not None else None
    except OSError:
        return None


def get_status():
    """Trang thai auto-logon hien tai.

    Tra {"enabled": bool, "username": str|None, "domain": str|None}.
    KHONG BAO GIO tra ve mat khau (khong doc DefaultPassword).
    Khoa Winlogon chua ton tai -> tat, username/domain None.
    """
    _require_winreg()
    key = _open_key(winreg.KEY_READ)
    if key is None:
        return {"enabled": False, "username": None, "domain": None}
    with key:
        auto = _read_str(key, "AutoAdminLogon")
        return {
            "enabled": (auto == "1"),
            "username": _read_str(key, "DefaultUserName"),
            "domain": _read_str(key, "DefaultDomainName"),
        }


def enable(username, password, domain=None):
    """Bat auto-logon: ghi 4 khoa Winlogon (AutoAdminLogon="1").

    - username: ten tai khoan (mac dinh "admin" o tang tool).
    - password: BAT BUOC, khong duoc trong (auto-logon mat khau
      trong khong chay tren Windows 10).
    - domain: ten may / domain; None thi dung ten may hien tai.
    Mat khau chi ghi vao registry DefaultPassword (plaintext theo
    thiet ke cua Windows); khong ghi log, khong luu config.
    Tra {"enabled": True, "username": ..., "domain": ...} (khong
    tra mat khau).
    """
    _require_winreg()
    if not username or not str(username).strip():
        raise invalid_args("username khong duoc trong.")
    if not password:
        raise invalid_args(
            "password khong duoc trong: auto-logon mat khau trong "
            "khong chay duoc tren Windows 10 (da kiem chung 8/11)."
        )
    domain = domain or default_domain()
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_LOCAL_MACHINE, WINLOGON_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, "AutoAdminLogon", 0, winreg.REG_SZ, "1")
            winreg.SetValueEx(
                key, "DefaultUserName", 0, winreg.REG_SZ, str(username)
            )
            winreg.SetValueEx(
                key, "DefaultPassword", 0, winreg.REG_SZ, str(password)
            )
            winreg.SetValueEx(
                key, "DefaultDomainName", 0, winreg.REG_SZ, str(domain)
            )
    except OSError as exc:
        raise MangoError(
            "AUTOLOGON_ERROR",
            "Khong ghi duoc khoa Winlogon (can quyen SYSTEM/admin).",
            detail=str(exc),
            retryable=False,
        )
    return {"enabled": True, "username": str(username), "domain": str(domain)}


def disable():
    """Tat auto-logon: AutoAdminLogon="0" + XOA DefaultPassword.

    Xoa mat khau khoi registry de khong con luu plaintext tren may.
    Giu lai DefaultUserName / DefaultDomainName (vo hai, bat lai
    nhanh). Tra {"enabled": False}.
    """
    _require_winreg()
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_LOCAL_MACHINE, WINLOGON_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, "AutoAdminLogon", 0, winreg.REG_SZ, "0")
            try:
                winreg.DeleteValue(key, "DefaultPassword")
            except OSError:
                # Chua co DefaultPassword thi khong sao.
                pass
    except OSError as exc:
        raise MangoError(
            "AUTOLOGON_ERROR",
            "Khong ghi duoc khoa Winlogon (can quyen SYSTEM/admin).",
            detail=str(exc),
            retryable=False,
        )
    return {"enabled": False}
