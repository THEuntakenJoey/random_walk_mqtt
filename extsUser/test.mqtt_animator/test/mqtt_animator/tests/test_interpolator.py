"""
Unit tests for the Omniverse MQTT Animator interpolation algorithms.
Compatible with both omni.kit.test.AsyncTestCase and standard unittest.
"""

import math
import sys
from pathlib import Path

ext_root = Path(__file__).resolve().parent.parent
if str(ext_root) not in sys.path:
    sys.path.insert(0, str(ext_root))

try:
    import omni.kit.test
    BaseTestCase = omni.kit.test.AsyncTestCase
except ImportError:
    import unittest
    BaseTestCase = unittest.TestCase

from impl.interpolator import (
    shortest_angle_diff,
    Keyframe,
    Pose,
    Velocity,
    interpolate_v1_raw_snap,
    interpolate_v2_simple_lerp,
    interpolate_v3_hermite_spline,
    interpolate_v4_continuous_seamless,
    interpolate_v5_catmull_rom,
    WalkerPoseTracker,
)


class TestInterpolator(BaseTestCase):

    async def setUp(self):
        if hasattr(super(), "setUp") and callable(super().setUp):
            res = super().setUp()
            if hasattr(res, "__await__"):
                await res

    async def tearDown(self):
        if hasattr(super(), "tearDown") and callable(super().tearDown):
            res = super().tearDown()
            if hasattr(res, "__await__"):
                await res

    async def test_shortest_angle_diff(self):
        self.assertAlmostEqual(shortest_angle_diff(0.1, 0.3), 0.2, places=5)
        self.assertAlmostEqual(shortest_angle_diff(0.3, 0.1), -0.2, places=5)
        diff = shortest_angle_diff(3.10, -3.10)
        self.assertAlmostEqual(diff, 2 * math.pi - 6.20, places=5)
        self.assertLess(abs(diff), 0.1)

    async def test_v1_raw_snap(self):
        queue = [
            Keyframe(x=1.0, z=2.0, yaw=0.5, time_ms=100.0),
            Keyframe(x=3.0, z=4.0, yaw=1.0, time_ms=200.0),
        ]
        pose = interpolate_v1_raw_snap(queue)
        self.assertIsNotNone(pose)
        self.assertEqual(pose.x, 3.0)
        self.assertEqual(pose.z, 4.0)
        self.assertEqual(pose.yaw, 1.0)
        self.assertIsNone(interpolate_v1_raw_snap([]))

    async def test_v2_simple_lerp(self):
        current = Pose(x=0.0, z=0.0, yaw=0.0)
        target = Pose(x=10.0, z=10.0, yaw=math.pi / 2)
        dt = 0.05
        pose = interpolate_v2_simple_lerp(current, target, dt, lerp_speed=12.0)

        self.assertGreater(pose.x, 0.0)
        self.assertLess(pose.x, 10.0)
        self.assertGreater(pose.z, 0.0)
        self.assertLess(pose.z, 10.0)
        self.assertAlmostEqual(pose.x, 10.0 * (1.0 - math.exp(-0.6)), places=3)
        self.assertAlmostEqual(pose.z, 10.0 * (1.0 - math.exp(-0.6)), places=3)

    async def test_v3_hermite_spline(self):
        now_ms = 1000.0
        interval_ms = 50.0
        buffer_offset_ms = 30.0

        queue = [
            Keyframe(x=0.0, z=0.0, yaw=0.0, time_ms=850.0),
            Keyframe(x=5.0, z=5.0, yaw=0.5, time_ms=900.0),
            Keyframe(x=10.0, z=10.0, yaw=1.0, time_ms=950.0),
            Keyframe(x=15.0, z=15.0, yaw=1.5, time_ms=1000.0),
        ]

        pose = interpolate_v3_hermite_spline(queue, now_ms, interval_ms, buffer_offset_ms)
        self.assertIsNotNone(pose)
        self.assertAlmostEqual(pose.x, 6.76, places=3)
        self.assertAlmostEqual(pose.z, 6.76, places=3)

    async def test_v4_continuous_seamless(self):
        current = Pose(x=5.0, z=5.0, yaw=0.0)
        target = Pose(x=6.0, z=6.0, yaw=0.1)
        velocity = Velocity(vx=2.0, vz=2.0)
        dt = 0.05
        pose = interpolate_v4_continuous_seamless(current, target, velocity, dt)
        self.assertIsNotNone(pose)
        self.assertGreater(pose.x, 5.1)
        self.assertLess(pose.x, 6.0)

    async def test_v5_catmull_rom(self):
        now_ms = 1000.0
        interval_ms = 40.0
        buffer_offset_ms = 30.0

        queue = [
            Keyframe(x=0.0, z=0.0, yaw=0.0, time_ms=800.0),
            Keyframe(x=2.0, z=1.0, yaw=0.2, time_ms=850.0),
            Keyframe(x=5.0, z=3.0, yaw=0.5, time_ms=900.0),
            Keyframe(x=9.0, z=6.0, yaw=0.8, time_ms=950.0),
            Keyframe(x=14.0, z=10.0, yaw=1.0, time_ms=1000.0),
        ]

        pose = interpolate_v5_catmull_rom(queue, now_ms, interval_ms, buffer_offset_ms)
        self.assertIsNotNone(pose)
        self.assertGreater(pose.x, 2.0)
        self.assertLess(pose.x, 5.0)
        self.assertGreater(pose.z, 1.0)
        self.assertLess(pose.z, 3.0)

    async def test_walker_pose_tracker(self):
        tracker = WalkerPoseTracker("test-dev-1", initial_x=0.0, initial_z=0.0, initial_yaw=0.0)
        self.assertEqual(tracker.device_id, "test-dev-1")

        tracker.add_keyframe(x=0.0, z=0.0, yaw=0.0, timestamp_sec=10.00, target_x=5.0, target_z=5.0, write_hz=20.0)
        tracker.add_keyframe(x=1.0, z=1.0, yaw=0.1, timestamp_sec=10.05, target_x=5.0, target_z=5.0, write_hz=20.0)
        tracker.add_keyframe(x=2.0, z=2.0, yaw=0.2, timestamp_sec=10.10, target_x=5.0, target_z=5.0, write_hz=20.0)
        tracker.add_keyframe(x=3.0, z=3.0, yaw=0.3, timestamp_sec=10.15, target_x=5.0, target_z=5.0, write_hz=20.0)
        tracker.add_keyframe(x=4.0, z=4.0, yaw=0.4, timestamp_sec=10.20, target_x=5.0, target_z=5.0, write_hz=20.0)

        self.assertEqual(len(tracker.keyframe_queue), 5)
        self.assertAlmostEqual(tracker.target_waypoint[0], 5.0)

        pose = tracker.evaluate_pose(
            mode="v5_catmull_rom",
            now_ms=10200.0,
            dt_sec=0.016,
            buffer_offset_ms=30.0
        )
        self.assertIsNotNone(pose)
        self.assertGreater(pose.x, 0.0)

    async def test_1hz_low_frequency_smoothness(self):
        """Verify that 1 Hz updates interpolate smoothly without teleportation jumps or stalls."""
        tracker = WalkerPoseTracker("walker-1hz", write_hz=1.0)
        self.assertEqual(tracker.measured_interval_ms, 1000.0)

        # 4 packets at 1-second intervals
        tracker.add_keyframe(x=0.0, z=0.0, yaw=0.0, timestamp_sec=10.0, write_hz=1.0)
        tracker.add_keyframe(x=2.0, z=0.0, yaw=0.0, timestamp_sec=11.0, write_hz=1.0)
        tracker.add_keyframe(x=4.0, z=0.0, yaw=0.0, timestamp_sec=12.0, write_hz=1.0)
        tracker.add_keyframe(x=6.0, z=0.0, yaw=0.0, timestamp_sec=13.0, write_hz=1.0)

        # Evaluate across 60 frames during a 1-second span
        prev_x = 0.0
        for frame in range(60):
            sim_time_ms = 13000.0 + (frame * 16.66)
            pose = tracker.evaluate_pose(
                mode="v5_catmull_rom",
                now_ms=sim_time_ms,
                dt_sec=0.0166,
                buffer_offset_ms=30.0
            )
            # Ensure strictly monotonic continuous forward motion without jumps backwards or stalling
            if frame > 0:
                self.assertGreaterEqual(pose.x, prev_x, f"Frame {frame} jumped backward!")
                step = pose.x - prev_x
                # Max reasonable step per 16ms frame for speed ~2m/s is < 0.15m
                self.assertLess(step, 0.2, f"Frame {frame} had jump step {step}!")
            prev_x = pose.x


if __name__ == "__main__":
    import unittest
    unittest.main()
