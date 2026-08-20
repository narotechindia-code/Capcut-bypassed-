from __future__ import annotations

import base64
import csv
import html
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

VPN_GATE_API = "https://www.vpngate.net/api/iphone/"
VPN_GATE_HOST = "vpn242832503.opengw.net"
VPN_GATE_EXPECTED_IP = "118.68.53.211"  # screenshot value; may change over time
VPN_GATE_TCP_PORT = 1653
VPN_GATE_USERNAME = "vpn"
VPN_GATE_PASSWORD = "vpn"
SPLIT_TUNNEL_REPO = "ENA526/OpenVPN-Split-Tunneling"
SPLIT_TUNNEL_INSTALL_ROOT = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "VpnClient"
OPENVPN_VERSION = "2.7.6"
OPENVPN_RELEASE = "I001"


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


def _request(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "CapCutBypassedLauncher/2.4",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def _download(url: str, destination: Path, timeout: int = 120) -> None:
    data = _request(url, timeout=timeout)
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
    existing = find_openvpn()
    if existing:
        return existing
    arch = platform.machine().lower()
    if arch in {"arm64", "aarch64"}:
        msi_name = f"OpenVPN-{OPENVPN_VERSION}-{OPENVPN_RELEASE}-arm64.msi"
    elif arch in {"x86", "i386", "i686"}:
        msi_name = f"OpenVPN-{OPENVPN_VERSION}-{OPENVPN_RELEASE}-x86.msi"
    else:
        msi_name = f"OpenVPN-{OPENVPN_VERSION}-{OPENVPN_RELEASE}-amd64.msi"
    msi = Path(tempfile.gettempdir()) / msi_name
    print(f"OpenVPN Community is not installed. Downloading official OpenVPN {OPENVPN_VERSION}...", flush=True)
    try:
        _download(f"https://swupdate.openvpn.org/community/releases/{msi_name}", msi, timeout=180)
    except Exception as exc:
        raise RuntimeError(f"Could not download the official OpenVPN installer: {exc}") from exc
    print("Installing OpenVPN silently (Administrator privileges are already active)...", flush=True)
    result = _run(["msiexec.exe", "/i", str(msi), "/qn", "/norestart"], timeout=900)
    try:
        msi.unlink(missing_ok=True)
    except OSError:
        pass
    if result.returncode not in (0, 3010):
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"OpenVPN installation failed (msiexec exit code {result.returncode}). {detail[-1800:]}")
    deadline = time.time() + 120
    while time.time() < deadline:
        found = find_openvpn()
        if found:
            print(f"OpenVPN installed: {found}", flush=True)
            return found
        time.sleep(2)
    raise RuntimeError("OpenVPN installation completed, but openvpn.exe was not detected.")


def find_redirector() -> Path | None:
    candidate = SPLIT_TUNNEL_INSTALL_ROOT / "redirector.exe"
    return candidate if candidate.is_file() else None


