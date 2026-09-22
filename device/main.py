import asyncio
import json
import math
import os
import random
import time
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import paho.mqtt.client as mqtt

app = FastAPI(title="Random Walk Device Simulator")

# Environment & Initial Configuration
DEVICE_ID: str = os.getenv("DEVICE_ID", f"dev-{random.randint(1000, 9999)}")
DEVICE_NAME: str = os.getenv("DEVICE_NAME", f"Device {DEVICE_ID}")
model_type: str = os.getenv("MODEL_TYPE", "target_waypoints")
write_hz: float = float(os.getenv("WRITE_HZ", "24.0"))
color: str = os.getenv("COLOR", "#38bdf8")

MQTT_BROKER_HOST: str = os.getenv("MQTT_BROKER_HOST", "mqtt")
MQTT_BROKER_PORT: int = int(os.getenv("MQTT_BROKER_PORT", "1883"))

PHYSICS_HZ: float = 60.0

# Simulation Physics State (60 Hz continuous)
sim_state = {
    "x": float(random.uniform(-5.0, 5.0)),
    "z": float(random.uniform(-5.0, 5.0)),
    "vx": 0.0,
    "vz": 0.0,
    "orientation": float(random.uniform(0, 2 * math.pi)),
    "area_bounds": 15.0
}

target_waypoint = {
    "x": round(random.uniform(-10.0, 10.0), 2),
    "z": round(random.uniform(-10.0, 10.0), 2)
}

mqtt_client: Optional[mqtt.Client] = None
is_mqtt_connected: bool = False


class ConfigUpdatePayload(BaseModel):
    model_type: Optional[str] = None
    write_hz: Optional[float] = None
    color: Optional[str] = None


def generate_new_waypoint():
    target_waypoint["x"] = round(random.uniform(-12.0, 12.0), 2)
    target_waypoint["z"] = round(random.uniform(-12.0, 12.0), 2)


def shortest_angle_diff(a, b):
    diff = b - a
    while diff < -math.pi:
        diff += math.pi * 2
    while diff > math.pi:
        diff -= math.pi * 2
    return diff


def publish_status(status_str: str = "online"):
    global mqtt_client
    if not mqtt_client:
        return
    status_topic = f"simulation/walkers/{DEVICE_ID}/status"
    payload = {
        "device_id": DEVICE_ID,
        "device_name": DEVICE_NAME,
        "status": status_str,
        "color": color,
        "model_type": model_type,
        "write_hz": write_hz,
        "timestamp": time.time()
    }
    try:
        mqtt_client.publish(status_topic, json.dumps(payload), qos=1, retain=True)
    except Exception as e:
        print(f"[{DEVICE_ID}] Error publishing status: {e}")


def init_mqtt():
    global mqtt_client, is_mqtt_connected
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"walker_{DEVICE_ID}_{random.randint(100, 999)}"
    )

    # Configure Last Will and Testament (LWT)
    status_topic = f"simulation/walkers/{DEVICE_ID}/status"
    lwt_payload = json.dumps({
        "device_id": DEVICE_ID,
        "device_name": DEVICE_NAME,
        "status": "offline",
        "timestamp": time.time()
    })
    client.will_set(status_topic, lwt_payload, qos=1, retain=True)

    def on_connect(c, userdata, flags, reason_code, properties):
        global is_mqtt_connected
        if reason_code == 0:
            is_mqtt_connected = True
            print(f"[{DEVICE_ID}] Connected to MQTT broker at {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}")
            publish_status("online")
        else:
            is_mqtt_connected = False
            print(f"[{DEVICE_ID}] Failed to connect to MQTT broker, reason: {reason_code}")

    def on_disconnect(c, userdata, disconnect_flags, reason_code, properties):
        global is_mqtt_connected
        is_mqtt_connected = False
        print(f"[{DEVICE_ID}] Disconnected from MQTT broker: {reason_code}")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    for attempt in range(15):
        try:
            client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=30)
            client.loop_start()
            mqtt_client = client
            return client
        except Exception as e:
            print(f"[{DEVICE_ID}] Waiting for MQTT broker at {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT} (attempt {attempt+1}/15): {e}")
            time.sleep(2)

    return None


