"""Quaternion attitude estimation for a 6-axis MPU6050.

The filter is the IMU variant of Madgwick's complementary filter:
gyro rates propagate the quaternion, the accelerometer corrects roll/pitch.
Without a magnetometer, yaw is integrated from the gyro and slowly drifts;
the UI shows this explicitly and offers a yaw reset.

Angles are degrees, rates are degrees/second, acceleration is g.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Sequence, Tuple

RAD2DEG = 180.0 / math.pi
DEG2RAD = math.pi / 180.0

Quat = Tuple[float, float, float, float]


def q_normalize(q: Sequence[float]) -> Quat:
    norm = math.sqrt(sum(v * v for v in q))
    if norm < 1e-12:
        return (1.0, 0.0, 0.0, 0.0)
    return (q[0] / norm, q[1] / norm, q[2] / norm, q[3] / norm)


def q_conjugate(q: Sequence[float]) -> Quat:
    return (q[0], -q[1], -q[2], -q[3])


def q_multiply(a: Sequence[float], b: Sequence[float]) -> Quat:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def q_rotate(q: Sequence[float], vector: Sequence[float]) -> Tuple[float, float, float]:
    """Rotate a 3-vector by a body->world quaternion."""
    w, x, y, z = q_normalize(q)
    vx, vy, vz = float(vector[0]), float(vector[1]), float(vector[2])
    # t = 2 * cross(q.xyz, v)
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def q_from_euler(roll_deg: float, pitch_deg: float, yaw_deg: float) -> Quat:
    """ZYX convention: R = Rz(yaw) * Ry(pitch) * Rx(roll)."""
    cr = math.cos(roll_deg * DEG2RAD * 0.5)
    sr = math.sin(roll_deg * DEG2RAD * 0.5)
    cp = math.cos(pitch_deg * DEG2RAD * 0.5)
    sp = math.sin(pitch_deg * DEG2RAD * 0.5)
    cy = math.cos(yaw_deg * DEG2RAD * 0.5)
    sy = math.sin(yaw_deg * DEG2RAD * 0.5)
    return q_normalize(
        (
            cr * cp * cy + sr * sp * sy,
            sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy,
        )
    )


def q_from_vector_to_z(vector: Sequence[float]) -> Quat:
    """Shortest rotation that brings ``vector`` onto local +Z.

    Used to mount the sensor in the board frame. For an upside-down sensor the
    rotation is 180° around X, which keeps the board X axis unchanged; yaw is
    unobservable without a magnetometer and is set by the first frame.
    """
    vx, vy, vz = (float(vector[0]), float(vector[1]), float(vector[2]))
    norm = math.sqrt(vx * vx + vy * vy + vz * vz)
    if norm < 1e-9:
        return (1.0, 0.0, 0.0, 0.0)
    vx, vy, vz = vx / norm, vy / norm, vz / norm
    dot = max(-1.0, min(1.0, vz))
    if dot > 0.999999:
        return (1.0, 0.0, 0.0, 0.0)
    if dot < -0.999999:
        return (0.0, 1.0, 0.0, 0.0)
    # axis = normalize(cross(vector, +Z)); this has no yaw component.
    horizontal = math.hypot(vx, vy)
    ax = vy / horizontal
    ay = -vx / horizontal
    angle = math.acos(dot)
    half = angle * 0.5
    s = math.sin(half)
    return q_normalize((math.cos(half), ax * s, ay * s, 0.0))


def euler_from_q(q: Sequence[float]) -> Tuple[float, float, float]:
    """Return roll, pitch, yaw in degrees for a ZYX quaternion."""
    w, x, y, z = q_normalize(q)
    roll = math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    sin_pitch = 2.0 * (w * y - z * x)
    sin_pitch = max(-1.0, min(1.0, sin_pitch))
    pitch = math.asin(sin_pitch)
    yaw = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    return (roll * RAD2DEG, pitch * RAD2DEG, yaw * RAD2DEG)


def gravity_in_body(roll_deg: float, pitch_deg: float) -> Tuple[float, float, float]:
    """Measured accelerometer direction (g) for a static ZYX orientation."""
    roll = roll_deg * DEG2RAD
    pitch = pitch_deg * DEG2RAD
    return (
        -math.sin(pitch),
        math.sin(roll) * math.cos(pitch),
        math.cos(roll) * math.cos(pitch),
    )


def wrap180(angle: float) -> float:
    return (angle + 180.0) % 360.0 - 180.0


class MadgwickAHRS:
    """6-axis Madgwick filter (no magnetometer)."""

    def __init__(self, beta: float = 0.08, q: Sequence[float] = (1.0, 0.0, 0.0, 0.0)) -> None:
        self.beta = float(beta)
        self.q: Quat = q_normalize(q)

    def reset(self, q: Sequence[float] = (1.0, 0.0, 0.0, 0.0)) -> None:
        self.q = q_normalize(q)

    def update(
        self,
        gyro_dps: Sequence[float],
        accel_g: Sequence[float],
        dt: float,
        accel_weight: float = 1.0,
    ) -> Quat:
        dt = max(1e-4, min(0.2, float(dt)))
        q0, q1, q2, q3 = self.q

        gx = float(gyro_dps[0]) * DEG2RAD
        gy = float(gyro_dps[1]) * DEG2RAD
        gz = float(gyro_dps[2]) * DEG2RAD

        # Rate of change from gyro
        q_dot0 = 0.5 * (-q1 * gx - q2 * gy - q3 * gz)
        q_dot1 = 0.5 * (q0 * gx + q2 * gz - q3 * gy)
        q_dot2 = 0.5 * (q0 * gy - q1 * gz + q3 * gx)
        q_dot3 = 0.5 * (q0 * gz + q1 * gy - q2 * gx)

        ax, ay, az = float(accel_g[0]), float(accel_g[1]), float(accel_g[2])
        norm = math.sqrt(ax * ax + ay * ay + az * az)
        if norm > 1e-6 and accel_weight > 0.0:
            ax /= norm
            ay /= norm
            az /= norm

            q0q0, q1q1, q2q2, q3q3 = q0 * q0, q1 * q1, q2 * q2, q3 * q3
            _2q0, _2q1, _2q2, _2q3 = 2.0 * q0, 2.0 * q1, 2.0 * q2, 2.0 * q3
            _4q0, _4q1, _4q2 = 4.0 * q0, 4.0 * q1, 4.0 * q2
            _8q1, _8q2 = 8.0 * q1, 8.0 * q2

            s0 = _4q0 * q2q2 + _2q2 * ax + _4q0 * q1q1 - _2q1 * ay
            s1 = (
                _4q1 * q3q3
                - _2q3 * ax
                + 4.0 * q0q0 * q1
                - _2q0 * ay
                - _4q1
                + _8q1 * q1q1
                + _8q1 * q2q2
                + _4q1 * az
            )
            s2 = (
                4.0 * q0q0 * q2
                + _2q0 * ax
                + _4q2 * q3q3
                - _2q3 * ay
                - _4q2
                + _8q2 * q1q1
                + _8q2 * q2q2
                + _4q2 * az
            )
            s3 = 4.0 * q1q1 * q3 - _2q1 * ax + 4.0 * q2q2 * q3 - _2q2 * ay

            grad_norm = math.sqrt(s0 * s0 + s1 * s1 + s2 * s2 + s3 * s3)
            if grad_norm > 1e-9:
                gain = self.beta * max(0.0, min(1.0, accel_weight)) / grad_norm
                q_dot0 -= gain * s0
                q_dot1 -= gain * s1
                q_dot2 -= gain * s2
                q_dot3 -= gain * s3

        q0 += q_dot0 * dt
        q1 += q_dot1 * dt
        q2 += q_dot2 * dt
        q3 += q_dot3 * dt
        self.q = q_normalize((q0, q1, q2, q3))
        return self.q


class AttitudeFilter:
    """Madgwick filter plus gyro-bias handling and continuous yaw output."""

    def __init__(self, beta: float = 0.08) -> None:
        self.filter = MadgwickAHRS(beta=beta)
        self.bias_dps: List[float] = [0.0, 0.0, 0.0]
        self.mount_q: Quat = (1.0, 0.0, 0.0, 0.0)
        self.accel_scale = 1.0
        self._yaw_continuous = 0.0
        self._last_yaw_raw = 0.0
        self._yaw_offset = 0.0
        self.last_gyro_dps: List[float] = [0.0, 0.0, 0.0]
        self.last_accel_g: List[float] = [0.0, 0.0, 0.0]
        self.last_accel_norm = 0.0
        self.sample_count = 0

    # ---------------------------------------------------------------- setup
    def reset(self, keep_bias: bool = True) -> None:
        if not keep_bias:
            self.bias_dps = [0.0, 0.0, 0.0]
        self.filter.reset()
        self._yaw_continuous = 0.0
        self._last_yaw_raw = 0.0
        self._yaw_offset = 0.0
        self.sample_count = 0

    def set_bias(self, bias_dps: Sequence[float]) -> None:
        self.bias_dps = [float(v) for v in bias_dps]

    def set_mount(self, mount_q: Sequence[float], accel_scale: float = 1.0) -> None:
        """Set the sensor->board mounting rotation and accelerometer scale."""
        self.mount_q = q_normalize(mount_q)
        self.accel_scale = max(0.2, min(5.0, float(accel_scale)))

    def initialize_from_accel(self, accel_g: Sequence[float]) -> None:
        """Start with the gravity-consistent tilt and yaw = 0.

        Gravity cannot observe yaw, so starting from identity while the board
        is already tilted would pick an arbitrary yaw. Seeding roll/pitch from
        the accelerometer keeps the first reading meaningful and yaw at zero.
        """
        ax, ay, az = q_rotate(self.mount_q, accel_g)
        ax *= self.accel_scale
        ay *= self.accel_scale
        az *= self.accel_scale
        norm = math.sqrt(ax * ax + ay * ay + az * az)
        if norm < 0.25:
            return
        roll = math.atan2(ay, az) * RAD2DEG
        pitch = math.atan2(-ax, math.hypot(ay, az)) * RAD2DEG
        self.filter.reset(q_from_euler(roll, pitch, 0.0))
        self._yaw_continuous = 0.0
        self._last_yaw_raw = 0.0
        self._yaw_offset = 0.0
        self.sample_count = 0
        self.last_accel_g = [ax, ay, az]
        self.last_accel_norm = norm

    def tare_yaw(self) -> None:
        """Make the current heading the new zero.

        The quaternion is rotated about the world vertical so the board's
        displayed yaw (and its 3D pose) becomes 0 while roll and pitch stay
        unchanged. Gravity is unaffected by a world-Z rotation.
        """
        yaw_now = self._yaw_continuous - self._yaw_offset
        if abs(yaw_now) > 1e-9:
            self.filter.q = q_multiply(
                q_from_euler(0.0, 0.0, -yaw_now), self.filter.q
            )
        self._yaw_continuous = 0.0
        self._yaw_offset = 0.0
        self._last_yaw_raw = euler_from_q(self.filter.q)[2]

    # ---------------------------------------------------------------- update
    def update(
        self,
        accel_g: Sequence[float],
        gyro_dps: Sequence[float],
        dt: float,
    ) -> Dict[str, object]:
        ax, ay, az = (float(accel_g[0]), float(accel_g[1]), float(accel_g[2]))
        gx, gy, gz = (
            float(gyro_dps[0]) - self.bias_dps[0],
            float(gyro_dps[1]) - self.bias_dps[1],
            float(gyro_dps[2]) - self.bias_dps[2],
        )

        # Move sensor vectors into the board frame and normalize the measured
        # gravity magnitude. This handles an upside-down or tilted sensor mount
        # and clone sensors whose 1 g reading is not exactly 1.0.
        ax, ay, az = q_rotate(self.mount_q, (ax, ay, az))
        ax *= self.accel_scale
        ay *= self.accel_scale
        az *= self.accel_scale
        gx, gy, gz = q_rotate(self.mount_q, (gx, gy, gz))

        norm = math.sqrt(ax * ax + ay * ay + az * az)
        self.last_accel_norm = norm
        # Reject free-fall / implausible readings; soften correction while the
        # board is being accelerated by hand.
        accel_weight = 0.0
        if norm > 0.25:
            deviation = abs(norm - 1.0)
            if deviation <= 0.15:
                accel_weight = 1.0
            else:
                accel_weight = max(0.05, 1.0 - (deviation - 0.15) * 3.0)

        self.filter.update((gx, gy, gz), (ax, ay, az), dt, accel_weight)
        roll, pitch, raw_yaw = euler_from_q(self.filter.q)

        delta = wrap180(raw_yaw - self._last_yaw_raw)
        self._yaw_continuous += delta
        self._last_yaw_raw = raw_yaw
        yaw = self._yaw_continuous - self._yaw_offset

        self.last_gyro_dps = [gx, gy, gz]
        self.last_accel_g = [ax, ay, az]
        self.sample_count += 1
        return {
            "q": self.filter.q,
            "roll": roll,
            "pitch": pitch,
            "yaw": yaw,
            "yaw_raw": raw_yaw,
            "gyro": [gx, gy, gz],
            "accel": [ax, ay, az],
        }

    @property
    def q(self) -> Quat:
        return self.filter.q


def median(values: Iterable[float]) -> float:
    items = sorted(float(v) for v in values)
    if not items:
        return 0.0
    middle = len(items) // 2
    if len(items) % 2:
        return items[middle]
    return 0.5 * (items[middle - 1] + items[middle])


def estimate_gyro_bias(
    samples: Sequence[Sequence[float]],
) -> Dict[str, object]:
    """Estimate a per-axis gyro bias from static samples.

    ``samples`` are (gx, gy, gz) tuples in deg/s. The spread is the worst
    peak-to-peak value across the three axes and tells whether the board was
    actually still.
    """
    axes: List[List[float]] = [[], [], []]
    for sample in samples:
        if len(sample) < 3:
            continue
        for index in range(3):
            axes[index].append(float(sample[index]))
    if not axes[0]:
        return {"bias": [0.0, 0.0, 0.0], "spread": 0.0, "ok": False, "samples": 0}

    bias = [median(axis) for axis in axes]
    spread = max((max(axis) - min(axis)) for axis in axes if axis)
    return {
        "bias": bias,
        "spread": spread,
        "ok": spread < 2.0,
        "samples": len(axes[0]),
    }
