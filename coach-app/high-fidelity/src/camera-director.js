import * as THREE from 'three';

export const CAMERA_PROFILES = {
  pro: {
    id: 'pro',
    name: 'Pro Standard (110° / 270 / 100 / -3°)',
    fov: 110,
    distance: 270,
    height: 100,
    pitch: -3,
    stiffness: 0.45,
  },
  default: {
    id: 'default',
    name: 'Rocket League Default (90° / 300 / 100 / 0°)',
    fov: 90,
    distance: 300,
    height: 100,
    pitch: 0,
    stiffness: 0.50,
  },
  wide: {
    id: 'wide',
    name: 'Wide Tactical (110° / 340 / 130 / -5°)',
    fov: 110,
    distance: 340,
    height: 130,
    pitch: -5,
    stiffness: 0.60,
  },
  aerial: {
    id: 'aerial',
    name: 'High Observation (105° / 550 / 350 / -18°)',
    fov: 105,
    distance: 550,
    height: 350,
    pitch: -18,
    stiffness: 0.70,
  },
};

const UP = new THREE.Vector3(0, 1, 0);
const ARENA_X_LIMIT = 4900;
const ARENA_Z_LIMIT = 3850;
const ARENA_Y_MIN = 80;
const ARENA_Y_MAX = 1950;

/**
 * Director Camera and Pro Profile Plugin.
 * Provides authentic esports camera profiles and broadcast autocam.
 */
