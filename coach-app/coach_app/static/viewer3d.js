/**
 * Replay Lab — Interactive 3D Arena Viewer (Three.js)
 * High-fidelity 3D Rocket League replay reconstruction.
 * Coordinates:
 *   Rocket League: X in [-4096, 4096], Y in [-5120, 5120], Z in [0, 2044]
 *   Three.js: X = -rlX * 0.01, Y = rlZ * 0.01, Z = -rlY * 0.01 (100 uu = 1 unit)
 */
(function(global) {
  'use strict';

  const SCALE = 0.01;
  const PITCH_W = 8192 * SCALE; // 81.92
  const PITCH_L = 10240 * SCALE; // 102.4
  const CEILING = 2044 * SCALE; // 20.44
  const GOAL_W = 1785.6 * SCALE;
  const GOAL_H = 642.775 * SCALE;
  const GOAL_D = 880 * SCALE;

  // 34 standard Rocket League boost pad positions (RLBot / game coordinates)
  const BOOST_PADS = [
    // Big pads (6 total)
    { x: -3072, y: -4096, z: 73, big: true, name: 'Blue Left Corner' },
    { x: 3072, y: -4096, z: 73, big: true, name: 'Blue Right Corner' },
    { x: -3584, y: 0, z: 73, big: true, name: 'Midfield Left' },
    { x: 3584, y: 0, z: 73, big: true, name: 'Midfield Right' },
    { x: -3072, y: 4096, z: 73, big: true, name: 'Orange Left Corner' },
    { x: 3072, y: 4096, z: 73, big: true, name: 'Orange Right Corner' },
    // Small pads (28 total)
    { x: 0, y: -4240, z: 70, big: false },
    { x: -1792, y: -4184, z: 70, big: false },
    { x: 1792, y: -4184, z: 70, big: false },
    { x: -940, y: -3308, z: 70, big: false },
    { x: 940, y: -3308, z: 70, big: false },
    { x: 0, y: -2816, z: 70, big: false },
    { x: -3584, y: -2484, z: 70, big: false },
    { x: 3584, y: -2484, z: 70, big: false },
    { x: -1792, y: -2484, z: 70, big: false },
    { x: 1792, y: -2484, z: 70, big: false },
    { x: -1024, y: 0, z: 70, big: false },
    { x: 0, y: -1024, z: 70, big: false },
    { x: 0, y: 1024, z: 70, big: false },
    { x: 1024, y: 0, z: 70, big: false },
    { x: -1792, y: 2484, z: 70, big: false },
    { x: 1792, y: 2484, z: 70, big: false },
    { x: -3584, y: 2484, z: 70, big: false },
    { x: 3584, y: 2484, z: 70, big: false },
    { x: 0, y: 2816, z: 70, big: false },
    { x: -940, y: 3308, z: 70, big: false },
    { x: 940, y: 3308, z: 70, big: false },
    { x: -1792, y: 4184, z: 70, big: false },
    { x: 1792, y: 4184, z: 70, big: false },
    { x: 0, y: 4240, z: 70, big: false },
    { x: -2048, y: -1036, z: 70, big: false },
    { x: 2048, y: -1036, z: 70, big: false },
    { x: -2048, y: 1036, z: 70, big: false },
    { x: 2048, y: 1036, z: 70, big: false }
  ];

  function toThreeX(rlX) { return -rlX * SCALE; }
  function toThreeY(rlZ) { return Math.max(0, rlZ) * SCALE; }
  function toThreeZ(rlY) { return -rlY * SCALE; }

  class Viewer3D {
    constructor(container) {
      this.container = container;
      this.scene = null;
      this.camera = null;
      this.renderer = null;
      this.controls = null;
      this.cameraMode = 'orbit'; // 'orbit', 'tactical', 'follow', 'ball'
      this.focusPlayerId = null;
      this.carObjects = new Map();
      this.ballMesh = null;
      this.ballShadow = null;
      this.ballDropLine = null;
      this.lastFrame = null;
      this.animationId = null;
      this.initialized = false;
      this.init();
    }

    init() {
      if (typeof THREE === 'undefined') {
        console.warn('Three.js is not loaded yet.');
        return;
      }
      const width = this.container.clientWidth || 700;
      const height = this.container.clientHeight || 550;

      this.scene = new THREE.Scene();
      this.scene.background = new THREE.Color(0x0c1e28);
      this.scene.fog = new THREE.FogExp2(0x0c1e28, 0.007);

      this.camera = new THREE.PerspectiveCamera(50, width / height, 0.5, 350);
      this.camera.position.set(0, 36, -55);

      this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
      this.renderer.setSize(width, height);
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      this.renderer.shadowMap.enabled = true;
      this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

      this.container.replaceChildren(this.renderer.domElement);

      if (typeof THREE.OrbitControls !== 'undefined') {
        this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.08;
        this.controls.maxPolarAngle = Math.PI / 2 - 0.02; // do not go below ground
        this.controls.minDistance = 4;
        this.controls.maxDistance = 140;
        this.controls.target.set(0, 3, 0);
      }

      this.setupLights();
      this.buildArena();
      this.buildBoostPads();
      this.buildBall();

      this.animate = this.animate.bind(this);
      this.animate();
      this.initialized = true;

      window.addEventListener('resize', () => this.onResize());
    }

    setupLights() {
      const ambient = new THREE.AmbientLight(0xddeeff, 0.55);
      this.scene.add(ambient);

      const dirLight = new THREE.DirectionalLight(0xffffff, 0.85);
      dirLight.position.set(20, 60, -20);
      dirLight.castShadow = true;
      dirLight.shadow.mapSize.width = 1024;
      dirLight.shadow.mapSize.height = 1024;
      dirLight.shadow.camera.near = 10;
      dirLight.shadow.camera.far = 160;
      dirLight.shadow.camera.left = -50;
      dirLight.shadow.camera.right = 50;
      dirLight.shadow.camera.top = 60;
      dirLight.shadow.camera.bottom = -60;
      this.scene.add(dirLight);

      // Subtle blue and orange stadium floodlights
      const blueLight = new THREE.PointLight(0x2196f3, 1.2, 80);
      blueLight.position.set(0, 15, toThreeZ(-5120));
      this.scene.add(blueLight);

      const orangeLight = new THREE.PointLight(0xff9800, 1.2, 80);
      orangeLight.position.set(0, 15, toThreeZ(5120));
      this.scene.add(orangeLight);
    }

    buildArena() {
      // 1. Pitch floor with authentic alternating Soccar turf mower stripes
      const turfCanvas = document.createElement('canvas');
      turfCanvas.width = 512;
      turfCanvas.height = 1024;
      const tctx = turfCanvas.getContext('2d');
      const stripeCount = 16;
      const stripeH = 1024 / stripeCount;
      for (let i = 0; i < stripeCount; i++) {
        tctx.fillStyle = (i % 2 === 0) ? '#103026' : '#0c271f';
        tctx.fillRect(0, i * stripeH, 512, stripeH);
      }
      const turfTexture = new THREE.CanvasTexture(turfCanvas);
      turfTexture.wrapS = THREE.RepeatWrapping;
      turfTexture.wrapT = THREE.RepeatWrapping;

      const floorGeo = new THREE.PlaneGeometry(PITCH_W, PITCH_L);
      const floorMat = new THREE.MeshStandardMaterial({
        map: turfTexture,
        roughness: 0.75,
        metalness: 0.12
      });
      const floor = new THREE.Mesh(floorGeo, floorMat);
      floor.rotation.x = -Math.PI / 2;
      floor.receiveShadow = true;
      this.scene.add(floor);

      // 2. Pitch lines (Canvas texture for crisp vector markings)
      const lineCanvas = document.createElement('canvas');
      lineCanvas.width = 1024;
      lineCanvas.height = 1280;
      const ctx = lineCanvas.getContext('2d');
      ctx.fillStyle = 'rgba(0,0,0,0)';
      ctx.fillRect(0, 0, 1024, 1280);

      ctx.strokeStyle = '#538d99';
      ctx.lineWidth = 6;
      // Perimeter
      ctx.strokeRect(40, 40, 944, 1200);
      // Center line
      ctx.beginPath();
      ctx.moveTo(40, 640);
      ctx.lineTo(984, 640);
      ctx.stroke();
      // Center circle
      ctx.beginPath();
      ctx.arc(512, 640, 115, 0, Math.PI * 2);
      ctx.stroke();
      // Center spot
      ctx.fillStyle = '#6cb5c2';
      ctx.beginPath();
      ctx.arc(512, 640, 8, 0, Math.PI * 2);
      ctx.fill();

      // Goal box Blue (bottom)
      ctx.strokeStyle = '#3277b3';
      ctx.strokeRect(360, 1080, 304, 160);
      // Goal box Orange (top)
      ctx.strokeStyle = '#c5743b';
      ctx.strokeRect(360, 40, 304, 160);

      const lineTexture = new THREE.CanvasTexture(lineCanvas);
      const lineMat = new THREE.MeshBasicMaterial({
        map: lineTexture,
        transparent: true,
        opacity: 0.85,
        depthWrite: false
      });
      const lineMesh = new THREE.Mesh(new THREE.PlaneGeometry(PITCH_W, PITCH_L), lineMat);
      lineMesh.rotation.x = -Math.PI / 2;
      lineMesh.position.y = 0.02;
      this.scene.add(lineMesh);

      // 3. Goal Posts and Nets
      this.buildGoal(toThreeZ(-5120), -1, 0x1e88e5); // Blue
      this.buildGoal(toThreeZ(5120), 1, 0xf57c00);   // Orange

      // 4. Perimeter wireframe fence/walls
      const wallMat = new THREE.LineBasicMaterial({ color: 0x224956, transparent: true, opacity: 0.4 });
      const wallGeo = new THREE.BufferGeometry();
      const hw = PITCH_W / 2;
      const hl = PITCH_L / 2;
      const pts = [
        new THREE.Vector3(-hw, 0, -hl), new THREE.Vector3(hw, 0, -hl),
        new THREE.Vector3(hw, 0, -hl), new THREE.Vector3(hw, 0, hl),
        new THREE.Vector3(hw, 0, hl), new THREE.Vector3(-hw, 0, hl),
        new THREE.Vector3(-hw, 0, hl), new THREE.Vector3(-hw, 0, -hl),
        // Top boundary
        new THREE.Vector3(-hw, CEILING, -hl), new THREE.Vector3(hw, CEILING, -hl),
        new THREE.Vector3(hw, CEILING, -hl), new THREE.Vector3(hw, CEILING, hl),
        new THREE.Vector3(hw, CEILING, hl), new THREE.Vector3(-hw, CEILING, hl),
        new THREE.Vector3(-hw, CEILING, hl), new THREE.Vector3(-hw, CEILING, -hl),
        // Corner pillars
        new THREE.Vector3(-hw, 0, -hl), new THREE.Vector3(-hw, CEILING, -hl),
        new THREE.Vector3(hw, 0, -hl), new THREE.Vector3(hw, CEILING, -hl),
        new THREE.Vector3(hw, 0, hl), new THREE.Vector3(hw, CEILING, hl),
        new THREE.Vector3(-hw, 0, hl), new THREE.Vector3(-hw, CEILING, hl),
      ];
      wallGeo.setFromPoints(pts);
      const wallLines = new THREE.LineSegments(wallGeo, wallMat);
      this.scene.add(wallLines);
    }

    buildGoal(zPos, direction, colorHex) {
      const group = new THREE.Group();
      const postMat = new THREE.MeshStandardMaterial({ color: colorHex, metalness: 0.6, roughness: 0.3 });
      const postRadius = 0.25;

      // Crossbar
      const barGeo = new THREE.CylinderGeometry(postRadius, postRadius, GOAL_W, 16);
      const crossbar = new THREE.Mesh(barGeo, postMat);
      crossbar.rotation.z = Math.PI / 2;
      crossbar.position.set(0, GOAL_H, zPos);
      group.add(crossbar);

      // Left post
      const postGeo = new THREE.CylinderGeometry(postRadius, postRadius, GOAL_H, 16);
      const leftPost = new THREE.Mesh(postGeo, postMat);
      leftPost.position.set(-GOAL_W / 2, GOAL_H / 2, zPos);
      group.add(leftPost);

      // Right post
      const rightPost = new THREE.Mesh(postGeo, postMat);
      rightPost.position.set(GOAL_W / 2, GOAL_H / 2, zPos);
      group.add(rightPost);

      // Net back box (translucent)
      const netMat = new THREE.MeshBasicMaterial({
        color: colorHex,
        transparent: true,
        opacity: 0.18,
        wireframe: true
      });
      const netGeo = new THREE.BoxGeometry(GOAL_W, GOAL_H, GOAL_D);
      const net = new THREE.Mesh(netGeo, netMat);
      net.position.set(0, GOAL_H / 2, zPos + (direction * GOAL_D / 2));
      group.add(net);

      this.scene.add(group);
    }

    buildBoostPads() {
      const bigGeo = new THREE.CylinderGeometry(1.4, 1.4, 0.25, 24);
      const bigMat = new THREE.MeshStandardMaterial({
        color: 0xffb300,
        emissive: 0xff8f00,
        emissiveIntensity: 0.6,
        roughness: 0.3,
        metalness: 0.7
      });

      const smallGeo = new THREE.CylinderGeometry(0.55, 0.55, 0.12, 12);
      const smallMat = new THREE.MeshStandardMaterial({
        color: 0x4dd0e1,
        emissive: 0x00acc1,
        emissiveIntensity: 0.45,
        roughness: 0.4
      });

      BOOST_PADS.forEach(pad => {
        const x = toThreeX(pad.x);
        const z = toThreeZ(pad.y);
        const mesh = new THREE.Mesh(pad.big ? bigGeo : smallGeo, pad.big ? bigMat : smallMat);
        mesh.position.set(x, pad.big ? 0.15 : 0.08, z);
        mesh.receiveShadow = true;
        this.scene.add(mesh);

        // Glowing outer halo for big pads
        if (pad.big) {
          const ringGeo = new THREE.RingGeometry(1.6, 1.9, 32);
          const ringMat = new THREE.MeshBasicMaterial({ color: 0xffca28, side: THREE.DoubleSide, transparent: true, opacity: 0.55 });
          const ring = new THREE.Mesh(ringGeo, ringMat);
          ring.rotation.x = -Math.PI / 2;
          ring.position.set(x, 0.03, z);
          this.scene.add(ring);
        }
      });
    }

    buildBall() {
      const radius = 92 * SCALE; // 0.92
      const ballGeo = new THREE.SphereGeometry(radius, 24, 24);
      const ballMat = new THREE.MeshStandardMaterial({
        color: 0xe6e6e6,
        emissive: 0x552200,
        emissiveIntensity: 0.3,
        roughness: 0.35,
        metalness: 0.5
      });
      this.ballMesh = new THREE.Mesh(ballGeo, ballMat);
      this.ballMesh.castShadow = true;
      this.scene.add(this.ballMesh);

      // Floor shadow disc
      const shadowGeo = new THREE.CircleGeometry(radius, 24);
      const shadowMat = new THREE.MeshBasicMaterial({
        color: 0x030a0d,
        transparent: true,
        opacity: 0.75,
        depthWrite: false
      });
      this.ballShadow = new THREE.Mesh(shadowGeo, shadowMat);
      this.ballShadow.rotation.x = -Math.PI / 2;
      this.ballShadow.position.y = 0.04;
      this.scene.add(this.ballShadow);

      // Vertical drop line from ball to ground
      const lineGeo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, 0, 0),
        new THREE.Vector3(0, 1, 0)
      ]);
      const lineMat = new THREE.LineBasicMaterial({ color: 0xffaa00, transparent: true, opacity: 0.45 });
      this.ballDropLine = new THREE.Line(lineGeo, lineMat);
      this.scene.add(this.ballDropLine);
    }

    createCarMesh(player) {
      const group = new THREE.Group();
      const isBlue = player.team === 'blue';
      const bodyColor = isBlue ? 0x1e88e5 : 0xf57c00;
      const trimColor = isBlue ? 0x0d47a1 : 0xe65100;

      // Chassis body (Octane proportions)
      const bodyGeo = new THREE.BoxGeometry(1.6, 0.55, 2.3);
      const bodyMat = new THREE.MeshStandardMaterial({
        color: bodyColor,
        roughness: 0.4,
        metalness: 0.5
      });
      const body = new THREE.Mesh(bodyGeo, bodyMat);
      body.position.y = 0.45;
      body.castShadow = true;
      group.add(body);

      // Cabin / windshield
      const cabinGeo = new THREE.BoxGeometry(1.2, 0.45, 1.1);
      const cabinMat = new THREE.MeshStandardMaterial({
        color: 0x1b2832,
        roughness: 0.2,
        metalness: 0.8
      });
      const cabin = new THREE.Mesh(cabinGeo, cabinMat);
      cabin.position.set(0, 0.8, -0.15);
      group.add(cabin);

      // Spoiler wing
      const wingGeo = new THREE.BoxGeometry(1.5, 0.1, 0.35);
      const wingMat = new THREE.MeshStandardMaterial({ color: trimColor, roughness: 0.5 });
      const wing = new THREE.Mesh(wingGeo, wingMat);
      wing.position.set(0, 0.95, -1.05);
      group.add(wing);

      // Roof air scoop
      const scoopGeo = new THREE.BoxGeometry(0.5, 0.2, 0.5);
      const scoopMat = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.3 });
      const scoop = new THREE.Mesh(scoopGeo, scoopMat);
      scoop.position.set(0, 1.1, -0.1);
      group.add(scoop);

      // Front wedge bumper / skid plate
      const bumperGeo = new THREE.BoxGeometry(1.4, 0.2, 0.4);
      const bumperMat = new THREE.MeshStandardMaterial({ color: 0x222222, roughness: 0.5 });
      const bumper = new THREE.Mesh(bumperGeo, bumperMat);
      bumper.position.set(0, 0.25, 1.25);
      group.add(bumper);

      // Dual glowing rear boost exhaust pipes
      const pipeGeo = new THREE.CylinderGeometry(0.12, 0.14, 0.35, 10);
      const pipeMat = new THREE.MeshStandardMaterial({
        color: 0x333333,
        emissive: isBlue ? 0x00e5ff : 0xff9100,
        emissiveIntensity: 0.7,
        roughness: 0.3
      });
      const pipeL = new THREE.Mesh(pipeGeo, pipeMat);
      pipeL.rotation.x = Math.PI / 2;
      pipeL.position.set(-0.38, 0.45, -1.25);
      const pipeR = new THREE.Mesh(pipeGeo, pipeMat);
      pipeR.rotation.x = Math.PI / 2;
      pipeR.position.set(0.38, 0.45, -1.25);
      group.add(pipeL, pipeR);

      // 4 Wheels
      const wheelGeo = new THREE.CylinderGeometry(0.32, 0.32, 0.28, 14);
      const wheelMat = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.8 });
      const wheelPos = [
        [-0.85, 0.32, 0.75],
        [0.85, 0.32, 0.75],
        [-0.85, 0.32, -0.75],
        [0.85, 0.32, -0.75]
      ];
      wheelPos.forEach(([wx, wy, wz]) => {
        const wheel = new THREE.Mesh(wheelGeo, wheelMat);
        wheel.rotation.z = Math.PI / 2;
        wheel.position.set(wx, wy, wz);
        group.add(wheel);
      });

      // Directional nose cone / arrow
      const noseGeo = new THREE.ConeGeometry(0.28, 0.6, 8);
      const noseMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
      const nose = new THREE.Mesh(noseGeo, noseMat);
      nose.rotation.x = -Math.PI / 2;
      nose.position.set(0, 0.5, 1.4);
      group.add(nose);

      // Focus player indicator halo
      const haloGeo = new THREE.RingGeometry(1.2, 1.45, 24);
      const haloMat = new THREE.MeshBasicMaterial({ color: 0x00e5ff, side: THREE.DoubleSide, transparent: true, opacity: 0.8 });
      const halo = new THREE.Mesh(haloGeo, haloMat);
      halo.rotation.x = -Math.PI / 2;
      halo.position.set(0, 1.8, 0);
      halo.visible = false;
      group.add(halo);

      // Vertical drop line to floor (height stalk)
      const stalkGeo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, 0, 0),
        new THREE.Vector3(0, 1, 0)
      ]);
      const stalkMat = new THREE.LineBasicMaterial({
        color: isBlue ? 0x64b5f6 : 0xffb74d,
        transparent: true,
        opacity: 0.4
      });
      const stalk = new THREE.Line(stalkGeo, stalkMat);
      stalk.visible = false;

      // Ground shadow
      const shadowGeo = new THREE.CircleGeometry(1.1, 16);
      const shadowMat = new THREE.MeshBasicMaterial({ color: 0x020709, transparent: true, opacity: 0.6, depthWrite: false });
      const shadow = new THREE.Mesh(shadowGeo, shadowMat);
      shadow.rotation.x = -Math.PI / 2;
      shadow.position.y = 0.03;

      this.scene.add(group);
      this.scene.add(stalk);
      this.scene.add(shadow);

      return { group, halo, stalk, shadow, player };
    }

    setCameraMode(mode) {
      this.cameraMode = mode;
      if (!this.controls) return;
      if (mode === 'orbit') {
        this.controls.enabled = true;
      } else if (mode === 'tactical') {
        this.controls.enabled = true;
        this.camera.position.set(0, 42, -50);
        this.controls.target.set(0, 2, 0);
      } else if (mode === 'follow' || mode === 'ball' || mode === 'pov') {
        this.controls.enabled = false;
      }
    }

    resetCamera() {
      this.cameraMode = 'orbit';
      if (this.controls) {
        this.controls.enabled = true;
        this.camera.position.set(0, 36, -55);
        this.controls.target.set(0, 3, 0);
      }
    }

    update(frame, focusPlayerId, players) {
      if (!this.initialized || !frame) return;
      this.lastFrame = frame;
      this.focusPlayerId = focusPlayerId;

      // Ensure all players have meshes
      if (players && Array.isArray(players)) {
        players.forEach(p => {
          if (!this.carObjects.has(p.id)) {
            this.carObjects.set(p.id, this.createCarMesh(p));
          }
        });
      }

      // Update ball
      const b = frame.ball;
      if (b && this.ballMesh) {
        const bx = toThreeX(b.x);
        const by = toThreeY(b.z);
        const bz = toThreeZ(b.y);
        this.ballMesh.position.set(bx, by, bz);

        // Ground shadow beneath ball
        if (this.ballShadow) {
          this.ballShadow.position.set(bx, 0.03, bz);
          // Scale and fade shadow with height
          const heightRatio = Math.min(1, Math.max(0, by / 20));
          const scale = 1 + heightRatio * 1.8;
          this.ballShadow.scale.set(scale, scale, 1);
          this.ballShadow.material.opacity = Math.max(0.15, 0.85 - heightRatio * 0.7);
        }

        // Vertical drop line to floor
        if (this.ballDropLine) {
          if (by > 1.2) {
            this.ballDropLine.visible = true;
            this.ballDropLine.position.set(bx, 0, bz);
            this.ballDropLine.scale.set(1, by, 1);
          } else {
            this.ballDropLine.visible = false;
          }
        }
      }

      // Update cars
      let focusCarObj = null;
      this.carObjects.forEach((carEntry, pid) => {
        const carData = frame.cars ? frame.cars[pid] : null;
        if (!carData || carData.demolished) {
          carEntry.group.visible = false;
          carEntry.stalk.visible = false;
          carEntry.shadow.visible = false;
          return;
        }

        carEntry.group.visible = true;
        const cx = toThreeX(carData.x);
        const cy = toThreeY(carData.z);
        const cz = toThreeZ(carData.y);
        carEntry.group.position.set(cx, cy, cz);

        // Orientation from forward vector
        if (carData.forward && carData.forward.length === 3) {
          // RL forward is [fx, fy, fz]; Three forward is [-fx, fz, -fy]
          const [fx, fy, fz] = carData.forward;
          const target = new THREE.Vector3(cx - fx * 5, cy + fz * 5, cz - fy * 5);
          carEntry.group.lookAt(target);
        }

        // Focus halo
        const isFocus = pid === focusPlayerId;
        carEntry.halo.visible = isFocus;
        if (isFocus) {
          focusCarObj = carEntry;
          carEntry.halo.rotation.z += 0.03;
        }

        // Aerial vertical drop stalk
        if (cy > 0.8) {
          carEntry.stalk.visible = true;
          carEntry.stalk.position.set(cx, 0, cz);
          carEntry.stalk.scale.set(1, cy, 1);
        } else {
          carEntry.stalk.visible = false;
        }

        // Ground shadow
        carEntry.shadow.visible = true;
        carEntry.shadow.position.set(cx, 0.03, cz);
      });

      // Update Camera based on mode
      if (focusCarObj && this.cameraMode === 'follow') {
        const cpos = focusCarObj.group.position;
        // Chase camera 8 units back, 4 units up
        const forwardDir = new THREE.Vector3();
        focusCarObj.group.getWorldDirection(forwardDir);
        const camTargetPos = cpos.clone().sub(forwardDir.clone().multiplyScalar(9)).add(new THREE.Vector3(0, 4.5, 0));
        this.camera.position.lerp(camTargetPos, 0.12);
        this.camera.lookAt(cpos.clone().add(new THREE.Vector3(0, 1.2, 0)));
      } else if (focusCarObj && this.ballMesh && this.cameraMode === 'ball') {
        const cpos = focusCarObj.group.position;
        const bpos = this.ballMesh.position;
        const toBall = bpos.clone().sub(cpos).normalize();
        const camTargetPos = cpos.clone().sub(toBall.multiplyScalar(8)).add(new THREE.Vector3(0, 4, 0));
        this.camera.position.lerp(camTargetPos, 0.12);
        this.camera.lookAt(bpos.clone().add(new THREE.Vector3(0, 0.5, 0)));
      } else if (focusCarObj && this.cameraMode === 'pov') {
        const cpos = focusCarObj.group.position;
        const forwardDir = new THREE.Vector3();
        focusCarObj.group.getWorldDirection(forwardDir);
        // Driver / bumper camera right above the hood looking forward
        const camPos = cpos.clone().add(new THREE.Vector3(0, 0.95, 0)).add(forwardDir.clone().multiplyScalar(0.6));
        this.camera.position.copy(camPos);
        const lookTarget = camPos.clone().add(forwardDir.clone().multiplyScalar(25));
        this.camera.lookAt(lookTarget);
      }
    }

    animate() {
      this.animationId = requestAnimationFrame(this.animate);
      if (this.controls && this.controls.enabled) {
        this.controls.update();
      }
      if (this.renderer && this.scene && this.camera) {
        this.renderer.render(this.scene, this.camera);
      }
    }

    onResize() {
      if (!this.container || !this.renderer || !this.camera) return;
      const width = this.container.clientWidth;
      const height = this.container.clientHeight;
      if (width && height) {
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(width, height);
      }
    }

    destroy() {
      if (this.animationId) {
        cancelAnimationFrame(this.animationId);
      }
      if (this.renderer && this.renderer.domElement && this.renderer.domElement.parentElement) {
        this.renderer.domElement.parentElement.removeChild(this.renderer.domElement);
      }
    }
  }

  global.Viewer3D = Viewer3D;
  global.BOOST_PADS_2D = BOOST_PADS;
})(typeof window !== 'undefined' ? window : this);
