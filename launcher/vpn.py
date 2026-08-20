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
    req = urllib.request.Request(url, headers={"User-Agent": "CapCutBypassedLauncher/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def find_openvpn() -> str | None:
    candidates = [
        shutil.which("openvpn.exe"),
        str(Path(os.environ.get("PROGRAMFILES", "")) / "OpenVPN" / "bin" / "openvpn.exe"),
        str(Path(os.environ.get("PROGRAMFILES(X86)", "")) / "OpenVPN" / "bin" / "openvpn.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def find_redirector() -> Path | None:
    candidate = SPLIT_TUNNEL_INSTALL_ROOT / "redirector.exe"
    return candidate if candidate.is_file() else None


def install_split_tunnel_helper() -> Path:
    """Install the external MIT split-tunnel helper used for process-only routing."""
    redirector = find_redirector()
    if redirector:
        return redirector

    api_url = f"https://api.github.com/repos/{SPLIT_TUNNEL_REPO}/releases/latest"
    req = urllib.request.Request(api_url, headers={"User-Agent": "CapCutBypassedLauncher/2.0"})
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
    print("Installing the process-only OpenVPN split-tunnel helper...")
    _download(str(installer["browser_download_url"]), temp, timeout=180)
    result = _run([str(temp), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"], timeout=600)
    try:
        temp.unlink(missing_ok=True)
    except OSError:
        pass
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Split-tunnel helper installation failed ({result.returncode}). {detail[-1200:]}")

    deadline = time.time() + 60
    while time.time() < deadline:
        redirector = find_redirector()
        if redirector:
            return redirector
        time.sleep(2)
    raise RuntimeError("Split-tunnel helper installed, but redirector.exe was not found.")


def _vpngate_row() -> dict[str, str]:
    req = urllib.request.Request(VPN_GATE_API, headers={"User-Agent": "CapCutBypassedLauncher/2.0"})
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
    raise RuntimeError(f"The requested VPN Gate server {VPN_GATE_HOST} ({VPN_GATE_IP}) is not currently present in the live API list.")


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


def _wait_for_vpn_adapter(timeout: float = 45.0) -> None:
    redirector = find_redirector()
    if redirector is None:
        raise RuntimeError("redirector.exe is unavailable.")
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = _run([str(redirector), "adapters"], timeout=15)
        output = f"{result.stdout}\n{result.stderr}"
        if "VPN adapter ready:" in output:
            return
        time.sleep(1)
    raise RuntimeError("OpenVPN did not expose a usable VPN adapter within 45 seconds.")


def start_split_vpn(capcut_exe: Path) -> SplitVpnSession:
    redirector = install_split_tunnel_helper()
    openvpn = find_openvpn()
    if openvpn is None:
        deadline = time.time() + 30
        while time.time() < deadline and openvpn is None:
            time.sleep(1)
            openvpn = find_openvpn()
    if openvpn is None:
        raise RuntimeError("OpenVPN Community was not found after installing the split-tunnel helper.")

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

    openvpn_proc = subprocess.Popen(
        [
            openvpn,
            "--config", str(profile),
            "--auth-user-pass", str(auth_file),
            "--windows-driver", "wintun",
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
            raise RuntimeError(f"OpenVPN exited unexpectedly with code {openvpn_proc.returncode}. See {log_file}")
        session.connected = True
        print(f"VPN: {VPN_GATE_HOST}:{VPN_GATE_TCP_PORT} ({VPN_GATE_IP})")
        print("Split tunnel: CapCut.exe only; Windows default routing is left unchanged.")
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
