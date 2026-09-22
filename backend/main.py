import asyncio
from contextlib import asynccontextmanager
import concurrent.futures
import json
import os
import random
import time
from typing import Set, Optional, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import docker
import paho.mqtt.client as mqtt

# Global Configuration
MQTT_BROKER_HOST: str = os.getenv("MQTT_BROKER_HOST", "mqtt")
MQTT_BROKER_PORT: int = int(os.getenv("MQTT_BROKER_PORT", "1883"))
DOCKER_NETWORK: str = os.getenv("DOCKER_NETWORK", "rw_network")
DEVICE_IMAGE: str = os.getenv("DEVICE_IMAGE", "random-walk-device:latest")

PRESET_COLORS = [
    "#38bdf8",  # Sky Blue
    "#a855f7",  # Purple
    "#34d399",  # Emerald Mint
    "#f43f5e",  # Rose
    "#fbbf24",  # Amber
    "#06b6d4",  # Cyan
    "#f97316",  # Bright Orange
    "#ec4899",  # Hot Pink
]

# In-memory fleet state tracking
active_devices: Dict[str, Dict[str, Any]] = {}
mqtt_client: Optional[mqtt.Client] = None
is_mqtt_connected: bool = False
connected_websockets: Set[WebSocket] = set()

# Docker Client
docker_client = None
try:
    docker_client = docker.from_env()
    print("[Docker] Docker client initialized successfully from environment.")
except Exception as e:
    print(f"[Docker Warning] Could not connect to Docker daemon: {e}")


def prune_exited_containers():
    """Prunes any dead/exited device containers left over from prior unclean runs."""
    if not docker_client:
        return
    try:
        exited = docker_client.containers.list(all=True, filters={"name": "rw-device-", "status": "exited"})
        for c in exited:
            try:
                c.remove(force=True)
            except Exception:
                pass
        if exited:
            print(f"[Backend Startup] Pruned {len(exited)} stale/exited device container(s).")
    except Exception as e:
        print(f"[Backend Startup Warning] Could not prune exited containers: {e}")


