# MQTT 3D Random Walk Animator & Fleet Manager (Omniverse Extension)

An Omniverse Kit extension that connects NVIDIA Omniverse / Isaac Sim to a distributed IoT/device simulation fleet via Eclipse Mosquitto MQTT and Docker.

---

## 🌟 Key Capabilities

1. **Sub-Millisecond MQTT Telemetry Streaming**:
   - Background threaded subscriber to `simulation/walkers/+/state` (QoS 0) and `simulation/walkers/+/status` (QoS 1).
   - Dynamic discovery and automatic deregistration on container offline / kill.

2. **Multi-Algorithm Motion Smoothing (v1 – v5)**:
   - **`v5: Centripetal Catmull-Rom Spline`** *(Recommended)*: 2-keyframe history window ($\alpha = 0.5$) preventing overshoots, cusps, and loops around sharp corners.
   - **`v4: Continuous Extrapolation`**: Zero-gap dead-reckoning with estimated velocity and target pull.
   - **`v3: Cubic Hermite Spline`**: Filtered unique keyframes with smoothstep polynomial.
   - **`v2: Simple Exp LERP`**: Real-time framerate-independent exponential smoothing.
   - **`v1: Raw 0-Lag Snap`**: Immediate coordinate snapping.

3. **Dynamic USD Stage Prim Lifecycle**:
   - Automatically detects Stage Up-Axis (Y-up vs Z-up).
   - Generates `/World/Walkers/{device_id}` with colored chassis and heading direction cone.
   - Generates `/World/Walkers/{device_id}_target` waypoint beacon with vertical laser beam.
   - Dynamic 3D motion trails via `UsdGeom.BasisCurves`.

4. **Omniverse UI & Fleet Orchestrator Window**:
   - Available in Omniverse top bar: `Window -> MQTT Random Walk Animator`.
   - Real-time connection badge (MQTT broker status, active walker count, FPS).
   - Global algorithm selector and buffer delay slider (0 to 200 ms with quick presets).
   - Container launcher: spawn new worker containers with custom name, random walk model, publish rate, and color directly from inside Omniverse.
   - Per-device live telemetry card with runtime configuration updates and instant container termination.

---

## 🚀 How to Load in Omniverse / Isaac Sim

1. Open Omniverse (Create / Code / Isaac Sim).
2. Open Extension Manager: **Window** > **Extensions**.
3. Click the **Gear (⚙️) icon** to open Extension Search Paths.
4. Add the extension folder path:
   ```
   /home/km/agy2-projects/random_walk_mqtt_ov/extsUser
   ```
5. Search for `mqtt_animator` or `MQTT 3D Random Walk Animator & Fleet Manager`.
6. Toggle the extension **ON**.
7. The control window will automatically open. You can also re-open it at any time via:
   **Window** > **MQTT Random Walk Animator**.

---

## 📡 MQTT Topics

| Topic | QoS | Payload | Description |
| :--- | :---: | :--- | :--- |
| `simulation/walkers/{id}/state` | 0 | `{"x": 0.0, "z": 0.0, "orientation": 0.0, "target_x": 0.0, "target_z": 0.0, "write_hz": 24.0, "timestamp": 123.45}` | Real-time position telemetry |
| `simulation/walkers/{id}/status` | 1 | `{"status": "online"/"offline", "device_name": "...", "color": "#38bdf8", "model_type": "..."}` | Fleet lifecycle & configuration |
