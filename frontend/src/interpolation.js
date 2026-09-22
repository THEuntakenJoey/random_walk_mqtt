// Interpolation Evolution Modes

function shortestAngleDiff(a, b) {
  let diff = b - a;
  while (diff < -Math.PI) diff += Math.PI * 2;
  while (diff > Math.PI) diff -= Math.PI * 2;
  return diff;
}

/**
 * MODE v1: Raw 0-Lag Snap
 */
export function interpolateV1RawSnap(keyframeQueue) {
  if (keyframeQueue.length === 0) return null;
  const lastK = keyframeQueue[keyframeQueue.length - 1];
  return {
    x: lastK.x,
    z: lastK.z,
    yaw: lastK.yaw
  };
}

/**
 * MODE v2: Simple Exponential LERP (Unfiltered Duplicates)
 */
export function interpolateV2SimpleLerp(currentPose, targetState, dt) {
  const lerpSpeed = 12.0;
  const factor = 1.0 - Math.exp(-lerpSpeed * dt);

  const newX = currentPose.x + (targetState.x - currentPose.x) * factor;
  const newZ = currentPose.z + (targetState.z - currentPose.z) * factor;

  const dYaw = shortestAngleDiff(currentPose.yaw, targetState.yaw);
  const newYaw = currentPose.yaw + dYaw * factor;

  return {
    x: newX,
    z: newZ,
    yaw: newYaw
  };
}

/**
 * MODE v3: Cubic Hermite Spline (Filtered Unique Keyframes)
 */
export function interpolateV3HermiteSpline(keyframeQueue, now, measuredDbWriteIntervalMs) {
  if (keyframeQueue.length === 0) return null;

  const targetDelay = measuredDbWriteIntervalMs + 30.0;
  const renderTime = now - targetDelay;

  let k0 = null;
  let k1 = null;

  for (let i = keyframeQueue.length - 1; i >= 0; i--) {
    if (keyframeQueue[i].time <= renderTime) {
      k0 = keyframeQueue[i];
      k1 = keyframeQueue[i + 1] || null;
      break;
    }
  }

  if (k0 && k1) {
    const interval = k1.time - k0.time;
    const t = interval > 0 ? (renderTime - k0.time) / interval : 1.0;
    const clampedT = Math.max(0.0, Math.min(1.0, t));
    const u = clampedT * clampedT * (3.0 - 2.0 * clampedT);

    const dYaw = shortestAngleDiff(k0.yaw, k1.yaw);
    return {
      x: k0.x + (k1.x - k0.x) * u,
      z: k0.z + (k1.z - k0.z) * u,
      yaw: k0.yaw + dYaw * u
    };
  } else {
    const lastK = keyframeQueue[keyframeQueue.length - 1];
    return {
      x: lastK.x,
      z: lastK.z,
      yaw: lastK.yaw
    };
  }
}

/**
 * MODE v4: Seamless Continuous Extrapolation & Target Blend
 */
export function interpolateV4ContinuousSeamless(currentPose, targetState, estimatedVelocity, dt) {
  let nextX = currentPose.x + estimatedVelocity.vx * dt;
  let nextZ = currentPose.z + estimatedVelocity.vz * dt;

  const pullRate = 3.0;
  const blendFactor = 1.0 - Math.exp(-pullRate * dt);

  nextX += (targetState.x - nextX) * blendFactor;
  nextZ += (targetState.z - nextZ) * blendFactor;

  const dYaw = shortestAngleDiff(currentPose.yaw, targetState.yaw);
  const nextYaw = currentPose.yaw + dYaw * (1.0 - Math.exp(-6.0 * dt));

  return {
    x: Math.max(-15.0, Math.min(15.0, nextX)),
    z: Math.max(-15.0, Math.min(15.0, nextZ)),
    yaw: nextYaw
  };
}

/**
 * Centripetal Catmull-Rom Spline Helper (alpha = 0.5)
 * Evaluates point on spline segment P1 -> P2 given 4 control points [P0, P1, P2, P3] at relative parameter t in [t1, t2].
 */
