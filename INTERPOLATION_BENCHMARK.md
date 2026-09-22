# Developer Evaluation Document: Interpolation Engine Evolution & Benchmark Analysis

This document records empirical performance evaluations, motion dynamics, and technical comparisons across all five versions of the interpolation engine (`v1` through `v5`) under various combinations of **Simulation DB Write Rate** ($\text{sim\_write\_hz}$) and **Backend DB Poll Rate** ($\text{poll\_hz}$).

---

## 📊 Empirical Matrix & Performance Summary

| Frequency Combination | DB Write Hz | DB Poll Hz | Winner / Ranking | Observed Motion Characteristics |
| :--- | :---: | :---: | :--- | :--- |
| **Super Low Poll Rate** | 60 Hz | 1 Hz | `v5 > v3 > v4 ≈ v2` | **v5** glides along historical spline; **v3** takes longer per step; **v4** shows fast-in + ease-out step motion; **v2** moves to next point very fast with zigzag motion. |
| **Low Poll Rate** | 60 Hz | 6 Hz | `v5 ≈ v4 > v3 ≈ v2` | **v5** and **v4** provide smooth continuous animation. **v3** and **v2** produce noticeable discrete step feelings. |
| **Decent Rates (Optimal)** | >24 Hz | >24 Hz | `v4 ≈ v5 ≈ v2 > v3` | Difference between v2, v4, and v5 is minimal. **v3** feels just a tiny bit unsmooth due to spline buffer delay. |
| **Low Write Rate** | 6 Hz | 60 Hz | `v5 ≈ v4 >> v3 ≈ v2` | **v5** and **v4** dominate. Barely feels any difference despite the DB write rate drop. |
| **Super Low Write Rate** | 1 Hz | 60 Hz | `v5 > v4 > v3 > v2` | **v5** achieves 100% fluid, zero-pause continuous motion across 1-second keyframe gaps by buffering 2 future keyframes into history. |

---

## 🔬 Detailed Version Comparison

### 1. Version 1: `v1_raw_snap` (Raw 0-Lag Snap)
- **Algorithm**: Immediate coordinate replacement upon packet receipt.
- **Characteristics**: Instantaneous 0-latency snap. Zero smoothing.
- **Best Used For**: Raw telemetry verification and 0-latency debugging.

### 2. Version 2: `v2_simple_lerp` (Simple Exponential LERP with Unfiltered Duplicates)
- **Algorithm**: Exponential decay $\vec{p}(t + \Delta t) = \vec{p}(t) + (\vec{p}_{\text{target}} - \vec{p}(t))(1 - e^{-\lambda \Delta t})$.
- **Characteristics**:
  - Unfiltered duplicate DB polling packets are processed.
  - Reaches next keyframe very quickly in ~150–200ms, then sits completely frozen for the remaining cycle duration.
  - Produces noticeable **zigzag animations** at low poll rates.

### 3. Version 3: `v3_hermite_spline` (Cubic Hermite Spline with Duplicate Filtering)
- **Algorithm**: Smoothstep curve $u = t^2(3 - 2t)$ evaluated across filtered unique keyframe write intervals.
- **Characteristics**:
  - Ignores duplicate polling packets and measures true DB write intervals $T_{\text{write\_interval}}$.
  - Takes longer to finish each step, making 1-second steps look slightly smoother than v2.
  - Still exhibits a minor pause at the end of keyframe intervals when waiting for the next unique packet.

### 4. Version 4: `v4_continuous_seamless` (Continuous Extrapolation & Target Blend)
- **Algorithm**: Velocity dead-reckoning $\vec{p}_{\text{next}} = \vec{p} + \vec{v}\Delta t$ combined with smooth target pull blending $(1 - e^{-\gamma \Delta t})$.
- **Characteristics**:
  - **Dominates at low DB write rates (6 Hz)**—virtually indistinguishable from high write rates.
  - Produces a natural **fast-start and ease-out** step motion.
  - Minimizes stutters across all frequency combinations.

### 5. Version 5: `v5_catmull_rom` (Centripetal Catmull-Rom Spline with 2-Keyframe History Buffer)
- **Algorithm**: Centripetal Catmull-Rom spline ($\alpha = 0.5$) with 2-keyframe history buffer ($P_0, P_1, P_2, P_3$). Derivative vector $\vec{v}(t) = \left(\frac{dx}{dt}, \frac{dz}{dt}\right)$ defines vehicle tangent heading.
- **Characteristics**:
  - **Zero Pause / Zero Detour**: Sacrifices 2 cycles of real-time latency ($T_{\text{buffer}} \approx 2030\text{ms}$ at 1 Hz write rate) to render true historical curves.
  - Centripetal parameterization ($\alpha = 0.5$) mathematically prevents wild loops or overshoots on sharp 90° or 180° turns.
  - Vehicle body rotates smoothly along curve tangents without rotation snapping.

---

## 📁 Related Source Files

- **Interpolation Module**: [`frontend/src/interpolation.js`](frontend/src/interpolation.js)
- **Main Animation Loop**: [`frontend/src/main.js`](frontend/src/main.js)
- **HTML UI Controls**: [`frontend/index.html`](frontend/index.html)
- **Backend FastAPI**: [`backend/main.py`](backend/main.py)