def install_split_tunnel_helper() -> Path:
    redirector = find_redirector()
    if redirector:
        return redirector
    api_url = f"https://api.github.com/repos/{SPLIT_TUNNEL_REPO}/releases/latest"
    response = json.loads(_request(api_url, timeout=30).decode("utf-8"))
    installer = next(
        (
            asset for asset in response.get("assets", [])
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


def _parse_csv_rows(text: str) -> list[dict[str, str]]:
    lines = [line for line in text.splitlines() if line.strip()]
    header_index = next((i for i, line in enumerate(lines) if line.startswith("#HostName,")), None)
    if header_index is None:
        return []
    reader = csv.DictReader(lines[header_index:], restval="")
    return list(reader)


def _find_row_in_api() -> dict[str, str] | None:
    for _ in range(5):
        try:
            text = _request(VPN_GATE_API, timeout=30).decode("utf-8", errors="replace")
            rows = _parse_csv_rows(text)
            wanted = VPN_GATE_HOST.lower().rstrip(".")
            for row in rows:
                host = (row.get("HostName") or "").strip().lower().rstrip(".")
                if host == wanted and (row.get("OpenVPN_ConfigData_Base64") or "").strip():
                    return row
        except Exception:
            pass
        time.sleep(2)
    return None


def _find_do_openvpn_link() -> str | None:
    """Fallback when the CSV API is blocked/empty: use the live VPN Gate server page."""
    try:
        ip = socket.gethostbyname(VPN_GATE_HOST)
    except OSError:
        ip = VPN_GATE_EXPECTED_IP

    # VPN Gate exposes a do_openvpn.aspx page for individual servers. Its query
    # parameters do not require the CSV API session ID; the page contains the
    # current openvpn_download.aspx link including the required sid/hid values.
    query = urllib.parse.urlencode({
        "fqdn": VPN_GATE_HOST,
        "ip": ip,
        "tcp": str(VPN_GATE_TCP_PORT),
        "udp": "0",
    })
    urls = [
        f"https://www.vpngate.net/en/do_openvpn.aspx?{query}",
        f"http://www.vpngate.net/en/do_openvpn.aspx?{query}",
    ]
    for url in urls:
        try:
            page = _request(url, timeout=30).decode("utf-8", errors="replace")
            # Prefer a TCP OpenVPN download link for the requested port.
            for match in re.finditer(r"(?:href|action)=[\"']([^\"']*openvpn_download\.aspx[^\"']*)[\"']", page, flags=re.IGNORECASE):
                href = html.unescape(match.group(1)).replace("&amp;", "&")
                if "tcp=1" not in href.lower():
                    continue
                if "port=" in href.lower() and f"port={VPN_GATE_TCP_PORT}" not in href.lower():
                    continue
                return urllib.parse.urljoin(url, href)
        except Exception:
            continue
    return None


def _download_profile_from_link(link: str) -> str:
    content = _request(link, timeout=60).decode("utf-8", errors="replace")
    if "client" not in content.lower() or "<ca>" not in content.lower():
        raise RuntimeError("VPN Gate returned an invalid OpenVPN profile.")
    return content


def _vpngate_row() -> dict[str, str] | None:
    row = _find_row_in_api()
    if row:
        live_ip = (row.get("IP") or "unknown").strip()
        if live_ip != VPN_GATE_EXPECTED_IP:
            print(f"VPN Gate server IP changed: screenshot={VPN_GATE_EXPECTED_IP}, live={live_ip}.", flush=True)
        return row
    return None


def _write_vpngate_profile(runtime_dir: Path) -> Path:
    row = _vpngate_row()
    config: str | None = None

    if row:
        try:
            config = base64.b64decode(row["OpenVPN_ConfigData_Base64"]).decode("utf-8")
        except Exception:
            config = None

    if config is None:
        print("VPN Gate CSV API is unavailable; switching to direct server-page profile retrieval...", flush=True)
        link = _find_do_openvpn_link()
        if not link:
            raise RuntimeError(
                f"VPN Gate could not provide an OpenVPN profile for {VPN_GATE_HOST}:{VPN_GATE_TCP_PORT}. "
                "The server is visible in current VPN Gate listings, but its direct configuration page could not be retrieved."
            )
        config = _download_profile_from_link(link)

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
    config = {"ovpnFiles": [], "activeOvpnId": None, "tunneledApps": [{"id": "capcut-auto", "displayName": "CapCut", "exePath": str(capcut_exe)}]}
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
    openvpn_proc = subprocess.Popen(
        [
            openvpn,
            "--config", str(profile),
            "--auth-user-pass", str(auth_file),
            "--pull-filter", "ignore", "redirect-gateway",
            "--pull-filter", "ignore", "block-outside-dns",
            "--log", str(log_file), "--verb", "3",
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
        try:
            live_ip = socket.gethostbyname(VPN_GATE_HOST)
        except OSError:
            live_ip = "unknown"
        print(f"VPN: {VPN_GATE_HOST}:{VPN_GATE_TCP_PORT} (live DNS {live_ip})", flush=True)
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
