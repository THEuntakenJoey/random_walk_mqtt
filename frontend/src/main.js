import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import mqtt from 'mqtt';
import {
  interpolateV1RawSnap,
  interpolateV2SimpleLerp,
  interpolateV3HermiteSpline,
  interpolateV4ContinuousSeamless,
  interpolateV5CatmullRom
} from './interpolation.js';

// --- Preset Colors ---
const PRESET_COLORS = [
  '#38bdf8', '#a855f7', '#34d399', '#f43f5e',
  '#fbbf24', '#06b6d4', '#f97316', '#ec4899'
];

// --- Scene Variables ---
let scene, camera, renderer, controls;
let currentInterpolationMode = 'v5_catmull_rom';
let showTrails = true;
let bufferOffsetMs = 40.0;
let mqttClient = null;
let selectedDeviceId = null;

// Multi-Device Registry: deviceId -> DeviceInstance
const devicesMap = new Map();

// Network & Delay Metrics
let currentPingMs = 0;
let frameCount = 0;
let lastFpsCheck = performance.now();
let fps = 60;

// DOM Elements
const badgeEl = document.getElementById('status-badge');
const activeBadgeEl = document.getElementById('active-device-badge');
const activeCountEl = document.getElementById('metric-active-count');
const transportEl = document.getElementById('metric-transport');
const selectedDeviceEl = document.getElementById('metric-selected-device');
const totalDelayEl = document.getElementById('metric-total-delay');

const delayNetPingEl = document.getElementById('delay-net-ping');
const delayDbPollEl = document.getElementById('delay-db-poll');
const delayRenderBufferEl = document.getElementById('delay-render-buffer');
const fpsEl = document.getElementById('fps-counter');

const deviceListEl = document.getElementById('device-list');
const emptyStateEl = document.getElementById('empty-state');
const interpolationSelectEl = document.getElementById('select-interpolation');
const interpolationDescEl = document.getElementById('interpolation-desc');
const trailToggleEl = document.getElementById('toggle-trail');
const bufferDelaySlider = document.getElementById('slider-buffer-delay');
const bufferDelayVal = document.getElementById('val-buffer-delay');
const presetBtns = document.querySelectorAll('.btn-preset');

// Spawn Modal Elements
const btnSpawnDevice = document.getElementById('btn-spawn-device');
const spawnModal = document.getElementById('spawn-modal');
const btnCloseModal = document.getElementById('btn-close-modal');
const btnCancelSpawn = document.getElementById('btn-cancel-spawn');
const btnConfirmSpawn = document.getElementById('btn-confirm-spawn');
const inputDeviceName = document.getElementById('input-device-name');
const inputSpawnModel = document.getElementById('input-spawn-model');
const inputSpawnHz = document.getElementById('input-spawn-hz');
const valSpawnHz = document.getElementById('val-spawn-hz');
const inputSpawnColor = document.getElementById('input-spawn-color');
const spawnColorSwatches = document.getElementById('spawn-color-swatches');

