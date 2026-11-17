# Mango Server

![Mango Server logo](assets/logo.png)

**One central server to see and control all your Windows machines — and a
standard MCP endpoint so any AI assistant can control them too.**

Mango Server is the hub. Windows machines run **Mango Client** and connect
*out* to the server over WebSocket, so the machines need **no inbound ports**.
An administrator approves each machine on a web dashboard, and from then on
the machine can be controlled from the dashboard or from any MCP-compatible
AI (Claude Desktop, Gemini CLI, ChatGPT, …) through the server's MCP
endpoint.

- **Server:** Mango Server `1.2.1` — pure Python (Starlette / uvicorn /
  websockets / MCP).
- **Client:** Mango Client `2.1.9` — Windows, runs as SYSTEM at startup,
  101 tools, self-updates from the server.

> **Status:** this project is used in production on a small home setup
> (one server, a handful of Windows machines). Windows is the tested
> platform. The server is pure Python and should run on Linux, but that
> has not been tested yet.

## How it works

```
AI assistant (Claude / Gemini / ChatGPT) ── MCP (Bearer token) ──┐
Web browser ── dashboard (admin password) ───────────────────────┤
                                                                  ▼
                                              ┌─────────────────────────────────┐
                                              │  Mango Server (port 8443)       │
                                              │  • MCP endpoint  • Dashboard    │
                                              │  • WebSocket hub • Monitor      │
                                              │  • Packages      • Audit log    │
                                              └──────────────┬──────────────────┘
                                                             │ WebSocket (clients dial out)
                              ┌──────────────────────────────┼──────────────────────────────┐
                              ▼                              ▼                              ▼
                    ┌───────────────────┐         ┌───────────────────┐         ┌───────────────────┐
                    │ Mango Client      │         │ Mango Client      │         │ Mango Client      │
                    │ Windows machine 1 │         │ Windows machine 2 │         │ Windows machine 3 │
                    │ 101 tools         │         │ 101 tools         │         │ 101 tools         │
                    └───────────────────┘         └───────────────────┘         └───────────────────┘
```

See [`assets/architecture.svg`](assets/architecture.svg) for the full
diagram.

A machine never accepts inbound connections. It dials out to the server,
sends a heartbeat, and waits for calls. The server routes every call over
that same WebSocket. If the server goes down, the client keeps retrying;
when the server comes back, the machine reconnects by itself.

## Features

### Server

- **Standard MCP endpoint** — the server *is* an MCP server
  (Streamable HTTP, JSON-RPC 2.0, protocol `2025-06-18`). One connection
  gives an AI exactly 5 tools:
  `machine_list`, `machine_status`, `machine_call`, `machine_restart`,
  `machine_upgrade`. `machine_call` is the universal remote: it runs any
  of a machine's ~101 tools and returns the result.
- **Web dashboard** — dark theme, live overview cards (total / online /
  offline / SSH / RDP / last scan), a machine table with real CPU, RAM,
  GPU and disk figures, search and filters, auto-refresh every 10 s, and
  a "Scan now" button. Tabs: Dashboard, Reports, Machine logs,
  Operation log, plus Enrollment code, Agent token and Config.
- **Background monitor** — pings every machine every 10 s and pulls full
  system stats (`system_info`) every 5 min. Machine names follow the real
  Windows computer name automatically.
- **Machine approval** — new machines start as *pending*. Nothing is
  controllable until an administrator approves it on the dashboard.
- **Enrollment codes** — one-time codes (about 24 h) that let a new
  machine register itself. No shared password is ever sent to a machine.
- **Agent tokens** — create one token per AI / integration. Each token
  has its own machine list (`["*"]` or specific machines) and its own
  tool groups (`read`, `control`, `files`, `admin`). A token is shown
  **once** at creation; the server stores only its hash. Revoke a token
  any time to cut that AI off without touching the others.
