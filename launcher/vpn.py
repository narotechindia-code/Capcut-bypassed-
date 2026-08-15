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
    changed_mode: bool = False


def _run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


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
    """Install Cloudflare's Windows client through WinGet, then locate warp-cli."""
    cli = find_warp_cli()
    if cli:
        return cli

    winget = shutil.which("winget")
    if not winget:
        raise RuntimeError("Windows Package Manager (winget) is required to install Cloudflare WARP automatically.")

    result = _run(
        [
            winget,
            "install",
            "--id",
            WARP_PACKAGE_ID,
            "--exact",
            "--source",
            "winget",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--disable-interactivity",
        ],
        timeout=180,
    )
    if result.returncode not in (0, 0x8A150014):
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Cloudflare WARP installation failed ({result.returncode}). {detail[-1200:]}")

    # WinGet can update PATH only for future processes, so also check known paths.
    for _ in range(10):
        cli = find_warp_cli()
        if cli:
            return cli
        time.sleep(1)

    raise RuntimeError("Cloudflare WARP was installed/reported installed, but warp-cli.exe could not be found.")


def _status(cli: str) -> str:
    result = _run([cli, "status"], timeout=15)
    return f"{result.stdout}\n{result.stderr}".strip()


def _settings(cli: str) -> str:
    result = _run([cli, "settings"], timeout=15)
    return f"{result.stdout}\n{result.stderr}".strip()


def _is_connected(status: str) -> bool:
    text = status.lower()
    return "connected" in text and "disconnected" not in text


def start_warp_proxy(port: int = WARP_PORT) -> WarpSession:
    """Put WARP into local-proxy mode and connect it.

    Local proxy mode is intentionally used so the launcher can pass the proxy
    only to CapCut. It does not change Windows' global proxy settings.
    """
    cli = install_warp()
    before = _status(cli)
    already_connected = _is_connected(before)

    # Consumer/One Client builds expose these commands on current clients.
    mode = _run([cli, "mode", "proxy"], timeout=20)
    if mode.returncode != 0:
        detail = (mode.stderr or mode.stdout).strip()
        raise RuntimeError(f"Could not enable WARP local proxy mode. {detail[-1200:]}")

    port_result = _run([cli, "proxy", "port", str(port)], timeout=20)
    if port_result.returncode != 0:
        detail = (port_result.stderr or port_result.stdout).strip()
        raise RuntimeError(f"Could not configure WARP proxy port {port}. {detail[-1200:]}")

    connected_by_us = False
    if not already_connected:
        connect = _run([cli, "connect"], timeout=30)
        if connect.returncode != 0:
            detail = (connect.stderr or connect.stdout).strip()
            raise RuntimeError(f"Could not connect WARP. {detail[-1200:]}")
        connected_by_us = True

    # Give the daemon time to open the local listener.
    deadline = time.time() + 20
    while time.time() < deadline:
        status = _status(cli)
        if _is_connected(status):
            return WarpSession(
                cli=cli,
                proxy_url=f"socks5://127.0.0.1:{port}",
                connected_by_us=connected_by_us,
                changed_mode=True,
            )
        time.sleep(1)

    raise RuntimeError("WARP did not reach Connected state within 20 seconds.")


def stop_warp_proxy(session: WarpSession) -> None:
    """Disconnect only when this launcher created the WARP connection."""
    if session.connected_by_us:
        _run([session.cli, "disconnect"], timeout=20)


def warp_status() -> str:
    cli = find_warp_cli()
    if not cli:
        return "Cloudflare WARP is not installed."
    return _status(cli)