// --- 1. Initialize Three.js Scene ---
function initScene() {
  const container = document.getElementById('canvas-container');

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0f19);
  scene.fog = new THREE.FogExp2(0x0b0f19, 0.012);

  camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 1000);
  camera.position.set(0, 26, 32);

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.appendChild(renderer.domElement);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.05;
  controls.maxPolarAngle = Math.PI / 2 - 0.05;
  controls.target.set(0, 0, 0);

  // Lighting
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.45);
  scene.add(ambientLight);

  const dirLight = new THREE.DirectionalLight(0x38bdf8, 1.2);
  dirLight.position.set(20, 40, 20);
  dirLight.castShadow = true;
  dirLight.shadow.mapSize.width = 2048;
  dirLight.shadow.mapSize.height = 2048;
  scene.add(dirLight);

  const pointLight = new THREE.PointLight(0x818cf8, 1.5, 60);
  pointLight.position.set(0, 15, 0);
  scene.add(pointLight);

  // Grid & Ground Area
  const groundGeo = new THREE.PlaneGeometry(60, 60);
  const groundMat = new THREE.MeshStandardMaterial({
    color: 0x070a13,
    roughness: 0.85,
    metalness: 0.2
  });
  const ground = new THREE.Mesh(groundGeo, groundMat);
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  scene.add(ground);

  const gridHelper = new THREE.GridHelper(30, 30, 0x38bdf8, 0x1e293b);
  gridHelper.position.y = 0.01;
  scene.add(gridHelper);

  // Arena Boundary Border
  const boundaryPoints = [
    new THREE.Vector3(-15, 0.05, -15),
    new THREE.Vector3(15, 0.05, -15),
    new THREE.Vector3(15, 0.05, 15),
    new THREE.Vector3(-15, 0.05, 15),
    new THREE.Vector3(-15, 0.05, -15)
  ];
  const boundaryGeo = new THREE.BufferGeometry().setFromPoints(boundaryPoints);
  const boundaryMat = new THREE.LineBasicMaterial({ color: 0xf43f5e, linewidth: 2 });
  const boundaryLine = new THREE.Line(boundaryGeo, boundaryMat);
  scene.add(boundaryLine);

  window.addEventListener('resize', onWindowResize);
}

function onWindowResize() {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
}

// --- 2. Multi-Device Visuals Factory ---
const MAX_TRAIL_POINTS = 150;
const MAX_KEYFRAMES = 12;

function parseHexColor(colorStr) {
  try {
    return parseInt(colorStr.replace('#', '0x'), 16);
  } catch {
    return 0x38bdf8;
  }
}

function createDeviceVisuals(deviceData) {
  const { device_id, device_name, color, model_type } = deviceData;
  const hexColor = parseHexColor(color);

  // Vehicle Mesh Group
  const meshGroup = new THREE.Group();

  // Chassis Body
  const bodyGeo = new THREE.BoxGeometry(1.2, 0.4, 2.0);
  const bodyMat = new THREE.MeshStandardMaterial({
    color: hexColor,
    roughness: 0.25,
    metalness: 0.75
  });
  const bodyMesh = new THREE.Mesh(bodyGeo, bodyMat);
  bodyMesh.position.y = 0.3;
  bodyMesh.castShadow = true;
  meshGroup.add(bodyMesh);

  // Cockpit
  const cabinGeo = new THREE.BoxGeometry(0.8, 0.35, 0.9);
  const cabinMat = new THREE.MeshStandardMaterial({
    color: 0x111827,
    roughness: 0.1,
    metalness: 0.9
  });
  const cabinMesh = new THREE.Mesh(cabinGeo, cabinMat);
  cabinMesh.position.set(0, 0.6, -0.2);
  cabinMesh.castShadow = true;
  meshGroup.add(cabinMesh);

  // Orientation Arrow (Front pointer in matching tone)
  const arrowGeo = new THREE.ConeGeometry(0.2, 0.6, 8);
  arrowGeo.rotateX(Math.PI / 2);
  const arrowMat = new THREE.MeshBasicMaterial({ color: hexColor });
  const arrowMesh = new THREE.Mesh(arrowGeo, arrowMat);
  arrowMesh.position.set(0, 0.55, 1.4);
  meshGroup.add(arrowMesh);

  scene.add(meshGroup);

  // Target Waypoint Beacon (Matching color tone)
  const beaconGroup = new THREE.Group();
  const beamGeo = new THREE.CylinderGeometry(0.05, 0.4, 2.8, 16);
  const beamMat = new THREE.MeshStandardMaterial({
    color: hexColor,
    emissive: hexColor,
    emissiveIntensity: 0.65,
    transparent: true,
    opacity: 0.55
  });
  const beamMesh = new THREE.Mesh(beamGeo, beamMat);
  beamMesh.position.y = 1.4;
  beaconGroup.add(beamMesh);

  const dotGeo = new THREE.CircleGeometry(0.35, 16);
  dotGeo.rotateX(-Math.PI / 2);
  const dotMat = new THREE.MeshBasicMaterial({
    color: hexColor,
    transparent: true,
    opacity: 0.85
  });
  const dotMesh = new THREE.Mesh(dotGeo, dotMat);
  dotMesh.position.y = 0.03;
  beaconGroup.add(dotMesh);

  beaconGroup.visible = (model_type === 'target_waypoints');
  scene.add(beaconGroup);

  // Trailing Path Buffer
  const positions = new Float32Array(MAX_TRAIL_POINTS * 3);
  const trailGeometry = new THREE.BufferGeometry();
  trailGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  const trailMat = new THREE.LineBasicMaterial({
    color: hexColor,
    transparent: true,
    opacity: 0.65,
    linewidth: 2
  });
  const trailLine = new THREE.Line(trailGeometry, trailMat);
  scene.add(trailLine);

  return {
    deviceId: device_id,
    deviceName: device_name || `Walker ${device_id}`,
    color: color,
    modelType: model_type,
    writeHz: deviceData.write_hz || 24.0,

    // Three.js visual objects
    meshGroup,
    bodyMat,
    arrowMat,
    beaconGroup,
    beamMat,
    dotMat,
    trailLine,
    trailGeometry,
    trailPoints: [],

    // Interpolation state
    keyframeQueue: [],
    currentPose: { x: deviceData.x || 0, z: deviceData.z || 0, yaw: deviceData.orientation || 0 },
    targetState: { x: deviceData.x || 0, z: deviceData.z || 0, yaw: deviceData.orientation || 0 },
    targetWaypointPos: { x: deviceData.target_x || 0, z: deviceData.target_z || 0 },
    measuredDbWriteIntervalMs: 1000.0 / (deviceData.write_hz || 24.0),
    estimatedVelocity: { vx: 0, vz: 0, vyaw: 0 }
  };
}