async def physics_worker():
    print(f"[{DEVICE_ID}] Physics Worker started at {PHYSICS_HZ} Hz. Model: {model_type}")
    last_time = time.time()
    max_bounds = sim_state["area_bounds"]

    while True:
        current_time = time.time()
        dt = current_time - last_time
        last_time = current_time

        if dt <= 0 or dt > 0.2:
            dt = 1.0 / PHYSICS_HZ

        try:
            if model_type == "target_waypoints":
                dx = target_waypoint["x"] - sim_state["x"]
                dz = target_waypoint["z"] - sim_state["z"]
                dist = math.hypot(dx, dz)

                if dist < 2.2:
                    generate_new_waypoint()
                    dx = target_waypoint["x"] - sim_state["x"]
                    dz = target_waypoint["z"] - sim_state["z"]

                desired_angle = math.atan2(dx, dz)
                angle_diff = shortest_angle_diff(sim_state["orientation"], desired_angle)
                sim_state["orientation"] += angle_diff * min(1.0, 3.5 * dt)

                speed = 2.8
                sim_state["vx"] = math.sin(sim_state["orientation"]) * speed
                sim_state["vz"] = math.cos(sim_state["orientation"]) * speed

                sim_state["x"] += sim_state["vx"] * dt
                sim_state["z"] += sim_state["vz"] * dt

            elif model_type == "edge_repulsion":
                sim_state["orientation"] += random.uniform(-1.2, 1.2) * dt
                cruise_speed = 2.5
                sim_state["vx"] = math.sin(sim_state["orientation"]) * cruise_speed
                sim_state["vz"] = math.cos(sim_state["orientation"]) * cruise_speed

                margin = 3.0
                if sim_state["x"] > max_bounds - margin:
                    sim_state["vx"] -= 4.0 * dt
                elif sim_state["x"] < -max_bounds + margin:
                    sim_state["vx"] += 4.0 * dt

                if sim_state["z"] > max_bounds - margin:
                    sim_state["vz"] -= 4.0 * dt
                elif sim_state["z"] < -max_bounds + margin:
                    sim_state["vz"] += 4.0 * dt

                sim_state["x"] += sim_state["vx"] * dt
                sim_state["z"] += sim_state["vz"] * dt

                if math.hypot(sim_state["vx"], sim_state["vz"]) > 0.1:
                    sim_state["orientation"] = math.atan2(sim_state["vx"], sim_state["vz"])

            elif model_type == "langevin":
                damping = 0.85
                sim_state["vx"] *= (1.0 - damping * dt)
                sim_state["vz"] *= (1.0 - damping * dt)

                noise_strength = 6.0
                sim_state["vx"] += random.gauss(0, 1) * noise_strength * math.sqrt(dt)
                sim_state["vz"] += random.gauss(0, 1) * noise_strength * math.sqrt(dt)

                speed = math.hypot(sim_state["vx"], sim_state["vz"])
                if speed < 0.8:
                    angle = random.uniform(0, 2 * math.pi)
                    sim_state["vx"] += math.cos(angle) * 1.2
                    sim_state["vz"] += math.sin(angle) * 1.2

                sim_state["x"] += sim_state["vx"] * dt
                sim_state["z"] += sim_state["vz"] * dt

                if math.hypot(sim_state["vx"], sim_state["vz"]) > 0.05:
                    sim_state["orientation"] = math.atan2(sim_state["vx"], sim_state["vz"])

            # Area bounds constraint
            if sim_state["x"] < -max_bounds:
                sim_state["x"] = -max_bounds
            elif sim_state["x"] > max_bounds:
                sim_state["x"] = max_bounds

            if sim_state["z"] < -max_bounds:
                sim_state["z"] = -max_bounds
            elif sim_state["z"] > max_bounds:
                sim_state["z"] = max_bounds

        except Exception as e:
            print(f"[{DEVICE_ID}] Physics Worker Error: {e}")

        await asyncio.sleep(1.0 / PHYSICS_HZ)


async def mqtt_publisher_worker():
    """Publishes coordinates and telemetry to MQTT simulation/walkers/{device_id}/state at write_hz."""
    state_topic = f"simulation/walkers/{DEVICE_ID}/state"
    print(f"[{DEVICE_ID}] MQTT Publisher Worker started at {write_hz} Hz on topic {state_topic}")

    while True:
        try:
            if mqtt_client and is_mqtt_connected:
                payload = {
                    "device_id": DEVICE_ID,
                    "device_name": DEVICE_NAME,
                    "model_type": model_type,
                    "color": color,
                    "x": round(sim_state["x"], 3),
                    "z": round(sim_state["z"], 3),
                    "orientation": round(sim_state["orientation"], 4),
                    "target_x": round(target_waypoint["x"], 2) if model_type == "target_waypoints" else 0.0,
                    "target_z": round(target_waypoint["z"], 2) if model_type == "target_waypoints" else 0.0,
                    "write_hz": write_hz,
                    "timestamp": time.time()
                }
                mqtt_client.publish(state_topic, json.dumps(payload), qos=0, retain=False)
        except Exception as e:
            print(f"[{DEVICE_ID}] MQTT Publisher Error: {e}")

        sleep_duration = max(0.005, 1.0 / write_hz)
        await asyncio.sleep(sleep_duration)


@app.on_event("startup")
async def startup_event():
    init_mqtt()
    asyncio.create_task(physics_worker())
    asyncio.create_task(mqtt_publisher_worker())


@app.on_event("shutdown")
async def shutdown_event():
    """Mark device inactive on clean container exit."""
    print(f"[{DEVICE_ID}] Shutting down cleanly...")
    publish_status("offline")
    if mqtt_client:
        try:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
        except Exception as e:
            print(f"[{DEVICE_ID}] Error stopping MQTT client: {e}")


@app.get("/health")
@app.get("/status")
async def get_status():
    return {
        "device_id": DEVICE_ID,
        "device_name": DEVICE_NAME,
        "model_type": model_type,
        "write_hz": write_hz,
        "color": color,
        "mqtt_connected": is_mqtt_connected,
        "current_pose": {
            "x": sim_state["x"],
            "z": sim_state["z"],
            "orientation": sim_state["orientation"]
        },
        "target_waypoint": target_waypoint if model_type == "target_waypoints" else None
    }


@app.post("/config")
async def update_config(payload: ConfigUpdatePayload):
    global model_type, write_hz, color
    if payload.model_type in ["target_waypoints", "edge_repulsion", "langevin"]:
        model_type = payload.model_type
        if model_type == "target_waypoints":
            generate_new_waypoint()
    if payload.write_hz is not None and 1.0 <= payload.write_hz <= 120.0:
        write_hz = float(payload.write_hz)
    if payload.color is not None:
        color = payload.color

    print(f"[{DEVICE_ID}] Config updated: Model={model_type}, WriteHz={write_hz}, Color={color}")
    publish_status("online")

    return {
        "device_id": DEVICE_ID,
        "model_type": model_type,
        "write_hz": write_hz,
        "color": color
    }
