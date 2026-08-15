# CapCut Windows Launcher

Windows-only launcher for running CapCut through a selected network path. The project now includes **Cloudflare WARP local-proxy mode**, a custom proxy mode, and direct mode.

## Modes

| Mode | Command | Effect |
|---|---|---|
| Auto | `--mode auto` | Try WARP first, then `CAPCUT_PROXY`; fail closed if neither works |
| WARP | `--mode warp` | Install/use Cloudflare WARP and route CapCut through its local SOCKS5 proxy |
| Proxy | `--mode proxy` | Use `CAPCUT_PROXY` only |
| Direct | `--mode direct` | Launch CapCut normally without a special route |

Cloudflare documents WARP Local Proxy as a desktop mode where only applications configured to use the HTTPS/SOCKS5 proxy are sent through WARP; other traffic remains on the normal Internet connection. WARP is not a country-spoofing service and does not promise a different country IP. See the official documentation: https://developers.cloudflare.com/warp-client/warp-modes/ .

## One-command PowerShell

```powershell
irm https://raw.githubusercontent.com/narotechindia-code/Capcut-bypassed-/main/scripts/run.ps1 | iex
```

Explicit WARP mode:

```powershell
irm https://raw.githubusercontent.com/narotechindia-code/Capcut-bypassed-/main/scripts/run.ps1 | iex --mode warp
```

**PowerShell note:** for reliable argument passing with a remote script, use:

```powershell
$script = irm https://raw.githubusercontent.com/narotechindia-code/Capcut-bypassed-/main/scripts/run.ps1
& ([scriptblock]::Create($script)) -Mode warp
```

Custom proxy:

```powershell
$env:CAPCUT_PROXY = 'http://127.0.0.1:7890'
$script = irm https://raw.githubusercontent.com/narotechindia-code/Capcut-bypassed-/main/scripts/run.ps1
& ([scriptblock]::Create($script)) -Mode proxy
```

WARP status:

```powershell
$script = irm https://raw.githubusercontent.com/narotechindia-code/Capcut-bypassed-/main/scripts/run.ps1
& ([scriptblock]::Create($script)) -WarpStatus
```

## WARP behavior

The launcher uses `warp-cli` and WARP local-proxy mode rather than enabling WARP's full-device tunnel. The selected SOCKS5 listener is passed to CapCut as process environment variables, so the launcher does not intentionally change Windows' global proxy settings.

The launcher can install WARP through WinGet when the `Cloudflare.Warp` package is available. If WARP is already installed, it reuses the existing client. First-time WARP registration may require the normal Cloudflare client registration flow.

## Important limitation

CapCut can use networking components that ignore standard proxy environment variables. Therefore **process-scoped proxying is not a mathematical guarantee that every CapCut network request uses WARP**. This repository does not use an invasive packet interceptor or modify CapCut's executable. A true kernel-level per-process VPN would require a dedicated process-aware networking driver/client.

## Safety / reliability choices

- No hard-coded VPN credentials.
- No random public VPN server list.
- No CapCut executable patching.
- Auto mode fails closed instead of silently launching CapCut directly when its special network route is unavailable.
- Existing WARP is not intentionally disconnected unless this launcher created the connection.
- The launcher only passes proxy variables to the CapCut child process.

## CapCut installation

If CapCut is not installed, the launcher reports that clearly instead of downloading an unverified executable. The official CapCut site provides the current Windows installer and Microsoft Store route: https://www.capcut.com/resource/capcut-for-windows .

## Project layout

- `launcher/main.py` — modes, lifecycle, fail-closed behavior
- `launcher/capcut.py` — CapCut discovery and process handling
- `launcher/network.py` — process-scoped proxy environment
- `launcher/vpn.py` — WARP installation, registration, local proxy, connection and cleanup
- `scripts/run.ps1` — PowerShell bootstrapper
- `requirements.txt` — Python dependencies