- **Remote upgrade & restart** — upload a client package (`.zip`) on the
  dashboard, set it as the target version for a machine, and the client
  downloads it, verifies the SHA-256, installs it and restarts itself.
  `machine_restart` reboots a machine remotely. Both need the `admin`
  tool group, and neither asks the machine's user for confirmation —
  the server is the authority.
- **Per-machine tool scope** — each machine has its own allowed-tool
  list. A call is allowed only if *both* the agent token's groups *and*
  the machine's own scope allow it.
- **Audit log** — every call is logged with metadata only (who, which
  machine, which tool, when). File contents, passwords and secrets are
  never logged.

### Client (Windows)

- **Runs as SYSTEM at Windows startup** — a Scheduled Task starts it
  before anyone logs in. Command, PowerShell, file and admin tools work
  with no one logged in.
- **101 tools** — command / PowerShell, files, system info, processes,
  registry, users, screenshots, and full screen / mouse / keyboard /
  desktop control through a GUI agent that runs in the logged-in user's
  session (or, if nobody is logged in, through the account saved at
  install time).
- **Self-update** — from version 2.1.1 on, the client updates itself from
  the server and restarts automatically. No prompt on the machine.
- **Remote password update** — the account saved at install time can
  have its password changed remotely (`config_set_user_password`), so a
  password change does not strand the machine.
- **Auto-logon (optional)** — the installer can enable Windows
  auto-logon for the saved account, so the GUI agent is available right
  after a reboot.

## Quick start

You need one machine for the server (Windows, always on) and one or more
Windows machines as clients. Full steps: [`INSTALL.md`](INSTALL.md).

1. **Install Mango Server** — run `MangoServer-Setup-1.2.1.exe` on the
   server machine (double-click, approve the admin prompt). Enter the
   port (default `8443`), the data directory, and an admin password.
   **Save the admin password and the agent token shown at the end** —
   both are shown only once. The server starts automatically at every
   boot (Scheduled Task, SYSTEM).
2. **Make the server reachable** — for machines and AI outside your LAN,
   put it behind a tunnel or reverse proxy that gives it a public HTTPS
   hostname (for example Cloudflare Tunnel pointing at
   `http://127.0.0.1:8443`). Do not expose the bare port to the internet
   without authentication in front of it.
3. **Install Mango Client on each Windows machine** — run
   `MangoClient-Setup-2.1.9.exe` (standard: it is pre-configured for
   your server) or `MangoClient-Setup-2.1.9-CustomHost.exe` (you enter
   the server host and port at install time). Enter the Windows account
   and password the client should use for screen/keyboard work, then
   click Install.
4. **Approve the machine** — it appears on the dashboard as *pending*.
   Click Approve. From then on it is controllable.
5. **Control it** — from the dashboard, or connect an AI assistant to
   the MCP endpoint (see [`docs/CONNECT-AGENTS.md`](docs/CONNECT-AGENTS.md)):

   ```json
   {
     "mcpServers": {
       "mango-server": {
         "url": "https://your-server.example.com/mcp",
         "headers": { "Authorization": "Bearer <agent-token>" }
       }
     }
   }
   ```

   The AI will see the 5 `machine_*` tools. Call `machine_list` to see
   your machines and their tools.

## Repository structure

