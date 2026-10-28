#!/usr/bin/env python3
"""Entry point for the Quectel Pi M2 MPU6050 attitude demo."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from attitude import VERSION
from attitude.config import load_config
from attitude.netinfo import access_urls, hostname
from attitude.server import serve
from attitude.service import AttitudeService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MPU6050 attitude visualisation for Quectel Pi M2"
    )
    parser.add_argument("--host", help="HTTP bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, help="HTTP port (default: 8081)")
    parser.add_argument("--bus", type=int, help="I2C bus number (default: 1)")
    parser.add_argument("--addr", help="I2C address, for example 0x68")
    parser.add_argument("--config", type=Path, help="path to config.json")
    parser.add_argument("--open", action="store_true", help="open the UI in a local browser")
    return parser


def _overrides(args: argparse.Namespace) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    if args.host:
        overrides.setdefault("server", {})["host"] = args.host
    if args.port:
        overrides.setdefault("server", {})["port"] = args.port
    if args.bus is not None:
        overrides.setdefault("i2c", {})["bus"] = args.bus
    if args.addr:
        overrides.setdefault("i2c", {})["address"] = args.addr
    return overrides


def _print_banner(service: AttitudeService, host: str, port: int) -> None:
    status = service.status()
    print("")
    print("=" * 62)
    print(f" IMU Visualization demo {VERSION}  |  Quectel Pi M2 + MPU6050")
    print("=" * 62)
    print(f" Mode      : {status['mode']}")
    print(f" Listening : http://{host}:{port}/")
    if status.get("source"):
        source = status["source"]
        print(
            f" Sensor    : {source.get('chip') or 'not detected'} "
            f"on {source.get('path', 'I2C')} at {source.get('address', '?')}"
        )
    urls = access_urls(port)
    if urls:
        print(" Open from :")
        for entry in urls:
            print(f"   {entry['url']}  ({entry['iface']})")
    else:
        print(f" Open from : http://{hostname()}:{port}/")
    print(" If the sensor is missing, check the I2C wiring.")
    print("=" * 62)
    print(" Press Ctrl+C to stop.")
    print("")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config, _overrides(args))
    host = config["server"]["host"]
    port = config["server"]["port"]

    service = AttitudeService(config)
    service.start()
    try:
        server = serve(service, host, port)
    except OSError as exc:
        print(f"Cannot listen on {host}:{port}: {exc}", file=sys.stderr)
        service.stop()
        return 1

    # Give the acquisition thread a moment so the banner shows real state.
    time.sleep(0.35)
    _print_banner(service, host, port)

    if args.open:
        browser_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        try:
            webbrowser.open(f"http://{browser_host}:{port}/")
        except Exception:  # noqa: BLE001 - a headless board has no browser
            pass

    stop_event = threading.Event()

    def _stop(signum: int, frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    try:
        signal.signal(signal.SIGTERM, _stop)
    except (AttributeError, ValueError):
        pass

    try:
        while not stop_event.wait(0.5):
            pass
    finally:
        server.shutdown()
        server.server_close()
        service.stop()
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
