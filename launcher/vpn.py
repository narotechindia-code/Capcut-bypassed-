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
VPN_GATE_EXPECTED_IP = "118.68.53.211"
VPN_GATE_TCP_PORT = 1653
VPN_GATE_USERNAME = "vpn"
VPN_GATE_PASSWORD = "vpn"
SPLIT_TUNNEL_REPO = "ENA526/OpenVPN-Split-Tunneling"
SPLIT_TUNNEL_INSTALL_ROOT = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "VpnClient"
OPENVPN_VERSION = "2.7.6"
OPENVPN_RELEASE = "I001"
VPN_GATE_MIRRORS = (
    "https://www.vpngate.net",
    "https://vpngate.4d.workers.dev",
    "https://sstp.mehdi-hoore.workers.dev",
)


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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CapCutBypassedLauncher/2.5",
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
    reader = csv.DictReader(lines[header_index:])
    return list(reader)


def _find_row_in_api() -> dict[str, str] | None:
    for _ in range(5):
        try:
            text = _request(VPN_GATE_API, timeout=30).decode("utf-8", errors="replace")
            wanted = VPN_GATE_HOST.lower().rstrip(".")
            for row in _parse_csv_rows(text):
                host = (row.get("HostName") or "").strip().lower().rstrip(".")
                if host == wanted and (row.get("OpenVPN_ConfigData_Base64") or "").strip():
                    return row
        except Exception:
            pass
        time.sleep(2)
    return None


def _extract_server_do_link(page: str) -> str | None:
    """Extract the exact do_openvpn.aspx link for our hostname from a VPN Gate listing page."""
    wanted = VPN_GATE_HOST.lower()
    page = html.unescape(page).replace("&amp;", "&")
    patterns = [
        r"(?:href|action)=[\"']([^\"']*do_openvpn\.aspx\?[^\"']*)[\"']",
        r"(do_openvpn\.aspx\?[^\"'<>\s]+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, page, flags=re.IGNORECASE):
            href = match.group(1)
            if "fqdn=" not in href.lower():
                continue
            query = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            fqdn = urllib.parse.unquote(query.get("fqdn", [""])[0]).lower().rstrip(".")
            if fqdn == wanted:
                return href
    return None


def _build_openvpn_download_url(base: str, do_link: str) -> str | None:
    """Build the documented common/openvpn_download.aspx URL from do_openvpn parameters."""
    href = html.unescape(do_link).replace("&amp;", "&")
    parsed = urllib.parse.urlparse(href)
    params = urllib.parse.parse_qs(parsed.query)
    ip = params.get("ip", [""])[0]
    fqdn = params.get("fqdn", [""])[0]
    tcp = params.get("tcp", ["0"])[0]
    udp = params.get("udp", ["0"])[0]
    sid = params.get("sid", [""])[0]
    hid = params.get("hid", [""])[0]
    if not sid or not hid or not (ip or fqdn):
        return None

    if tcp and tcp != "0":
        transport = {"tcp": "1", "host": ip or fqdn, "port": tcp}
        suffix = f"{ip or fqdn}_tcp_{tcp}.ovpn"
    elif udp and udp != "0":
        transport = {"udp": "1", "host": ip or fqdn, "port": udp}
        suffix = f"{ip or fqdn}_udp_{udp}.ovpn"
    else:
        return None

    query_items = [
        ("sid", sid),
        *transport.items(),
        ("hid", hid),
    ]
    query = urllib.parse.urlencode(query_items)
    return f"{base}/common/openvpn_download.aspx?{query}&/{urllib.parse.quote('vpngate_' + suffix)}"


def _find_do_openvpn_link() -> tuple[str, str] | None:
    """Get the current exact server link from the VPN Gate HTML listing, not a guessed URL."""
    try:
        current_ip = socket.gethostbyname(VPN_GATE_HOST)
    except OSError:
        current_ip = VPN_GATE_EXPECTED_IP

    for base in VPN_GATE_MIRRORS:
        for path in ("/en/", "/"):
            url = f"{base}{path}"
            try:
                page = _request(url, timeout=45).decode("utf-8", errors="replace")
                if VPN_GATE_HOST.lower() not in page.lower() and current_ip not in page:
                    continue
                do_link = _extract_server_do_link(page)
                if not do_link:
                    continue
                absolute = urllib.parse.urljoin(url, do_link)
                parsed = urllib.parse.urlparse(absolute)
                params = urllib.parse.parse_qs(parsed.query)
                tcp = params.get("tcp", ["0"])[0]
                if tcp != str(VPN_GATE_TCP_PORT):
                    continue
                download = _build_openvpn_download_url(base, absolute)
                if download:
                    return absolute, download
            except Exception:
                continue
    return None


def _download_profile_from_link(link: str) -> str:
    content = _request(link, timeout=60).decode("utf-8", errors="replace")
    lowered = content.lower()
    if "client" not in lowered or "<ca>" not in lowered:
        raise RuntimeError("VPN Gate returned an invalid OpenVPN profile.")
    return content


def _write_vpngate_profile(runtime_dir: Path) -> Path:
    row = _find_row_in_api()
    config: str | None = None

    if row:
        live_ip = (row.get("IP") or "unknown").strip()
        if live_ip != VPN_GATE_EXPECTED_IP:
            print(f"VPN Gate server IP changed: screenshot={VPN_GATE_EXPECTED_IP}, live={live_ip}.", flush=True)
        try:
            config = base64.b64decode(row["OpenVPN_ConfigData_Base64"]).decode("utf-8")
        except Exception:
            config = None

    if config is None:
        print("VPN Gate CSV API is unavailable; finding the exact server entry from the live VPN Gate HTML listing...", flush=True)
        found = _find_do_openvpn_link()
        if not found:
            raise RuntimeError(
                f"VPN Gate could not locate the live OpenVPN entry for {VPN_GATE_HOST}:{VPN_GATE_TCP_PORT}. "
                "The server is currently listed, but no matching configuration link was returned."
            )
        server_page, download_link = found
        print(f"VPN Gate server entry found: {server_page}", flush=True)
        print("Downloading the exact TCP OpenVPN profile for the requested server...", flush=True)
        config = _download_profile_from_link(download_link)

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
