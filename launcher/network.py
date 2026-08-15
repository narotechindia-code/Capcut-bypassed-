from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class ProxyConfig:
    url: str
    scheme: str
    host: str
    port: int


def parse_proxy(value: str) -> ProxyConfig:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https", "socks4", "socks5"}:
        raise ValueError("Proxy must use http, https, socks4, or socks5.")
    if not parsed.hostname or not parsed.port:
        raise ValueError("Proxy must include a hostname and port.")
    return ProxyConfig(value, parsed.scheme.lower(), parsed.hostname, parsed.port)


def get_proxy_from_environment() -> ProxyConfig | None:
    raw = os.environ.get("CAPCUT_PROXY", "").strip()
    return parse_proxy(raw) if raw else None


def check_tcp_endpoint(proxy: ProxyConfig, timeout: float = 5.0) -> None:
    with socket.create_connection((proxy.host, proxy.port), timeout=timeout):
        return


def capcut_environment(proxy: ProxyConfig | None) -> dict[str, str]:
    env = os.environ.copy()
    if proxy:
        # These variables are inherited by CapCut's process only; Windows' global
        # proxy configuration is not changed by this function.
        env["HTTP_PROXY"] = proxy.url
        env["HTTPS_PROXY"] = proxy.url
        env["ALL_PROXY"] = proxy.url
        env["http_proxy"] = proxy.url
        env["https_proxy"] = proxy.url
        env["all_proxy"] = proxy.url
    return env
