from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    from .capcut import find_capcut, launch_capcut
    from .vpn import start_split_vpn, stop_split_vpn, split_vpn_status
except ImportError:
    from capcut import find_capcut, launch_capcut
    from vpn import start_split_vpn, stop_split_vpn, split_vpn_status

CAPCUT_WINGET_ID = "ByteDance.CapCut"
LOG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CapCutBypassedLauncher" / "logs"


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


def _is_admin() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _write_log(message: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / "launcher.log").open("a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except Exception:
        pass


def _run_command(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def install_capcut() -> Path | None:
    existing = find_capcut()
    if existing:
        return existing
    winget = shutil.which("winget.exe") or shutil.which("winget")
    if not winget:
        raise RuntimeError("Windows Package Manager (winget) is not available for the automatic CapCut install.")
    print("CapCut is not installed. Installing the official CapCut package through WinGet...", flush=True)
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
        print("ERROR: This launcher supports Windows only.", flush=True)
        return 2

    args = parse_args()
    if args.vpn_status:
        print(split_vpn_status(), flush=True)
        return 0

    # VPN split-tunneling requires an elevated process. Elevation is handled by
    # run.ps1 before Python starts so the Python console does not flash and exit.
    if args.mode in ("auto", "vpn") and not _is_admin():
        message = "Administrator privileges are required for VPN split tunneling. Start the PowerShell launcher again."
        _write_log(message)
        print(f"ERROR: {message}", flush=True)
        return 12

    _write_log(f"Starting launcher: mode={args.mode}, argv={sys.argv[1:]}")
    executable = find_capcut(args.capcut or os.environ.get("CAPCUT_EXE"))
    if executable is None and not args.no_install and not args.capcut and not os.environ.get("CAPCUT_EXE"):
        try:
            executable = install_capcut()
        except Exception as exc:
            _write_log(f"CapCut install failed: {exc}")
            print(f"ERROR: {exc}", flush=True)
            return 11

    if executable is None:
        message = "CapCut was not found on this PC. Install the official Windows CapCut application, then rerun this launcher."
        _write_log(message)
        print(message, flush=True)
        print("Or set CAPCUT_EXE to the full path of CapCut.exe.", flush=True)
        return 10

    print(f"CapCut: {executable}", flush=True)
    session = None
    try:
        if args.mode in ("auto", "vpn"):
            print("Network mode: VPN Gate split tunnel (CapCut only)", flush=True)
            session = start_split_vpn(executable)
        else:
            print("Network mode: direct Windows connection", flush=True)

        if args.dry_run:
            print("Dry run successful.", flush=True)
            return 0

        print("Starting CapCut...", flush=True)
        code = launch_capcut(executable, os.environ.copy())
        print(f"CapCut exited with code {code}.", flush=True)
        _write_log(f"CapCut exited with code {code}")
        return code if isinstance(code, int) else 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        _write_log(f"ERROR: {type(exc).__name__}: {exc}")
        print(f"ERROR: {exc}", flush=True)
        return 30
    finally:
        if session is not None:
            try:
                stop_split_vpn(session)
                print("VPN session cleaned up; normal Windows routing restored.", flush=True)
                _write_log("VPN session cleaned up")
            except Exception as exc:
                _write_log(f"VPN cleanup error: {exc}")
                print(f"WARNING: VPN cleanup error: {exc}", flush=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        _write_log("Interrupted by user")
        print("\nLauncher interrupted.", flush=True)
        raise SystemExit(130)
    except BaseException as exc:
        _write_log(f"FATAL: {type(exc).__name__}: {exc}")
        print(f"FATAL ERROR: {exc}", flush=True)
        raise SystemExit(99)