```
mango-server/
├── README.md                  This file
├── INSTALL.md                 Install guide (server + client)
├── BUILD.md                   Build the installers and run from source
├── CONTRIBUTING.md            How to contribute
├── LICENSE                    MIT (proposed — see below)
├── .gitignore
├── requirements-server.txt    Python dependencies of the server
├── server/                    Mango Server 1.2.1 (pure Python)
│   ├── mangoserver/           app, auth, dashboard, hub, MCP endpoint,
│   │   ├── static/            logo, favicon, icons
│   │   └── ...                monitor, packages, registry, security
│   ├── run_server.py          Start the server
│   ├── init_server.py         Manual first-time setup helper
│   └── start_server.bat       Windows start script
├── client-2.0/
│   └── client/                Mango Client 2.1.9 (Python)
│       ├── mangoclient/       config, agent link, updater
│       ├── mangoengine/       the 101 tools (core, desktop, lock, ...)
│       ├── gui_agent.py       GUI agent (user session)
│       └── run_client.py      Client entry point
├── server-setup/              Mango Server installer (C# GUI + PowerShell)
├── client-setup-2.0/          Mango Client installer (C# GUI + PowerShell)
│   ├── MangoClientSetup.cs    Standard + CustomHost variants
│   └── INVESTIGATION-215-217.md  Post-mortem: the 2.1.5–2.1.7 install bug
├── tests/                     Unit + integration tests (166 tests, all pass)
├── docs/                      Technical docs (see below)
└── assets/                    Logo and architecture diagram for this README
```

### Docs

- [`docs/CONNECT-AGENTS.md`](docs/CONNECT-AGENTS.md) — how an AI
  connects to the MCP endpoint (protocol, auth, the 5 tools, errors).
- [`docs/DASHBOARD-1.2.md`](docs/DASHBOARD-1.2.md) — the 1.2 dashboard
  and background monitor.
- [`docs/DESIGN-CLIENT-2.0.md`](docs/DESIGN-CLIENT-2.0.md) — the client
  2.x design (SYSTEM service + GUI agent + auto-update).
- [`docs/MERGE-MAP-2.0.md`](docs/MERGE-MAP-2.0.md) — how the old
  MangoMCP engine was merged into the client.
- [`docs/DEPLOY-1.1.md`](docs/DEPLOY-1.1.md) — historical 1.1 deployment
  notes (refers to the 1.x client installer, which is not in this repo;
  current deployment is in `INSTALL.md`).

> The existing technical docs in `docs/` and the installer READMEs are
> in Vietnamese (as originally written). The guides in this repo root
> (`README.md`, `INSTALL.md`, `BUILD.md`, `CONTRIBUTING.md`) are in
> English. Translating `docs/` to English is a welcome contribution.

## Build from source

See [`BUILD.md`](BUILD.md). In short: the server runs from source with
Python 3.12 (`pip install -r requirements-server.txt`, then
`python server/run_server.py start`), and the tests run with
`python tests/run_tests.py` (166 tests). The Windows `Setup.exe`
installers are built on Windows with PowerShell + `csc.exe` (.NET
Framework) and need the **MangoMCP Full package** (Python 3.12 runtime
plus `agent-desktop.exe` and `MangoOverlay.exe`) — a separate component
that is not in this repo; see `BUILD.md` for where it comes from.

Prebuilt installers are **not** committed to this repo. They are
published as **GitHub Release assets** (`MangoServer-Setup-1.2.1.exe`,
`MangoClient-Setup-2.1.9.exe`,
`MangoClient-Setup-2.1.9-CustomHost.exe`).

## Security

- **Agent tokens are Bearer credentials.** Treat them like passwords:
  one token per integration, least privilege (only the tool groups that
  integration needs), revoke when done. The server stores only hashes.
- **Never hard-code secrets.** The server has no default admin password
  (`init_server.py` requires the `MANGO_ADMIN_PASSWORD` environment
  variable); the installer generates a random one if you leave the field
  empty. Windows account passwords live only on the machine that uses
  them, never on the server.
- **Failed logins are rate-limited** (too many failed MCP auth attempts
  from one IP returns `429` for 5 minutes).
- **Audit is metadata only.** No file contents, no passwords, no
  secrets in the audit log.
- If you find a security problem, please report it privately first
  (see [`CONTRIBUTING.md`](CONTRIBUTING.md)).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Bug reports, fixes and
translations are welcome. Please run the test suite before submitting a
pull request.

## License

MIT — see [`LICENSE`](LICENSE). (This is the proposed license; the
maintainer may change it before the first public release.)
