# Build guide

This guide covers running from source, running the tests, and building
the Windows `Setup.exe` installers. For installing the prebuilt
installers, see [`INSTALL.md`](INSTALL.md).

## Prerequisites

| What | Needed for |
|---|---|
| Python 3.12 | Running the server from source, running the tests. |
| Windows 10 or later, PowerShell 5.1 | Building the `Setup.exe` installers (Windows only). |
| .NET Framework 4.0+ (`csc.exe`) | Compiling the installer GUIs. Present on Windows 10 at `C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe`. |
| **MangoMCP Full package** (`MangoMCP-*-win64-full.zip`, ~37 MB) | Building the installers. It supplies the Python 3.12 runtime plus `agent-desktop.exe` and `MangoOverlay.exe` that the installers embed. See below. |

### The MangoMCP Full package (external prerequisite)

The client and server installers embed a Python runtime so the target
machine needs nothing pre-installed. That runtime (plus the GUI agent
`agent-desktop.exe` and `MangoOverlay.exe`) comes from the **MangoMCP
Full package**, a separate component that is **not in this repo** and is
**not committed** (it is ~37 MB of binaries).

- The build scripts look for it in `C:\MangoMCP-Package\` (any
  `MangoMCP-*-win64-full.zip`), or take an explicit path:
  `-MangoMCPZip "C:\MangoMCP-Package\MangoMCP-0.14.2-win64-full.zip"`.
- If you do not have it, you can still **run the server from source**
  and **run the tests** (below) — only the `Setup.exe` builds need it.
- Making the Full package (or an equivalent runtime bundle) publicly
  available is an open item for this project; see
  [`FILES-TO-UPLOAD.md`](FILES-TO-UPLOAD.md) (prep note, not part of
  the repo) or the issue tracker.

## Run the server from source

```bash
python -m pip install -r requirements-server.txt
python server/run_server.py start --data-dir ./data --host 127.0.0.1 --port 8443
```

- First run needs an admin password: set the `MANGO_ADMIN_PASSWORD`
  environment variable (the server has **no** default password).
- Dashboard: `http://127.0.0.1:8443/dashboard`.
- Health: `http://127.0.0.1:8443/health`.
- The server is pure Python (Starlette / uvicorn / websockets / MCP).
  Windows is the tested platform; Linux should work in principle
  (the monitor's ping helper already has a Linux branch) but has not
  been tested live.

## Run the tests

```bash
python tests/run_tests.py            # all tests
python tests/run_tests.py -k auth    # only tests whose name contains "auth"
```

The suite in this repo has **166 tests** (server + client 2.x) and must
pass with no failures before a pull request is submitted. It needs no
Windows machine and no real server — everything is local and mocked,
except where a test file says otherwise.

> The 1.x client (`client/`) and its tests are not in this repo
> (superseded by the 2.x client). The public suite is therefore 166
> tests, not the 201 of the private tree (which still contains the 1.x
> line).

## Build the Server installer

On Windows, in PowerShell, from the `server-setup/` folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_server_setup.ps1 -Version "1.2.1"
```

- Produces `MangoServer-Setup-1.2.1.exe` (plus `MangoServer-1.2.1.zip`,
  the server package).
- The build verifies the version string is consistent everywhere,
  checks the installer scripts' encoding, compiles the C# GUI with
  `csc.exe`, embeds the MangoMCP Full package and the server package
  as resources, and prints the SHA-256 of the exe.
- The script also runs a `py_compile` check over the server code.

## Build the Client installer

On Windows, in PowerShell, from the `client-setup-2.0/` folder:

```powershell
# Standard variant (bakes in the default server host)
powershell -ExecutionPolicy Bypass -File .\build_client_setup.ps1 -Version "2.1.9"

# Custom Host variant (the user enters the server host at install time)
powershell -ExecutionPolicy Bypass -File .\build_client_setup.ps1 -Version "2.1.9" -CustomHost
```

- Produces `MangoClient-Setup-2.1.9.exe` (standard) or
  `MangoClient-Setup-2.1.9-CustomHost.exe`, plus the client package
  `MangoClient-2.1.9.zip` (upload this zip to the server's package
  store on the dashboard to enable remote upgrades).
- Build guards (the build **fails loudly** instead of shipping a bad
  exe):
  - `Test-PsScriptEncoding` — installer scripts must be UTF-8 **with
    BOM** and clean CRLF (no `\r\r\n`, no lone LF), and parse with
    0 errors.
  - `Assert-VersionMatch` — the version must match in
    `mangoclient/__init__.py`, `mangoengine/server_tools.py`,
    `MangoClientSetup.cs` and `install_client.ps1`.
  - Byte-exact checks — the script inside the zip must equal the
    source file, and the `MangoClient.zip` resource inside the exe
    must equal the zip just built.
  - **CustomHost guard** — the CustomHost exe must not contain the
    public default-host placeholder (`your-server.example.com`). If it
    does, the build stops.

### Setting your own default server host (standard variant)

The standard installer is pre-configured for one server. In this
public source the default host is the placeholder
`your-server.example.com`. **Before building the standard variant for
your own use, set your real server host** in
`client-setup-2.0/MangoClientSetup.cs`:

- the info label (standard branch, `#else`): the `Server: https://…`
  text, and
- the install arguments (standard branch, `#else`): the
  `-ServerHost "…"` argument.

If you configure your own host, also add it to the CustomHost guard
list in `client-setup-2.0/build_client_setup.ps1` (§2c) so the guard
keeps checking the CustomHost exe for it. The CustomHost variant
itself needs no default host — its host field starts empty and the
installer refuses to continue until a host is entered.

> The prebuilt release installers were built from the operator's
> private tree. The public source in this repo is identical except
> for the default-host placeholder above. That is the only intended
> difference.

## Version-bump checklist

When releasing a new version, update the version string in **all** of
these places (the build guards check most of them and fail if they
disagree):

- Server: `server/mangoserver/__init__.py` (`VERSION`),
  `server-setup/MangoServerSetup.cs`, `server-setup/app.manifest`,
  `server-setup/build_server_setup.ps1`,
  `server-setup/install_server.ps1`,
  `server-setup/uninstall_server.ps1`.
- Client: `client-2.0/client/mangoclient/__init__.py` (`VERSION`),
  `client-2.0/client/mangoengine/server_tools.py`,
  `client-setup-2.0/MangoClientSetup.cs`,
  `client-setup-2.0/install_client.ps1`,
  `client-setup-2.0/build_client_setup.ps1`.

## Installer script rules (read before editing `.ps1` files)

PowerShell 5.1 is picky about these files, and a mistake here fails
silently at install time (no log is written). The rules are enforced
by the build guards, but they are worth knowing:

- **Save every `.ps1` as UTF-8 with BOM and CRLF line endings.**
  UTF-8 without BOM + LF breaks PowerShell 5.1 on non-ASCII text.
  Verify with
  `[System.Management.Automation.Language.Parser]::ParseFile()` — it
  must report 0 errors.
- **Never declare `param([string]$Host …)`.** `$Host` is a read-only
  automatic variable; the script dies at parameter binding, before
  any logging. (This exact bug once shipped a silent exit-1 installer.)
- **Robocopy exits `1` on a successful copy.** A script that ends
  after a robocopy must finish with an explicit `exit 0`.
- **With `$ErrorActionPreference = "Stop"`, any stderr from a native
  command is a terminating error**, even with `2>$null`. Guard native
  calls or set the preference to `Continue` around them and check
  `$LASTEXITCODE`.
- **`Copy-Item` of a file onto itself fails.** When installing over an
  existing install, compare source and destination absolute paths
  first and skip the copy when they are the same.
- **Never use `$var:` inside a double-quoted string** (`"$path:"` is
  parsed as a drive reference). Write `${var}:` instead.