function evalCatmullRomPoint(p0, p1, p2, p3, t) {
  const alpha = 0.5;

  const getKnot = (pa, pb) => {
    const distSq = (pb.x - pa.x) ** 2 + (pb.z - pa.z) ** 2;
    return Math.max(0.0001, Math.pow(distSq, alpha * 0.5));
  };

  const t0 = 0.0;
  const t1 = t0 + getKnot(p0, p1);
  const t2 = t1 + getKnot(p1, p2);
  const t3 = t2 + getKnot(p2, p3);

  // Clamp t to [t1, t2]
  const clampedT = Math.max(t1, Math.min(t2, t));

  const evalVector = (s) => {
    const a1x = ((t1 - s) * p0.x + (s - t0) * p1.x) / (t1 - t0);
    const a1z = ((t1 - s) * p0.z + (s - t0) * p1.z) / (t1 - t0);

    const a2x = ((t2 - s) * p1.x + (s - t1) * p2.x) / (t2 - t1);
    const a2z = ((t2 - s) * p1.z + (s - t1) * p2.z) / (t2 - t1);

    const a3x = ((t3 - s) * p2.x + (s - t2) * p3.x) / (t3 - t2);
    const a3z = ((t3 - s) * p2.z + (s - t2) * p3.z) / (t3 - t2);

    const b1x = ((t2 - s) * a1x + (s - t0) * a2x) / (t2 - t0);
    const b1z = ((t2 - s) * a1z + (s - t0) * a2z) / (t2 - t0);

    const b2x = ((t3 - s) * a2x + (s - t1) * a3x) / (t3 - t1);
    const b2z = ((t3 - s) * a2z + (s - t1) * a3z) / (t3 - t1);

    const cx = ((t2 - s) * b1x + (s - t1) * b2x) / (t2 - t1);
    const cz = ((t2 - s) * b1z + (s - t1) * b2z) / (t2 - t1);

    return { x: cx, z: cz };
  };

  const pt = evalVector(clampedT);

  // Compute tangent velocity vector via small delta
  const delta = 0.001;
  const ptA = evalVector(clampedT - delta);
  const ptB = evalVector(clampedT + delta);
  const vx = ptB.x - ptA.x;
  const vz = ptB.z - ptA.z;

  let yaw = Math.atan2(vx, vz);
  if (Math.hypot(vx, vz) < 0.0001) {
    yaw = p1.yaw;
  }

  return {
    x: Math.max(-15.0, Math.min(15.0, pt.x)),
    z: Math.max(-15.0, Math.min(15.0, pt.z)),
    yaw: yaw
  };
}

/**
 * MODE v5: Centripetal Catmull-Rom Spline with 2-Keyframe History Buffer
 * Buffers 2 future keyframes into history (render delay = 2 * write_interval + 30ms).
 * Centripetal parameterization (alpha = 0.5) mathematically guarantees NO overshoots or loops on sharp turns.
 */
export function interpolateV5CatmullRom(keyframeQueue, now, measuredDbWriteIntervalMs) {
  if (keyframeQueue.length < 4) {
    // Fallback to v3 if less than 4 keyframes in queue
    return interpolateV3HermiteSpline(keyframeQueue, now, measuredDbWriteIntervalMs);
  }

  // 2-Keyframe History Buffer Delay
  const targetDelay = 2.0 * measuredDbWriteIntervalMs + 30.0;
  const renderTime = now - targetDelay;

  let k1Idx = -1;
  for (let i = keyframeQueue.length - 2; i >= 1; i--) {
    if (keyframeQueue[i].time <= renderTime) {
      k1Idx = i;
      break;
    }
  }

  if (k1Idx >= 1 && (k1Idx + 2) < keyframeQueue.length) {
    const p0 = keyframeQueue[k1Idx - 1];
    const p1 = keyframeQueue[k1Idx];
    const p2 = keyframeQueue[k1Idx + 1];
    const p3 = keyframeQueue[k1Idx + 2];

    const segmentDuration = p2.time - p1.time;
    const normT = segmentDuration > 0 ? (renderTime - p1.time) / segmentDuration : 0.0;

    // Map normT in [0, 1] to knot parameter in [t1, t2]
    const alpha = 0.5;
    const getKnot = (pa, pb) => Math.max(0.0001, Math.pow((pb.x - pa.x) ** 2 + (pb.z - pa.z) ** 2, alpha * 0.5));
    const t0 = 0.0;
    const t1 = t0 + getKnot(p0, p1);
    const t2 = t1 + getKnot(p1, p2);
    const knotT = t1 + normT * (t2 - t1);

    return evalCatmullRomPoint(p0, p1, p2, p3, knotT);
  } else {
    // Fallback if buffer not deep enough
    return interpolateV3HermiteSpline(keyframeQueue, now, measuredDbWriteIntervalMs);
  }
}
