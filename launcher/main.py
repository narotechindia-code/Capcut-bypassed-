from __future__ import annotations

import argparse
import os
import platform
import sys
from pathlib import Path

from .capcut import find_capcut, launch_capcut
from .network import capcut_environment, check_tcp_endpoint, get_proxy_from_environment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Windows CapCut launcher")
    parser.add_argument("--capcut", help="Explicit path to CapCut.exe")
    parser.add_argument("--dry-run", action="store_true", help="Detect and validate without launching CapCut")
    parser.add_argument("--no-proxy-check", action="store_true", help="Do not test the configured proxy endpoint")
    return parser.parse_args()


def main() -> int:
    if platform.system() != "Windows":
        print("ERROR: This launcher supports Windows only.")
        return 2

    args = parse_args()
    explicit = args.capcut or os.environ.get("CAPCUT_EXE")
    executable = find_capcut(explicit)

    if executable is None:
        print("CapCut was not found on this PC.")
        print("Install CapCut from its official Windows distribution, then run this launcher again.")
        print("You can also set CAPCUT_EXE to the full path of CapCut.exe.")
        return 10

    print(f"CapCut: {executable}")
    proxy = get_proxy_from_environment()

    if proxy:
        print(f"Proxy: {proxy.scheme}://{proxy.host}:{proxy.port}")
        if not args.no_proxy_check:
            try:
                check_tcp_endpoint(proxy)
            except OSError as exc:
                print(f"ERROR: The configured proxy endpoint is unreachable: {exc}")
                return 20
    else:
        print("Proxy: not configured (CapCut will use its normal network path).")

    if args.dry_run:
        print("Dry run successful. CapCut was detected and configuration is valid.")
        return 0

    try:
        code = launch_capcut(executable, capcut_environment(proxy))
    except OSError as exc:
        print(f"ERROR: Could not launch CapCut: {exc}")
        return 30

    print(f"CapCut exited with code {code}.")
    return code if isinstance(code, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