function updateDeviceVisualColor(device, newColor) {
  device.color = newColor;
  const hex = parseHexColor(newColor);
  device.bodyMat.color.setHex(hex);
  device.arrowMat.color.setHex(hex);
  device.beamMat.color.setHex(hex);
  device.beamMat.emissive.setHex(hex);
  device.dotMat.color.setHex(hex);
  device.trailLine.material.color.setHex(hex);
}

function disposeDeviceVisuals(device) {
  scene.remove(device.meshGroup);
  scene.remove(device.beaconGroup);
  scene.remove(device.trailLine);
  device.trailGeometry.dispose();
}

function updateTrailBuffer(device, x, z) {
  if (!showTrails) {
    device.trailLine.visible = false;
    return;
  }
  device.trailLine.visible = true;

  device.trailPoints.push(new THREE.Vector3(x, 0.1, z));
  if (device.trailPoints.length > MAX_TRAIL_POINTS) {
    device.trailPoints.shift();
  }

  const positions = device.trailGeometry.attributes.position.array;
  for (let i = 0; i < device.trailPoints.length; i++) {
    positions[i * 3] = device.trailPoints[i].x;
    positions[i * 3 + 1] = device.trailPoints[i].y;
    positions[i * 3 + 2] = device.trailPoints[i].z;
  }
  device.trailGeometry.setDrawRange(0, device.trailPoints.length);
  device.trailGeometry.attributes.position.needsUpdate = true;
}

