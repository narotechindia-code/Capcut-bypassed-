from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

WARP_PORT = int(os.environ.get("CAPCUT_WARP_PORT", "40000"))
WARP_PACKAGE_ID = "Cloudflare.Warp"

@dataclass
class WarpSession:
    cli: str
    proxy_url: str
    connected_by_us: bool = False


def _run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def find_warp_cli() -> str | None:
    found = shutil.which("warp-cli")
    if found:
        return found
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Cloudflare" / "Cloudflare WARP" / "warp-cli.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Cloudflare" / "Cloudflare One Client" / "warp-cli.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Cloudflare" / "Cloudflare WARP" / "warp-cli.exe",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def install_warp() -> str:
    cli = find_warp_cli()
    if cli:
        return cli
    winget = shutil.which("winget")
    if not winget:
        raise RuntimeError("winget is required to install Cloudflare WARP automatically. Install WARP manually and rerun.")
    result = _run([winget, "install", "--id", WARP_PACKAGE_ID, "--exact", "--source", "winget",
                   "--silent", "--accept-package-agreements", "--accept-source-agreements",
                   "--disable-interactivity"], timeout=180)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"WARP installation failed ({result.returncode}). {detail[-1200:]}")
    for _ in range(15):
        cli = find_warp_cli()
        if cli:
            return cli
        time.sleep(1)
    raise RuntimeError("WARP installed but warp-cli.exe was not found.")


def _status(cli: str) -> str:
    result = _run([cli, "status"], timeout=15)
    return f"{result.stdout}\n{result.stderr}".strip()


def _is_connected(status: str) -> bool:
    text = status.lower()
    return "connected" in text and "disconnected" not in text


def _ensure_registered(cli: str) -> None:
    result = _run([cli, "registration", "show"], timeout=15)
    text = f"{result.stdout}\n{result.stderr}".lower()
    if result.returncode == 0 and "account type" in text:
        return
    register = _run([cli, "registration", "new"], timeout=60)
    if register.returncode != 0:
        detail = (register.stderr or register.stdout).strip()
        raise RuntimeError("WARP is not registered and automatic registration failed. " + detail[-1000:])


def _set_proxy_mode(cli: str) -> None:
    result = _run([cli, "mode", "proxy"], timeout=20)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Could not enable WARP local-proxy mode. {detail[-1200:]}")


def _set_proxy_port(cli: str, port: int) -> None:
    current = _run([cli, "proxy", "port", str(port)], timeout=20)
    if current.returncode == 0:
        return
    legacy = _run([cli, "set-proxy-port", str(port)], timeout=20)
    if legacy.returncode == 0:
        return
    detail = (legacy.stderr or legacy.stdout or current.stderr or current.stdout).strip()
    raise RuntimeError(f"Could not configure WARP proxy port {port}. {detail[-1200:]}")


def start_warp_proxy(port: int = WARP_PORT) -> WarpSession:
    """Start WARP local-proxy mode; only CapCut receives the proxy settings."""
    cli = install_warp()
    already_connected = _is_connected(_status(cli))
    _ensure_registered(cli)
    _set_proxy_mode(cli)
    _set_proxy_port(cli, port)

    connected_by_us = False
    if not already_connected:
        result = _run([cli, "connect"], timeout=45)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"Could not connect WARP. {detail[-1200:]}")
        connected_by_us = True

    deadline = time.time() + 30
    while time.time() < deadline:
        if _is_connected(_status(cli)):
            return WarpSession(cli, f"socks5://127.0.0.1:{port}", connected_by_us)
        time.sleep(1)
    raise RuntimeError("WARP did not reach Connected state within 30 seconds.")


def stop_warp_proxy(session: WarpSession) -> None:
    if session.connected_by_us:
        _run([session.cli, "disconnect"], timeout=20)


def warp_status() -> str:
    cli = find_warp_cli()
    return "Cloudflare WARP is not installed." if not cli else _status(cli)
