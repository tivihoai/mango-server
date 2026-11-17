# Install guide

This guide covers installing Mango Server and Mango Client from the
prebuilt `Setup.exe` installers (published as GitHub Release assets),
and the manual alternative (run from source). For building the
installers yourself, see [`BUILD.md`](BUILD.md).

## Requirements

| Component | Requirements |
|---|---|
| Mango Server | Windows 10 or later, always on. The installer bundles its own Python 3.12 runtime — you do not need to install Python separately for the `Setup.exe` path. |
| Mango Client | Windows 10 or later, administrator rights to install. |
| Network | Clients connect **out** to the server (WebSocket). No inbound port is needed on a client machine. The server listens on port `8443` by default. |

## 1. Install Mango Server

1. Copy `MangoServer-Setup-1.2.1.exe` to the server machine and
   double-click it. Approve the administrator prompt.
2. Enter:
   - **Port** — default `8443`.
   - **Data directory** — default `C:\MangoMCPServer\data`. This is
     where the machine registry, auth data and audit log live. Keep it
     (the uninstaller keeps it too, so a reinstall preserves your
     machines and tokens).
   - **Admin password** — the dashboard password. Leave it empty and
     the installer generates a random 16-character password and shows
     it once.
3. Click **Install**. The installer registers a Scheduled Task
   (`MangoServer`, SYSTEM, runs at startup) and starts the server.
4. **Save two things shown at the end of the install:**
   - the **admin password** (if it was generated), and
   - the **Agent token** (shown once; the server stores only its hash).
   Both are shown only once. If you lose the agent token, create a new
   one on the dashboard (tab **Token Agent**). If you forget the admin
   password, reinstall the server with a new password — the reinstall
   replaces the password while keeping enrolled machines and tokens.
5. Open `http://127.0.0.1:8443/dashboard` on the server machine and log
   in with the admin password. `http://127.0.0.1:8443/health` should
   return `{"status":"ok","version":"1.2.1"}`.

### Silent install

```bat
MangoServer-Setup-1.2.1.exe /SILENT /PORT:8443 /DATADIR:C:\MangoMCPServer\data /ADMINPASSWORD:<your-admin-password>
```

Omit `/ADMINPASSWORD:` to get a random generated password (shown in the
installer's final screen). The installer exits `0` on success.

### Making the server reachable from outside your LAN

The server only needs to be reachable by its clients and by the AI
assistants that connect to it. The recommended way is a tunnel that
gives it a public HTTPS hostname without opening a port on your router,
for example **Cloudflare Tunnel** pointing at
`http://127.0.0.1:8443`. (The tunnel itself is set up separately; a
future installer version may automate it.)

Do **not** expose the bare port `8443` to the internet without
authentication in front of it. The dashboard and the MCP endpoint both
require credentials, but the server is meant to sit behind a tunnel or
a reverse proxy with TLS, not directly on a public IP.

### Verify the server is running

- Dashboard: `http://127.0.0.1:8443/dashboard` (or your public URL).
- Health: `http://127.0.0.1:8443/health` →
  `{"status":"ok","version":"1.2.1"}`.
- After a reboot the server must come back by itself (Scheduled Task
  `MangoServer`, SYSTEM, "At startup"). No login is needed.

## 2. Install Mango Client on each Windows machine

There are two installer variants. Both install the same client
(`2.1.9`); they differ only in how the server address is set.

| Variant | File | Server address |
|---|---|---|
| Standard | `MangoClient-Setup-2.1.9.exe` | Baked in at build time (the operator's own server). Zero input: just install. |
| Custom Host | `MangoClient-Setup-2.1.9-CustomHost.exe` | You enter the server host and port at install time. Use this for any server other than the one the standard build was made for. |

1. Copy the installer to the machine and double-click it. Approve the
   administrator prompt.
2. (Custom Host only) Enter the **Server host** (a hostname or IP, no
   `https://`, no `:port`) and the **Port** (default `8443`). The host
   field is empty by default — leaving it empty stops the install with
   a clear error instead of silently using a wrong server.
3. Enter the **Windows account and password** the client should use for
   screen / mouse / keyboard work. The client itself runs as SYSTEM at
   startup and needs no login for command, PowerShell, file and admin
   tools; the saved account is only used when GUI control is needed.
4. Click **Install**. The installer registers a Scheduled Task
   (`MangoClient`, SYSTEM, runs at startup), starts the client, and the
   machine registers itself on the server.
5. On the dashboard the machine appears as **pending**. Click
   **Approve**. From then on it is controllable.

> The client installer embeds a Python 3.12 runtime (from the MangoMCP
> Full package) into `C:\MangoClient\python\`, so the machine does not
> need Python installed. It also installs `agent-desktop.exe` (the GUI
> agent) and `MangoOverlay.exe` into `C:\MangoClient\bin\`.

### Verify a client

- On the dashboard the machine shows **online** with client version
  `2.1.9` and 101 tools.
- The client log is at `C:\MangoClient\client.log`; the install log is
  at `%TEMP%\MangoClient-install.log` (`C:\Windows\Temp\` for SYSTEM
  installs).
- Uninstall from Windows Settings → Apps → **Mango Client** (the
  uninstaller removes the task and the files, and keeps nothing
  behind except the machine's registration on the server, which you
  can delete from the dashboard).

## 3. Connect an AI assistant (MCP)

1. On the dashboard, open the **Token Agent** tab and create a token
   for the AI (give it a name, pick the machines it may touch, and the
   tool groups it needs — `read` to look, `control` to operate machines,
   `admin` only for full control). **Save the token immediately**; it is
   shown only once.
2. Add the server to the AI app. Examples:
   - **Claude Desktop** (`claude_desktop_config.json`):
     ```json
     { "mcpServers": { "mango-server": {
       "url": "https://your-server.example.com/mcp",
       "headers": { "Authorization": "Bearer <agent-token>" } } } }
     ```
   - **Gemini CLI** (`settings.json`): same, but the key is `httpUrl`
     instead of `url`.
   - **ChatGPT**: add an MCP connector with the URL and the Bearer token.
3. Restart the AI app. It must show the 5 `machine_*` tools. Call
   `machine_list` to see your machines.

Notes: the endpoint is `POST /mcp` only (Streamable HTTP, no legacy
GET SSE — clients that require SSE cannot connect yet). Authentication
is a Bearer agent token; a wrong or missing token returns `401`. More
than 10 failed auth attempts in 5 minutes from one IP returns `429`
for 5 minutes. Full protocol details:
[`docs/CONNECT-AGENTS.md`](docs/CONNECT-AGENTS.md).

## Troubleshooting

| Symptom | What to check |
|---|---|
| Machine stays **pending** | Approve it on the dashboard (tab **Machines**). A machine is not controllable until approved. |
| Machine **offline** | On the machine: is the `MangoClient` Scheduled Task running? Is the server reachable from that machine (`https://<server>:8443/health`)? Did the server host change? Reinstall the client with the correct host (Custom Host variant). |
| Dashboard login says the password is wrong | Reinstall the server with the new admin password (the installer replaces it; machines and tokens are kept). |
| Client install fails with "Server host not specified" | You used the Custom Host installer and left the host empty. Enter the server host and install again. |
| Dashboard shows no CPU/RAM/GPU for a machine | The machine is running an old client. Upgrade it from the dashboard (upload the client package, set the target version) or reinstall it. |
| AI gets `401` from `/mcp` | Wrong or missing Bearer token, or the token has no `read` group. Create a fresh token on the dashboard and use it exactly as shown. |
| AI gets `429` from `/mcp` | Too many failed auth attempts from that IP. Wait 5 minutes and check the token. |
