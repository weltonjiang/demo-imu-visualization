"""LAN address discovery for the access URL shown in the UI and console."""

from __future__ import annotations

import shutil
import socket
import subprocess
from typing import Dict, List


def hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "quectel-pi"


def _from_ip_command() -> List[Dict[str, str]]:
    if not shutil.which("ip"):
        return []
    try:
        result = subprocess.run(
            ["ip", "-4", "-o", "addr", "show"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    entries: List[Dict[str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[2] != "inet":
            continue
        iface = parts[1].rstrip(":")
        address = parts[3].split("/")[0]
        if address.startswith("127."):
            continue
        if iface.startswith(("docker", "veth", "br-", "virbr", "tun", "tap")):
            continue
        entries.append({"iface": iface, "address": address})
    return entries


def _fallback_primary() -> List[Dict[str, str]]:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
        finally:
            sock.close()
    except OSError:
        return []
    if not address or address.startswith("127."):
        return []
    return [{"iface": "default", "address": address}]


def addresses() -> List[Dict[str, str]]:
    entries = _from_ip_command()
    if not entries:
        entries = _fallback_primary()
    # Prefer Wi-Fi / Ethernet style interfaces, keep them unique by address.
    seen = set()
    unique: List[Dict[str, str]] = []
    for entry in entries:
        if entry["address"] in seen:
            continue
        seen.add(entry["address"])
        unique.append(entry)
    return unique


def access_urls(port: int) -> List[Dict[str, str]]:
    return [
        {"iface": entry["iface"], "url": f"http://{entry['address']}:{port}/"}
        for entry in addresses()
    ]
