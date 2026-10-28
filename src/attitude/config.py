"""Configuration for the IMU visualization demo.

The file config.json at the project root is the single source of tunables.
CLI flags in main.py override a few fields after loading.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Optional

VERSION = "1.0.0"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"

DEFAULTS: Dict[str, Any] = {
    "server": {
        "host": "0.0.0.0",
        "port": 8081,
    },
    "i2c": {
        "bus": 1,
        "address": "0x68",
        "auto_detect": True,
    },
    "sensor": {
        "sample_rate_hz": 100,
        "gyro_range_dps": 500,
        "accel_range_g": 2,
        "dlpf_hz": 42,
        # Treat the still pose during calibration as the board's level reference.
        # Handles an upside-down or slightly tilted sensor mount.
        "level_on_start": True,
        # Mounting correction. Each key selects a source axis, optionally
        # negated, e.g. {"x": "y", "y": "-x", "z": "z"}.
        "axis_map": {"x": "x", "y": "y", "z": "z"},
    },
    "fusion": {
        "beta": 0.08,
    },
    "calibration": {
        "seconds": 2.0,
        "auto": True,
        "still_spread_dps": 2.0,
    },
}


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def parse_address(value: Any) -> int:
    """Accept 0x68, "0x68" or 104."""
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    return int(text, 10)


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    server = data.setdefault("server", {})
    server["host"] = str(server.get("host") or "0.0.0.0")
    server["port"] = max(1, min(65535, int(server.get("port") or 8081)))

    i2c = data.setdefault("i2c", {})
    i2c["bus"] = max(0, int(i2c.get("bus", 1)))
    i2c["address"] = parse_address(i2c.get("address", "0x68"))
    i2c["auto_detect"] = bool(i2c.get("auto_detect", True))

    sensor = data.setdefault("sensor", {})
    sensor["sample_rate_hz"] = max(20, min(200, int(sensor.get("sample_rate_hz", 100))))
    sensor["gyro_range_dps"] = int(sensor.get("gyro_range_dps", 500))
    sensor["accel_range_g"] = int(sensor.get("accel_range_g", 2))
    sensor["dlpf_hz"] = int(sensor.get("dlpf_hz", 42))
    sensor["level_on_start"] = bool(sensor.get("level_on_start", True))

    axis_map = sensor.get("axis_map") or {}
    clean_map: Dict[str, str] = {}
    for target in ("x", "y", "z"):
        token = str(axis_map.get(target, target)).strip().lower()
        sign = "-" if token.startswith("-") else ""
        source = token.lstrip("+-")
        if source not in ("x", "y", "z"):
            source = target
        clean_map[target] = sign + source
    sensor["axis_map"] = clean_map

    fusion = data.setdefault("fusion", {})
    fusion["beta"] = max(0.005, min(0.5, float(fusion.get("beta", 0.08))))

    calibration = data.setdefault("calibration", {})
    calibration["seconds"] = max(0.5, min(10.0, float(calibration.get("seconds", 2.0))))
    calibration["auto"] = bool(calibration.get("auto", True))
    calibration["still_spread_dps"] = max(
        0.2, float(calibration.get("still_spread_dps", 2.0))
    )

    return data


def load_config(
    path: Optional[Path] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Load defaults, then config.json, then explicit overrides."""
    data = copy.deepcopy(DEFAULTS)
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if config_path.is_file():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                _merge(data, loaded)
        except (OSError, ValueError) as exc:
            raise SystemExit(f"Cannot read {config_path}: {exc}") from exc
    if overrides:
        _merge(data, overrides)
    return _normalize(data)
