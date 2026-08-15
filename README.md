# CapCut Windows Launcher

A Windows-only Python launcher for starting CapCut through a configured VPN/proxy path without intentionally changing proxy settings for unrelated applications.

## Goals

- One-command PowerShell bootstrap.
- Detect/install Python when required.
- Detect an existing CapCut installation.
- If CapCut is missing, offer a safe path for the official installer rather than bundling an outdated executable.
- Support a configured local HTTP/HTTPS/SOCKS proxy.
- Verify the proxy before launching CapCut.
- Wait for CapCut to exit and clean up the launcher state.
- Never hard-code VPN credentials or ship an unknown public VPN server.

## Important limitation

A process-level proxy is **not guaranteed** to capture every network request made by a desktop application. CapCut may use networking components that do not honor standard proxy environment variables. True CapCut-only VPN routing requires a VPN client/provider that explicitly supports per-app or split tunneling. The project is intentionally structured so an official provider CLI/API can be integrated later.

## One-command PowerShell

```powershell
irm https://raw.githubusercontent.com/narotechindia-code/Capcut-bypassed-/main/scripts/run.ps1 | iex
```

Optional local proxy:

```powershell
$env:CAPCUT_PROXY = 'http://127.0.0.1:7890'
irm https://raw.githubusercontent.com/narotechindia-code/Capcut-bypassed-/main/scripts/run.ps1 | iex
```

The project does not pretend that a random public VPN is a reliable "free forever" service. It keeps the VPN/provider layer explicit so the final implementation can use a legitimate endpoint and, where available, official per-app routing.

## Project layout

- `launcher/main.py` — launcher entry point and lifecycle
- `launcher/capcut.py` — CapCut discovery and process handling
- `launcher/network.py` — proxy parsing and connectivity tests
- `scripts/run.ps1` — PowerShell bootstrapper
- `requirements.txt` — Python dependencies