// --- 3. UI Fleet Panel Management ---
function renderDeviceCard(device) {
  const cardId = `device-card-${device.deviceId}`;
  let card = document.getElementById(cardId);

  if (!card) {
    card = document.createElement('div');
    card.id = cardId;
    card.className = 'device-card';
    deviceListEl.appendChild(card);
  }

  card.innerHTML = `
    <div class="device-card-header">
      <div class="device-title-area">
        <div class="device-color-indicator" style="background-color: ${device.color}; color: ${device.color};">
          <input type="color" class="device-color-input" value="${device.color}" title="Change Color Tone" />
        </div>
        <div>
          <div class="device-name">${device.deviceName}</div>
          <div class="device-id-tag">${device.deviceId}</div>
        </div>
      </div>
      <div class="device-header-actions">
        <button class="btn-icon-action btn-icon-focus ${selectedDeviceId === device.deviceId ? 'active-focus' : ''}" title="Focus Camera">🎯</button>
        <button class="btn-icon-action btn-icon-kill" title="Kill Container">✕</button>
      </div>
    </div>
    <div class="device-card-body">
      <div class="card-control-row">
        <div class="card-control-header">
          <span>Random Walk Model:</span>
        </div>
        <select class="device-model-select">
          <option value="target_waypoints" ${device.modelType === 'target_waypoints' ? 'selected' : ''}>Target Waypoints</option>
          <option value="edge_repulsion" ${device.modelType === 'edge_repulsion' ? 'selected' : ''}>Edge-Repulsion Cruise</option>
          <option value="langevin" ${device.modelType === 'langevin' ? 'selected' : ''}>Langevin Brownian</option>
        </select>
      </div>
      <div class="card-control-row">
        <div class="card-control-header">
          <span>MQTT Publish Rate:</span>
          <span class="freq-value device-write-hz-val">${Math.round(device.writeHz)} Hz</span>
        </div>
        <input type="range" class="device-hz-slider" min="1" max="60" value="${Math.round(device.writeHz)}" step="1" />
      </div>
      <div class="device-telemetry-pill">
        <span>X: <b class="metric-x">${device.currentPose.x.toFixed(2)}</b> Z: <b class="metric-z">${device.currentPose.z.toFixed(2)}</b></span>
        <span>Yaw: <b class="metric-yaw">${((device.currentPose.yaw * 180 / Math.PI) % 360).toFixed(0)}°</b></span>
      </div>
    </div>
  `;

  // Attach Card Event Listeners
  const colorInput = card.querySelector('.device-color-input');
  colorInput.addEventListener('input', (e) => {
    const newCol = e.target.value;
    updateDeviceVisualColor(device, newCol);
    card.querySelector('.device-color-indicator').style.backgroundColor = newCol;
    card.querySelector('.device-color-indicator').style.color = newCol;
    pushDeviceConfig(device.deviceId, { color: newCol });
  });

  const focusBtn = card.querySelector('.btn-icon-focus');
  focusBtn.addEventListener('click', () => {
    if (selectedDeviceId === device.deviceId) {
      selectedDeviceId = null;
      selectedDeviceEl.textContent = 'All / Free';
      focusBtn.classList.remove('active-focus');
      card.classList.remove('selected');
    } else {
      selectedDeviceId = device.deviceId;
      selectedDeviceEl.textContent = device.deviceName;
      document.querySelectorAll('.device-card').forEach(c => c.classList.remove('selected'));
      document.querySelectorAll('.btn-icon-focus').forEach(b => b.classList.remove('active-focus'));
      card.classList.add('selected');
      focusBtn.classList.add('active-focus');
    }
  });

  const killBtn = card.querySelector('.btn-icon-kill');
  killBtn.addEventListener('click', async () => {
    killBtn.disabled = true;
    killBtn.textContent = '...';
    await killDeviceContainer(device.deviceId);
  });

  const modelSelect = card.querySelector('.device-model-select');
  modelSelect.addEventListener('change', (e) => {
    device.modelType = e.target.value;
    device.beaconGroup.visible = (device.modelType === 'target_waypoints');
    pushDeviceConfig(device.deviceId, { model_type: e.target.value });
  });

  const hzSlider = card.querySelector('.device-hz-slider');
  const hzValSpan = card.querySelector('.device-write-hz-val');
  hzSlider.addEventListener('input', (e) => {
    const newHz = parseFloat(e.target.value);
    hzValSpan.textContent = `${newHz} Hz`;
    device.writeHz = newHz;
    pushDeviceConfig(device.deviceId, { write_hz: newHz });
  });
}

function removeDeviceCard(deviceId) {
  const card = document.getElementById(`device-card-${deviceId}`);
  if (card) card.remove();
  if (selectedDeviceId === deviceId) {
    selectedDeviceId = null;
    selectedDeviceEl.textContent = 'All / Free';
  }
}

