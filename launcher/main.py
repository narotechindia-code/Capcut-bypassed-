from __future__ import annotations

import argparse
import os
import platform

from .capcut import find_capcut, launch_capcut
from .network import capcut_environment, check_tcp_endpoint, get_proxy_from_environment
from .vpn import start_warp_proxy, stop_warp_proxy, warp_status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Windows CapCut launcher")
    parser.add_argument("--capcut", help="Explicit path to CapCut.exe")
    parser.add_argument(
        "--mode", choices=("auto", "warp", "proxy", "direct"), default="auto",
        help="auto=try WARP then configured proxy; warp=Cloudflare WARP; proxy=CAPCUT_PROXY; direct=normal network",
    )
    parser.add_argument("--dry-run", action="store_true", help="Detect and validate without launching CapCut")
    parser.add_argument("--no-proxy-check", action="store_true", help="Skip local proxy TCP reachability test")
    parser.add_argument("--warp-status", action="store_true", help="Print WARP status and exit")
    return parser.parse_args()


def main() -> int:
    if platform.system() != "Windows":
        print("ERROR: This launcher supports Windows only.")
        return 2

    args = parse_args()
    if args.warp_status:
        print(warp_status())
        return 0

    executable = find_capcut(args.capcut or os.environ.get("CAPCUT_EXE"))
    if executable is None:
        print("CapCut was not found on this PC.")
        print("Install the official Windows CapCut application, then rerun this launcher.")
        print("Or set CAPCUT_EXE to the full path of CapCut.exe.")
        return 10

    print(f"CapCut: {executable}")
    session = None
    proxy_config = None

    try:
        configured_proxy = get_proxy_from_environment()

        if args.mode in ("auto", "warp"):
            try:
                print("Network mode: Cloudflare WARP local proxy")
                session = start_warp_proxy()
                os.environ["CAPCUT_PROXY"] = session.proxy_url
                proxy_config = get_proxy_from_environment()
                print(f"CapCut proxy: {session.proxy_url}")
            except Exception as exc:
                if args.mode == "warp":
                    print(f"ERROR: WARP mode could not be started: {exc}")
                    return 20
                print(f"WARP unavailable: {exc}")

        if session is None and args.mode in ("auto", "proxy"):
            if configured_proxy:
                proxy_config = configured_proxy
                print(f"Network mode: configured {configured_proxy.scheme.upper()} proxy")
            elif args.mode == "proxy":
                print("ERROR: --mode proxy requires CAPCUT_PROXY.")
                return 21
            elif args.mode == "auto":
                print("ERROR: No working WARP or configured proxy is available.")
                print("Refusing to launch directly because the purpose of this launcher is the CapCut network route.")
                return 22

        if args.mode == "direct":
            proxy_config = None
            print("Network mode: direct Windows connection")

        if proxy_config and not args.no_proxy_check:
            check_tcp_endpoint(proxy_config)
            print("Proxy endpoint: reachable")

        if args.dry_run:
            print("Dry run successful.")
            return 0

        code = launch_capcut(executable, capcut_environment(proxy_config))
        print(f"CapCut exited with code {code}.")
        return code if isinstance(code, int) else 0

    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 30
    finally:
        if session is not None:
            try:
                stop_warp_proxy(session)
                print("WARP session cleaned up.")
            except Exception as exc:
                print(f"WARNING: WARP cleanup failed: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