def cleanup_device_containers():
    """Stops and force-removes all dynamically spawned device containers so docker network and host resources are released cleanly."""
    if not docker_client:
        return
    try:
        containers = docker_client.containers.list(all=True, filters={"name": "rw-device-"})
        if not containers:
            return
        print(f"[Backend Shutdown] Tearing down {len(containers)} dynamically spawned device container(s)...")

        def remove_single(c):
            try:
                c.remove(force=True)
                print(f"[Backend Shutdown] Removed device container {c.name}")
            except Exception as ce:
                print(f"[Backend Shutdown Warning] Could not remove {c.name}: {ce}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, max(len(containers), 1))) as executor:
            list(executor.map(remove_single, containers))

        print("[Backend Shutdown] All device containers successfully removed.")
    except Exception as e:
        print(f"[Backend Shutdown Cleanup Error] Failed to list or remove device containers: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    prune_exited_containers()
    init_mqtt_subscriber()
    yield
    # Shutdown logic (triggered when container receives SIGTERM from docker compose down)
    global mqtt_client
    if mqtt_client:
        try:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
        except Exception as e:
            print(f"[Backend Shutdown Warning] MQTT disconnect error: {e}")
    # Force clean up all dynamic devices to immediately free the docker network
    cleanup_device_containers()


app = FastAPI(title="Random Walk Orchestrator & MQTT Gateway API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SpawnRequest(BaseModel):
    device_id: Optional[str] = None
    device_name: Optional[str] = None
    model_type: Optional[str] = "target_waypoints"
    write_hz: Optional[float] = 24.0
    color: Optional[str] = None


class DeviceConfigPayload(BaseModel):
    model_type: Optional[str] = None
    write_hz: Optional[float] = None
    color: Optional[str] = None


def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    global is_mqtt_connected
    if reason_code == 0:
        is_mqtt_connected = True
        print(f"[Backend MQTT] Connected to broker at {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}")
        # Subscribe to walker status and state topics
        client.subscribe([
            ("simulation/walkers/+/status", 1),
            ("simulation/walkers/+/state", 0)
        ])
        print("[Backend MQTT] Subscribed to simulation/walkers/+/status and simulation/walkers/+/state")
    else:
        is_mqtt_connected = False
        print(f"[Backend MQTT] Connect failed, reason: {reason_code}")


def on_mqtt_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    global is_mqtt_connected
    is_mqtt_connected = False
    print(f"[Backend MQTT] Disconnected from broker: {reason_code}")


def on_mqtt_message(client, userdata, msg):
    try:
        topic_parts = msg.topic.split("/")
        if len(topic_parts) >= 4 and topic_parts[0] == "simulation" and topic_parts[1] == "walkers":
            device_id = topic_parts[2]
            action = topic_parts[3]
            payload = json.loads(msg.payload.decode("utf-8"))

            if action == "status":
                status = payload.get("status")
                if status == "offline":
                    if device_id in active_devices:
                        print(f"[Backend Fleet] Walker {device_id} went offline.")
                        del active_devices[device_id]
                else:
                    if device_id not in active_devices:
                        print(f"[Backend Fleet] Walker {device_id} discovered online.")
                    active_devices[device_id] = {
                        **active_devices.get(device_id, {}),
                        **payload,
                        "device_id": device_id,
                        "is_active": True,
                        "last_seen": time.time()
                    }

            elif action == "state":
                if device_id in active_devices:
                    active_devices[device_id].update({
                        "x": payload.get("x", 0.0),
                        "z": payload.get("z", 0.0),
                        "orientation": payload.get("orientation", 0.0),
                        "target_x": payload.get("target_x", 0.0),
                        "target_z": payload.get("target_z", 0.0),
                        "write_hz": payload.get("write_hz", 24.0),
                        "last_seen": time.time()
                    })
    except Exception as e:
        print(f"[Backend MQTT Message Error] {e}")


def init_mqtt_subscriber():
    global mqtt_client
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"backend_orchestrator_{random.randint(1000, 9999)}"
    )
    client.on_connect = on_mqtt_connect
    client.on_disconnect = on_mqtt_disconnect
    client.on_message = on_mqtt_message

    for attempt in range(15):
        try:
            client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=30)
            client.loop_start()
            mqtt_client = client
            return client
        except Exception as e:
            print(f"[Backend] Waiting for MQTT broker at {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT} (attempt {attempt+1}/15): {e}")
            time.sleep(2)
    return None




@app.get("/api/status")
async def get_status():
    return {
        "status": "online",
        "service": "Random Walk Orchestrator & MQTT Gateway",
        "mqtt_connected": is_mqtt_connected,
        "mqtt_host": f"{MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}",
        "docker_available": docker_client is not None,
        "active_devices_count": len(active_devices),
        "active_devices": active_devices,
        "connected_ws_clients": len(connected_websockets)
    }


@app.get("/api/containers")
async def list_containers():
    """Lists device containers and their status."""
    containers_info = []
    if not docker_client:
        raise HTTPException(status_code=500, detail="Docker client not available")

    try:
        containers = docker_client.containers.list(all=True, filters={"name": "rw-device-"})
        for c in containers:
            d_id = c.name.replace("rw-device-", "")
            containers_info.append({
                "container_id": c.id[:12],
                "container_name": c.name,
                "device_id": d_id,
                "status": c.status
            })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error querying Docker: {e}")

    return {"containers": containers_info}


@app.post("/api/containers/spawn")
async def spawn_container(req: SpawnRequest):
    """Spawns a new device container attached to the Docker network with MQTT broker settings."""
    if not docker_client:
        raise HTTPException(status_code=500, detail="Docker client not available (check /var/run/docker.sock)")

    # 1. Generate unique Device ID and Name
    suffix = random.randint(100, 999)
    device_id = req.device_id or f"dev-{suffix}"
    device_name = req.device_name or f"Walker #{suffix}"
    container_name = f"rw-device-{device_id}"

    # Pick color from palette or request
    color = req.color
    if not color:
        color = random.choice(PRESET_COLORS)

    # 2. Check if container with this name already exists
    try:
        existing = docker_client.containers.get(container_name)
        if existing:
            if existing.status == "running":
                return {"status": "already_running", "device_id": device_id, "container_name": container_name}
            else:
                existing.remove(force=True)
    except docker.errors.NotFound:
        pass
    except Exception as e:
        print(f"[Spawn Check Warning] {e}")

    # 3. Launch container
    try:
        env_vars = {
            "DEVICE_ID": device_id,
            "DEVICE_NAME": device_name,
            "MODEL_TYPE": req.model_type or "target_waypoints",
            "WRITE_HZ": str(req.write_hz or 24.0),
            "COLOR": color,
            "MQTT_BROKER_HOST": MQTT_BROKER_HOST,
            "MQTT_BROKER_PORT": str(MQTT_BROKER_PORT)
        }

        # Verify network exists or fallback
        network_to_use = DOCKER_NETWORK
        try:
            docker_client.networks.get(network_to_use)
        except docker.errors.NotFound:
            for net in docker_client.networks.list():
                if "rw" in net.name or "random_walk" in net.name:
                    network_to_use = net.name
                    break

        print(f"[Docker Spawn] Running {container_name} on network '{network_to_use}' with MQTT broker {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}...")
        container = docker_client.containers.run(
            DEVICE_IMAGE,
            name=container_name,
            detach=True,
            environment=env_vars,
            network=network_to_use,
            restart_policy={"Name": "on-failure", "MaximumRetryCount": 3},
            labels={
                "random_walk.managed": "true",
                "random_walk.device_id": device_id
            }
        )

        return {
            "status": "spawned",
            "device_id": device_id,
            "device_name": device_name,
            "container_name": container_name,
            "color": color,
            "model_type": req.model_type,
            "write_hz": req.write_hz
        }
    except Exception as e:
        print(f"[Docker Spawn Error] {e}")
        raise HTTPException(status_code=500, detail=f"Failed to spawn device container: {e}")


@app.post("/api/containers/{device_id}/kill")
async def kill_container(device_id: str):
    """Kills and removes a device container, cleans up state, and announces offline over MQTT."""
    container_name = f"rw-device-{device_id}"
    removed_from_docker = False

    if docker_client:
        try:
            container = docker_client.containers.get(container_name)
            container.stop(timeout=2)
            container.remove(force=True)
            removed_from_docker = True
            print(f"[Docker Kill] Successfully stopped and removed {container_name}")
        except docker.errors.NotFound:
            print(f"[Docker Kill Notice] Container {container_name} not found in Docker.")
        except Exception as e:
            print(f"[Docker Kill Error] {e}")

    # Remove from active devices
    active_devices.pop(device_id, None)

    # Publish retained offline status to notify MQTT subscribers immediately
    if mqtt_client and is_mqtt_connected:
        try:
            status_topic = f"simulation/walkers/{device_id}/status"
            mqtt_client.publish(
                status_topic,
                json.dumps({"device_id": device_id, "status": "offline", "timestamp": time.time()}),
                qos=1,
                retain=True
            )
        except Exception as e:
            print(f"[Backend Kill Status Pub Error] {e}")

    return {
        "status": "killed",
        "device_id": device_id,
        "removed_from_docker": removed_from_docker
    }


@app.post("/api/containers/{device_id}/config")
async def update_device_config(device_id: str, payload: DeviceConfigPayload):
    """Proxies config changes directly to the device container's internal HTTP REST port (8001)."""
    container_host = f"rw-device-{device_id}"
    target_url = f"http://{container_host}:8001/config"

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(target_url, json=payload.dict(exclude_none=True))
            if resp.status_code == 200:
                result = resp.json()
                if device_id in active_devices:
                    if payload.color:
                        active_devices[device_id]["color"] = payload.color
                    if payload.model_type:
                        active_devices[device_id]["model_type"] = payload.model_type
                    if payload.write_hz:
                        active_devices[device_id]["write_hz"] = payload.write_hz
                return result
            else:
                raise HTTPException(status_code=resp.status_code, detail=f"Device replied with: {resp.text}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Could not reach device {device_id} HTTP port 8001: {e}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for clients that want status / heartbeat / ping-pong."""
    await websocket.accept()
    connected_websockets.add(websocket)
    print(f"[Backend WS] Client connected. Total active: {len(connected_websockets)}")

    try:
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type")

            if msg_type == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "client_time": msg.get("client_time"),
                    "server_time": time.time()
                })
    except WebSocketDisconnect:
        print("[Backend WS] Client disconnected.")
    except Exception as e:
        print(f"[Backend WS Error] {e}")
    finally:
        connected_websockets.discard(websocket)