function updateDeviceCardTelemetry(device) {
  const card = document.getElementById(`device-card-${device.deviceId}`);
  if (card) {
    const xEl = card.querySelector('.metric-x');
    const zEl = card.querySelector('.metric-z');
    const yawEl = card.querySelector('.metric-yaw');
    if (xEl) xEl.textContent = device.currentPose.x.toFixed(2);
    if (zEl) zEl.textContent = device.currentPose.z.toFixed(2);
    if (yawEl) yawEl.textContent = `${((device.currentPose.yaw * 180 / Math.PI) % 360).toFixed(0)}°`;
  }
}

function updateFleetUI() {
  const count = devicesMap.size;
  activeBadgeEl.textContent = `${count} Device${count === 1 ? '' : 's'}`;
  activeCountEl.textContent = count;
  emptyStateEl.style.display = count === 0 ? 'flex' : 'none';
}

// --- 4. API & MQTT Interaction ---
const API_BASE = window.location.port === '5173' ? '' : (window.location.port === '8000' ? '' : `http://${window.location.hostname}:8000`);

async function pushDeviceConfig(deviceId, config) {
  try {
    await fetch(`${API_BASE}/api/containers/${deviceId}/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });
  } catch (err) {
    console.warn(`[Config Proxy Error] Failed to push config for ${deviceId}:`, err);
  }
}

async function spawnDeviceContainer(params) {
  try {
    const resp = await fetch(`${API_BASE}/api/containers/spawn`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params)
    });
    const result = await resp.json();
    console.log('[Spawn Result]', result);
  } catch (err) {
    console.error('[Spawn Error]', err);
    alert(`Could not spawn container: ${err.message}`);
  }
}

async function killDeviceContainer(deviceId) {
  try {
    await fetch(`${API_BASE}/api/containers/${deviceId}/kill`, {
      method: 'POST'
    });
    // Remove immediately from UI
    const device = devicesMap.get(deviceId);
    if (device) {
      disposeDeviceVisuals(device);
      devicesMap.delete(deviceId);
      removeDeviceCard(deviceId);
      updateFleetUI();
    }
  } catch (err) {
    console.error(`[Kill Error] Could not kill ${deviceId}:`, err);
  }
}

function initMQTT() {
  // Support both direct WebSocket port 9001 and reverse proxy /mqtt
  const brokerHost = window.location.hostname || 'localhost';
  const mqttWsUrl = `ws://${brokerHost}:9001`;

  updateBadge('connecting', 'Connecting MQTT :9001...');
  console.log(`[MQTT] Connecting to broker at ${mqttWsUrl}`);

  mqttClient = mqtt.connect(mqttWsUrl, {
    clientId: `threejs_${Math.random().toString(16).substring(2, 8)}`,
    clean: true,
    reconnectPeriod: 2000
  });

  mqttClient.on('connect', () => {
    updateBadge('connected', 'MQTT WS Live (:9001)');
    console.log('[MQTT] Connected successfully to Mosquitto WebSocket listener.');

    // Subscribe to multi-topics
    mqttClient.subscribe([
      'simulation/walkers/+/status',
      'simulation/walkers/+/state'
    ], (err) => {
      if (err) {
        console.error('[MQTT] Subscription error:', err);
      } else {
        console.log('[MQTT] Subscribed to simulation/walkers/+/status and state');
      }
    });
  });

  mqttClient.on('message', (topic, messageBuffer) => {
    try {
      const topicParts = topic.split('/');
      if (topicParts.length < 4 || topicParts[0] !== 'simulation' || topicParts[1] !== 'walkers') {
        return;
      }
      const deviceId = topicParts[2];
      const action = topicParts[3];
      const payload = JSON.parse(messageBuffer.toString());

      if (action === 'status') {
        handleDeviceStatus(deviceId, payload);
      } else if (action === 'state') {
        handleDeviceState(deviceId, payload);
      }
    } catch (e) {
      console.error('[MQTT Message Parse Error]', e);
    }
  });

  mqttClient.on('error', (err) => {
    console.error('[MQTT Client Error]', err);
  });

  mqttClient.on('close', () => {
    updateBadge('disconnected', 'MQTT Disconnected. Reconnecting...');
  });
}

function handleDeviceStatus(deviceId, payload) {
  const status = payload.status;
  if (status === 'offline') {
    const device = devicesMap.get(deviceId);
    if (device) {
      disposeDeviceVisuals(device);
      devicesMap.delete(deviceId);
      removeDeviceCard(deviceId);
      updateFleetUI();
    }
  } else if (status === 'online') {
    let device = devicesMap.get(deviceId);
    if (!device) {
      device = createDeviceVisuals({
        device_id: deviceId,
        device_name: payload.device_name || `Walker ${deviceId}`,
        color: payload.color || '#38bdf8',
        model_type: payload.model_type || 'target_waypoints',
        write_hz: payload.write_hz || 24.0
      });
      devicesMap.set(deviceId, device);
      renderDeviceCard(device);
      updateFleetUI();
    } else {
      if (payload.color && payload.color !== device.color) {
        updateDeviceVisualColor(device, payload.color);
      }
      if (payload.model_type) {
        device.modelType = payload.model_type;
        device.beaconGroup.visible = (device.modelType === 'target_waypoints');
      }
      if (payload.write_hz) {
        device.writeHz = payload.write_hz;
      }
    }
  }
}

function handleDeviceState(deviceId, payload) {
  let device = devicesMap.get(deviceId);
  if (!device) {
    device = createDeviceVisuals({
      device_id: deviceId,
      device_name: payload.device_name || `Walker ${deviceId}`,
      color: payload.color || '#38bdf8',
      model_type: payload.model_type || 'target_waypoints',
      write_hz: payload.write_hz || 24.0,
      x: payload.x,
      z: payload.z,
      orientation: payload.orientation,
      target_x: payload.target_x,
      target_z: payload.target_z
    });
    devicesMap.set(deviceId, device);
    renderDeviceCard(device);
    updateFleetUI();
  }

  // Update visual color if payload differs
  if (payload.color && payload.color !== device.color) {
    updateDeviceVisualColor(device, payload.color);
  }

  // Update target waypoint coordinates for beacon
  if (payload.target_x !== undefined && payload.target_z !== undefined) {
    device.targetWaypointPos.x = payload.target_x;
    device.targetWaypointPos.z = payload.target_z;
    device.beaconGroup.position.set(payload.target_x, 0, payload.target_z);
  }
  device.beaconGroup.visible = (payload.model_type === 'target_waypoints' || device.modelType === 'target_waypoints');

  const now = performance.now();
  device.targetState.x = payload.x;
  device.targetState.z = payload.z;
  device.targetState.yaw = payload.orientation;

  // Track intervals
  const lastK = device.keyframeQueue.length > 0 ? device.keyframeQueue[device.keyframeQueue.length - 1] : null;
  if (lastK && payload.timestamp && lastK.timestamp) {
    const deltaSec = payload.timestamp - lastK.timestamp;
    if (deltaSec > 0.001 && deltaSec < 5.0) {
      device.measuredDbWriteIntervalMs = device.measuredDbWriteIntervalMs * 0.3 + (deltaSec * 1000.0) * 0.7;
    }
  }

  device.keyframeQueue.push({
    x: payload.x,
    z: payload.z,
    yaw: payload.orientation,
    time: now,
    timestamp: payload.timestamp
  });

  if (device.keyframeQueue.length > MAX_KEYFRAMES) {
    device.keyframeQueue.shift();
  }

  updateLatencyTelemetry();
}

function updateBadge(status, text) {
  badgeEl.className = `badge badge-${status}`;
  badgeEl.textContent = text;
}

// Background RTT probe for Telemetry HUD
async function probeNetworkLatency() {
  const start = performance.now();
  try {
    const resp = await fetch(`${API_BASE}/api/status`, { method: 'GET', cache: 'no-store' });
    if (resp.ok) {
      currentPingMs = Math.round(performance.now() - start);
      updateLatencyTelemetry();
    }
  } catch (err) {
    // API momentarily unreachable
  }
}
setInterval(probeNetworkLatency, 2500);

function updateLatencyTelemetry() {
  let maxWriteDelay = 1000.0 / 24.0;
  for (const dev of devicesMap.values()) {
    if (dev.measuredDbWriteIntervalMs > maxWriteDelay) {
      maxWriteDelay = dev.measuredDbWriteIntervalMs;
    }
  }

  let renderBufferDelay = 0.0;
  if (currentInterpolationMode === 'v5_catmull_rom') {
    renderBufferDelay = 2.0 * maxWriteDelay + bufferOffsetMs;
  } else if (currentInterpolationMode === 'v3_hermite_spline' || currentInterpolationMode === 'v4_continuous_seamless') {
    renderBufferDelay = maxWriteDelay + bufferOffsetMs;
  } else if (currentInterpolationMode === 'v2_simple_lerp') {
    renderBufferDelay = bufferOffsetMs;
  }

  const totalPipelineDelay = currentPingMs + renderBufferDelay;

  delayNetPingEl.textContent = `${currentPingMs} ms`;
  delayRenderBufferEl.textContent = `${renderBufferDelay.toFixed(1)} ms`;
  totalDelayEl.textContent = `${totalPipelineDelay.toFixed(1)} ms`;
}

// --- 5. Main Animation & Render Loop ---
let lastTime = performance.now();

function animate() {
  requestAnimationFrame(animate);

  const now = performance.now();
  const dt = Math.min((now - lastTime) / 1000.0, 0.1);
  lastTime = now;

  // FPS Counter
  frameCount++;
  if (now - lastFpsCheck >= 1000) {
    fps = Math.round((frameCount * 1000) / (now - lastFpsCheck));
    fpsEl.textContent = `${fps} FPS`;
    frameCount = 0;
    lastFpsCheck = now;
  }

  // Interpolate each active device
  for (const device of devicesMap.values()) {
    let targetPose = null;

    if (currentInterpolationMode === 'v1_raw_snap') {
      targetPose = interpolateV1RawSnap(device.keyframeQueue);
    } else if (currentInterpolationMode === 'v2_simple_lerp') {
      targetPose = interpolateV2SimpleLerp(device.currentPose, device.targetState, dt);
    } else if (currentInterpolationMode === 'v3_hermite_spline') {
      targetPose = interpolateV3HermiteSpline(device.keyframeQueue, now, device.measuredDbWriteIntervalMs);
    } else if (currentInterpolationMode === 'v4_continuous_seamless') {
      targetPose = interpolateV4ContinuousSeamless(device.keyframeQueue, now, device.measuredDbWriteIntervalMs, device.currentPose, dt);
    } else if (currentInterpolationMode === 'v5_catmull_rom') {
      targetPose = interpolateV5CatmullRom(device.keyframeQueue, now, device.measuredDbWriteIntervalMs, device.estimatedVelocity, dt);
    }

    if (targetPose) {
      device.currentPose.x = targetPose.x;
      device.currentPose.z = targetPose.z;
      device.currentPose.yaw = targetPose.yaw;

      device.meshGroup.position.set(device.currentPose.x, 0, device.currentPose.z);
      device.meshGroup.rotation.y = device.currentPose.yaw;

      updateTrailBuffer(device, device.currentPose.x, device.currentPose.z);
      updateDeviceCardTelemetry(device);
    }

    // Beacon subtle pulse effect
    if (device.modelType === 'target_waypoints' && device.beaconGroup.visible) {
      const pulse = 0.5 + 0.25 * Math.sin(now * 0.005);
      device.beamMat.opacity = pulse;
    }
  }

  // Camera Focus tracking
  if (selectedDeviceId && devicesMap.has(selectedDeviceId)) {
    const focused = devicesMap.get(selectedDeviceId);
    controls.target.lerp(new THREE.Vector3(focused.currentPose.x, 0, focused.currentPose.z), 0.08);
  }

  controls.update();
  renderer.render(scene, camera);
}

// --- 6. Event Handlers & Modal Setup ---
function initUIControls() {
  // Global Smoothing Algorithm
  const descriptions = {
    v5_catmull_rom: 'v5: Centripetal Catmull-Rom Spline across all active walkers (Recommended)',
    v4_continuous_seamless: 'v4: Continuous Extrapolation (Zero Gap at MQTT arrivals)',
    v3_hermite_spline: 'v3: Cubic Hermite Spline (Filtered Unique Keyframes)',
    v2_simple_lerp: 'v2: Simple Exponential LERP (Direct exponential smoothing)',
    v1_raw_snap: 'v1: Raw 0-Lag Snap (No interpolation, instantaneous jumps)'
  };

  interpolationSelectEl.addEventListener('change', (e) => {
    currentInterpolationMode = e.target.value;
    interpolationDescEl.textContent = descriptions[currentInterpolationMode];
    updateLatencyTelemetry();
  });

  // Global Trails
  trailToggleEl.addEventListener('change', (e) => {
    showTrails = e.target.checked;
    for (const dev of devicesMap.values()) {
      dev.trailLine.visible = showTrails;
    }
  });

  // Target Buffer Delay Slider
  bufferDelaySlider.addEventListener('input', (e) => {
    const val = parseInt(e.target.value, 10);
    bufferOffsetMs = val;
    bufferDelayVal.textContent = `${val} ms`;
    updateLatencyTelemetry();
    presetBtns.forEach(btn => {
      btn.classList.toggle('active', parseInt(btn.dataset.delay, 10) === val);
    });
  });

  // Presets
  presetBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      presetBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const val = parseInt(btn.dataset.delay, 10);
      bufferOffsetMs = val;
      bufferDelaySlider.value = val;
      bufferDelayVal.textContent = `${val} ms`;
      updateLatencyTelemetry();
    });
  });

  // Spawn Modal Controls
  btnSpawnDevice.addEventListener('click', () => {
    const randColor = PRESET_COLORS[Math.floor(Math.random() * PRESET_COLORS.length)];
    inputSpawnColor.value = randColor;
    inputDeviceName.value = `Walker #${Math.floor(Math.random() * 900) + 100}`;
    spawnModal.classList.remove('hidden');
  });

  btnCloseModal.addEventListener('click', () => spawnModal.classList.add('hidden'));
  btnCancelSpawn.addEventListener('click', () => spawnModal.classList.add('hidden'));

  inputSpawnHz.addEventListener('input', (e) => {
    valSpawnHz.textContent = `${e.target.value} Hz`;
  });

  // Swatches inside spawn modal
  spawnColorSwatches.innerHTML = '';
  PRESET_COLORS.forEach(colorHex => {
    const swatch = document.createElement('button');
    swatch.className = 'swatch-btn';
    swatch.style.backgroundColor = colorHex;
    swatch.style.color = colorHex;
    swatch.addEventListener('click', () => {
      inputSpawnColor.value = colorHex;
      document.querySelectorAll('.swatch-btn').forEach(s => s.classList.remove('active'));
      swatch.classList.add('active');
    });
    spawnColorSwatches.appendChild(swatch);
  });

  btnConfirmSpawn.addEventListener('click', async () => {
    const name = inputDeviceName.value.trim() || undefined;
    const model = inputSpawnModel.value;
    const hz = parseFloat(inputSpawnHz.value);
    const color = inputSpawnColor.value;

    btnConfirmSpawn.disabled = true;
    btnConfirmSpawn.textContent = 'Spawning...';

    await spawnDeviceContainer({
      device_name: name,
      model_type: model,
      write_hz: hz,
      color: color
    });

    btnConfirmSpawn.disabled = false;
    btnConfirmSpawn.innerHTML = '<span>Launch Container</span>';
    spawnModal.classList.add('hidden');
  });
}

// --- 7. Application Entrypoint ---
initScene();
initUIControls();
initMQTT();
animate();
probeNetworkLatency();
