/* Three.js stage: a Quectel Pi M2 board.
 * The board rotates with the fused quaternion; the base ring and grid stay
 * fixed so tilt is easy to read. */
(function () {
  "use strict";

  if (THREE.ColorManagement) {
    // Hex colours in this file are authored in sRGB, like CSS.
    THREE.ColorManagement.legacyMode = false;
  }

  const DEG = Math.PI / 180;
  const C_YAW_TO_THREE = new THREE.Quaternion().setFromAxisAngle(
    new THREE.Vector3(1, 0, 0),
    -Math.PI / 2
  );

  function clamp(value, low, high) {
    return value < low ? low : value > high ? high : value;
  }

  function roundedRectShape(width, height, radius) {
    const shape = new THREE.Shape();
    const x = -width / 2;
    const y = -height / 2;
    const r = Math.min(radius, width / 2, height / 2);
    shape.moveTo(x + r, y);
    shape.lineTo(x + width - r, y);
    shape.quadraticCurveTo(x + width, y, x + width, y + r);
    shape.lineTo(x + width, y + height - r);
    shape.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
    shape.lineTo(x + r, y + height);
    shape.quadraticCurveTo(x, y + height, x, y + height - r);
    shape.lineTo(x, y + r);
    shape.quadraticCurveTo(x, y, x + r, y);
    shape.closePath();
    return shape;
  }

  function box(width, height, depth, material) {
    return new THREE.Mesh(new THREE.BoxGeometry(width, height, depth), material);
  }

  function canvasTexture(width, height, draw) {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    draw(ctx, width, height);
    const texture = new THREE.CanvasTexture(canvas);
    texture.encoding = THREE.sRGBEncoding;
    texture.anisotropy = 4;
    return texture;
  }

  function textSprite(text, color, scale) {
    const texture = canvasTexture(256, 96, (ctx, w, h) => {
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = color;
      ctx.font = '600 54px "Segoe UI", Arial, sans-serif';
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(text, w / 2, h / 2);
    });
    const material = new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      depthWrite: false,
      depthTest: true,
      toneMapped: false,
    });
    const sprite = new THREE.Sprite(material);
    sprite.scale.set(scale || 1.1, (scale || 1.1) * 0.42, 1);
    return sprite;
  }

  class AttitudeScene {
    constructor(canvas) {
      this.canvas = canvas;
      this.available = false;
      this.width = 1;
      this.height = 1;
      this.frameTimes = [];
      this.theta = 0.0;
      this.phi = 0.14;
      this.radius = 14.0;
      this.thetaTarget = this.theta;
      this.phiTarget = this.phi;
      this.radiusTarget = this.radius;
      this.pointers = new Map();
      this.lastPointerDistance = 0;
      this.targetQuaternion = new THREE.Quaternion();
      this.headingAngle = 0;
      this.headingTarget = 0;

      try {
        this.renderer = new THREE.WebGLRenderer({
          canvas,
          antialias: true,
          alpha: true,
          powerPreference: "high-performance",
        });
      } catch (error) {
        this.error = error;
        console.error("AttitudeScene renderer failed", error);
        return;
      }

      try {
        this.renderer.setClearColor(0x000000, 0);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        this.renderer.outputEncoding = THREE.sRGBEncoding;
        this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
        this.renderer.toneMappingExposure = 1.0;
        this.renderer.shadowMap.enabled = true;
        this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(36, 1, 0.1, 200);
        this.cameraTarget = new THREE.Vector3(0, 0.1, 0);

        this.buildLights();
        this.buildStage();
        this.buildBoard();

        this.updateCamera();
        this.bindControls();
        this.resize();
        this.available = true;
      } catch (error) {
        this.error = error;
        this.available = false;
        console.error("AttitudeScene build failed", error);
      }
    }

    // ---------------------------------------------------------------- lights
    buildLights() {
      const hemi = new THREE.HemisphereLight(0xbfd9ff, 0x101725, 0.66);
      this.scene.add(hemi);

      const key = new THREE.DirectionalLight(0xffffff, 1.65);
      key.position.set(10, 17, 12);
      key.castShadow = true;
      key.shadow.mapSize.set(1024, 1024);
      key.shadow.camera.left = -15;
      key.shadow.camera.right = 15;
      key.shadow.camera.top = 15;
      key.shadow.camera.bottom = -15;
      key.shadow.camera.near = 1;
      key.shadow.camera.far = 55;
      key.shadow.bias = -0.0006;
      key.shadow.normalBias = 0.02;
      this.scene.add(key);

      const rim = new THREE.DirectionalLight(0x57c8ff, 0.85);
      rim.position.set(-12, 8, -10);
      this.scene.add(rim);

      const warm = new THREE.DirectionalLight(0xffc98a, 0.28);
      warm.position.set(4, -6, -12);
      this.scene.add(warm);

      const under = new THREE.PointLight(0x46d8ff, 0.45, 30, 2);
      under.position.set(0, -3.2, 5);
      this.scene.add(under);
      this.underLight = under;
    }

    // ---------------------------------------------------------------- stage
    buildStage() {
      const shadow = new THREE.Mesh(
        new THREE.PlaneGeometry(60, 60),
        new THREE.ShadowMaterial({ color: 0x000000, opacity: 0.3 })
      );
      shadow.rotation.x = -Math.PI / 2;
      shadow.position.y = -3.62;
      shadow.receiveShadow = true;
      this.scene.add(shadow);

      const grid = new THREE.GridHelper(36, 36, 0x2f5a7a, 0x172b40);
      grid.position.y = -3.6;
      grid.material.transparent = true;
      grid.material.opacity = 0.34;
      grid.material.depthWrite = false;
      this.scene.add(grid);

      const ringMaterial = new THREE.MeshBasicMaterial({
        color: 0x46d8ff,
        transparent: true,
        opacity: 0.34,
        side: THREE.DoubleSide,
        depthWrite: false,
        toneMapped: false,
      });
      const ring = new THREE.Mesh(new THREE.RingGeometry(5.0, 5.04, 144), ringMaterial);
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = -3.56;
      this.scene.add(ring);

      const faintRing = new THREE.Mesh(
        new THREE.RingGeometry(6.0, 6.03, 144),
        new THREE.MeshBasicMaterial({
          color: 0x46d8ff,
          transparent: true,
          opacity: 0.1,
          side: THREE.DoubleSide,
          depthWrite: false,
          toneMapped: false,
        })
      );
      faintRing.rotation.x = -Math.PI / 2;
      faintRing.position.y = -3.56;
      this.scene.add(faintRing);

      // Tick marks every 15° on the fixed base ring.
      const tickMaterial = new THREE.MeshBasicMaterial({
        color: 0x7ad7ef,
        transparent: true,
        opacity: 0.36,
        toneMapped: false,
      });
      const tickGeometry = new THREE.BoxGeometry(0.035, 0.02, 0.42);
      for (let index = 0; index < 24; index += 1) {
        const angle = (index * 15) * DEG;
        const major = index % 6 === 0;
        const tick = new THREE.Mesh(tickGeometry, tickMaterial);
        const radius = 5.3;
        tick.position.set(Math.cos(angle) * radius, -3.55, -Math.sin(angle) * radius);
        tick.rotation.y = angle;
        tick.scale.z = major ? 1.7 : 0.8;
        tick.scale.x = major ? 1.5 : 1;
        this.scene.add(tick);
      }

      // Heading pointer: rotates around the fixed ring with yaw only.
      this.headingGroup = new THREE.Group();
      this.headingGroup.position.y = -3.48;
      // The only motion direction arrow is the upper-left MOTION HUD.
      this.headingGroup.visible = false;
      this.scene.add(this.headingGroup);

      const pointerMaterial = new THREE.MeshBasicMaterial({
        color: 0xffc45a,
        transparent: true,
        opacity: 0.95,
        toneMapped: false,
      });
      const pointer = new THREE.Mesh(new THREE.ConeGeometry(0.2, 0.62, 4), pointerMaterial);
      pointer.rotation.z = Math.PI / 2;
      pointer.position.set(5.62, 0, 0);
      this.headingGroup.add(pointer);

      const pointerLine = new THREE.Mesh(
        new THREE.BoxGeometry(1.1, 0.025, 0.045),
        new THREE.MeshBasicMaterial({
          color: 0xffc45a,
          transparent: true,
          opacity: 0.55,
          toneMapped: false,
        })
      );
      pointerLine.position.set(5.02, 0, 0);
      this.headingGroup.add(pointerLine);
    }

    // ---------------------------------------------------------------- board
    buildBoard() {
      this.board = new THREE.Group();
      this.scene.add(this.board);

      const pcbMaterial = new THREE.MeshStandardMaterial({
        color: 0x0b2a25,
        roughness: 0.58,
        metalness: 0.32,
      });
      const pcbShape = roundedRectShape(8.5, 5.6, 0.22);
      const pcbGeometry = new THREE.ExtrudeGeometry(pcbShape, {
        depth: 0.16,
        bevelEnabled: true,
        bevelSize: 0.025,
        bevelThickness: 0.02,
        bevelSegments: 2,
        curveSegments: 10,
      });
      pcbGeometry.translate(0, 0, -0.08);
      const pcb = new THREE.Mesh(pcbGeometry, pcbMaterial);
      pcb.castShadow = true;
      pcb.receiveShadow = true;
      this.board.add(pcb);

      const edge = new THREE.LineSegments(
        new THREE.EdgesGeometry(pcbGeometry, 32),
        new THREE.LineBasicMaterial({
          color: 0x2e7b70,
          transparent: true,
          opacity: 0.32,
        })
      );
      this.board.add(edge);

      // Top view of the real Quectel Pi M2 (OSM610ZAP V1.2), supplied by the user.
      // The PNG is already alpha-matted; the opaque PCB slab underneath gives it
      // thickness and a soft contact shadow.
      const topMaterial = new THREE.MeshBasicMaterial({
        color: 0x0b2a25,
        transparent: true,
        depthWrite: false,
        toneMapped: false,
      });
      const top = new THREE.Mesh(new THREE.PlaneGeometry(8.46, 5.56), topMaterial);
      top.position.z = 0.128;
      this.board.add(top);

      new THREE.TextureLoader().load(
        "/assets/m2-board-top.png",
        (texture) => {
          texture.encoding = THREE.sRGBEncoding;
          texture.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
          topMaterial.map = texture;
          topMaterial.color.set(0xffffff);
          topMaterial.needsUpdate = true;
        },
        undefined,
        () => {
          // Keep the dark-green slab visible if the photo cannot be loaded.
          topMaterial.color.set(0x0b2a25);
        }
      );

      // Underside of the same board. The photo is taken from below, so the
      // plane is turned to face down; it becomes visible when the board rolls
      // far enough to expose its bottom.
      const bottomMaterial = new THREE.MeshBasicMaterial({
        color: 0x0b2a25,
        transparent: true,
        depthWrite: false,
        toneMapped: false,
      });
      const bottom = new THREE.Mesh(new THREE.PlaneGeometry(8.46, 5.56), bottomMaterial);
      bottom.position.z = -0.128;
      bottom.rotation.y = Math.PI;
      this.board.add(bottom);

      new THREE.TextureLoader().load(
        "/assets/m2-board-bottom.png",
        (texture) => {
          texture.encoding = THREE.sRGBEncoding;
          texture.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
          bottomMaterial.map = texture;
          bottomMaterial.color.set(0xffffff);
          bottomMaterial.needsUpdate = true;
        },
        undefined,
        () => {
          bottomMaterial.color.set(0x0b2a25);
        }
      );


    }

    buildAxisTriad() {
      const originX = -3.85;
      const originY = -1.45;
      const length = 0.95;

      const makeAxis = (direction, color, label) => {
        const group = new THREE.Group();
        const shaft = new THREE.Mesh(
          new THREE.CylinderGeometry(0.022, 0.022, length * 0.72, 6),
          new THREE.MeshBasicMaterial({ color, toneMapped: false })
        );
        shaft.position.y = length * 0.36;
        group.add(shaft);
        const tip = new THREE.Mesh(
          new THREE.ConeGeometry(0.07, 0.22, 8),
          new THREE.MeshBasicMaterial({ color, toneMapped: false })
        );
        tip.position.y = length * 0.83;
        group.add(tip);
        const sprite = textSprite(label, color, 0.42);
        sprite.position.set(0, length + 0.15, 0);
        group.add(sprite);
        group.position.set(originX, originY, 0.2);
        group.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction);
        this.board.add(group);
      };

      makeAxis(new THREE.Vector3(1, 0, 0), "#ff6b81", "X");
      makeAxis(new THREE.Vector3(0, 1, 0), "#7ee787", "Y");
      makeAxis(new THREE.Vector3(0, 0, 1), "#5b8cff", "Z");
    }

    // ---------------------------------------------------------------- camera
    updateCamera() {
      const sinPhi = Math.sin(this.phi);
      const x = this.radius * sinPhi * Math.sin(this.theta);
      const y = this.radius * Math.cos(this.phi);
      const z = this.radius * sinPhi * Math.cos(this.theta);
      this.camera.position.set(x, y, z).add(this.cameraTarget);
      this.camera.lookAt(this.cameraTarget);
    }

    bindControls() {
      const canvas = this.canvas;

      const onPointerDown = (event) => {
        canvas.setPointerCapture(event.pointerId);
        this.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
        if (this.pointers.size === 2) {
          this.lastPointerDistance = this.pointerDistance();
        }
      };

      const onPointerMove = (event) => {
        const previous = this.pointers.get(event.pointerId);
        if (!previous) return;
        const dx = event.clientX - previous.x;
        const dy = event.clientY - previous.y;
        previous.x = event.clientX;
        previous.y = event.clientY;

        if (this.pointers.size === 1) {
          this.thetaTarget -= dx * 0.006;
          this.phiTarget = clamp(this.phiTarget - dy * 0.005, 0.25, 1.42);
        } else if (this.pointers.size === 2) {
          const distance = this.pointerDistance();
          if (this.lastPointerDistance > 0 && distance > 0) {
            this.radiusTarget = clamp(
              this.radiusTarget * (this.lastPointerDistance / distance),
              13,
              38
            );
          }
          this.lastPointerDistance = distance;
        }
      };

      const onPointerUp = (event) => {
        this.pointers.delete(event.pointerId);
        if (this.pointers.size < 2) this.lastPointerDistance = 0;
      };

      canvas.addEventListener("pointerdown", onPointerDown);
      canvas.addEventListener("pointermove", onPointerMove);
      canvas.addEventListener("pointerup", onPointerUp);
      canvas.addEventListener("pointercancel", onPointerUp);

      canvas.addEventListener(
        "wheel",
        (event) => {
          event.preventDefault();
          const scale = Math.exp(event.deltaY * 0.0012);
          this.radiusTarget = clamp(this.radiusTarget * scale, 13, 38);
        },
        { passive: false }
      );

      canvas.addEventListener("dblclick", () => this.resetCamera());
    }

    pointerDistance() {
      const values = Array.from(this.pointers.values());
      if (values.length < 2) return 0;
      return Math.hypot(values[0].x - values[1].x, values[0].y - values[1].y);
    }

    resetCamera() {
      this.thetaTarget = 0.0;
      this.phiTarget = 0.14;
      this.radiusTarget = 14.0;
    }

    // ---------------------------------------------------------------- api
    setAttitude(quaternion, yawDegrees) {
      this.targetQuaternion.set(quaternion[1], quaternion[2], quaternion[3], quaternion[0]);
      this.headingTarget = Number(yawDegrees) * DEG;
    }

    setOrientation(quaternion, yawDegrees) {
      this.targetQuaternion.copy(quaternion);
      this.headingTarget = Number(yawDegrees) * DEG;
    }

    resize() {
      if (!this.available) return;
      const rect = this.canvas.getBoundingClientRect();
      this.width = Math.max(1, rect.width);
      this.height = Math.max(1, rect.height);
      this.renderer.setSize(this.width, this.height, false);
      this.camera.aspect = this.width / this.height;
      this.camera.updateProjectionMatrix();
      this.radiusTarget = clamp(this.radiusTarget, 13, 38);
    }

    render(dt) {
      if (!this.available) return;

      const ease = 1 - Math.exp(-Math.max(0.001, dt) * 12);
      this.theta += (this.thetaTarget - this.theta) * ease;
      this.phi += (this.phiTarget - this.phi) * ease;
      this.radius += (this.radiusTarget - this.radius) * ease;
      this.updateCamera();

      // Quaternion in physics frame (Z up) -> three.js frame (Y up).
      this.board.quaternion.copy(C_YAW_TO_THREE).multiply(this.targetQuaternion);
      this.board.position.set(0, 0, 0);

      let headingDelta = this.headingTarget - this.headingAngle;
      while (headingDelta > Math.PI) headingDelta -= Math.PI * 2;
      while (headingDelta < -Math.PI) headingDelta += Math.PI * 2;
      this.headingAngle += headingDelta * ease;
      this.headingGroup.rotation.y = this.headingAngle;


      this.renderer.render(this.scene, this.camera);
    }
  }

  window.AttitudeScene = AttitudeScene;
})();
