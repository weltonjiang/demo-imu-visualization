"""Minimal MPU6050 driver using Linux i2c-dev directly.

No smbus / pip package is required on the board: the driver opens
``/dev/i2c-N`` and uses the I2C_SLAVE ioctl through the standard library.

Wiring (Quectel Pi M2 40-pin header, I2C bus 1):

    MPU6050 VCC -> 3.3V (pin 1)
    MPU6050 GND -> GND  (pin 6)
    MPU6050 SDA -> GPIO2 / SDA (pin 3)
    MPU6050 SCL -> GPIO3 / SCL (pin 5)
    AD0 / INT   -> leave open (address 0x68, polling)

CLI:
    python3 -m attitude.imu --probe
    python3 -m attitude.imu --watch
"""

from __future__ import annotations

import argparse
import glob
import time
from typing import Dict, List, Optional, Sequence, Tuple

try:  # Windows has no fcntl; only the board needs I2C.
    import fcntl
except ImportError:  # pragma: no cover - platform difference
    fcntl = None

I2C_SLAVE = 0x0703

REG_SMPLRT_DIV = 0x19
REG_CONFIG = 0x1A
REG_GYRO_CONFIG = 0x1B
REG_ACCEL_CONFIG = 0x1C
REG_ACCEL_XOUT_H = 0x3B
REG_PWR_MGMT_1 = 0x6B
REG_PWR_MGMT_2 = 0x6C
REG_WHO_AM_I = 0x75

#: WHO_AM_I values accepted from MPU6050 boards and common clones.
KNOWN_CHIPS = {
    0x68: "MPU6050",
    0x69: "MPU6050 (clone)",
    0x70: "MPU6500",
    0x71: "MPU9250",
    0x73: "MPU9255",
    0x98: "MPU6050 (clone)",
}

GYRO_RANGES = {250: 0, 500: 1, 1000: 2, 2000: 3}
GYRO_SCALE = {250: 131.0, 500: 65.5, 1000: 32.8, 2000: 16.4}
ACCEL_RANGES = {2: 0, 4: 1, 8: 2, 16: 3}
ACCEL_SCALE = {2: 16384.0, 4: 8192.0, 8: 4096.0, 16: 2048.0}

#: (DLPF cutoff Hz, CONFIG register value)
DLPF_SETTINGS = [
    (260, 0),
    (184, 1),
    (94, 2),
    (44, 3),
    (21, 4),
    (10, 5),
    (5, 6),
]


class ImuError(RuntimeError):
    """The sensor could not be opened or a read failed."""


