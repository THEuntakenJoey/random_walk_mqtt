"""
Omniverse Extension Entrypoint for MQTT Random Walk Animator & Fleet Manager.
Coordinates MQTT subscriptions, USD stage updates, interpolation, and the omni.ui interface.
"""

import time
from typing import Dict, Any, Optional

try:
    import carb
    import omni.ext
    import omni.kit.app
    _BaseExt = omni.ext.IExt
except ImportError:
    carb = None
    omni = None
    _BaseExt = object

from .interpolator import WalkerPoseTracker
from .stage_manager import UsdStageManager
from .mqtt_service import MqttService
from .container_client import FleetApiClient
from .ui_builder import UIBuilder


class Extension(_BaseExt):
    """Omniverse Kit Extension for Real-Time MQTT Telemetry & Fleet Control."""

    def on_startup(self, ext_id):
        if carb:
            carb.log_info(f"[MQTT Animator] on_startup {ext_id}")
        else:
            print(f"[MQTT Animator] on_startup {ext_id}")

        # 1. State and Configuration
        self.current_interpolation_mode = "v5_catmull_rom"
        self.buffer_offset_ms = 40.0
        self.trackers: Dict[str, WalkerPoseTracker] = {}
        self.device_meta: Dict[str, Dict[str, Any]] = {}

        self._frame_count = 0
        self._last_fps_time = time.time()
        self._fps = 60
        self._last_tick_time = time.time()

        # 2. Initialize Subsystems
        self.stage_manager = UsdStageManager(base_root_path="/World/Walkers")
        self.fleet_client = FleetApiClient(base_url="http://localhost:8000")
        self.mqtt_service = MqttService(host="localhost", port=1883)
        self.mqtt_service.start()

        # 3. Build UI
        self.ui_builder = UIBuilder(
            window_title="MQTT Random Walk Animator & Fleet",
            menu_path="Window/MQTT Random Walk Animator",
            extension_instance=self
        )

        # 4. Subscribe to Kit Update Loop
        self._update_sub = None
        try:
            if omni and hasattr(omni, "kit") and hasattr(omni.kit, "app"):
                app = omni.kit.app.get_app()
                self._update_sub = app.get_update_event_stream().create_subscription_to_pop(
                    self._on_update, name="test.mqtt_animator.update"
                )
        except Exception as e:
            print(f"[MQTT Animator Warning] Could not subscribe to Kit update stream: {e}")

    def _on_update(self, event):
        """Called once per frame on Omniverse rendering thread."""
        now = time.time()
        dt = min(now - self._last_tick_time, 0.1)
        self._last_tick_time = now

        # FPS calculation
        self._frame_count += 1
        if now - self._last_fps_time >= 1.0:
            self._fps = int(self._frame_count / (now - self._last_fps_time))
            self._frame_count = 0
            self._last_fps_time = now

        # 1. Drain incoming MQTT messages
        messages = self.mqtt_service.poll_messages(max_batch=200)
        for device_id, action, payload in messages:
            if action == "status":
                status = payload.get("status")
                if status == "offline":
                    self._handle_device_offline(device_id)
                else:
                    self._handle_device_online(device_id, payload)
            elif action == "state":
                self._handle_device_state(device_id, payload)

        now_ms = now * 1000.0

        # 2. Evaluate interpolation and update USD Stage Prims
        for device_id, tracker in list(self.trackers.items()):
            tracker.purge_old_keyframes(now_ms)
            pose = tracker.evaluate_pose(
                mode=self.current_interpolation_mode,
                now_ms=now_ms,
                dt_sec=dt,
                buffer_offset_ms=self.buffer_offset_ms
            )

            meta = self.device_meta.get(device_id, {})
            model_type = meta.get("model_type", "target_waypoints")
            target_x, target_z = tracker.target_waypoint

            # Update USD Prim transforms
            self.stage_manager.update_pose(
                device_id=device_id,
                x=pose.x,
                z=pose.z,
                yaw_rad=pose.yaw,
                target_x=target_x,
                target_z=target_z,
                model_type=model_type,
                now_time=now
            )

            # Sync UI telemetry card
            if self.ui_builder:
                self.ui_builder.sync_device_card(
                    device_id=device_id,
                    name=meta.get("device_name", device_id),
                    color_hex=meta.get("color", "#38bdf8"),
                    model_type=model_type,
                    write_hz=tracker.write_hz,
                    x=pose.x,
                    z=pose.z,
                    yaw_rad=pose.yaw
                )

        # 3. Update global UI telemetry
        if self.ui_builder:
            self.ui_builder.update_telemetry(
                is_connected=self.mqtt_service.is_connected,
                device_count=len(self.trackers),
                fps=self._fps
            )

    def _handle_device_online(self, device_id: str, payload: Dict[str, Any]):
        """Register newly active device."""
        color = payload.get("color", "#38bdf8")
        model_type = payload.get("model_type", "target_waypoints")
        name = payload.get("device_name", device_id)
        write_hz = float(payload.get("write_hz", 24.0))

        self.device_meta[device_id] = {
            "device_id": device_id,
            "device_name": name,
            "color": color,
            "model_type": model_type,
            "write_hz": write_hz
        }

        if device_id not in self.trackers:
            self.trackers[device_id] = WalkerPoseTracker(device_id)

        self.trackers[device_id].write_hz = write_hz
        self.stage_manager.register_device(device_id, color_hex=color, model_type=model_type)

    def _handle_device_offline(self, device_id: str):
        """Clean up device when offline."""
        self.trackers.pop(device_id, None)
        self.device_meta.pop(device_id, None)
        self.stage_manager.remove_device(device_id)
        if self.ui_builder:
            self.ui_builder.remove_device_card(device_id)

    def _handle_device_state(self, device_id: str, payload: Dict[str, Any]):
        """Process incoming position keyframe."""
        if device_id not in self.trackers:
            self.trackers[device_id] = WalkerPoseTracker(device_id)
            if device_id not in self.device_meta:
                self.device_meta[device_id] = {"device_id": device_id, "color": "#38bdf8"}
            self.stage_manager.register_device(device_id)

        x = float(payload.get("x", 0.0))
        z = float(payload.get("z", 0.0))
        yaw = float(payload.get("orientation", 0.0))
        ts = float(payload.get("timestamp", time.time()))
        target_x = float(payload.get("target_x", 0.0))
        target_z = float(payload.get("target_z", 0.0))
        write_hz = float(payload.get("write_hz", 24.0))

        self.trackers[device_id].add_keyframe(
            x=x,
            z=z,
            yaw=yaw,
            timestamp_sec=ts,
            target_x=target_x,
            target_z=target_z,
            write_hz=write_hz
        )

    def on_shutdown(self):
        """Called when extension is disabled or Omniverse exits."""
        if carb:
            carb.log_info("[MQTT Animator] on_shutdown")

        if self._update_sub is not None:
            self._update_sub = None

        if hasattr(self, "mqtt_service") and self.mqtt_service:
            self.mqtt_service.stop()

        if hasattr(self, "fleet_client") and self.fleet_client:
            self.fleet_client.shutdown()

        if hasattr(self, "stage_manager") and self.stage_manager:
            self.stage_manager.clear_all()

        if hasattr(self, "ui_builder") and self.ui_builder:
            self.ui_builder.cleanup()


del _BaseExt
__all__ = ["Extension"]
