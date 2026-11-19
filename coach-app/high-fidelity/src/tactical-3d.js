import * as THREE from 'three';

/**
 * Replay Lab 3D Tactical Visualization Plugin
 *
 * Renders in-stadium 3D spatial connections, Decision Lens t0 pins,
 * +2s recorded follow-through ghost markers, and vehicle overhead boost HUDs.
 * Runs directly in the Three.js scene context alongside the high-fidelity player.
 */

const UP = new THREE.Vector3(0, 1, 0);
const tempV1 = new THREE.Vector3();
const tempV2 = new THREE.Vector3();
const tempV3 = new THREE.Vector3();

export function createTactical3DPlugin({
  getFollowId = () => null,
  getLensState = () => null,
  isEnabled = () => true,
} = {}) {
  let rootGroup = null;
  let ballLine = null;
  let teammateLine = null;
  let t0Ring = null;
  let ghostMarker = null;
  const boostHUDs = new Map(); // carId -> Object3D

  function initGroup(scene) {
    if (rootGroup && rootGroup.parent === scene) return rootGroup;
    rootGroup = new THREE.Group();
    rootGroup.name = 'replay-lab-tactical-3d-root';

    // 1. Line from focus car to ball
    const ballLineGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(),
      new THREE.Vector3()
    ]);
    const ballLineMat = new THREE.LineBasicMaterial({
      color: 0x00d2ff,
      transparent: true,
      opacity: 0.75,
      linewidth: 2,
      depthTest: true
    });
    ballLine = new THREE.Line(ballLineGeo, ballLineMat);
    ballLine.visible = false;
    rootGroup.add(ballLine);

    // 2. Line between focus car and teammate (spacing/rotation)
    const teamLineGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(),
      new THREE.Vector3()
    ]);
    const teamLineMat = new THREE.LineDashedMaterial({
      color: 0x39ff14,
      transparent: true,
      opacity: 0.65,
      dashSize: 80,
      gapSize: 40,
      depthTest: true
    });
    teammateLine = new THREE.Line(teamLineGeo, teamLineMat);
    teammateLine.visible = false;
    rootGroup.add(teammateLine);

    // 3. Decision Lens t0 ground marker ring
    const ringGeo = new THREE.RingGeometry(110, 130, 48);
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0xffaa00,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.85,
      depthWrite: false
    });
    t0Ring = new THREE.Mesh(ringGeo, ringMat);
    t0Ring.rotation.x = -Math.PI / 2; // Lie flat on arena floor
    t0Ring.position.y = 8; // Slightly above ground to prevent z-fighting
    t0Ring.visible = false;
    rootGroup.add(t0Ring);

    // 4. Ghost marker for actual +2s follow-through
    const ghostGeo = new THREE.BoxGeometry(118, 36, 84);
    const ghostMat = new THREE.MeshStandardMaterial({
      color: 0x00ffff,
      transparent: true,
      opacity: 0.35,
      wireframe: true
    });
    ghostMarker = new THREE.Mesh(ghostGeo, ghostMat);
    ghostMarker.visible = false;
    rootGroup.add(ghostMarker);

    scene.add(rootGroup);
    return rootGroup;
  }

  function getOrCreateBoostHUD(carId, scene) {
    if (boostHUDs.has(carId)) return boostHUDs.get(carId);

    const hudGroup = new THREE.Group();
    hudGroup.name = `boost-hud-${carId}`;

    // Outer circular track
    const trackGeo = new THREE.RingGeometry(24, 28, 32);
    const trackMat = new THREE.MeshBasicMaterial({
      color: 0x222222,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.6,
      depthTest: false
    });
    const trackMesh = new THREE.Mesh(trackGeo, trackMat);
    hudGroup.add(trackMesh);

    // Fill arc representing boost percentage
    const fillGeo = new THREE.RingGeometry(24, 28, 32, 1, 0, Math.PI * 2);
    const fillMat = new THREE.MeshBasicMaterial({
      color: 0x00ffff,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.9,
      depthTest: false
    });
    const fillMesh = new THREE.Mesh(fillGeo, fillMat);
    hudGroup.add(fillMesh);

    hudGroup.userData = { fillMesh, currentBoost: -1 };
    rootGroup.add(hudGroup);
    boostHUDs.set(carId, hudGroup);
    return hudGroup;
  }

  const api = {
    id: 'replay-lab-tactical-3d',

    beforeRender(ctx) {
      if (!ctx?.scene || !ctx?.camera) return;
      initGroup(ctx.scene);

      const active = Boolean(isEnabled());
      rootGroup.visible = active;
      if (!active) return;

      const focusId = getFollowId();
      const cars = ctx.cars || [];
      const ball = ctx.ball;

      // Locate followed vehicle
      const focusCarEntry = cars.find(c => c.id != null && String(c.id) === String(focusId));
      const focusObj = focusCarEntry?.object3d;
      const focusVisible = focusCarEntry?.visible !== false && focusObj;

      // 1. Update Focus -> Ball Spatial Line
      if (focusVisible && ball && ball.position) {
        focusObj.getWorldPosition(tempV1);
        tempV1.y += 20; // center of car
        tempV2.copy(ball.position);

        const posAttr = ballLine.geometry.attributes.position;
        posAttr.setXYZ(0, tempV1.x, tempV1.y, tempV1.z);
        posAttr.setXYZ(1, tempV2.x, tempV2.y, tempV2.z);
        posAttr.needsUpdate = true;

        const dist = tempV1.distanceTo(tempV2);
        // Color transition: close = bright cyan/yellow, far = dimmer blue
        if (dist < 1200) {
          ballLine.material.color.setHex(0xffdd00); // Contest range
          ballLine.material.opacity = 0.9;
        } else {
          ballLine.material.color.setHex(0x00d2ff);
          ballLine.material.opacity = 0.6;
        }
        ballLine.visible = true;
      } else {
        ballLine.visible = false;
      }

      // 2. Update Focus -> Teammate Spacing Line
      let teammateFound = false;
      if (focusVisible && focusObj.userData?.team !== undefined) {
        const team = focusObj.userData.team;
        const teammateEntry = cars.find(c =>
          c.id != null &&
          String(c.id) !== String(focusId) &&
          c.object3d?.userData?.team === team &&
          c.visible !== false
        );
        if (teammateEntry?.object3d) {
          focusObj.getWorldPosition(tempV1);
          teammateEntry.object3d.getWorldPosition(tempV3);
          tempV1.y += 20;
          tempV3.y += 20;

          const teamPosAttr = teammateLine.geometry.attributes.position;
          teamPosAttr.setXYZ(0, tempV1.x, tempV1.y, tempV1.z);
          teamPosAttr.setXYZ(1, tempV3.x, tempV3.y, tempV3.z);
          teamPosAttr.needsUpdate = true;
          teammateLine.computeLineDistances();
          teammateLine.visible = true;
          teammateFound = true;
        }
      }
      if (!teammateFound) teammateLine.visible = false;

      // 3. Decision Lens t0 Pin and +2s Ghost Follow-through
      const lens = getLensState();
      const lensWindow = lens?.window;
      if (lensWindow && Number.isFinite(lensWindow.t0)) {
        const anchor = lensWindow.anchor;
        const focusAnchor = anchor?.cars?.find(c => String(c.id) === String(focusId));
        if (focusAnchor && Number.isFinite(focusAnchor.x) && Number.isFinite(focusAnchor.y)) {
          // Three.js coordinates: X = x, Z = y (pitch horizontal)
          t0Ring.position.set(focusAnchor.x, 8, focusAnchor.y);
          t0Ring.visible = true;
        } else {
          t0Ring.visible = false;
        }

        // Ghost car for actual +2s outcome (when user clicks Reveal)
        if (lens.revealed && lensWindow.after) {
          const afterFocus = lensWindow.after.cars?.find(c => String(c.id) === String(focusId));
          if (afterFocus && Number.isFinite(afterFocus.x) && Number.isFinite(afterFocus.y)) {
            ghostMarker.position.set(afterFocus.x, (afterFocus.z || 18) + 18, afterFocus.y);
            ghostMarker.visible = true;
          } else {
            ghostMarker.visible = false;
          }
        } else {
          ghostMarker.visible = false;
        }
      } else {
        t0Ring.visible = false;
        ghostMarker.visible = false;
      }

      // 4. Floating Overhead Boost HUDs
      const activeCarIds = new Set();
      for (const car of cars) {
        if (!car.object3d || car.visible === false) continue;
        const id = String(car.id);
        activeCarIds.add(id);

        const hud = getOrCreateBoostHUD(id, ctx.scene);
        car.object3d.getWorldPosition(tempV1);
        tempV1.y += 85; // Float 85 units above car roof
        hud.position.copy(tempV1);

        // Billboard to face the active camera
        hud.quaternion.copy(ctx.camera.quaternion);

        // Update fill arc based on boost
        const boostVal = car.object3d.userData?.boost ?? car.boost ?? 100;
        const boostPct = THREE.MathUtils.clamp(boostVal, 0, 100) / 100;

        if (Math.abs(hud.userData.currentBoost - boostPct) > 0.01) {
          hud.userData.currentBoost = boostPct;
          hud.userData.fillMesh.geometry.dispose();
          hud.userData.fillMesh.geometry = new THREE.RingGeometry(
            24, 28, 32, 1, Math.PI / 2, -Math.PI * 2 * boostPct
          );
          // Color based on boost level & team
          if (boostPct < 0.20) {
            hud.userData.fillMesh.material.color.setHex(0xff3333); // Danger low boost
          } else if (car.object3d.userData?.team === 1) {
            hud.userData.fillMesh.material.color.setHex(0xff8c00); // Orange team
          } else {
            hud.userData.fillMesh.material.color.setHex(0x00d2ff); // Blue team
          }
        }
        hud.visible = true;
      }

      // Hide HUDs for cars no longer in scene
      for (const [id, hud] of boostHUDs.entries()) {
        if (!activeCarIds.has(id)) hud.visible = false;
      }
    },

    teardown() {
      if (rootGroup && rootGroup.parent) {
        rootGroup.parent.remove(rootGroup);
      }
      boostHUDs.clear();
      rootGroup = null;
    }
  };

  return api;
}
