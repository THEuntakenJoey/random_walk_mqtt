import asyncio
import json
import websockets

async def test_websocket():
    uri = "ws://localhost:8000/ws"
    print(f"Connecting to {uri}...")
    async with websockets.connect(uri) as ws:
        print("[Client] Connected!")
        
        # 1. Listen for state updates
        for i in range(3):
            msg = await ws.recv()
            data = json.loads(msg)
            print(f"[Client Rx {i+1}] Received: {data}")
            assert data["type"] == "state_update"
            assert "x" in data["data"]
            assert "z" in data["data"]
            assert "orientation" in data["data"]

        # 2. Test Ping / Pong
        print("[Client] Sending Ping...")
        ping_msg = {"type": "ping", "client_time": 1000.0}
        await ws.send(json.dumps(ping_msg))
        
        resp = await ws.recv()
        data = json.loads(resp)
        print(f"[Client Rx Pong] Received: {data}")
        assert data["type"] == "pong"
        assert data["client_time"] == 1000.0

        # 3. Test Config Update
        print("[Client] Updating frequencies to 30 Hz...")
        config_msg = {"type": "config", "sim_hz": 30.0, "poll_hz": 30.0}
        await ws.send(json.dumps(config_msg))
        
        resp = await ws.recv()
        data = json.loads(resp)
        print(f"[Client Rx Config Ack] Received: {data}")
        assert data["type"] == "config_ack"
        assert data["sim_hz"] == 30.0
        assert data["poll_hz"] == 30.0

        print("\n✅ WebSocket & DB Protocol Verification PASSED Successfully!")

if __name__ == "__main__":
    asyncio.run(test_websocket())
