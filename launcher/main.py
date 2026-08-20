from __future__ import annotations

import argparse
import ctypes
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

try:
    from .capcut import find_capcut, launch_capcut
    from .vpn import start_split_vpn, stop_split_vpn, split_vpn_status
except ImportError:
    from capcut import find_capcut, launch_capcut
    from vpn import start_split_vpn, stop_split_vpn, split_vpn_status

CAPCUT_WINGET_ID = "ByteDance.CapCut"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Windows CapCut process-only VPN launcher")
    parser.add_argument("--capcut", help="Explicit path to CapCut.exe")
    parser.add_argument(
        "--mode", choices=("auto", "vpn", "direct"), default="auto",
        help="auto/vpn=VPN Gate split tunnel; direct=normal Windows networking",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate dependencies without launching CapCut")
    parser.add_argument("--no-install", action="store_true", help="Do not automatically install CapCut when missing")
    parser.add_argument("--vpn-status", action="store_true", help="Show split-tunnel VPN adapter status and exit")
    return parser.parse_args()


def _run_command(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _is_admin() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _elevate() -> bool:
    """Re-launch this module with UAC; return True in the parent process."""
    if _is_admin():
        return False
    root = Path(__file__).resolve().parent.parent
    params = subprocess.list2cmdline(["-m", "launcher.main", *os.sys.argv[1:]])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", os.sys.executable, params, str(root), 1)
    if rc <= 32:
        raise RuntimeError(f"Administrator elevation was refused or failed (ShellExecute code {rc}).")
    return True


def install_capcut() -> Path | None:
    existing = find_capcut()
    if existing:
        return existing
    winget = shutil.which("winget.exe") or shutil.which("winget")
    if not winget:
        raise RuntimeError("Windows Package Manager (winget) is not available for the automatic CapCut install.")
    print("CapCut is not installed. Installing the official CapCut package through WinGet...")
    result = _run_command(
        [winget, "install", "--id", CAPCUT_WINGET_ID, "--exact", "--source", "winget",
         "--silent", "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"],
        timeout=600,
    )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    if result.returncode not in (0, 0x8A150014):
        raise RuntimeError(f"CapCut installation failed (WinGet exit code {result.returncode}).\n{output[-1800:]}")
    deadline = time.time() + 90
    while time.time() < deadline:
        executable = find_capcut()
        if executable:
            return executable
        time.sleep(2)
    raise RuntimeError("WinGet completed, but CapCut.exe could not be detected.")


def main() -> int:
    if platform.system() != "Windows":
        print("ERROR: This launcher supports Windows only.")
        return 2

    args = parse_args()
    if args.vpn_status:
        print(split_vpn_status())
        return 0

    if args.mode in ("auto", "vpn") and not _is_admin():
        try:
            if _elevate():
                return 0
        except Exception as exc:
            print(f"ERROR: {exc}")
            return 12

    executable = find_capcut(args.capcut or os.environ.get("CAPCUT_EXE"))
    if executable is None and not args.no_install and not args.capcut and not os.environ.get("CAPCUT_EXE"):
        try:
            executable = install_capcut()
        except Exception as exc:
            print(f"ERROR: {exc}")
            return 11

    if executable is None:
        print("CapCut was not found on this PC.")
        print("Install the official Windows CapCut application, then rerun this launcher.")
        print("Or set CAPCUT_EXE to the full path of CapCut.exe.")
        return 10

    print(f"CapCut: {executable}")
    session = None
    try:
        if args.mode in ("auto", "vpn"):
            print("Network mode: VPN Gate split tunnel (CapCut only)")
            session = start_split_vpn(executable)
        else:
            print("Network mode: direct Windows connection")

        if args.dry_run:
            print("Dry run successful.")
            return 0

        code = launch_capcut(executable, os.environ.copy())
        print(f"CapCut exited with code {code}.")
        return code if isinstance(code, int) else 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 30
    finally:
        if session is not None:
            stop_split_vpn(session)
            print("VPN session cleaned up; normal Windows routing restored.")


if __name__ == "__main__":
    raise SystemExit(main())