export function createDirectorCameraPlugin({
  getCameraPlugin = null,
  getProfileName = () => 'pro',
  isDirectorActive = () => false,
} = {}) {
  let currentProfileId = 'pro';
  let appliedFov = null;

  // Shake state
  let shakeIntensity = 0;
  let shakeEndTime = 0;
  let shakeDuration = 0;
  const shakeOffset = new THREE.Vector3();

  // Director state
  let currentVantage = 'sideline';
  let lastVantageSwitchTime = -Infinity;
  const VANTAGE_HOLD_SECONDS = 2.5;

  const targetCamPos = new THREE.Vector3(0, 1400, 3100);
  const currentCamPos = new THREE.Vector3(0, 1400, 3100);
  const targetLookAt = new THREE.Vector3(0, 100, 0);
  const currentLookAt = new THREE.Vector3(0, 100, 0);

  const ballPos = new THREE.Vector3();
  let hasBallPos = false;
  let lastFrameTime = null;

  function pickDirectorVantage(ball, time) {
    // Determine context: Endzone attack vs Midfield vs Aerial
    const absX = Math.abs(ball.x);
    const absZ = Math.abs(ball.z);

    // If ball is high in the air (> 850 units)
    if (ball.y > 850) {
      return 'aerial_high';
    }

    // If ball is near orange net (X > 2500)
    if (ball.x > 2500) {
      return 'endzone_orange';
    }

    // If ball is near blue net (X < -2500)
    if (ball.x < -2500) {
      return 'endzone_blue';
    }

    // If ball is tight to one sidewall, pick the opposite elevated sideline
    if (absZ > 1800) {
      return ball.z > 0 ? 'sideline_neg' : 'sideline_pos';
    }

    // Midfield neutral
    return 'sideline_pos';
  }

  function computeVantagePose(vantage, ball, outPos, outLook) {
    outLook.copy(ball);
    // Keep look target off the immediate floor
    outLook.y = Math.max(outLook.y, 120);

    switch (vantage) {
      case 'aerial_high':
        outPos.set(ball.x * 0.5, 1750, ball.z * 0.5 + 1600);
        break;
      case 'endzone_orange':
        // Attack toward orange goal (+X): camera behind in midfield/blue side
        outPos.set(Math.max(-1500, ball.x - 2200), 1150, THREE.MathUtils.clamp(ball.z * 0.4, -1200, 1200));
        break;
      case 'endzone_blue':
        // Attack toward blue goal (-X): camera behind in midfield/orange side
        outPos.set(Math.min(1500, ball.x + 2200), 1150, THREE.MathUtils.clamp(ball.z * 0.4, -1200, 1200));
        break;
      case 'sideline_neg':
        outPos.set(THREE.MathUtils.clamp(ball.x * 0.7, -2400, 2400), 1350, -3200);
        break;
      case 'sideline_pos':
      default:
        outPos.set(THREE.MathUtils.clamp(ball.x * 0.7, -2400, 2400), 1350, 3200);
        break;
    }

    // Clamp to arena safety box
    outPos.x = THREE.MathUtils.clamp(outPos.x, -ARENA_X_LIMIT, ARENA_X_LIMIT);
    outPos.y = THREE.MathUtils.clamp(outPos.y, ARENA_Y_MIN, ARENA_Y_MAX);
    outPos.z = THREE.MathUtils.clamp(outPos.z, -ARENA_Z_LIMIT, ARENA_Z_LIMIT);
  }

  const api = {
    id: 'replay-lab-camera-director',

    triggerShake(intensity = 1.0, durationMs = 350) {
      shakeIntensity = Math.min(2.5, Math.max(0.1, intensity));
      shakeDuration = durationMs / 1000;
      shakeEndTime = performance.now() / 1000 + shakeDuration;
    },

    getProfile(profileId = null) {
      const id = profileId || getProfileName() || currentProfileId;
      return CAMERA_PROFILES[id] || CAMERA_PROFILES.pro;
    },

    setProfile(profileId) {
      if (CAMERA_PROFILES[profileId]) {
        currentProfileId = profileId;
      }
    },

    getDirectorStatus() {
      return {
        active: isDirectorActive(),
        vantage: currentVantage,
        shaking: performance.now() / 1000 < shakeEndTime,
        profile: api.getProfile(),
      };
    },

    beforeRender(ctx) {
      if (!ctx || !ctx.camera) return;
      const cam = ctx.camera;
      const now = performance.now() / 1000;
      const dt = lastFrameTime === null ? 1 / 60 : Math.max(0.001, Math.min(0.1, now - lastFrameTime));
      lastFrameTime = now;

      // 1. Profile FOV Sync
      const profile = api.getProfile();
      if (cam.fov !== profile.fov) {
        cam.fov = profile.fov;
        cam.updateProjectionMatrix();
        appliedFov = profile.fov;
      }

      // 2. Camera Shake Calculation
      shakeOffset.set(0, 0, 0);
      if (now < shakeEndTime && shakeDuration > 0) {
        const remainingNorm = (shakeEndTime - now) / shakeDuration;
        const amplitude = shakeIntensity * remainingNorm * 18.0;
        // Pseudo-random high-frequency jitter
        shakeOffset.set(
          (Math.sin(now * 85) + Math.cos(now * 117)) * 0.5 * amplitude,
          (Math.cos(now * 93) + Math.sin(now * 123)) * 0.5 * amplitude * 0.6,
          (Math.sin(now * 77) - Math.cos(now * 105)) * 0.5 * amplitude
        );
      }

      // 3. Director Autocam (if active)
      const directorActive = isDirectorActive();
      if (directorActive) {
        // Locate ball
        if (ctx.ball?.object3d) {
          ctx.ball.object3d.getWorldPosition(ballPos);
          hasBallPos = true;
        }

        if (hasBallPos) {
          const replayTime = ctx.player?.getState?.()?.currentTime ?? 0;
          // Check if we should evaluate a vantage change
          if (replayTime - lastVantageSwitchTime > VANTAGE_HOLD_SECONDS || lastVantageSwitchTime === -Infinity) {
            const nextVantage = pickDirectorVantage(ballPos, replayTime);
            if (nextVantage !== currentVantage) {
              currentVantage = nextVantage;
              lastVantageSwitchTime = replayTime;
            }
          }

          computeVantagePose(currentVantage, ballPos, targetCamPos, targetLookAt);

          // Smooth exponential damping toward director vantage
          const posAlpha = 1 - Math.exp(-4.5 * dt);
          const lookAlpha = 1 - Math.exp(-6.0 * dt);

          currentCamPos.lerp(targetCamPos, posAlpha);
          currentLookAt.lerp(targetLookAt, lookAlpha);

          cam.position.copy(currentCamPos).add(shakeOffset);
          cam.up.copy(UP);
          cam.lookAt(currentLookAt);
        }
      } else {
        // If not in director mode, apply shake directly to whatever camera is active
        if (shakeOffset.lengthSq() > 0.001) {
          cam.position.add(shakeOffset);
        }
      }
    },

    teardown() {
      appliedFov = null;
      shakeIntensity = 0;
      shakeEndTime = 0;
      lastFrameTime = null;
      lastVantageSwitchTime = -Infinity;
    },
  };

  return api;
}
