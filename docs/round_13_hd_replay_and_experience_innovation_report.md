# Replay Lab — Round 13: HD Replay & Experience Innovation Report

**Author:** Principal Replay Reconstruction, Frontend Architecture & Native Game Integration Engineer  
**Branch:** `feature/round13-hd-replay-experience-innovation-20261118`  
**Starting Point:** Draft PR #52 (`cfc5b2a`)  
**Status:** Verification Complete — 89 Node Tests Passing (73 unit + 16 QA), 516 Pytest Passing, Full Playwright Browser E2E Verified with Native Replay

---

## Executive Summary

Round 13 delivers a major leap in Replay Lab's standalone replay experience, transforming our visual player from an observational viewer into an authentic, spatial, film-room coaching studio. We systematically tackled the architectural boundaries of browser-based replay reconstruction, implemented high-fidelity vehicle dynamics, integrated an asset-free procedural Web Audio synthesizer, projected 3D tactical vectors directly into the Three.js stadium, and introduced an automated broadcast Director Cam.

```
       ┌────────────────────────────────────────────────────────┐
       │              REPLAY LAB ROUND 13 STUDIO                │
       └──────────────────────────┬─────────────────────────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         ▼                        ▼                        ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   3D TACTICAL    │    │    PROCEDURAL    │    │    BROADCAST     │
│    OVERLAYS      │    │   AUDIO ENGINE   │    │   DIRECTOR CAM   │
│                  │    │                  │    │                  │
│ • Focus-to-Ball  │    │ • Boost Thruster │    │ • Endzone Attack │
│ • Team Spacing   │    │ • Sonic Boom     │    │ • Midfield High  │
│ • Lens t0 Ring   │    │ • Ball Impact    │    │ • Dynamic Damping│
│ • +2s Ghost Car  │    │ • 0KB Audio Size │    │ • Camera Shake   │
└──────────────────┘    └──────────────────┘    └──────────────────┘
```

---

## 1. Architectural Reconsideration: Browser WebGL vs. Native Rendering

We conducted an architectural investigation into our rendering stack to answer: *What is the fundamental ceiling of browser replay reconstruction, and should Replay Lab transition to native rendering, WebGPU, or hybrid video streaming?*

### 1.1 Architectural Comparison Matrix

| Dimension | Browser WebGL / Three.js (Current) | WebGPU Next-Gen | Native BakkesMod / Unreal Engine | Headless Server Video Streaming (e.g. Pixel Streaming) |
| :--- | :--- | :--- | :--- | :--- |
| **User Setup Friction** | **Zero** (100% browser local, drag & drop) | **Zero** (modern Chrome/Edge) | **High** (Requires Rocket League, Windows, BakkesMod install) | **Low** for user, **Extreme** cost/latency for host |
| **Frame Latency / Seeking** | **Instantaneous (< 16ms)**, bidirectional scrub | **Instantaneous (< 10ms)** | Requires game replay scrub API (jittery) | 80–250ms stream latency, video bitrate compression |
| **Tactical 3D Overlays** | **Native integration** (Three.js meshes, lines, billboard HUD) | High (compute shaders, raw pipelines) | BakkesMod Canvas API (C++ hook, primitive 2D projection) | Statically burned into video or separated in web layer |
| **Visual Fidelity** | High (PBR GLTF cars, HDR stadium, soft ribbon trails) | Near-Native (compute particles, clustered lighting) | **Authentic Native Unreal Engine 3** | Authentic, but lossy H.264/WebRTC compression |
| **Cross-Platform** | Windows, Mac, Linux, iOS, ChromeOS | Modern desktop WebGPU browsers | **Windows only** (Rocket League + BakkesMod) | Any browser, but requires GPU server cluster ($$$) |

### 1.2 Verdict & Roadmap Recommendation
1. **Retain Browser WebGL / WASM as the Primary Standalone Core:** Zero-friction replay loading, instant frame-accurate scrubbing, and tight DOM/split-view synchronization cannot be matched by any external desktop dependency.
2. **Path to WebGPU:** The current `@rlrml/player` Three.js architecture cleanly maps to Three.js WebGPURenderer (`three/webgpu`). This unlocks compute-shader-driven tire smoke, GPU trajectory curves, and authentic volumetric stadium lighting without requiring client installs.
3. **Keep Native Companion Purely as an Opt-In Companion:** Rocket League's local loopback (port 49123 / 49124) remains an optional auxiliary controller for players who have the native game running on PC, but Replay Lab will never require it to function.

---

## 2. Vehicle Dynamics & Authentic Asset Fidelity

### 2.1 Authentic Car Models & Hitbox Accuracy
- Vehicles in Replay Lab are automatically swapped from wireframe placeholders to authentic PBR GLTF models (Octane, Fennec, Dominus, Breakout, Merc, Mantis, X-Devil).
- Material parameters preserve authentic gloss, clearcoat roughness, and team decals (Blue vs. Orange primary palettes).

### 2.2 Active Wheel Steering & Rolling Dynamics
- Vehicle meshes detect separate `Wheel_FR`, `Wheel_FL`, `Wheel_BR`, and `Wheel_BL` sockets loaded with `Wheel_Boog.glb`.
- **Axle Roll:** Calculated proportional to car translation speed:
  $$\Delta \theta_{\text{roll}} = \min\left(\frac{\Delta d}{17}, 0.5\right)$$
