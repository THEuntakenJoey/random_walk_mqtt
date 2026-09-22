"""
Smoothing and Interpolation Engine for Omniverse MQTT Animator.
Ports v1-v5 interpolation modes with robust low-frequency (e.g. 1 Hz) handling,
virtual endpoint reflection, and continuous knot parameterization.
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple


def shortest_angle_diff(a: float, b: float) -> float:
    """Calculate the shortest angular difference between two angles in radians."""
    diff = b - a
    while diff < -math.pi:
        diff += math.pi * 2
    while diff > math.pi:
        diff -= math.pi * 2
    return diff


@dataclass
class Keyframe:
    x: float
    z: float
    yaw: float
    time_ms: float
    target_x: float = 0.0
    target_z: float = 0.0


@dataclass
class Pose:
    x: float
    z: float
    yaw: float


@dataclass
class Velocity:
    vx: float = 0.0
    vz: float = 0.0


def interpolate_v1_raw_snap(keyframe_queue: List[Keyframe]) -> Optional[Pose]:
    """MODE v1: Raw 0-Lag Snap to latest received keyframe."""
    if not keyframe_queue:
        return None
    last_k = keyframe_queue[-1]
    return Pose(x=last_k.x, z=last_k.z, yaw=last_k.yaw)


def interpolate_v2_simple_lerp(
    current_pose: Pose,
    target_state: Pose,
    dt: float,
    lerp_speed: float = 12.0
) -> Pose:
    """MODE v2: Simple Exponential LERP."""
    factor = 1.0 - math.exp(-lerp_speed * dt)
    new_x = current_pose.x + (target_state.x - current_pose.x) * factor
    new_z = current_pose.z + (target_state.z - current_pose.z) * factor
    d_yaw = shortest_angle_diff(current_pose.yaw, target_state.yaw)
    new_yaw = current_pose.yaw + d_yaw * factor
    return Pose(x=new_x, z=new_z, yaw=new_yaw)


def interpolate_v3_hermite_spline(
    keyframe_queue: List[Keyframe],
    render_time_or_now: float,
    measured_interval_ms: Optional[float] = None,
    buffer_offset_ms: float = 30.0
) -> Optional[Pose]:
    """
    MODE v3: Cubic Hermite Spline.
    Accepts either render_time directly or (now_ms, measured_interval_ms, buffer_offset_ms).
    Supports smooth damped extrapolation during packet starvation.
    """
    if not keyframe_queue:
        return None

    if measured_interval_ms is not None:
        render_time = render_time_or_now - (measured_interval_ms + buffer_offset_ms)
    else:
        render_time = render_time_or_now

    if len(keyframe_queue) == 1:
        k = keyframe_queue[0]
        return Pose(x=k.x, z=k.z, yaw=k.yaw)

    # 1. Before oldest keyframe in buffer: hold oldest pose
    if render_time <= keyframe_queue[0].time_ms:
        k = keyframe_queue[0]
        return Pose(x=k.x, z=k.z, yaw=k.yaw)

    # 2. Beyond newest keyframe in buffer: damped forward extrapolation
    if render_time >= keyframe_queue[-1].time_ms:
        k_prev = keyframe_queue[-2]
        k_last = keyframe_queue[-1]
        dt = (k_last.time_ms - k_prev.time_ms) / 1000.0
        if dt > 0.001:
            extra_t = (render_time - k_last.time_ms) / 1000.0
            damp = math.exp(-1.5 * extra_t)
            vx = (k_last.x - k_prev.x) / dt
            vz = (k_last.z - k_prev.z) / dt
            return Pose(
                x=k_last.x + vx * extra_t * damp,
                z=k_last.z + vz * extra_t * damp,
                yaw=k_last.yaw
            )
        return Pose(x=k_last.x, z=k_last.z, yaw=k_last.yaw)

    # 3. Standard interpolation range: find k0 and k1 bounding render_time
    for i in range(len(keyframe_queue) - 1):
        if keyframe_queue[i].time_ms <= render_time <= keyframe_queue[i + 1].time_ms:
            k0 = keyframe_queue[i]
            k1 = keyframe_queue[i + 1]
            interval = k1.time_ms - k0.time_ms
            t = (render_time - k0.time_ms) / interval if interval > 0 else 1.0
            clamped_t = max(0.0, min(1.0, t))
            u = clamped_t * clamped_t * (3.0 - 2.0 * clamped_t)
            d_yaw = shortest_angle_diff(k0.yaw, k1.yaw)
            return Pose(
                x=k0.x + (k1.x - k0.x) * u,
                z=k0.z + (k1.z - k0.z) * u,
                yaw=k0.yaw + d_yaw * u
            )

    last_k = keyframe_queue[-1]
    return Pose(x=last_k.x, z=last_k.z, yaw=last_k.yaw)


def interpolate_v4_continuous_seamless(
    current_pose: Pose,
    target_state: Pose,
    estimated_velocity: Velocity,
    dt: float,
    pull_rate: float = 3.0,
    boundary_limit: float = 15.0
) -> Pose:
    """MODE v4: Continuous Extrapolation & Target Blend (Dead Reckoning)."""
    next_x = current_pose.x + estimated_velocity.vx * dt
    next_z = current_pose.z + estimated_velocity.vz * dt

    blend_factor = 1.0 - math.exp(-pull_rate * dt)
    next_x += (target_state.x - next_x) * blend_factor
    next_z += (target_state.z - next_z) * blend_factor

    d_yaw = shortest_angle_diff(current_pose.yaw, target_state.yaw)
    yaw_factor = 1.0 - math.exp(-6.0 * dt)
    next_yaw = current_pose.yaw + d_yaw * yaw_factor

    return Pose(
        x=max(-boundary_limit, min(boundary_limit, next_x)),
        z=max(-boundary_limit, min(boundary_limit, next_z)),
        yaw=next_yaw
    )


def eval_catmull_rom_point(
    p0: Keyframe,
    p1: Keyframe,
    p2: Keyframe,
    p3: Keyframe,
    t: float,
    boundary_limit: float = 15.0
) -> Pose:
    """
    Centripetal Catmull-Rom Spline Helper (alpha = 0.5).
    Evaluates point on segment P1 -> P2 given 4 control points [P0, P1, P2, P3]
    at relative parameter t in [t1, t2].
    """
    alpha = 0.5

    def get_knot(pa: Keyframe, pb: Keyframe) -> float:
        dist_sq = (pb.x - pa.x) ** 2 + (pb.z - pa.z) ** 2
        return max(0.0001, math.pow(dist_sq, alpha * 0.5))

    t0 = 0.0
    t1 = t0 + get_knot(p0, p1)
    t2 = t1 + get_knot(p1, p2)
    t3 = t2 + get_knot(p2, p3)

    clamped_t = max(t1, min(t2, t))

    def eval_vector(s: float) -> Tuple[float, float]:
        a1x = ((t1 - s) * p0.x + (s - t0) * p1.x) / (t1 - t0)
        a1z = ((t1 - s) * p0.z + (s - t0) * p1.z) / (t1 - t0)

        a2x = ((t2 - s) * p1.x + (s - t1) * p2.x) / (t2 - t1)
        a2z = ((t2 - s) * p1.z + (s - t1) * p2.z) / (t2 - t1)

        a3x = ((t3 - s) * p2.x + (s - t2) * p3.x) / (t3 - t2)
        a3z = ((t3 - s) * p2.z + (s - t2) * p3.z) / (t3 - t2)

        b1x = ((t2 - s) * a1x + (s - t0) * a2x) / (t2 - t0)
        b1z = ((t2 - s) * a1z + (s - t0) * a2z) / (t2 - t0)

        b2x = ((t3 - s) * a2x + (s - t1) * a3x) / (t3 - t1)
        b2z = ((t3 - s) * a2z + (s - t1) * a3z) / (t3 - t1)

        cx = ((t2 - s) * b1x + (s - t1) * b2x) / (t2 - t1)
        cz = ((t2 - s) * b1z + (s - t1) * b2z) / (t2 - t1)

        return cx, cz

    pt_x, pt_z = eval_vector(clamped_t)

    delta = 0.001
    pt_a_x, pt_a_z = eval_vector(clamped_t - delta)
    pt_b_x, pt_b_z = eval_vector(clamped_t + delta)
    vx = pt_b_x - pt_a_x
    vz = pt_b_z - pt_a_z

    if math.hypot(vx, vz) > 0.0001:
        yaw = math.atan2(vx, vz)
    else:
        yaw = p1.yaw

    return Pose(
        x=max(-boundary_limit, min(boundary_limit, pt_x)),
        z=max(-boundary_limit, min(boundary_limit, pt_z)),
        yaw=yaw
    )


def interpolate_v5_catmull_rom(
    keyframe_queue: List[Keyframe],
    now_ms: float,
    measured_interval_ms: float,
    buffer_offset_ms: float = 30.0,
    boundary_limit: float = 15.0
) -> Optional[Pose]:
    """
    MODE v5: Centripetal Catmull-Rom Spline with 2-Keyframe History Buffer.
    Uses virtual endpoint reflection for seamless evaluation across all segments.
    """
    if not keyframe_queue:
        return None

    target_delay = 2.0 * measured_interval_ms + buffer_offset_ms
    render_time = now_ms - target_delay

    if len(keyframe_queue) < 2:
        return Pose(x=keyframe_queue[0].x, z=keyframe_queue[0].z, yaw=keyframe_queue[0].yaw)

    # If render_time is before the oldest keyframe: hold oldest pose
    if render_time <= keyframe_queue[0].time_ms:
        return Pose(x=keyframe_queue[0].x, z=keyframe_queue[0].z, yaw=keyframe_queue[0].yaw)

    # If render_time is beyond the newest keyframe: use smooth Hermite extrapolation
    if render_time >= keyframe_queue[-1].time_ms:
        return interpolate_v3_hermite_spline(keyframe_queue, render_time)

    # Find segment [k_idx, k_idx + 1] containing render_time
    k_idx = -1
    for i in range(len(keyframe_queue) - 1):
        if keyframe_queue[i].time_ms <= render_time <= keyframe_queue[i + 1].time_ms:
            k_idx = i
            break

    if k_idx == -1:
        return interpolate_v3_hermite_spline(keyframe_queue, render_time)

    p1 = keyframe_queue[k_idx]
    p2 = keyframe_queue[k_idx + 1]

    # P0: real keyframe or mirrored reflection
    if k_idx > 0:
        p0 = keyframe_queue[k_idx - 1]
    else:
        dt0 = p2.time_ms - p1.time_ms
        p0 = Keyframe(
            x=2.0 * p1.x - p2.x,
            z=2.0 * p1.z - p2.z,
            yaw=p1.yaw,
            time_ms=p1.time_ms - dt0
        )

    # P3: real keyframe or mirrored reflection
    if (k_idx + 2) < len(keyframe_queue):
        p3 = keyframe_queue[k_idx + 2]
    else:
        dt3 = p2.time_ms - p1.time_ms
        p3 = Keyframe(
            x=2.0 * p2.x - p1.x,
            z=2.0 * p2.z - p1.z,
            yaw=p2.yaw,
            time_ms=p2.time_ms + dt3
        )

    segment_duration = p2.time_ms - p1.time_ms
    norm_t = (render_time - p1.time_ms) / segment_duration if segment_duration > 0 else 0.0

    alpha = 0.5

    def get_knot(pa: Keyframe, pb: Keyframe) -> float:
        dist_sq = (pb.x - pa.x) ** 2 + (pb.z - pa.z) ** 2
        return max(0.0001, math.pow(dist_sq, alpha * 0.5))

    t0 = 0.0
    t1 = t0 + get_knot(p0, p1)
    t2 = t1 + get_knot(p1, p2)
    knot_t = t1 + norm_t * (t2 - t1)

    return eval_catmull_rom_point(p0, p1, p2, p3, knot_t, boundary_limit)


class WalkerPoseTracker:
    """Manages the pose, keyframe buffer, and interpolation for a single walker."""

    def __init__(
        self,
        device_id: str,
        initial_x: float = 0.0,
        initial_z: float = 0.0,
        initial_yaw: float = 0.0,
        write_hz: float = 24.0
    ):
        self.device_id = device_id
        self.current_pose = Pose(x=initial_x, z=initial_z, yaw=initial_yaw)
        self.target_state = Pose(x=initial_x, z=initial_z, yaw=initial_yaw)
        self.target_waypoint = (0.0, 0.0)
        self.estimated_velocity = Velocity(0.0, 0.0)
        self.keyframe_queue: List[Keyframe] = []
        self.write_hz: float = write_hz
        self.measured_interval_ms: float = 1000.0 / max(0.2, write_hz)
        self.last_keyframe_time_ms: float = 0.0

    def add_keyframe(
        self,
        x: float,
        z: float,
        yaw: float,
        timestamp_sec: float,
        target_x: float = 0.0,
        target_z: float = 0.0,
        write_hz: Optional[float] = None
    ):
        """Pushes a new MQTT telemetry keyframe into buffer and updates interval metrics."""
        time_ms = timestamp_sec * 1000.0
        if write_hz and write_hz > 0:
            self.write_hz = write_hz
            expected_interval = 1000.0 / write_hz
            # If rate changed substantially (e.g. slider moved to 1 Hz), adapt immediately
            if abs(self.measured_interval_ms - expected_interval) > 100.0:
                self.measured_interval_ms = expected_interval

        if self.last_keyframe_time_ms > 0:
            delta_ms = time_ms - self.last_keyframe_time_ms
            if 5.0 < delta_ms < 5000.0:
                self.measured_interval_ms = 0.7 * self.measured_interval_ms + 0.3 * delta_ms

                dt_sec = delta_ms / 1000.0
                if dt_sec > 0.001 and self.keyframe_queue:
                    prev_k = self.keyframe_queue[-1]
                    inst_vx = (x - prev_k.x) / dt_sec
                    inst_vz = (z - prev_k.z) / dt_sec
                    self.estimated_velocity.vx = 0.6 * self.estimated_velocity.vx + 0.4 * inst_vx
                    self.estimated_velocity.vz = 0.6 * self.estimated_velocity.vz + 0.4 * inst_vz

        self.last_keyframe_time_ms = time_ms
        self.target_state = Pose(x=x, z=z, yaw=yaw)
        self.target_waypoint = (target_x, target_z)

        self.keyframe_queue.append(
            Keyframe(x=x, z=z, yaw=yaw, time_ms=time_ms, target_x=target_x, target_z=target_z)
        )

        if len(self.keyframe_queue) > 50:
            self.keyframe_queue = self.keyframe_queue[-50:]

    def purge_old_keyframes(self, now_ms: float, max_age_ms: Optional[float] = None):
        """Purge keyframes older than max_age_ms, keeping enough history for low frequencies."""
        if max_age_ms is None:
            max_age_ms = max(12000.0, 6.0 * self.measured_interval_ms)

        cutoff = now_ms - max_age_ms
        if len(self.keyframe_queue) > 6:
            self.keyframe_queue = [k for k in self.keyframe_queue if k.time_ms >= cutoff]

    def evaluate_pose(
        self,
        mode: str,
        now_ms: float,
        dt_sec: float,
        buffer_offset_ms: float = 30.0
    ) -> Pose:
        """Evaluate and step the walker pose according to selected interpolation algorithm."""
        target_pose: Optional[Pose] = None

        if mode == "v1_raw_snap":
            target_pose = interpolate_v1_raw_snap(self.keyframe_queue)
        elif mode == "v2_simple_lerp":
            target_pose = interpolate_v2_simple_lerp(self.current_pose, self.target_state, dt_sec)
        elif mode == "v3_hermite_spline":
            target_delay = self.measured_interval_ms + buffer_offset_ms
            render_time = now_ms - target_delay
            target_pose = interpolate_v3_hermite_spline(self.keyframe_queue, render_time)
        elif mode == "v4_continuous_seamless":
            target_pose = interpolate_v4_continuous_seamless(
                self.current_pose, self.target_state, self.estimated_velocity, dt_sec
            )
        elif mode == "v5_catmull_rom":
            target_pose = interpolate_v5_catmull_rom(
                self.keyframe_queue, now_ms, self.measured_interval_ms, buffer_offset_ms
            )
        else:
            target_pose = interpolate_v5_catmull_rom(
                self.keyframe_queue, now_ms, self.measured_interval_ms, buffer_offset_ms
            )

        if target_pose:
            self.current_pose = target_pose

        return self.current_pose
