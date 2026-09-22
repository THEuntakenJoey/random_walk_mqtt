"""
MQTT Service for subscribing to walker telemetry and status messages.
Uses paho-mqtt client with thread-safe message queue consumed by Omniverse main update loop.
"""

import json
import queue
import random
import sys
import threading
import time
from typing import Dict, Any, List, Optional, Tuple

# Dynamic dependency resolution: if in Omniverse Kit, ensure paho-mqtt is available
try:
    import paho.mqtt.client as mqtt
except ImportError:
    try:
        import omni.kit.pipapi
        omni.kit.pipapi.install("paho-mqtt>=2.0.0")
        import paho.mqtt.client as mqtt
    except Exception as e:
        mqtt = None


class MqttService:
    """Subscribes to MQTT topics and stores parsed events in a thread-safe queue."""

    def __init__(self, host: str = "localhost", port: int = 1883, client_id: Optional[str] = None):
        self.host = host
        self.port = port
        self.client_id = client_id or f"ov_animator_{random.randint(1000, 9999)}"

        self._client: Optional[Any] = None
        self._is_connected: bool = False
        self._stop_event = threading.Event()
        self._message_queue: queue.Queue = queue.Queue(maxsize=1000)
        self._thread: Optional[threading.Thread] = None
        self.last_seen_devices: Dict[str, float] = {}

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def start(self):
        """Starts the MQTT client network loop in background."""
        if mqtt is None:
            print("[MqttService Warning] paho-mqtt library is not available. MQTT subscriber disabled.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ov_mqtt_loop")
        self._thread.start()

    def _run_loop(self):
        """Worker thread loop managing connection and reconnections."""
        try:
            # Handle paho-mqtt v1 vs v2 callback API versions
            if hasattr(mqtt, "CallbackAPIVersion"):
                self._client = mqtt.Client(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id=self.client_id
                )
            else:
                self._client = mqtt.Client(client_id=self.client_id)

            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message = self._on_message

            print(f"[MqttService] Connecting to {self.host}:{self.port}...")
            self._client.connect(self.host, self.port, keepalive=30)
            self._client.loop_start()

            while not self._stop_event.is_set():
                time.sleep(0.5)

            self._client.loop_stop()
            self._client.disconnect()
        except Exception as e:
            print(f"[MqttService Error] Failed in MQTT loop: {e}")
            self._is_connected = False

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        rc = getattr(reason_code, "value", reason_code)
        if rc == 0:
            self._is_connected = True
            print(f"[MqttService] Successfully connected to broker at {self.host}:{self.port}")
            client.subscribe([
                ("simulation/walkers/+/status", 1),
                ("simulation/walkers/+/state", 0)
            ])
            print("[MqttService] Subscribed to simulation/walkers/+/status and state")
        else:
            self._is_connected = False
            print(f"[MqttService] Connect failed with code: {reason_code}")

    def _on_disconnect(self, client, userdata, disconnect_flags=None, reason_code=None, properties=None):
        self._is_connected = False
        print(f"[MqttService] Disconnected from MQTT broker (reason: {reason_code})")

    def _on_message(self, client, userdata, msg):
        try:
            topic_parts = msg.topic.split("/")
            if len(topic_parts) >= 4 and topic_parts[0] == "simulation" and topic_parts[1] == "walkers":
                device_id = topic_parts[2]
                action = topic_parts[3]  # "state" or "status"
                payload = json.loads(msg.payload.decode("utf-8"))

                self.last_seen_devices[device_id] = time.time()

                if not self._message_queue.full():
                    self._message_queue.put_nowait((device_id, action, payload))
        except Exception as e:
            print(f"[MqttService Error] Error parsing message on {msg.topic}: {e}")

    def poll_messages(self, max_batch: int = 150) -> List[Tuple[str, str, Dict[str, Any]]]:
        """Drains up to max_batch messages from thread-safe queue. Called from main update thread."""
        messages = []
        count = 0
        while not self._message_queue.empty() and count < max_batch:
            try:
                item = self._message_queue.get_nowait()
                messages.append(item)
                count += 1
            except queue.Empty:
                break
        return messages

    def stop(self):
        """Stops background loop and cleans up."""
        self._stop_event.set()
        if self._client:
            try:
                self._client.disconnect()
            except Exception:
                pass
        self._is_connected = False
