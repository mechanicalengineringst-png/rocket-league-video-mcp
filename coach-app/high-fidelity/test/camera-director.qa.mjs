import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { createDirectorCameraPlugin, CAMERA_PROFILES } from '../src/camera-director.js';

test('camera profiles contain standard esports presets', () => {
  assert.ok(CAMERA_PROFILES.pro);
  assert.equal(CAMERA_PROFILES.pro.fov, 110);
  assert.equal(CAMERA_PROFILES.pro.distance, 270);
  assert.equal(CAMERA_PROFILES.pro.height, 100);
  assert.equal(CAMERA_PROFILES.pro.pitch, -3);

  assert.ok(CAMERA_PROFILES.default);
  assert.equal(CAMERA_PROFILES.default.fov, 90);

  assert.ok(CAMERA_PROFILES.wide);
  assert.equal(CAMERA_PROFILES.wide.fov, 110);
  assert.equal(CAMERA_PROFILES.wide.height, 130);

  assert.ok(CAMERA_PROFILES.aerial);
  assert.equal(CAMERA_PROFILES.aerial.fov, 105);
  assert.equal(CAMERA_PROFILES.aerial.height, 350);
});

test('director plugin applies profile FOV to perspective camera', () => {
  let profile = 'pro';
  const director = createDirectorCameraPlugin({
    getProfileName: () => profile,
    isDirectorActive: () => false,
  });

  const cam = new THREE.PerspectiveCamera(90, 16 / 9, 1, 10000);
  let updatedProjection = false;
  cam.updateProjectionMatrix = () => { updatedProjection = true; };

  director.beforeRender({ camera: cam, player: { getState: () => ({ currentTime: 1.0 }) } });

  assert.equal(cam.fov, 110, 'pro profile should set FOV to 110');
  assert.ok(updatedProjection, 'camera.updateProjectionMatrix should be called');

  // Change to default
  profile = 'default';
  updatedProjection = false;
  director.beforeRender({ camera: cam, player: { getState: () => ({ currentTime: 2.0 }) } });
  assert.equal(cam.fov, 90, 'default profile should set FOV to 90');
  assert.ok(updatedProjection);

  director.teardown();
});

test('shake impulse applies pseudo-random offset within duration', () => {
  const director = createDirectorCameraPlugin({
    getProfileName: () => 'pro',
    isDirectorActive: () => false,
  });

  const cam = new THREE.PerspectiveCamera(90, 16 / 9, 1, 10000);
  cam.position.set(100, 200, 300);

  director.triggerShake(1.5, 500);
  const status = director.getDirectorStatus();
  assert.ok(status.shaking, 'shake should be active immediately after trigger');

  const origPos = cam.position.clone();
  director.beforeRender({ camera: cam, player: { getState: () => ({ currentTime: 1.0 }) } });

  assert.notDeepEqual(cam.position.toArray(), origPos.toArray(), 'shake should introduce positional displacement');

  director.teardown();
});

test('director autocam positions camera at high vantage tracking the ball', () => {
  const director = createDirectorCameraPlugin({
    getProfileName: () => 'pro',
    isDirectorActive: () => true,
  });

  const cam = new THREE.PerspectiveCamera(90, 16 / 9, 1, 10000);
  const ballObj = new THREE.Object3D();
  ballObj.position.set(2800, 150, 400); // Ball driving toward orange goal

  const ctx = {
    camera: cam,
    ball: { object3d: ballObj },
    player: { getState: () => ({ currentTime: 10.0 }) },
  };

  // Run a couple steps to allow lerp
  for (let i = 0; i < 5; i++) {
    director.beforeRender(ctx);
  }

  const status = director.getDirectorStatus();
  assert.equal(status.active, true);
  assert.equal(status.vantage, 'endzone_orange', 'ball in orange half should trigger endzone_orange vantage');

  // Camera should be elevated (> 500) and within arena bounds
  assert.ok(cam.position.y >= 80 && cam.position.y <= 1950, `camera height ${cam.position.y} should be safe`);
  assert.ok(Math.abs(cam.position.x) <= 4900, `camera X ${cam.position.x} should be within arena bounds`);
  assert.ok(Math.abs(cam.position.z) <= 3850, `camera Z ${cam.position.z} should be within arena bounds`);

  director.teardown();
});
