import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { createTactical3DPlugin } from '../src/tactical-3d.js';

test('createTactical3DPlugin initializes cleanly and attaches to scene', () => {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera();
  const plugin = createTactical3DPlugin();

  assert.equal(plugin.id, 'replay-lab-tactical-3d');
  plugin.beforeRender({ scene, camera, cars: [], ball: null });

  const root = scene.getObjectByName('replay-lab-tactical-3d-root');
  assert.ok(root, 'Root tactical group must be added to scene');
  assert.equal(root.visible, true);
});

test('tactical 3D plugin respects isEnabled toggle', () => {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera();
  let enabled = true;
  const plugin = createTactical3DPlugin({ isEnabled: () => enabled });

  plugin.beforeRender({ scene, camera, cars: [], ball: null });
  const root = scene.getObjectByName('replay-lab-tactical-3d-root');
  assert.equal(root.visible, true);

  enabled = false;
  plugin.beforeRender({ scene, camera, cars: [], ball: null });
  assert.equal(root.visible, false);
});

test('tactical 3D connects focus car to ball and teammate', () => {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera();
  const car1 = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial());
  car1.position.set(100, 20, 200);
  car1.userData = { team: 0 };

  const car2 = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial());
  car2.position.set(500, 20, 800);
  car2.userData = { team: 0 };

  const ball = { position: new THREE.Vector3(150, 93, 400) };

  const plugin = createTactical3DPlugin({ getFollowId: () => '1' });
  plugin.beforeRender({
    scene,
    camera,
    cars: [
      { id: '1', object3d: car1, visible: true },
      { id: '2', object3d: car2, visible: true },
    ],
    ball,
  });

  const root = scene.getObjectByName('replay-lab-tactical-3d-root');
  const ballLine = root.children.find(c => c.isLine && !c.material.isLineDashedMaterial);
  const teamLine = root.children.find(c => c.isLine && c.material.isLineDashedMaterial);

  assert.ok(ballLine, 'Ball line must exist');
  assert.equal(ballLine.visible, true, 'Ball line must be visible when focused car and ball exist');

  assert.ok(teamLine, 'Teammate line must exist');
  assert.equal(teamLine.visible, true, 'Teammate line must be visible for same-team vehicles');
});

test('Decision Lens t0 ring and +2s ghost follow-through sync with lens state', () => {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera();
  const car = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial());
  car.position.set(0, 0, 0);

  let lensState = {
    window: {
      t0: 125.4,
      anchor: { cars: [{ id: '1', x: 250, y: -400 }] },
      after: { cars: [{ id: '1', x: 800, y: 150 }] },
    },
    revealed: false,
  };

  const plugin = createTactical3DPlugin({
    getFollowId: () => '1',
    getLensState: () => lensState,
  });

  plugin.beforeRender({
    scene,
    camera,
    cars: [{ id: '1', object3d: car, visible: true }],
    ball: null,
  });

  const root = scene.getObjectByName('replay-lab-tactical-3d-root');
  const t0Ring = root.children.find(c => c.geometry.type === 'RingGeometry');
  const ghostBox = root.children.find(c => c.geometry.type === 'BoxGeometry');

  assert.ok(t0Ring, 't0 ring must exist');
  assert.equal(t0Ring.visible, true, 't0 ring must be visible when lens is active');
  assert.equal(t0Ring.position.x, 250);
  assert.equal(t0Ring.position.z, -400);

  assert.ok(ghostBox, 'Ghost box must exist');
  assert.equal(ghostBox.visible, false, 'Ghost box must stay hidden until user clicks reveal');

  // Now reveal future outcome
  lensState.revealed = true;
  plugin.beforeRender({
    scene,
    camera,
    cars: [{ id: '1', object3d: car, visible: true }],
    ball: null,
  });

  assert.equal(ghostBox.visible, true, 'Ghost box must appear after reveal');
  assert.equal(ghostBox.position.x, 800);
  assert.equal(ghostBox.position.z, 150);
});

test('teardown removes root group and clears resources', () => {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera();
  const plugin = createTactical3DPlugin();

  plugin.beforeRender({ scene, camera, cars: [], ball: null });
  assert.ok(scene.getObjectByName('replay-lab-tactical-3d-root'));

  plugin.teardown();
  assert.equal(scene.getObjectByName('replay-lab-tactical-3d-root'), undefined);
});
