/* UI glue: polling, smoothing, controls and render loop. */
(function () {
  "use strict";

  const DEG = Math.PI / 180;

  function byId(id) {
    return document.getElementById(id);
  }

  const dom = {
    statusPill: byId("status-pill"),
    statusText: byId("status-text"),
    rateValue: byId("rate-value"),
    i2cValue: byId("i2c-value"),
    clock: byId("clock"),
    stage: byId("stage"),
    sceneCanvas: byId("scene-canvas"),
    horizonCanvas: byId("horizon-canvas"),
    stageYaw: byId("stage-yaw"),
    stageTilt: byId("stage-tilt"),
    motionHudCanvas: byId("motion-hud-canvas"),
    stageFps: byId("stage-fps"),
    stageError: byId("stage-error"),
    stageHint: byId("stage-hint"),
    viewSwitch: byId("view-switch"),
    rollValue: byId("roll-value"),
    pitchValue: byId("pitch-value"),
    yawValue: byId("yaw-value"),
    rollFill: byId("roll-fill"),
    pitchFill: byId("pitch-fill"),
    yawFill: byId("yaw-fill"),
    accXFill: byId("acc-x-fill"),
    accYFill: byId("acc-y-fill"),
    accZFill: byId("acc-z-fill"),
    gyroXFill: byId("gyro-x-fill"),
    gyroYFill: byId("gyro-y-fill"),
    gyroZFill: byId("gyro-z-fill"),
    accXValue: byId("acc-x-value"),
    accYValue: byId("acc-y-value"),
    accZValue: byId("acc-z-value"),
    gyroXValue: byId("gyro-x-value"),
    gyroYValue: byId("gyro-y-value"),
    gyroZValue: byId("gyro-z-value"),
    tempTag: byId("temp-tag"),
    ctrlState: byId("ctrl-state"),
    controlNote: byId("control-note"),
    hwTag: byId("hw-tag"),
    hwBus: byId("hw-bus"),
    hwAddr: byId("hw-addr"),
    hwRate: byId("hw-rate"),
    btnCalibrate: byId("btn-calibrate"),
    btnTare: byId("btn-tare"),
    btnPause: byId("btn-pause"),
    btnFullscreen: byId("btn-fullscreen"),
    pauseLabel: byId("pause-label"),
    pauseSub: byId("pause-sub"),
    accessUrl: byId("access-url"),
    toast: byId("toast"),
    chartCanvas: byId("chart-canvas"),
  };

  const params = new URLSearchParams(window.location.search);
  const initialView = params.get("view") === "horizon" ? "horizon" : "scene";

  const state = {
    mode: "hardware",
    serverState: "connecting",
    connected: false,
    offline: false,
    paused: false,
    calibrating: false,
    busy: false,
    seq: -1,
    latest: null,
    latestEuler: { roll: 0, pitch: 0, yaw: 0 },
    status: null,
    view: initialView,
    needSnap: true,
    webglFailed: false,
    targetQ: new THREE.Quaternion(),
    currentQ: new THREE.Quaternion(),
    lastSampleWall: 0,
    pollTimer: null,
    statusTimer: null,
    toastTimer: null,
    errorsLogged: 0,
  };

  let scene = null;
  let horizon = null;
  let chart = null;

  // ---------------------------------------------------------------- utilities
  function clamp(value, low, high) {
    return value < low ? low : value > high ? high : value;
  }

  function wrap360(value) {
    return ((value % 360) + 360) % 360;
  }

  function formatAngle(value, digits) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "--";
    return `${number >= 0 ? "+" : ""}${number.toFixed(digits)}`;
  }

  function formatSigned(value, digits) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "--";
    return `${number >= 0 ? "+" : ""}${number.toFixed(digits)}`;
  }

  function setText(element, text) {
    if (element && element.textContent !== text) element.textContent = text;
  }

  function setFill(element, value, fullScale) {
    if (!element) return;
    const number = Number(value) || 0;
    const percent = clamp(Math.abs(number) / fullScale, 0, 1) * 50;
    if (number >= 0) {
      element.style.left = "50%";
      element.style.width = `${percent}%`;
    } else {
      element.style.left = `${50 - percent}%`;
      element.style.width = `${percent}%`;
    }
  }

  function setCompassFill(element, value) {
    if (!element) return;
    const percent = clamp(Number(value) / 360, 0, 1) * 100;
    element.style.left = "0%";
    element.style.width = `${percent}%`;
  }

  function quatEuler(quaternion) {
    const x = quaternion.x;
    const y = quaternion.y;
    const z = quaternion.z;
    const w = quaternion.w;
    const roll = Math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y));
    const sinPitch = clamp(2 * (w * y - z * x), -1, 1);
    const pitch = Math.asin(sinPitch);
    const yaw = Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z));
    return { roll: roll / DEG, pitch: pitch / DEG, yaw: yaw / DEG };
  }

  function showToast(message, isError) {
    if (!dom.toast) return;
    dom.toast.textContent = message;
    dom.toast.classList.toggle("error", Boolean(isError));
    dom.toast.classList.add("show");
    window.clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(() => {
      dom.toast.classList.remove("show");
    }, isError ? 4200 : 2800);
  }

  function logClient(payload) {
    if (state.errorsLogged >= 8) return;
    state.errorsLogged += 1;
    try {
      fetch("/api/client_log", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(() => {});
    } catch (error) {
      /* ignore */
    }
  }

  // ---------------------------------------------------------------- status ui
  function setStatusPill(label, className) {
    setText(dom.statusText, label);
    dom.statusPill.className = `status-pill ${className || ""}`.trim();
  }

  function setStageError(message, kind) {
    if (!dom.stageError) return;
    if (!message) {
      dom.stageError.hidden = true;
      dom.stageError.textContent = "";
      dom.stageError.classList.remove("is-paused");
      return;
    }
    dom.stageError.hidden = false;
    dom.stageError.textContent = message;
    dom.stageError.classList.toggle("is-paused", kind === "paused");
  }

  function updateStatusUi() {
    const status = state.status;
    const mode = status ? status.mode : state.mode;
    const serverState = status ? status.state : state.serverState;
    const connected = status ? status.connected : state.connected;
    const paused = status ? status.paused : state.paused;

    state.mode = mode;
    state.serverState = serverState;
    state.connected = connected;
    state.paused = paused;

    if (state.offline) {
      setStatusPill("Offline", "is-offline");
    } else if (state.calibrating || serverState === "calibrating") {
      setStatusPill("Calibrating", "is-calibrating");
    } else if (paused) {
      setStatusPill("Paused", "is-paused");
    } else if (!connected || serverState === "error") {
      setStatusPill("Sensor lost", "is-warn");
    } else if (connected) {
      setStatusPill("Live", "is-live");
    } else {
      setStatusPill("Connecting", "");
    }

    dom.ctrlState.textContent = state.calibrating
      ? "Calibrating"
      : paused
        ? "Paused"
        : state.offline
          ? "Offline"
          : connected
            ? "Live"
            : "Waiting";

    if (dom.pauseLabel) dom.pauseLabel.textContent = paused ? "Resume" : "Pause";
    if (dom.pauseSub) dom.pauseSub.textContent = paused ? "Continue stream" : "Freeze stream";

    const source = status && status.source ? status.source : {};
    if (source.path) {
      setText(dom.i2cValue, `${source.path.replace("/dev/", "")} · ${source.address || "?"}`);
      setText(dom.hwTag, status && status.connected ? source.chip || "MPU6050" : "not found");
      setText(dom.hwBus, source.path.replace("/dev/", ""));
      setText(dom.hwAddr, source.address || "--");
    } else {
      setText(dom.i2cValue, "detecting");
      setText(dom.hwTag, "waiting");
      setText(dom.hwBus, "--");
      setText(dom.hwAddr, "--");
    }
    setText(dom.hwRate, `${(status && status.sample_rate_hz) || 100} Hz`);

    const rate = state.latest ? state.latest.rate_hz : status ? status.rate_hz : 0;
    setText(dom.rateValue, rate ? Number(rate).toFixed(0) : "--");

    if (status && status.net && status.net.urls && status.net.urls.length) {
      const urls = status.net.urls;
      const preferred =
        urls.find((entry) => /wl|wlan|eth|enp|eno/.test(entry.iface || "")) || urls[0];
      setText(dom.accessUrl, preferred.url.replace(/\/$/, ""));
    } else {
      setText(dom.accessUrl, window.location.origin);
    }

    updateControlNote();
    updateButtons();
    updateStageMessage();
  }

  function updateControlNote() {
    if (!dom.controlNote) return;
    dom.controlNote.classList.remove("ok", "warn", "error");
    const status = state.status || {};
    const calibration = status.calibration || {};
    const mode = status.mode || state.mode;

    if (state.offline) {
      dom.controlNote.textContent = "Server unreachable — retrying the connection.";
      dom.controlNote.classList.add("error");
      return;
    }
    if (mode === "hardware" && (!status.connected || status.state === "error")) {
      dom.controlNote.textContent = status.error || status.message || "MPU6050 is not responding. Check the wiring.";
      dom.controlNote.classList.add("error");
      return;
    }
    if (state.paused) {
      dom.controlNote.textContent = "Stream paused. Resume before calibrating or resetting yaw.";
      dom.controlNote.classList.add("warn");
      return;
    }
    if (calibration.bias_dps && calibration.bias_dps.length === 3) {
      const bias = calibration.bias_dps.map((value) => Number(value).toFixed(2)).join(" / ");
      if (calibration.ok) {
        dom.controlNote.textContent = `Gyro bias ${bias} °/s · calibrated`;
        dom.controlNote.classList.add("ok");
      } else {
        dom.controlNote.textContent = `${calibration.message || "Calibration uncertain"} · previous bias kept`;
        dom.controlNote.classList.add("warn");
      }
      return;
    }
    dom.controlNote.textContent = "Gyro bias: waiting for calibration";
  }

  function updateButtons() {
    const offline = state.offline;
    const paused = state.paused;
    const noSensor = !state.connected;
    const busy = state.busy || state.calibrating;

    dom.btnCalibrate.disabled = offline || paused || noSensor || busy;
    dom.btnTare.disabled = offline || paused || noSensor || busy;
    dom.btnPause.disabled = offline;
  }

  function updateStageMessage() {
    if (state.webglFailed) {
      setStageError("WebGL is unavailable on this browser. The horizon view is still available.");
      return;
    }
    if (state.offline) {
      setStageError("Server unreachable — retrying the connection...");
      return;
    }
    const status = state.status;
    if (status && status.mode === "hardware" && !status.connected) {
      setStageError(status.error || status.message || "MPU6050 is not responding. Check the wiring.");
      return;
    }
    if (state.paused) {
      setStageError("Stream paused — orientation is frozen.", "paused");
      return;
    }
    setStageError(null);
  }

  // ---------------------------------------------------------------- networking
  async function fetchJson(url, options, timeoutMs) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs || 4000);
    try {
      const response = await fetch(url, { cache: "no-store", signal: controller.signal, ...options });
      const data = await response.json();
      if (!response.ok && (!data || data.ok !== false)) {
        throw new Error(`HTTP ${response.status}`);
      }
      return data;
    } finally {
      window.clearTimeout(timer);
    }
  }

  function setOffline(offline) {
    if (state.offline === offline) return;
    state.offline = offline;
    updateStatusUi();
  }

  function applyStatus(data) {
    if (!data || !data.ok) return;
    state.status = data;
    state.mode = data.mode;
    state.serverState = data.state;
    state.connected = Boolean(data.connected);
    state.paused = Boolean(data.paused);
    state.offline = false;
    updateStatusUi();
  }

  async function refreshStatus() {
    try {
      const data = await fetchJson("/api/status", {}, 4000);
      applyStatus(data);
    } catch (error) {
      setOffline(true);
    } finally {
      window.clearTimeout(state.statusTimer);
      state.statusTimer = window.setTimeout(refreshStatus, 5000);
    }
  }

  function applyAttitude(attitude) {
    if (!attitude) return;
    if (attitude.seq === state.seq) return;
    state.seq = attitude.seq;
    state.latest = attitude;
    state.latestEuler = attitude.euler || { roll: 0, pitch: 0, yaw: 0 };
    state.connected = Boolean(attitude.connected);
    state.paused = Boolean(attitude.paused);
    state.lastSampleWall = performance.now();
    setOffline(false);

    const q = attitude.q || [1, 0, 0, 0];
    state.targetQ.set(q[1], q[2], q[3], q[0]).normalize();
    if (state.needSnap) {
      state.currentQ.copy(state.targetQ);
      state.needSnap = false;
    }
    chart.push(attitude.t, state.latestEuler.roll, state.latestEuler.pitch, wrap360(state.latestEuler.yaw));
  }

  async function pollAttitude() {
    if (document.hidden) {
      state.pollTimer = window.setTimeout(pollAttitude, 500);
      return;
    }
    try {
      const data = await fetchJson("/api/attitude", {}, 3000);
      if (data && data.ok) {
        applyAttitude(data.attitude);
      } else {
        setOffline(true);
      }
    } catch (error) {
      setOffline(true);
    }
    const delay = state.offline ? 1100 : state.paused ? 150 : 33;
    state.pollTimer = window.setTimeout(pollAttitude, delay);
  }

  async function postJson(url, body) {
    const response = await fetch(url, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const data = await response.json().catch(() => ({ ok: false, error: `HTTP ${response.status}` }));
    return data;
  }

  // ---------------------------------------------------------------- actions
  async function calibrate() {
    if (state.busy || state.calibrating || state.paused) return;
    state.busy = true;
    state.calibrating = true;
    state.serverState = "calibrating";
    updateStatusUi();
    showToast("Keep the board still — calibrating the gyro bias (about 2 s).");
    try {
      const data = await postJson("/api/calibrate", {});
      if (data.status) applyStatus(data.status);
      if (data.ok && data.calibration) {
        if (data.calibration.ok) {
          showToast("Gyro bias calibrated.");
        } else {
          showToast(data.calibration.message || "Calibration was noisy — try again while still.", true);
        }
      } else if (!data.ok) {
        showToast(data.message || data.error || "Calibration failed.", true);
      }
    } catch (error) {
      showToast("Calibration request failed — check the connection.", true);
    } finally {
      state.busy = false;
      state.calibrating = false;
      updateStatusUi();
      refreshStatus();
    }
  }

  async function resetYaw() {
    if (state.busy || state.paused) return;
    state.busy = true;
    updateStatusUi();
    try {
      const data = await postJson("/api/tare", {});
      if (data.status) applyStatus(data.status);
      if (data.ok) {
        showToast("Yaw reference reset.");
      } else {
        showToast(data.message || "Yaw reset failed.", true);
      }
    } catch (error) {
      showToast("Yaw reset failed — check the connection.", true);
    } finally {
      state.busy = false;
      updateStatusUi();
      refreshStatus();
    }
  }

  async function togglePause() {
    if (state.offline) return;
    const next = !state.paused;
    try {
      const data = await postJson("/api/pause", { paused: next });
      if (data.status) applyStatus(data.status);
      if (data.ok) {
        showToast(next ? "Stream paused." : "Stream resumed.");
      } else {
        showToast(data.message || "Pause request failed.", true);
      }
    } catch (error) {
      showToast("Pause request failed — check the connection.", true);
    }
  }

  async function toggleFullscreen() {
    try {
      if (!document.fullscreenElement) {
        await document.documentElement.requestFullscreen();
      } else {
        await document.exitFullscreen();
      }
    } catch (error) {
      showToast("Fullscreen is not available in this browser.", true);
    }
  }

  // ---------------------------------------------------------------- view
  function setView(view, updateHistory) {
    if (view === "scene" && scene && !scene.available) {
      showToast("WebGL is unavailable — showing the horizon view.", true);
      view = "horizon";
    }
    state.view = view;
    const sceneActive = view === "scene";
    dom.stage.classList.toggle("horizon-view", !sceneActive);
    dom.sceneCanvas.hidden = !sceneActive;
    dom.horizonCanvas.hidden = sceneActive;
    Array.from(dom.viewSwitch.querySelectorAll("button")).forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
    dom.stageHint.textContent = sceneActive
      ? "Drag to orbit · double-click to reset"
      : "Artificial horizon · yaw tape";

    if (sceneActive) {
      if (scene) scene.resize();
    } else {
      if (horizon) horizon.resize();
    }

    if (updateHistory) {
      const url = new URL(window.location.href);
      if (view === "horizon") url.searchParams.set("view", "horizon");
      else url.searchParams.delete("view");
      window.history.replaceState({}, "", url);
    }
  }

  // ---------------------------------------------------------------- render
  let lastFrame = performance.now();
  let fpsFrames = 0;
  let fpsAt = performance.now();
  let readoutAt = 0;
  let chartAt = 0;
  let resizePending = false;

  function drawMotionHud(motion) {
    const canvas = dom.motionHudCanvas;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const width = canvas.width;
    const height = canvas.height;
    const cx = width * 0.5;
    const cy = height * 0.5;
    const radius = Math.min(width, height) * 0.4;

    ctx.clearRect(0, 0, width, height);
    ctx.strokeStyle = "rgba(105, 165, 215, 0.28)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(cx - radius * 0.1, cy);
    ctx.lineTo(cx + radius * 0.1, cy);
    ctx.moveTo(cx, cy - radius * 0.1);
    ctx.lineTo(cx, cy + radius * 0.1);
    ctx.stroke();

    for (let index = 0; index < 8; index += 1) {
      const angle = (index * Math.PI) / 4;
      const inner = radius * (index % 2 ? 0.9 : 0.86);
      const outer = radius * 0.96;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(angle) * inner, cy + Math.sin(angle) * inner);
      ctx.lineTo(cx + Math.cos(angle) * outer, cy + Math.sin(angle) * outer);
      ctx.stroke();
    }

    // Cardinal hints: screen-up is world +Y (the board's forward at startup).
    ctx.fillStyle = "rgba(120, 170, 215, 0.5)";
    ctx.font = "600 12px ui-monospace, Menlo, Consolas, monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("FWD", cx, 14);
    ctx.fillText("BACK", cx, height - 14);
    ctx.fillText("LEFT", 26, cy);
    ctx.fillText("RIGHT", width - 20, cy);

    const x = Number(motion && motion.x) || 0;
    // World +Y points toward the operator in this mounting (the sensor's Y axis
    // was flipped when it was re-fixed), so screen-up is -Y: use the raw sign.
    const y = Number(motion && motion.y) || 0;
    const speed = Math.hypot(x, y);
    ctx.font = "600 16px ui-monospace, Menlo, Consolas, monospace";
    ctx.textAlign = "center";

    if (speed < 0.012) {
      ctx.fillStyle = "rgba(120, 210, 240, 0.8)";
      ctx.beginPath();
      ctx.arc(cx, cy, 3.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "rgba(130, 175, 210, 0.55)";
      ctx.fillText("STILL", cx, cy + radius * 0.66);
      return;
    }

    // Snap the qualitative HUD to the dominant axis: a hand slide is never
    // perfectly axis-aligned, and a diagonal arrow reads as "wrong direction"
    // during a live demo.
    const horizontal = Math.abs(x) >= Math.abs(y) * 0.7;
    const direction = horizontal
      ? x >= 0
        ? "RIGHT"
        : "LEFT"
      : y >= 0
        ? "FWD"
        : "BACK";
    const angle = horizontal ? (x >= 0 ? 0 : Math.PI) : y >= 0 ? -Math.PI / 2 : Math.PI / 2;
    // Qualitative display: any detected movement gets a full-length arrow, so
    // the HUD reads as a direction indicator instead of a speed meter.
    const length = radius * 0.95;
    const endX = cx + Math.cos(angle) * length;
    const endY = cy + Math.sin(angle) * length;
    const head = 14;

    ctx.save();
    ctx.shadowColor = "rgba(255, 184, 77, 0.55)";
    ctx.shadowBlur = 10;
    ctx.strokeStyle = "#ffb84d";
    ctx.fillStyle = "#ffb84d";
    ctx.lineWidth = 5;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(angle) * 9, cy + Math.sin(angle) * 9);
    ctx.lineTo(endX, endY);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(endX, endY);
    ctx.lineTo(
      endX - Math.cos(angle - 0.46) * head,
      endY - Math.sin(angle - 0.46) * head
    );
    ctx.lineTo(
      endX - Math.cos(angle + 0.46) * head,
      endY - Math.sin(angle + 0.46) * head
    );
    ctx.closePath();
    ctx.fill();
    ctx.restore();

    ctx.fillStyle = "rgba(255, 205, 140, 0.9)";
    ctx.fillText(direction, cx, cy + radius * 0.66);
  }

  function updateReadout() {
    drawMotionHud(state.latest ? state.latest.motion : null);
    const euler = state.latestEuler || { roll: 0, pitch: 0, yaw: 0 };
    const yawCompass = wrap360(Number(euler.yaw) || 0);
    const tilt = Math.acos(
      clamp(
        Math.cos((Number(euler.roll) || 0) * DEG) * Math.cos((Number(euler.pitch) || 0) * DEG),
        -1,
        1
      )
    ) / DEG;

    setText(dom.rollValue, formatAngle(euler.roll, 1));
    setText(dom.pitchValue, formatAngle(euler.pitch, 1));
    setText(dom.yawValue, yawCompass.toFixed(1));
    setFill(dom.rollFill, euler.roll, 90);
    setFill(dom.pitchFill, euler.pitch, 90);
    setCompassFill(dom.yawFill, yawCompass);

    setText(dom.stageYaw, `${yawCompass.toFixed(1)}°`);
    setText(dom.stageTilt, `${Math.abs(tilt) < 0.05 ? "0.0" : tilt.toFixed(1)}°`);

    const attitude = state.latest;
    if (!attitude) return;

    const accel = attitude.accel || [0, 0, 0];
    const gyro = attitude.gyro || [0, 0, 0];
    const accelMax = 2;
    const gyroMax = Number((state.status && state.status.source && state.status.source.gyro_range_dps) || 500);

    setText(dom.accXValue, formatSigned(accel[0], 3));
    setText(dom.accYValue, formatSigned(accel[1], 3));
    setText(dom.accZValue, formatSigned(accel[2], 3));
    setFill(dom.accXFill, accel[0], accelMax);
    setFill(dom.accYFill, accel[1], accelMax);
    setFill(dom.accZFill, accel[2], accelMax);

    setText(dom.gyroXValue, formatSigned(gyro[0], 1));
    setText(dom.gyroYValue, formatSigned(gyro[1], 1));
    setText(dom.gyroZValue, formatSigned(gyro[2], 1));
    setFill(dom.gyroXFill, gyro[0], gyroMax);
    setFill(dom.gyroYFill, gyro[1], gyroMax);
    setFill(dom.gyroZFill, gyro[2], gyroMax);

    if (Number.isFinite(Number(attitude.temp_c))) {
      setText(dom.tempTag, `${Number(attitude.temp_c).toFixed(1)} °C`);
    }
  }

  function frame(now) {
    window.requestAnimationFrame(frame);
    const dt = Math.min(0.1, Math.max(0.001, (now - lastFrame) / 1000));
    lastFrame = now;

    const ease = 1 - Math.exp(-dt * 14);
    state.currentQ.slerp(state.targetQ, ease);

    if (state.view === "scene" && scene && scene.available) {
      scene.setOrientation(state.currentQ, state.latestEuler.yaw);
      scene.render(dt);
    } else if (state.view === "horizon" && horizon) {
      const visual = quatEuler(state.currentQ);
      // The service reports bank as Roll and nose-up as Pitch (the board is
      // held landscape). quatEuler returns the raw Madgwick X/Y labels, so
      // swap them here too or the horizon would lift instead of tilting.
      horizon.draw({
        roll: visual.pitch,
        pitch: visual.roll,
        yaw: Number(state.latestEuler.yaw) || 0,
        connected: state.connected && !state.offline,
      });
    }

    if (now - readoutAt > 66) {
      updateReadout();
      readoutAt = now;
    }
    if (now - chartAt > 100) {
      chart.draw();
      chartAt = now;
    }

    fpsFrames += 1;
    if (now - fpsAt > 1000) {
      setText(dom.stageFps, `${fpsFrames} fps`);
      fpsFrames = 0;
      fpsAt = now;
    }
  }

  function scheduleResize() {
    if (resizePending) return;
    resizePending = true;
    window.requestAnimationFrame(() => {
      resizePending = false;
      if (scene) scene.resize();
      if (horizon) horizon.resize();
      if (chart) chart.resize();
    });
  }

  function updateClock() {
    const now = new Date();
    setText(
      dom.clock,
      [now.getHours(), now.getMinutes(), now.getSeconds()]
        .map((value) => String(value).padStart(2, "0"))
        .join(":")
    );
  }

  // ---------------------------------------------------------------- init
  function init() {
    scene = new AttitudeScene(dom.sceneCanvas);
    horizon = new Horizon(dom.horizonCanvas);
    chart = new AttitudeChart(dom.chartCanvas);

    if (!scene.available) {
      state.webglFailed = true;
      showToast("WebGL is unavailable — showing the horizon view.", true);
      setStageError("WebGL is unavailable on this browser. The horizon view is still available.");
    }

    dom.viewSwitch.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-view]");
      if (button) setView(button.dataset.view, true);
    });
    dom.btnCalibrate.addEventListener("click", calibrate);
    dom.btnTare.addEventListener("click", resetYaw);
    dom.btnPause.addEventListener("click", togglePause);
    dom.btnFullscreen.addEventListener("click", toggleFullscreen);

    document.addEventListener("keydown", (event) => {
      if (event.repeat) return;
      const key = event.key.toLowerCase();
      if (key === "c") calibrate();
      else if (key === "r") resetYaw();
      else if (key === "f") toggleFullscreen();
      else if (key === "1") setView("scene", true);
      else if (key === "2") setView("horizon", true);
      else if (key === " ") {
        event.preventDefault();
        togglePause();
      }
    });

    window.addEventListener("resize", scheduleResize);
    if (window.ResizeObserver) {
      const observer = new ResizeObserver(scheduleResize);
      observer.observe(dom.stage);
      observer.observe(dom.chartCanvas);
    }

    window.addEventListener("error", (event) => {
      logClient({
        type: "error",
        message: event.message,
        source: event.filename,
        line: event.lineno,
        column: event.colno,
      });
    });
    window.addEventListener("unhandledrejection", (event) => {
      const reason = event.reason;
      logClient({ type: "rejection", message: String((reason && reason.message) || reason) });
    });

    setView(initialView, false);
    updateClock();
    window.setInterval(updateClock, 1000);
    updateStatusUi();
    refreshStatus();
    pollAttitude();
    window.requestAnimationFrame(frame);
  }

  init();
})();