def available_buses() -> List[int]:
    buses: List[int] = []
    for path in glob.glob("/dev/i2c-*"):
        try:
            buses.append(int(path.rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return sorted(set(buses))


def _nearest_dlpf(hz: int) -> Tuple[int, int]:
    return min(DLPF_SETTINGS, key=lambda item: abs(item[0] - hz))


def _s16(high: int, low: int) -> int:
    value = (high << 8) | low
    return value - 65536 if value >= 32768 else value


class MPU6050:
    """I2C register access plus a ready-to-use configuration."""

    def __init__(self, bus: int = 1, address: int = 0x68) -> None:
        self.bus = int(bus)
        self.address = int(address)
        self.path = f"/dev/i2c-{self.bus}"
        self.gyro_range_dps = 500
        self.accel_range_g = 2
        self.sample_rate_hz = 100
        self.dlpf_hz = 44
        self.who_am_i: Optional[int] = None
        self.chip = "MPU6050"
        self._fh = None

    # ---------------------------------------------------------------- low level
    def open(self) -> "MPU6050":
        if fcntl is None:
            raise ImuError(
                "I2C is only available on Linux; run this on the Quectel Pi M2 board"
            )
        try:
            self._fh = open(self.path, "r+b", buffering=0)
            fcntl.ioctl(self._fh.fileno(), I2C_SLAVE, self.address)
        except OSError as exc:
            self.close()
            raise ImuError(
                f"cannot open {self.path} at 0x{self.address:02x}: {exc}"
            ) from exc
        return self

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            finally:
                self._fh = None

    def _write(self, register: int, value: int) -> None:
        if self._fh is None:
            raise ImuError("sensor is not open")
        try:
            self._fh.write(bytes((register & 0xFF, value & 0xFF)))
        except OSError as exc:
            raise ImuError(f"I2C write 0x{register:02x} failed: {exc}") from exc

    def _read(self, register: int, length: int, retries: int = 3) -> bytes:
        if self._fh is None:
            raise ImuError("sensor is not open")
        last: Optional[BaseException] = None
        for attempt in range(max(1, retries)):
            try:
                self._fh.write(bytes((register & 0xFF,)))
                data = self._fh.read(length)
                if len(data) == length:
                    return data
                last = ImuError(
                    f"register 0x{register:02x}: got {len(data)}/{length} bytes"
                )
            except OSError as exc:
                last = exc
            time.sleep(0.003 * (attempt + 1))
        raise ImuError(f"I2C read 0x{register:02x} failed: {last}")

    # ---------------------------------------------------------------- setup
    def read_who_am_i(self) -> int:
        value = self._read(REG_WHO_AM_I, 1)[0]
        self.who_am_i = value
        self.chip = KNOWN_CHIPS.get(value, f"unknown (0x{value:02x})")
        return value

    def configure(
        self,
        sample_rate_hz: int = 100,
        gyro_range_dps: int = 500,
        accel_range_g: int = 2,
        dlpf_hz: int = 42,
    ) -> "MPU6050":
        if gyro_range_dps not in GYRO_RANGES:
            gyro_range_dps = 500
        if accel_range_g not in ACCEL_RANGES:
            accel_range_g = 2
        self.gyro_range_dps = gyro_range_dps
        self.accel_range_g = accel_range_g
        self.sample_rate_hz = int(sample_rate_hz)
        cutoff, dlpf_code = _nearest_dlpf(int(dlpf_hz))
        self.dlpf_hz = cutoff

        # Wake up, clock source = gyro X PLL.
        self._write(REG_PWR_MGMT_1, 0x01)
        time.sleep(0.05)
        self._write(REG_PWR_MGMT_2, 0x00)

        divider = int(round(1000.0 / max(20, self.sample_rate_hz))) - 1
        self._write(REG_SMPLRT_DIV, max(0, min(255, divider)))
        self._write(REG_CONFIG, dlpf_code)
        self._write(REG_GYRO_CONFIG, GYRO_RANGES[gyro_range_dps] << 3)
        self._write(REG_ACCEL_CONFIG, ACCEL_RANGES[accel_range_g] << 3)
        time.sleep(0.05)
        return self

    # ---------------------------------------------------------------- data
    def read_raw(self) -> Tuple[int, int, int, int, int, int, int]:
        """One 14-byte burst: ax ay az temp gx gy gz (signed 16-bit)."""
        data = self._read(REG_ACCEL_XOUT_H, 14)
        return (
            _s16(data[0], data[1]),
            _s16(data[2], data[3]),
            _s16(data[4], data[5]),
            _s16(data[6], data[7]),
            _s16(data[8], data[9]),
            _s16(data[10], data[11]),
            _s16(data[12], data[13]),
        )

    def read(self) -> Tuple[Tuple[float, float, float], Tuple[float, float, float], float]:
        """Return (accel_g, gyro_dps, temperature_c)."""
        ax_raw, ay_raw, az_raw, temp_raw, gx_raw, gy_raw, gz_raw = self.read_raw()
        accel_scale = ACCEL_SCALE[self.accel_range_g]
        gyro_scale = GYRO_SCALE[self.gyro_range_dps]
        accel = (
            ax_raw / accel_scale,
            ay_raw / accel_scale,
            az_raw / accel_scale,
        )
        gyro = (
            gx_raw / gyro_scale,
            gy_raw / gyro_scale,
            gz_raw / gyro_scale,
        )
        temperature = temp_raw / 340.0 + 36.53
        return accel, gyro, temperature

    @property
    def info(self) -> Dict[str, object]:
        return {
            "bus": self.bus,
            "path": self.path,
            "address": f"0x{self.address:02x}",
            "who_am_i": f"0x{self.who_am_i:02x}" if self.who_am_i is not None else None,
            "chip": self.chip,
            "gyro_range_dps": self.gyro_range_dps,
            "accel_range_g": self.accel_range_g,
            "sample_rate_hz": self.sample_rate_hz,
            "dlpf_hz": self.dlpf_hz,
        }


def probe(buses: Optional[Sequence[int]] = None, addresses: Sequence[int] = (0x68, 0x69)) -> List[Dict[str, object]]:
    """Scan I2C buses/addresses and return every MPU-compatible sensor found."""
    found: List[Dict[str, object]] = []
    candidates = list(buses) if buses is not None else available_buses()
    for bus in candidates:
        for address in addresses:
            device = MPU6050(bus=bus, address=address)
            try:
                device.open()
                who = device.read_who_am_i()
            except (ImuError, OSError):
                device.close()
                continue
            if who in KNOWN_CHIPS:
                found.append(device.info)
            device.close()
    return found


def open_sensor(
    bus: int = 1,
    address: int = 0x68,
    auto_detect: bool = True,
    sample_rate_hz: int = 100,
    gyro_range_dps: int = 500,
    accel_range_g: int = 2,
    dlpf_hz: int = 42,
) -> MPU6050:
    """Open a known address, or scan all buses when auto_detect is enabled."""
    chosen_bus = bus
    chosen_address = address
    if auto_detect:
        found = probe()
        if not found:
            raise ImuError(
                "MPU6050 not found on any /dev/i2c-* bus at 0x68/0x69; "
                "check SDA/SCL/3V3/GND and the i2c group permission"
            )
        # Prefer the configured bus/address, then the first hit.
        found.sort(
            key=lambda item: (
                item.get("bus") != bus or int(str(item.get("address")), 16) != address,
                int(item.get("bus", 999)),
            )
        )
        chosen_bus = int(found[0]["bus"])
        chosen_address = int(str(found[0]["address"]), 16)

    device = MPU6050(bus=chosen_bus, address=chosen_address).open()
    device.read_who_am_i()
    if device.who_am_i not in KNOWN_CHIPS:
        device.close()
        raise ImuError(
            f"unexpected WHO_AM_I 0x{device.who_am_i or 0:02x} at "
            f"/dev/i2c-{chosen_bus} 0x{chosen_address:02x}"
        )
    device.configure(
        sample_rate_hz=sample_rate_hz,
        gyro_range_dps=gyro_range_dps,
        accel_range_g=accel_range_g,
        dlpf_hz=dlpf_hz,
    )
    return device


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="MPU6050 probe / live readout")
    parser.add_argument("--probe", action="store_true", help="scan all I2C buses")
    parser.add_argument("--watch", action="store_true", help="print live readings at 10 Hz")
    parser.add_argument("--bus", type=int, default=1)
    parser.add_argument("--addr", type=lambda text: int(text, 0), default=0x68)
    args = parser.parse_args(argv)

    if args.probe:
        buses = available_buses()
        print(f"I2C buses: {', '.join(f'/dev/i2c-{bus}' for bus in buses) or 'none'}")
        found = probe(buses if buses else None)
        if not found:
            print("No MPU6050-compatible device found at 0x68/0x69.")
            return 2
        for item in found:
            print(
                f"  found {item['chip']} on {item['path']} at {item['address']} "
                f"(WHO_AM_I {item['who_am_i']})"
            )
        return 0

    device = open_sensor(
        bus=args.bus,
        address=args.addr,
        auto_detect=not args.watch,
    )
    print(
        f"{device.chip} on {device.path} at 0x{device.address:02x} "
        f"({device.gyro_range_dps} dps / {device.accel_range_g} g, "
        f"{device.sample_rate_hz} Hz)"
    )
    if not args.watch:
        device.close()
        return 0

    print("Press Ctrl+C to stop.")
    try:
        while True:
            accel, gyro, temp = device.read()
            print(
                f"accel=({accel[0]:+.2f},{accel[1]:+.2f},{accel[2]:+.2f}) g  "
                f"gyro=({gyro[0]:+7.2f},{gyro[1]:+7.2f},{gyro[2]:+7.2f}) dps  "
                f"temp={temp:5.1f} C",
                end="\r",
            )
            time.sleep(0.1)
    except KeyboardInterrupt:
        print()
    finally:
        device.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
