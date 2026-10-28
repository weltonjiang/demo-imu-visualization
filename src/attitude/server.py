"""Static web server and JSON API (standard library only)."""

from __future__ import annotations

import datetime
import gzip
import json
import mimetypes
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from . import VERSION, netinfo
from .config import WEB_DIR

_ASSET_CACHE: Dict[str, Tuple[bytes, Optional[bytes], str, str]] = {}
_COMPRESSIBLE = ("text/", "application/javascript", "application/json", "image/svg+xml")

_STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/style.css": "style.css",
    "/app.js": "app.js",
    "/scene3d.js": "scene3d.js",
    "/horizon.js": "horizon.js",
    "/chart.js": "chart.js",
    "/vendor/three.min.js": "vendor/three.min.js",
    "/assets/m2-board-top.png": "assets/m2-board-top.png",
    "/assets/m2-board-bottom.png": "assets/m2-board-bottom.png",
}

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


def _load_asset(path: Path, key: str) -> Tuple[bytes, Optional[bytes], str, str]:
    try:
        stat = path.stat()
    except OSError:
        return b"", None, '"0"', "application/octet-stream"
    etag = '"{:x}-{:x}"'.format(int(stat.st_mtime), stat.st_size)
    cached = _ASSET_CACHE.get(key)
    if cached is not None and cached[2] == etag:
        return cached

    raw = path.read_bytes()
    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    if content_type.startswith("text/") or content_type in (
        "application/javascript",
        "application/json",
        "image/svg+xml",
    ):
        content_type += "; charset=utf-8"
    gz: Optional[bytes] = None
    if content_type.startswith(_COMPRESSIBLE):
        try:
            candidate = gzip.compress(raw, 6)
            gz = candidate if len(candidate) < len(raw) * 0.95 else None
        except OSError:
            gz = None
    entry = (raw, gz, etag, content_type)
    _ASSET_CACHE[key] = entry
    return entry


class AttitudeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: Tuple[str, int], service: Any, web_dir: Path) -> None:
        super().__init__(address, AttitudeRequestHandler)
        self.service = service
        self.web_dir = Path(web_dir)


class AttitudeRequestHandler(BaseHTTPRequestHandler):
    disable_nagle_algorithm = True
    server_version = f"AttitudeSensorDemo/{VERSION}"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, TimeoutError):
            self.close_connection = True

    def finish(self) -> None:
        try:
            super().finish()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, OSError):
            pass

    @property
    def app(self) -> AttitudeHTTPServer:
        return self.server  # type: ignore[return-value]

    # ---------------------------------------------------------------- helpers
    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _error(self, message: str, status: int = 400) -> None:
        self._send_json({"ok": False, "error": message}, status)

    def _read_json(self) -> Optional[Dict[str, Any]]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _status_payload(self) -> Dict[str, Any]:
        payload = self.app.service.status()
        port = int(self.app.server_address[1])
        payload["net"] = {
            "hostname": netinfo.hostname(),
            "urls": netinfo.access_urls(port),
            "port": port,
        }
        return payload

    def _send_static(self, route: str) -> None:
        filename = _STATIC_FILES.get(route)
        if filename is None:
            self._error("unknown static asset", 404)
            return
        path = self.app.web_dir / filename
        if not path.is_file():
            self._error(f"missing frontend file: {filename}", 404)
            return
        raw, gz, etag, content_type = _load_asset(path, filename)

        if self.headers.get("If-None-Match") == etag:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return

        accepts_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "").lower()
        body = gz if (accepts_gzip and gz is not None) else raw
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Vary", "Accept-Encoding")
        if accepts_gzip and gz is not None:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    # ---------------------------------------------------------------- routes
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in _STATIC_FILES:
            self._send_static(path)
            return
        if path == "/api/attitude":
            self._send_json({"ok": True, "attitude": self.app.service.snapshot(), "server_time": time.time()})
            return
        if path == "/api/status":
            self._send_json(self._status_payload())
            return
        if path == "/api/health":
            status = self.app.service.status()
            self._send_json({"ok": True, "state": status["state"], "uptime_s": status["uptime_s"]})
            return
        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._error(f"unknown path: {path}", 404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        data = self._read_json()
        if data is None:
            self._error("request body is not valid JSON")
            return
        service = self.app.service

        try:
            if path == "/api/calibrate":
                result = service.request("calibrate", timeout=12.0)
                self._send_json({"ok": bool(result.get("ok")), **result, "status": self._status_payload()})
                return
            if path == "/api/tare":
                result = service.request("tare", timeout=4.0)
                self._send_json({"ok": bool(result.get("ok")), **result, "status": self._status_payload()})
                return
            if path == "/api/pause":
                paused = bool(data.get("paused", True))
                result = service.request("pause", value=paused, timeout=4.0)
                self._send_json({"ok": bool(result.get("ok")), **result, "status": self._status_payload()})
                return
            if path == "/api/client_log":
                self._client_log(data)
                return
        except Exception as exc:  # noqa: BLE001 - defensive API boundary
            self._error(f"request failed: {type(exc).__name__}: {exc}", 500)
            return
        self._error(f"unknown API: {path}", 404)

    def _client_log(self, data: Dict[str, Any]) -> None:
        try:
            text = json.dumps(data, ensure_ascii=False)[:4000]
        except Exception:  # noqa: BLE001
            text = "<unserializable>"
        path = Path(os.path.expanduser("~/attitude-client-errors.log"))
        try:
            with path.open("a", encoding="utf-8") as handle:
                stamp = datetime.datetime.now().strftime("%m-%d %H:%M:%S")
                handle.write(f"{stamp} {text}\n")
            if path.stat().st_size > 200_000:
                path.replace(path.with_suffix(".log.old"))
        except OSError:
            pass
        self._send_json({"ok": True})


def create_server(
    service: Any,
    host: str,
    port: int,
    web_dir: Optional[Path] = None,
) -> AttitudeHTTPServer:
    return AttitudeHTTPServer((host, port), service, web_dir or WEB_DIR)


def serve(
    service: Any,
    host: str,
    port: int,
    web_dir: Optional[Path] = None,
) -> AttitudeHTTPServer:
    server = create_server(service, host, port, web_dir)
    thread = threading.Thread(target=server.serve_forever, name="attitude-http", daemon=True)
    thread.start()
    return server
