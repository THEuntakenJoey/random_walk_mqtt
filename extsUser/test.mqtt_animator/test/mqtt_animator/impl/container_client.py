"""
REST Client for the Container Fleet Orchestrator (FastAPI backend on port 8000).
Uses Python standard library urllib with background thread execution to prevent UI freezes.
"""

import json
import urllib.request
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional, Callable


class FleetApiClient:
    """Communicates with the FastAPI Container Orchestrator at http://localhost:8000."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="ov_fleet_api")

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: float = 3.0
    ) -> Dict[str, Any]:
        """Perform synchronous HTTP request using standard library urllib."""
        url = f"{self.base_url}{path}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "Omniverse-MqttAnimator/1.0"
        }
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_bytes = resp.read()
                if resp_bytes:
                    return json.loads(resp_bytes.decode("utf-8"))
                return {}
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8") if e.fp else str(e)
            raise RuntimeError(f"HTTP {e.code} Error: {err_msg}")
        except Exception as e:
            raise RuntimeError(f"Network error connecting to {url}: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Fetch orchestrator health, MQTT status, and active device count."""
        return self._request("GET", "/api/status")

    def list_containers(self) -> List[Dict[str, Any]]:
        """List active device containers from Docker daemon."""
        res = self._request("GET", "/api/containers")
        return res.get("containers", [])

    def spawn_container(
        self,
        device_name: Optional[str] = None,
        model_type: str = "target_waypoints",
        write_hz: float = 24.0,
        color: Optional[str] = None
    ) -> Dict[str, Any]:
        """Spawn a new device container."""
        payload = {
            "device_name": device_name,
            "model_type": model_type,
            "write_hz": write_hz,
            "color": color
        }
        return self._request("POST", "/api/containers/spawn", payload)

    def kill_container(self, device_id: str) -> Dict[str, Any]:
        """Stop, remove container and broadcast offline status."""
        safe_id = urllib.parse.quote(device_id)
        return self._request("POST", f"/api/containers/{safe_id}/kill")

    def update_config(
        self,
        device_id: str,
        model_type: Optional[str] = None,
        write_hz: Optional[float] = None,
        color: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update live settings on running container via REST proxy."""
        safe_id = urllib.parse.quote(device_id)
        payload = {}
        if model_type is not None:
            payload["model_type"] = model_type
        if write_hz is not None:
            payload["write_hz"] = write_hz
        if color is not None:
            payload["color"] = color

        return self._request("POST", f"/api/containers/{safe_id}/config", payload)

    def dispatch_async(
        self,
        func: Callable[..., Any],
        *args,
        on_success: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        **kwargs
    ):
        """Execute API request in a background thread to prevent blocking Omniverse UI."""
        def worker():
            try:
                res = func(*args, **kwargs)
                if on_success:
                    on_success(res)
            except Exception as ex:
                if on_error:
                    on_error(ex)

        self._executor.submit(worker)

    def shutdown(self):
        """Shutdown thread executor."""
        self._executor.shutdown(wait=False)
