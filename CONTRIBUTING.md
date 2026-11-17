# Contributing to Mango Server

Thank you for helping improve Mango Server. Bug reports, fixes,
documentation and translations are all welcome.

## How to contribute

1. **Open an issue first** for anything non-trivial (a new feature, a
   behaviour change, a new platform). Small fixes and doc corrections
   can go straight to a pull request.
2. **Fork the repo, create a branch** from `main`, make your change.
3. **Run the tests** and make sure they pass:
   ```bash
   python tests/run_tests.py
   ```
   The suite has 166 tests and needs no Windows machine and no real
   server. Do not submit a pull request with failing tests.
4. **Keep the scope tight.** One change per pull request. If you touch
   installer scripts (`.ps1`), read the "Installer script rules"
   section of [`BUILD.md`](BUILD.md) first — those files fail silently
   at install time when the encoding or a reserved variable is wrong.
5. **Write in English** for code comments, commit messages and docs
   aimed at users. (The existing technical docs in `docs/` are in
   Vietnamese; translating them is a welcome contribution on its own.)
6. **Do not commit secrets, hostnames, tokens or machine IDs.** See
   "Security" below.

## Reporting bugs

Please include:

- server version (`/health`) and client version (dashboard),
- what you did, what you expected, what happened instead,
- the relevant log tail (`C:\MangoMCPServer\server.log` on the server,
  `C:\MangoClient\client.log` and `%TEMP%\MangoClient-install.log` on
  a client),
- **never** paste tokens, passwords, machine secrets or your server's
  hostname into an issue. Replace them with placeholders such as
  `<your-server.example.com>`.

## Reporting security issues

If you find a security problem (authentication bypass, token leak,
remote code execution, …), **do not open a public issue**. Contact the
maintainer privately first so it can be fixed before it is disclosed.
See the repository's security policy / maintainer contact on GitHub.

## Security rules for contributors

- Never hard-code a hostname, token, password or machine ID — not even
  a "test" one that happens to be real. Use placeholders
  (`your-server.example.com`, `<agent-token>`,
  `<your-admin-password>`).
- Never log a token, password or secret. Log only whether a value was
  provided, never the value itself.
- The CustomHost client installer must never contain a default server
  host. The build guard in `client-setup-2.0/build_client_setup.ps1`
  (§2c) enforces this; do not weaken it.
- Test files must use obviously fake values only
  (`test-admin-password`, `1.2.3.4`, `your-server.example.com`).

## Style

- Python: keep the existing style (the server is plain stdlib +
  Starlette / websockets / MCP; no new heavy dependencies without a
  discussion in an issue first).
- PowerShell: UTF-8 with BOM + CRLF, and the rules in `BUILD.md`.
- C#: keep the existing WinForms style; the installers target
  .NET Framework 4.0 (`csc.exe`).
