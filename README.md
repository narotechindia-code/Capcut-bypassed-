# CapCut Windows Process-Only VPN Launcher

Windows launcher for running CapCut through a selected VPN path without intentionally changing Windows' normal/default route for other applications.

## Network mode

The default mode uses the **VPN Gate Vietnam server shown in the supplied configuration**:

- Host: `vpn242832503.opengw.net`
- IP: `118.68.53.211`
- OpenVPN TCP: `1653`
- VPN Gate public credentials: username `vpn`, password `vpn`

The launcher downloads the live OpenVPN profile at runtime so the server's certificates/keys are not hard-coded in this repository.

The launcher uses the open-source `ENA526/OpenVPN-Split-Tunneling` helper for the process-only part. Its redirector uses WinDivert and sends selected applications through the OpenVPN adapter while leaving unselected applications on the normal Windows route.

## Important limitation

A normal OpenVPN client is system-wide at the adapter/routing layer. Merely setting `route-nopull` does **not** make OpenVPN process-only. The split-tunnel redirector is therefore required for the requested CapCut-only behavior.

The helper currently redirects IPv4 traffic only. If CapCut uses IPv6, that traffic can remain on the normal connection.

## One-command PowerShell

```powershell
irm https://raw.githubusercontent.com/narotechindia-code/Capcut-bypassed-/main/scripts/run.ps1 | iex
```

The bootstrapper:

1. Detects Python 3.10+.
2. If Python is missing, installs Python 3.12 automatically through the Python Software Foundation package in WinGet.
3. Downloads the launcher files into `%LOCALAPPDATA%\CapCutBypassedLauncher`.
4. Creates an isolated Python virtual environment.
5. Automatically installs the CapCut process-only split-tunnel helper if it is missing.
6. Downloads the live VPN Gate OpenVPN profile for the configured Vietnam server.
7. Starts OpenVPN with the default-route redirect disabled.
8. Starts the process-only redirector with only `CapCut.exe` admitted to the tunnel.
9. Launches CapCut.
10. Cleans up the OpenVPN/redirector processes when CapCut exits.

The launcher requests administrator elevation because the split-tunnel redirector needs to load its Windows packet-diversion driver.

## Modes

- `--mode auto` — default; VPN Gate process-only tunnel, fail closed if unavailable.
- `--mode vpn` — same as auto, explicitly.
- `--mode direct` — launch CapCut without the VPN.
- `--dry-run` — validate setup without launching CapCut.
- `--vpn-status` — show the split-tunnel helper's VPN adapter status.
- `--capcut "C:\path\to\CapCut.exe"` — use an explicit CapCut executable.

## Reliability choices

- No Cloudflare WARP dependency.
- No hard-coded VPN certificates or private keys.
- No Windows global proxy setting changes.
- OpenVPN's pushed `redirect-gateway` is ignored.
- The process-only helper is used instead of pretending ordinary OpenVPN routing is per-application.
- The launcher fails closed when the requested VPN path cannot be established.
- CapCut is installed only through the official `ByteDance.CapCut` WinGet package if it is missing.

## Project layout

- `launcher/main.py` — CLI, UAC elevation, CapCut lifecycle
- `launcher/capcut.py` — CapCut discovery/launch
- `launcher/network.py` — retained proxy parsing utilities
- `launcher/vpn.py` — VPN Gate profile retrieval, OpenVPN lifecycle, split-tunnel helper setup
- `scripts/run.ps1` — Python/bootstrapper
- `requirements.txt` — standard-library-only Python runtime