- **Front Wheel Steering Pivots:** Front axle wheels rotate about the vertical steering axis based on the recorded steering angle input:
  $$\theta_{\text{steer}} = -\text{steer} \cdot \frac{\pi}{6}$$
- **Scrub & Step Animation Parity:** In Round 13, wheel rotations and steering pivots are explicitly re-evaluated during manual scrubbing and frame-by-frame stepping (`stepBackBtn`, `stepForwardBtn`, and `seek`), ensuring wheels do not stay frozen during slow-motion analysis.

---

## 3. Procedural Web Audio Engine (Zero Assets, Zero Latency)

A major gap in web-based replay players has been the lack of auditory cues. However, downloading hundreds of megabytes of audio samples creates massive bandwidth overhead and licensing friction.

In Round 13, we built `createReplayAudioEngine`—a procedural Web Audio synthesizer operating entirely via native browser oscillators, noise generators, and biquad filters:
1. **Continuous Thruster Whoosh:** A looped white-noise buffer fed through a bandpass filter ($f_0 = 450\text{ Hz}, Q = 1.8$) with exponential gain envelope following `isBoosting` state.
2. **Supersonic Sonic Boom:** Low-frequency resonant punch ($f_0 = 95\text{ Hz} \to 30\text{ Hz}$) with high-frequency pop ($1800\text{ Hz}$) triggered upon exceeding the supersonic speed threshold (2200 UU/s).
3. **Ball Impact Thumps:** Dual-oscillator sine frequency sweep ($160\text{ Hz} \to 45\text{ Hz}$) dynamically scaled by impact impulse $\Delta v_{\text{ball}}$.
4. **Goal Horn Resonance:** Triad saw-wave chord (110 Hz, 138.6 Hz, 164.8 Hz) through low-pass saturation.
5. **Autoplay Compliance:** Muted by default with a single-click toggle (`#audioToggleBtn`) and volume slider (`#audioVolumeSlider`).

---

## 4. 3D Tactical Overlays & Decision Lens Stadium Integration

Previously, tactical connection vectors and Decision Lens markers existed only in the 2D pitch view. In Round 13, `tactical-3d.js` renders spatial tactical evidence directly in the 3D stadium:
- **Focus-to-Ball Dynamic Vector:** Real-time 3D line from the focused vehicle to the ball center, color-coded by tactical contest range (teal for close/immediate play $\le 1000$ UU, transitioning to gold/orange at long distances).
- **Teammate Spacing Vector:** Dashed spatial connection line to the nearest teammate to visualize team structure and rotation spacing.
- **Decision Lens $t_0$ Ground Ring:** Pulsing 3D marker at the vehicle's position at decision point $t_0$.
- **$+2\text{s}$ Ghost Follow-Through Marker:** Visualizes the actual subsequent path of the car inside the stadium relative to alternative tactical choices.

---

## 5. Camera Innovation & Broadcast Director Autocam

### 5.1 Esports Pro Camera Profiles
Esports players rely on standardized camera settings to judge touches and field perspective. We added authentic presets via `#cameraProfileSelect`:
- **Pro Standard (Squishy/Zen):** FOV $110^\circ$, Distance $270$, Height $100$, Pitch $-3^\circ$, Stiffness $0.45$.
- **Rocket League Default:** FOV $90^\circ$, Distance $300$, Height $100$, Pitch $0^\circ$, Stiffness $0.50$.
- **Wide Tactical:** FOV $110^\circ$, Distance $340$, Height $130$, Pitch $-5^\circ$, Stiffness $0.60$.
- **High Observation (Bird's-Eye):** FOV $105^\circ$, Distance $550$, Height $350$, Pitch $-18^\circ$, Stiffness $0.70$.

### 5.2 Broadcast Director Autocam (TV Mode)
Selecting `Director (TV)` enables an automated cinematic camera that selects high vantage points tracking play:
- **Endzone Attack (Orange/Blue):** High behind-the-attack angle when play enters an offensive zone.
- **Elevated Sideline:** Wide mid-court perspective during midfield transitions.
- **Aerial High:** High $45^\circ$ downward view when the ball is launched into the air ($y > 850$).
- **Inertial Smoothing:** Exponential damping ($\alpha = 1 - e^{-4.5 \Delta t}$) prevents disorienting camera snaps, while enforcing arena boundary safety boxes.
- **Camera Shake Impulse:** Subtle high-frequency jitter triggered by supersonic shockwaves and goal explosions.

---

## 6. Timeline Innovation: Ultra Slow-Motion & Frame Navigation

- Added **0.1× Ultra Slow-Motion** playback mode, essential for analyzing micro-mechanics, flip resets, 50-50 pinches, and kickoff touches.
- Full speed range: `0.1×`, `0.25×`, `0.5×`, `1.0×`, `1.5×`, `2.0×`.
- Instant frame step-forward and step-backward with wheel physics synchronization.

---

## 7. Verification & Test Results

```
========================================================================
Test Suite                                  Status      Passing    Time
========================================================================
High-Fidelity Node Unit Tests (npm test)    PASSED      73 / 73    661ms
High-Fidelity QA Shaders & Polish Tests     PASSED      16 / 16    312ms
Total High-Fidelity JavaScript Tests        PASSED      89 / 89    973ms
Pytest Full Backend Suite                   PASSED     516 / 516   82.8s
Playwright E2E Browser Test (real replay)   PASSED       All       65.2s
========================================================================
```
