from __future__ import annotations

import base64
import csv
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

VPN_GATE_API = "https://www.vpngate.net/api/iphone/"
VPN_GATE_HOST = "vpn242832503.opengw.net"
VPN_GATE_IP = "118.68.53.211"
VPN_GATE_TCP_PORT = 1653
VPN_GATE_USERNAME = "vpn"
VPN_GATE_PASSWORD = "vpn"
SPLIT_TUNNEL_REPO = "ENA526/OpenVPN-Split-Tunneling"
SPLIT_TUNNEL_INSTALL_ROOT = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "VpnClient"
OPENVPN_WINGET_ID = "OpenVPNTechnologies.OpenVPN"


@dataclass
class SplitVpnSession:
    openvpn: str
    openvpn_process: subprocess.Popen[str]
    redirector: subprocess.Popen[str]
    profile: Path
    auth_file: Path
    config_file: Path
    connected: bool = False


def _run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _download(url: str, destination: Path, timeout: int = 60) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "CapCutBypassedLauncher/2.1"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def find_openvpn() -> str | None:
    candidates = [
        shutil.which("openvpn.exe"),
        str(Path(os.environ.get("PROGRAMFILES", "")) / "OpenVPN" / "bin" / "openvpn.exe"),
        str(Path(os.environ.get("PROGRAMFILES(X86)", "")) / "OpenVPN" / "bin" / "openvpn.exe"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "OpenVPN" / "bin" / "openvpn.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def install_openvpn() -> str:
    """Install the official OpenVPN Community package automatically when absent."""
    existing = find_openvpn()
    if existing:
        return existing

    winget = shutil.which("winget.exe") or shutil.which("winget")
    if not winget:
        raise RuntimeError(
            "OpenVPN is not installed and WinGet is unavailable. "
            "Install Microsoft App Installer/WinGet and run the launcher again."
        )

    print("OpenVPN Community is not installed. Installing it automatically...", flush=True)
    result = _run(
        [
            winget,
            "install",
            "--id",
            OPENVPN_WINGET_ID,
            "--exact",
            "--source",
            "winget",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--disable-interactivity",
            "--scope",
            "machine",
        ],
        timeout=900,
    )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    if result.returncode not in (0, 0x8A150014):
        raise RuntimeError(
            f"Automatic OpenVPN installation failed (WinGet exit code {result.returncode}).\n"
            f"{output[-1800:]}"
        )

    # Windows does not always refresh PATH immediately after an MSI install.
    deadline = time.time() + 120
    while time.time() < deadline:
        found = find_openvpn()
        if found:
            print(f"OpenVPN installed: {found}", flush=True)
            return found
        time.sleep(2)

    raise RuntimeError(
        "OpenVPN installation completed, but openvpn.exe was not detected. "
        "Please restart the launcher once so Windows can refresh the installation paths."
    )


def find_redirector() -> Path | None:
    candidate = SPLIT_TUNNEL_INSTALL_ROOT / "redirector.exe"
    return candidate if candidate.is_file() else None


def install_split_tunnel_helper() -> Path:
    """Install the external split-tunnel helper used for process-only routing."""
    redirector = find_redirector()
    if redirector:
        return redirector

    api_url = f"https://api.github.com/repos/{SPLIT_TUNNEL_REPO}/releases/latest"
    req = urllib.request.Request(api_url, headers={"User-Agent": "CapCutBypassedLauncher/2.1"})
    with urllib.request.urlopen(req, timeout=30) as response:
        release = json.loads(response.read().decode("utf-8"))

    assets = release.get("assets", [])
    installer = next(
        (
            asset
            for asset in assets
            if str(asset.get("name", "")).lower().startswith("vpnclientsetup-")
            and str(asset.get("name", "")).lower().endswith(".exe")
        ),
        None,
    )
    if not installer or not installer.get("browser_download_url"):
        raise RuntimeError("Could not find the split-tunnel helper installer in its latest GitHub release.")

    temp = Path(tempfile.gettempdir()) / str(installer["name"])
    print("Installing the process-only OpenVPN split-tunnel helper...", flush=True)
    _download(str(installer["browser_download_url"]), temp, timeout=180)
    result = _run([str(temp), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"], timeout=600)
    try:
        temp.unlink(missing_ok=True)
    except OSError:
        pass
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Split-tunnel helper installation failed ({result.returncode}). {detail[-1200:]}")

    deadline = time.time() + 90
    while time.time() < deadline:
        redirector = find_redirector()
        if redirector:
            print(f"Split-tunnel helper installed: {redirector}", flush=True)
            return redirector
        time.sleep(2)
    raise RuntimeError("Split-tunnel helper installed, but redirector.exe was not found.")


def _vpngate_row() -> dict[str, str]:
    req = urllib.request.Request(VPN_GATE_API, headers={"User-Agent": "CapCutBypassedLauncher/2.1"})
    with urllib.request.urlopen(req, timeout=30) as response:
        text = response.read().decode("utf-8", errors="replace")

    lines = [line for line in text.splitlines() if line and not line.startswith("*")]
    if len(lines) < 2:
        raise RuntimeError("VPN Gate API returned no server data.")
    header = lines[0][1:] if lines[0].startswith("#") else lines[0]
    for row in csv.DictReader([header] + lines[1:]):
        host = (row.get("HostName") or row.get("#HostName") or "").strip()
        ip = (row.get("IP") or "").strip()
        if host in {VPN_GATE_HOST, VPN_GATE_HOST.removesuffix(".opengw.net")} or ip == VPN_GATE_IP:
            if (row.get("OpenVPN_ConfigData_Base64") or "").strip():
                return row
    raise RuntimeError(
        f"The requested VPN Gate server {VPN_GATE_HOST} ({VPN_GATE_IP}) "
        "is not currently present in the live API list."
    )


def _write_vpngate_profile(runtime_dir: Path) -> Path:
    row = _vpngate_row()
    try:
        config = base64.b64decode(row["OpenVPN_ConfigData_Base64"]).decode("utf-8")
    except Exception as exc:
        raise RuntimeError(f"Could not decode the VPN Gate OpenVPN profile: {exc}") from exc

    lines = []
    for line in config.splitlines():
        stripped = line.strip()
        if stripped.startswith("remote ") or stripped.startswith("redirect-gateway"):
            continue
        if stripped.startswith("route ") and "0.0.0.0" in stripped:
            continue
        lines.append(line)

    # OpenVPN 2.7 uses win-dco by default and removed the old Wintun selector.
    # We therefore avoid forcing the obsolete "wintun" driver here.
    lines.extend([
        f"remote {VPN_GATE_HOST} {VPN_GATE_TCP_PORT}",
        "proto tcp-client",
        "route-nopull",
        "pull-filter ignore \"redirect-gateway\"",
        "pull-filter ignore \"block-outside-dns\"",
        "auth-nocache",
        "verb 3",
    ])

    profile = runtime_dir / "capcut-vpngate.ovpn"
    profile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return profile


def _write_split_config(capcut_exe: Path) -> Path:
    appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    root = appdata / "VpnClient"
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / "config.json"
    config = {
        "ovpnFiles": [],
        "activeOvpnId": None,
        "tunneledApps": [{
            "id": "capcut-auto",
            "displayName": "CapCut",
            "exePath": str(capcut_exe),
        }],
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


def _wait_for_vpn_adapter(timeout: float = 60.0) -> None:
    redirector = find_redirector()
    if redirector is None:
        raise RuntimeError("redirector.exe is unavailable.")
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = _run([str(redirector), "adapters"], timeout=20)
        output = f"{result.stdout}\n{result.stderr}"
        if "VPN adapter ready:" in output:
            return
        time.sleep(1)
    raise RuntimeError("OpenVPN did not expose a usable VPN adapter within 60 seconds.")


def start_split_vpn(capcut_exe: Path) -> SplitVpnSession:
    # Fix for the failure shown in the screenshot: the previous version only
    # installed the split-tunnel helper and assumed OpenVPN already existed.
    openvpn = find_openvpn() or install_openvpn()
    redirector = install_split_tunnel_helper()

    runtime_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CapCutBypassedLauncher" / "vpn"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    config_file = _write_split_config(capcut_exe)
    profile = _write_vpngate_profile(runtime_dir)
    auth_file = runtime_dir / "auth.txt"
    auth_file.write_text(f"{VPN_GATE_USERNAME}\n{VPN_GATE_PASSWORD}\n", encoding="utf-8")
    try:
        os.chmod(auth_file, 0o600)
    except OSError:
        pass
    log_file = runtime_dir / "openvpn.log"

    redirector_proc = subprocess.Popen(
        [str(redirector), "observe"],
        cwd=str(redirector.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    time.sleep(2)

    # OpenVPN 2.7.x no longer accepts --windows-driver wintun; the default
    # Windows DCO/TAP stack is selected by the installed client instead.
    openvpn_proc = subprocess.Popen(
        [
            openvpn,
            "--config", str(profile),
            "--auth-user-pass", str(auth_file),
            "--pull-filter", "ignore", "redirect-gateway",
            "--pull-filter", "ignore", "block-outside-dns",
            "--log", str(log_file),
            "--verb", "3",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    session = SplitVpnSession(openvpn, openvpn_proc, redirector_proc, profile, auth_file, config_file)
    try:
        _wait_for_vpn_adapter()
        time.sleep(2)
        if openvpn_proc.poll() is not None:
            log_tail = ""
            try:
                if log_file.is_file():
                    log_tail = log_file.read_text(encoding="utf-8", errors="replace")[-3000:]
            except OSError:
                pass
            raise RuntimeError(
                f"OpenVPN exited unexpectedly with code {openvpn_proc.returncode}.\n"
                f"OpenVPN log: {log_file}\n{log_tail}"
            )
        session.connected = True
        print(f"VPN: {VPN_GATE_HOST}:{VPN_GATE_TCP_PORT} ({VPN_GATE_IP})", flush=True)
        print("Split tunnel: CapCut.exe only; Windows default routing is left unchanged.", flush=True)
        return session
    except Exception:
        stop_split_vpn(session)
        raise


def stop_split_vpn(session: SplitVpnSession | None) -> None:
    if session is None:
        return
    for process in (session.openvpn_process, session.redirector):
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=8)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
    try:
        session.auth_file.unlink(missing_ok=True)
    except OSError:
        pass


def split_vpn_status() -> str:
    redirector = find_redirector()
    if redirector is None:
        return "Process-only OpenVPN split-tunnel helper is not installed."
    result = _run([str(redirector), "adapters"], timeout=15)
    return f"{result.stdout}\n{result.stderr}".strip()
