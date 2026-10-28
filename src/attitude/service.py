"""Sensor acquisition thread: MPU6050 hardware, fusion and commands."""

from __future__ import annotations

import math
import queue
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import VERSION
from .config import parse_address
from .fusion import (
    AttitudeFilter,
    estimate_gyro_bias,
    q_conjugate,
    q_from_vector_to_z,
    q_rotate,
)
from .imu import ImuError, MPU6050, open_sensor

AXES = ("x", "y", "z")


def _axis_value(vector: Sequence[float], token: str) -> float:
    source = token.lstrip("+-")
    sign = -1.0 if token.startswith("-") else 1.0
    index = AXES.index(source) if source in AXES else 0
    return sign * float(vector[index])


class HardwareSource:
    """MPU6050 source with automatic reconnection and mounting-axis mapping."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        i2c = config["i2c"]
        sensor = config["sensor"]
        self.bus = int(i2c["bus"])
        self.address = parse_address(i2c["address"])
        self.auto_detect = bool(i2c["auto_detect"])
        self.rate_hz = float(sensor["sample_rate_hz"])
        self.device: Optional[MPU6050] = None
        self.error: Optional[str] = None
        self._axis_map = dict(sensor["axis_map"])

    def open(self) -> None:
        sensor = self.config["sensor"]
        self.device = open_sensor(
            bus=self.bus,
            address=self.address,
            auto_detect=self.auto_detect,
            sample_rate_hz=sensor["sample_rate_hz"],
            gyro_range_dps=sensor["gyro_range_dps"],
            accel_range_g=sensor["accel_range_g"],
            dlpf_hz=sensor["dlpf_hz"],
        )
        info = self.device.info
        self.bus = int(info["bus"])
        self.address = parse_address(info["address"])
        self.error = None

    def close(self) -> None:
        if self.device is not None:
            try:
                self.device.close()
            finally:
                self.device = None

    def read(self) -> Tuple[Tuple[float, float, float], Tuple[float, float, float], float]:
        if self.device is None:
            raise ImuError("sensor is not open")
        accel, gyro, temperature = self.device.read()
        mapped_accel = tuple(
            _axis_value(accel, self._axis_map[axis]) for axis in AXES
        )
        mapped_gyro = tuple(
            _axis_value(gyro, self._axis_map[axis]) for axis in AXES
        )
        return mapped_accel, mapped_gyro, temperature

    @property
    def info(self) -> Dict[str, Any]:
        if self.device is None:
            return {
                "bus": self.bus,
                "address": f"0x{self.address:02x}",
                "path": f"/dev/i2c-{self.bus}",
                "chip": None,
                "who_am_i": None,
            }
        return dict(self.device.info)


class AttitudeService:
    """Runs one acquisition thread and publishes the latest fused sample."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        sensor = config["sensor"]
        self.rate_hz = max(20, int(sensor["sample_rate_hz"]))
        self.period = 1.0 / self.rate_hz
        self.filter = AttitudeFilter(beta=float(config["fusion"]["beta"]))
        self._source: Optional[object] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._commands: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._paused = False
        self._seq = 0
        self._started = time.monotonic()
        self._last_sample_t: Optional[float] = None
        self._mount_initialized = not bool(config["sensor"].get("level_on_start", True))
        self._rate_ema = 0.0
        # Motion HUD state: a qualitative direction indicator. Hand braking
        # right after a push produces a short opposite acceleration, which an
        # integrated velocity would turn into an arrow pointing the other way.
        # Instead the heading is captured from each push and held briefly; the
        # opposite (braking) stroke is ignored.
        self._motion_clock = 0.0
        self._motion_dir: Optional[List[float]] = None
        self._motion_until = 0.0
        self._motion_started = -1.0
        self._motion_candidate_since: Optional[float] = None
        self._motion_candidate = [0.0, 0.0]
        self._state = "starting"
        self._message = "Starting sensor service"
        self._connected = False
        self._error: Optional[str] = None
        self._calibration: Dict[str, Any] = {
            "bias_dps": [0.0, 0.0, 0.0],
            "ok": False,
            "spread_dps": None,
            "samples": 0,
            "at": None,
            "message": "not calibrated",
        }
        self._sample: Dict[str, Any] = {
            "seq": 0,
            "t": 0.0,
            "q": [1.0, 0.0, 0.0, 0.0],
            "euler": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
            "gyro": [0.0, 0.0, 0.0],
            "gyro_raw": [0.0, 0.0, 0.0],
            "accel": [0.0, 0.0, 1.0],
            "temp_c": 0.0,
            "motion": {"x": 0.0, "y": 0.0, "z": 0.0},
            "rate_hz": 0.0,
            "paused": False,
            "connected": False,
            "source": "mpu6050",
        }
        self._source_info: Dict[str, Any] = {}

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="imu-visualization", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._close_source()
        with self._cond:
            self._state = "stopped"
            self._message = "Sensor service stopped"
            self._cond.notify_all()

    def _close_source(self) -> None:
        with self._lock:
            source = self._source
            self._source = None
            self._connected = False
        if source is not None:
            close = getattr(source, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:  # noqa: BLE001 - best effort on shutdown
                    pass

    # ---------------------------------------------------------------- thread
    def _run(self) -> None:
        try:
            self._open_source()
            if self._source is not None and bool(self.config["calibration"]["auto"]):
                self._calibrate_now(auto=True)
            next_tick = time.monotonic()
            while not self._stop.is_set():
                self._process_commands()
                if self._paused:
                    self._wait(0.05)
                    continue
                if self._source is None:
                    if not self._try_open_source():
                        self._wait(1.0)
                        continue
                tick = time.monotonic()
                try:
                    accel, gyro_raw, temperature = self._source.read()
                except (ImuError, OSError) as exc:
                    self._handle_read_error(str(exc))
                    continue

                dt = self.period
                if self._last_sample_t is not None:
                    measured = tick - self._last_sample_t
                    if 0.0005 < measured < 0.25:
                        dt = measured
                self._last_sample_t = tick

                if (
                    not self._mount_initialized
                    and self.config["sensor"].get("level_on_start", True)
                ):
                    accel_norm = math.sqrt(sum(value * value for value in accel))
                    if accel_norm > 0.2:
                        self.filter.set_mount(
                            q_from_vector_to_z(accel), 1.0 / accel_norm
                        )
                        self._mount_initialized = True

                if self.filter.sample_count == 0:
                    self.filter.initialize_from_accel(accel)
                fused = self.filter.update(accel, gyro_raw, dt)
                rate = 1.0 / dt if dt > 0 else 0.0
                self._rate_ema = rate if self._rate_ema <= 0 else self._rate_ema * 0.9 + rate * 0.1

                motion = self._update_motion(fused, dt)
                sample = {
                    "seq": self._seq + 1,
                    "t": round(tick - self._started, 3),
                    "q": [round(value, 6) for value in fused["q"]],
                    "euler": {
                        # The board is held landscape: its long axis is the
                        # lateral (screen X) axis, so a bank is a rotation about
                        # the board's short/forward axis. Swap the Madgwick
                        # X/Y labels so "Roll" means bank and "Pitch" means
                        # nose up/down, matching the horizon convention.
                        "roll": round(float(fused["pitch"]), 2),
                        "pitch": round(float(fused["roll"]), 2),
                        # Compass heading: clockwise seen from above increases
                        # the number. The fused yaw is a right-handed math angle
                        # (counter-clockwise positive), so report its negation.
                        "yaw": round(-float(fused["yaw"]), 2),
                    },
                    "gyro": [round(float(value), 3) for value in fused["gyro"]],
                    "gyro_raw": [round(float(value), 3) for value in gyro_raw],
                    "accel": [round(float(value), 4) for value in fused["accel"]],
                    "temp_c": round(float(temperature), 2),
                    "motion": {
                        "x": round(motion[0], 4),
                        "y": round(motion[1], 4),
                        "z": round(motion[2], 4),
                    },
                    "rate_hz": round(self._rate_ema, 1),
                    "paused": False,
                    "connected": True,
                    "source": "mpu6050",
                }
                with self._cond:
                    self._seq += 1
                    self._sample = sample
                    self._state = "streaming"
                    self._message = f"Streaming from {self._source_info.get('path', 'I2C')}"
                    self._connected = True
                    self._error = None
                    self._cond.notify_all()

                next_tick += self.period
                delay = next_tick - time.monotonic()
                if delay < -0.15:
                    next_tick = time.monotonic()
                    delay = 0.0
                self._wait(delay)
        except Exception as exc:  # noqa: BLE001 - keep the thread alive for diagnostics
            with self._cond:
                self._state = "error"
                self._message = f"Sensor thread stopped: {type(exc).__name__}: {exc}"
                self._error = self._message
                self._connected = False
                self._cond.notify_all()

    #: Horizontal push acceleration that captures a new heading (m/s^2).
    MOTION_ONSET_ACC = 0.7
    #: The push must stay above the onset level for this long (seconds) so a
    #: small nudge or a hand tremor cannot trigger the arrow.
    MOTION_MIN_PUSH_S = 0.08
    #: How long the heading stays on screen after the last push (seconds).
    MOTION_HOLD_S = 0.7
    #: Window used to average the first samples of a push (seconds).
    MOTION_REFINE_S = 0.12
    #: Minimum alignment for a sample to count as the same push (cosine).
    MOTION_ALIGN = 0.2

    def _reset_motion(self) -> None:
        with self._lock:
            self._motion_clock = 0.0
            self._motion_dir = None
            self._motion_until = 0.0
            self._motion_started = -1.0
            self._motion_candidate_since: Optional[float] = None
            self._motion_candidate = [0.0, 0.0]

    def _update_motion(self, fused: Dict[str, Any], dt: float):
        """Return the current motion heading as a unit world vector (x, y, 0).

        The accelerometer measures gravity plus linear acceleration; gravity is
        removed with the fused quaternion and the remainder is rotated to the
        world frame. A push captures the heading and keeps it visible for a
        short hold window. The opposite acceleration that appears when the hand
        stops is ignored, because integrating it was what made the arrow jump to
        the other side right after a move.
        """
        dt = max(1e-4, min(0.2, float(dt)))
        q = fused["q"]
        accel = fused["accel"]
        gravity_body = q_rotate(q_conjugate(q), (0.0, 0.0, 1.0))
        linear_body = [float(accel[i]) - gravity_body[i] for i in range(3)]
        magnitude = math.sqrt(sum(value * value for value in linear_body))
        if magnitude < 0.018:
            linear_world = [0.0, 0.0, 0.0]
        else:
            linear_world = q_rotate(
                q,
                tuple(value * 9.80665 for value in linear_body),
            )

        horizontal = math.hypot(linear_world[0], linear_world[1])
        clock = self._motion_clock + dt
        self._motion_clock = clock
        if self._motion_dir is None:
            if horizontal > self.MOTION_ONSET_ACC:
                if self._motion_candidate_since is None:
                    self._motion_candidate_since = clock
                    self._motion_candidate = [0.0, 0.0]
                self._motion_candidate[0] += linear_world[0] * dt
                self._motion_candidate[1] += linear_world[1] * dt
                if clock - self._motion_candidate_since >= self.MOTION_MIN_PUSH_S:
                    norm = math.hypot(
                        self._motion_candidate[0], self._motion_candidate[1]
                    )
                    if norm > 1e-6:
                        self._motion_dir = [
                            self._motion_candidate[0] / norm,
                            self._motion_candidate[1] / norm,
                        ]
                        self._motion_started = self._motion_candidate_since
                        self._motion_until = clock + self.MOTION_HOLD_S
                    self._motion_candidate_since = None
            else:
                self._motion_candidate_since = None
        elif horizontal > self.MOTION_ONSET_ACC:
            heading = [linear_world[0] / horizontal, linear_world[1] / horizontal]
            alignment = (
                heading[0] * self._motion_dir[0]
                + heading[1] * self._motion_dir[1]
            )
            if alignment > self.MOTION_ALIGN:
                # Same push continues; extend the hold and average the first
                # 120 ms so one noisy sample cannot set the heading.
                if clock - self._motion_started < self.MOTION_REFINE_S:
                    blend = min(0.35, dt / self.MOTION_REFINE_S)
                    dx = self._motion_dir[0] * (1.0 - blend) + heading[0] * blend
                    dy = self._motion_dir[1] * (1.0 - blend) + heading[1] * blend
                    norm = math.hypot(dx, dy)
                    if norm > 1e-6:
                        self._motion_dir = [dx / norm, dy / norm]
                self._motion_until = max(
                    self._motion_until, clock + self.MOTION_HOLD_S
                )
            # Opposite acceleration is the hand braking. Ignoring it is what
            # stops the arrow from jumping to the other side after a push.

        if self._motion_dir is not None:
            if clock >= self._motion_until:
                self._motion_dir = None
            elif clock - self._motion_started >= self.MOTION_REFINE_S:
                # Wait for the short averaging window so the arrow does not
                # flash a slightly different angle before settling.
                return (self._motion_dir[0], self._motion_dir[1], 0.0)
        return (0.0, 0.0, 0.0)

    def _wait(self, seconds: float) -> None:
        if seconds > 0:
            self._stop.wait(min(0.25, seconds))

    def _open_source(self) -> None:
        source = HardwareSource(self.config)
        try:
            source.open()
        except (ImuError, OSError) as exc:
            with self._lock:
                self._error = str(exc)
                self._state = "error"
                self._message = str(exc)
                self._connected = False
                self._source_info = source.info
            return
        with self._lock:
            self._source = source
            self._source_info = source.info
            self._error = None

    def _try_open_source(self) -> bool:
        self._open_source()
        return self._source is not None

    def _handle_read_error(self, message: str) -> None:
        self._close_source()
        with self._cond:
            self._state = "error"
            self._error = message
            self._message = f"Sensor read failed: {message}. Reconnecting..."
            self._connected = False
            self._last_sample_t = None
            self._motion_dir = None
            self._motion_clock = 0.0
            self._motion_until = 0.0
            self._motion_started = -1.0
            self._motion_candidate_since: Optional[float] = None
            self._motion_candidate = [0.0, 0.0]
            self._sample = dict(self._sample)
            self._sample["connected"] = False
            self._cond.notify_all()
        self._wait(0.5)

    # ---------------------------------------------------------------- calibration
    def _collect_static(
        self, seconds: float
    ) -> Tuple[List[Sequence[float]], Optional[List[float]]]:
        source = self._source
        if source is None:
            return [], None
        deadline = time.monotonic() + max(0.3, seconds)
        samples: List[Sequence[float]] = []
        accel_sum = [0.0, 0.0, 0.0]
        accel_count = 0
        while time.monotonic() < deadline and not self._stop.is_set():
            try:
                accel, gyro, _ = source.read()
            except (ImuError, OSError):
                break
            samples.append(gyro)
            for index in range(3):
                accel_sum[index] += float(accel[index])
            accel_count += 1
            time.sleep(0.005)
        accel_average = None
        if accel_count:
            accel_average = [value / accel_count for value in accel_sum]
        return samples, accel_average

    def _calibrate_now(self, auto: bool = False) -> Dict[str, Any]:
        seconds = float(self.config["calibration"]["seconds"])
        with self._cond:
            if self._source is None:
                return {"ok": False, "message": "sensor is not connected"}
            self._state = "calibrating"
            self._message = "Keep the board still: calibrating gyro bias"
            self._cond.notify_all()

        samples, accel_average = self._collect_static(seconds)
        estimate = estimate_gyro_bias(samples)
        threshold = float(self.config["calibration"]["still_spread_dps"])
        bias = estimate["bias"] if samples else [0.0, 0.0, 0.0]
        spread = float(estimate["spread"]) if samples else None
        ok = (
            len(samples) > 10
            and spread is not None
            and spread < threshold
        )
        if samples and ok:
            self.filter.set_bias(bias)
            # Re-capture the level reference on every calibration, not only at
            # startup: after the sensor is re-mounted the old mount rotation is
            # wrong and the resting pose would otherwise read as tilted.
            if (
                self.config["sensor"].get("level_on_start", True)
                and accel_average is not None
            ):
                norm = math.sqrt(sum(value * value for value in accel_average))
                if norm > 0.2:
                    self.filter.set_mount(
                        q_from_vector_to_z(accel_average), 1.0 / norm
                    )
                    self._mount_initialized = True
            self.filter.reset(keep_bias=True)
        message = "Gyro bias calibrated; level reference set to this pose" if ok else "Calibration uncertain: the board was moving"
        if not samples:
            message = "Calibration failed: no sensor samples"
        if spread is not None and not ok:
            message += f" (spread {spread:.1f} dps > {threshold:.1f} dps)"

        with self._cond:
            self._calibration = {
                "bias_dps": [round(float(value), 3) for value in bias],
                "ok": ok,
                "applied": bool(samples and ok),
                "spread_dps": round(spread, 2) if spread is not None else None,
                "samples": len(samples),
                "at": time.time(),
                "message": message,
                "auto": auto,
            }
            self._state = "streaming"
            self._message = message
            self._last_sample_t = None
            self._motion_dir = None
            self._motion_clock = 0.0
            self._motion_until = 0.0
            self._motion_started = -1.0
            self._motion_candidate_since: Optional[float] = None
            self._motion_candidate = [0.0, 0.0]
            self._cond.notify_all()
        return dict(self._calibration)

    # ---------------------------------------------------------------- commands
    def _process_commands(self) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            kind = command.get("kind")
            result: Dict[str, Any] = {"ok": False, "message": "unknown command"}
            try:
                if kind == "calibrate":
                    if self._paused:
                        result = {"ok": False, "message": "Resume the stream before calibrating"}
                    elif self._source is None:
                        result = {"ok": False, "message": "sensor is not connected"}
                    else:
                        calibration = self._calibrate_now(auto=False)
                        result = {"ok": True, "calibration": calibration}
                elif kind == "tare":
                    if self._paused:
                        result = {"ok": False, "message": "Resume the stream before resetting yaw"}
                    elif self._source is None:
                        result = {"ok": False, "message": "sensor is not connected"}
                    else:
                        self.filter.tare_yaw()
                        with self._cond:
                            sample = dict(self._sample)
                            sample["euler"] = dict(sample["euler"])
                            sample["euler"]["yaw"] = 0.0
                            self._sample = sample
                            self._message = "Yaw reference reset"
                            self._cond.notify_all()
                        result = {"ok": True, "message": "Yaw reference reset"}
                elif kind == "pause":
                    paused = bool(command.get("value"))
                    with self._cond:
                        self._paused = paused
                        self._state = "paused" if paused else "streaming"
                        self._message = "Stream paused" if paused else "Stream resumed"
                        self._last_sample_t = None
                        sample = dict(self._sample)
                        sample["paused"] = paused
                        sample["seq"] = self._seq
                        self._sample = sample
                        self._cond.notify_all()
                    result = {"ok": True, "paused": paused, "message": self._message}
            except Exception as exc:  # noqa: BLE001 - report to the caller
                result = {"ok": False, "message": f"{type(exc).__name__}: {exc}"}
            command["result"] = result
            event = command.get("event")
            if event is not None:
                event.set()

    def request(self, kind: str, value: Any = None, timeout: float = 8.0) -> Dict[str, Any]:
        command: Dict[str, Any] = {"kind": kind, "value": value, "event": threading.Event()}
        self._commands.put(command)
        if not command["event"].wait(timeout):
            return {"ok": False, "message": f"{kind} timed out"}
        return command.get("result") or {"ok": False, "message": "no result"}

    # ---------------------------------------------------------------- readers
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            sample = dict(self._sample)
            sample["euler"] = dict(sample["euler"])
            sample["seq"] = self._seq
            sample["paused"] = self._paused
            sample["connected"] = self._connected and self._state != "error"
            return sample

    def status(self) -> Dict[str, Any]:
        with self._lock:
            age = None
            if self._last_sample_t is not None:
                age = max(0.0, time.monotonic() - self._last_sample_t)
            return {
                "ok": True,
                "version": VERSION,
                "mode": "hardware",
                "source": dict(self._source_info),
                "state": self._state,
                "message": self._message,
                "error": self._error,
                "connected": self._connected,
                "paused": self._paused,
                "rate_hz": round(self._rate_ema, 1),
                "sample_rate_hz": self.rate_hz,
                "seq": self._seq,
                "uptime_s": round(time.monotonic() - self._started, 1),
                "sample_age_s": round(age, 3) if age is not None else None,
                "calibration": dict(self._calibration),
                "mount": {
                    "level_on_start": bool(
                        self.config["sensor"].get("level_on_start", True)
                    ),
                    "initialized": bool(self._mount_initialized),
                    "accel_scale": round(float(self.filter.accel_scale), 4),
                    "q": [round(float(value), 5) for value in self.filter.mount_q],
                },
            }
