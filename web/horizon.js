/* Full-stage artificial horizon.
 * Draws a classic attitude indicator plus a yaw tape, using the smoothed
 * Euler angles computed by app.js. No external assets. */
(function () {
  "use strict";

  const DEG = Math.PI / 180;

  function clamp(value, low, high) {
    return value < low ? low : value > high ? high : value;
  }

  function wrap360(value) {
    return ((value % 360) + 360) % 360;
  }

  class Horizon {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.width = 1;
      this.height = 1;
      this.dpr = 1;
      this.resize();
    }

    resize() {
      const rect = this.canvas.getBoundingClientRect();
      this.width = Math.max(1, rect.width);
      this.height = Math.max(1, rect.height);
      this.dpr = Math.min(window.devicePixelRatio || 1, 2);
      this.canvas.width = Math.round(this.width * this.dpr);
      this.canvas.height = Math.round(this.height * this.dpr);
      this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    }

    draw(state) {
      const ctx = this.ctx;
      const w = this.width;
      const h = this.height;
      if (w < 10 || h < 10) return;

      const roll = Number(state.roll) || 0;
      const pitch = Number(state.pitch) || 0;
      const yaw = Number(state.yaw) || 0;

      ctx.clearRect(0, 0, w, h);

      // Background wash, consistent with the 3D stage.
      const bg = ctx.createRadialGradient(w * 0.5, h * 0.44, 10, w * 0.5, h * 0.5, Math.max(w, h) * 0.72);
      bg.addColorStop(0, "#13263f");
      bg.addColorStop(0.52, "#0a1424");
      bg.addColorStop(1, "#060a12");
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, w, h);

      const topReserve = 44;
      const bottomReserve = 30;
      const radius = Math.min((w - 44) * 0.5, (h - topReserve - bottomReserve) * 0.5);
      if (radius < 40) return;
      const cx = w * 0.5;
      const cy = topReserve + (h - topReserve - bottomReserve) * 0.5;
      const ppd = radius / 62; // pixels per degree of pitch

      this.drawBall(ctx, cx, cy, radius, roll, pitch, ppd);
      this.drawBezel(ctx, cx, cy, radius, roll);
      this.drawAircraft(ctx, cx, cy, radius);
      this.drawYawTape(ctx, cx, cy, radius, yaw);

      // Corner labels
      ctx.font = '10px "Cascadia Code", Consolas, monospace';
      ctx.textBaseline = "middle";
      ctx.fillStyle = "rgba(159,177,201,0.72)";
      ctx.textAlign = "left";
      ctx.fillText(`ROLL ${roll >= 0 ? "+" : ""}${roll.toFixed(1)}°`, 16, h - 16);
      ctx.textAlign = "right";
      ctx.fillText(`PITCH ${pitch >= 0 ? "+" : ""}${pitch.toFixed(1)}°`, w - 16, h - 16);

      if (!state.connected) {
        ctx.fillStyle = "rgba(255,107,129,0.9)";
        ctx.font = '600 10px "Segoe UI", sans-serif';
        ctx.textAlign = "center";
        ctx.fillText("NO SENSOR DATA", cx, cy + radius + 20);
      }
    }

    drawBall(ctx, cx, cy, radius, roll, pitch, ppd) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.clip();

      ctx.translate(cx, cy);
      ctx.rotate(-roll * DEG);
      ctx.translate(0, pitch * ppd);

      const span = radius * 3;

      // Sky
      const sky = ctx.createLinearGradient(0, -span, 0, 0);
      sky.addColorStop(0, "#0c3350");
      sky.addColorStop(0.62, "#19587c");
      sky.addColorStop(1, "#2b7da0");
      ctx.fillStyle = sky;
      ctx.fillRect(-span, -span, span * 2, span);

      // Ground
      const ground = ctx.createLinearGradient(0, 0, 0, span);
      ground.addColorStop(0, "#8b6034");
      ground.addColorStop(0.55, "#573a20");
      ground.addColorStop(1, "#24170d");
      ctx.fillStyle = ground;
      ctx.fillRect(-span, 0, span * 2, span);

      // Horizon line
      ctx.strokeStyle = "rgba(255,255,255,0.92)";
      ctx.lineWidth = Math.max(1.4, radius * 0.008);
      ctx.beginPath();
      ctx.moveTo(-span, 0);
      ctx.lineTo(span, 0);
      ctx.stroke();

      // Pitch ladder
      ctx.font = '10px "Cascadia Code", Consolas, monospace';
      ctx.textBaseline = "middle";
      ctx.textAlign = "center";

      for (let angle = -80; angle <= 80; angle += 5) {
        if (angle === 0) continue;
        const y = -angle * ppd;
        if (Math.abs(y) > radius * 1.12) continue;
        const major = angle % 10 === 0;
        const half = (major ? radius * 0.30 : radius * 0.15) * (angle > 0 ? 1 : 1);
        ctx.strokeStyle = major ? "rgba(233,244,255,0.78)" : "rgba(233,244,255,0.32)";
        ctx.lineWidth = major ? 1.25 : 1;
        ctx.beginPath();
        ctx.moveTo(-half, y);
        ctx.lineTo(half, y);
        ctx.stroke();

        if (major && angle !== 0) {
          ctx.fillStyle = "rgba(233,244,255,0.82)";
          const label = angle < 0 ? `-${Math.abs(angle)}` : `${angle}`;
          ctx.textAlign = "right";
          ctx.fillText(label, -half - 6, y);
          ctx.textAlign = "left";
          ctx.fillText(label, half + 6, y);
        }
      }

      // Subtle cardinal-ish ticks around the horizon
      ctx.strokeStyle = "rgba(255,255,255,0.18)";
      ctx.lineWidth = 1;
      for (let angle = -60; angle <= 60; angle += 20) {
        if (angle === 0) continue;
        const y = -angle * ppd;
        ctx.beginPath();
        ctx.moveTo(-radius * 0.5, y);
        ctx.lineTo(-radius * 0.44, y);
        ctx.moveTo(radius * 0.44, y);
        ctx.lineTo(radius * 0.5, y);
        ctx.stroke();
      }

      ctx.restore();

      // Inner vignette on the ball
      const vignette = ctx.createRadialGradient(cx, cy, radius * 0.58, cx, cy, radius);
      vignette.addColorStop(0, "rgba(0,0,0,0)");
      vignette.addColorStop(1, "rgba(0,0,0,0.36)");
      ctx.fillStyle = vignette;
      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.fill();
    }

    drawBezel(ctx, cx, cy, radius, roll) {
      ctx.save();

      // Outer bezel
      const ring = ctx.createLinearGradient(cx - radius, cy - radius, cx + radius, cy + radius);
      ring.addColorStop(0, "rgba(120,198,235,0.55)");
      ring.addColorStop(0.5, "rgba(53,92,126,0.35)");
      ring.addColorStop(1, "rgba(120,198,235,0.24)");
      ctx.strokeStyle = ring;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.stroke();

      ctx.strokeStyle = "rgba(70,216,255,0.13)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(cx, cy, radius + 6, 0, Math.PI * 2);
      ctx.stroke();

      // Fixed roll scale and ticks
      ctx.strokeStyle = "rgba(220,236,255,0.62)";
      ctx.fillStyle = "rgba(159,177,201,0.72)";
      ctx.font = '9px "Cascadia Code", Consolas, monospace';
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";

      for (let deg = -60; deg <= 60; deg += 10) {
        const angle = deg * DEG - Math.PI / 2;
        const major = deg % 30 === 0;
        const inner = radius + (major ? 2 : 5);
        const outer = radius + (major ? 12 : 9);
        ctx.lineWidth = major ? 1.4 : 1;
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(angle) * inner, cy + Math.sin(angle) * inner);
        ctx.lineTo(cx + Math.cos(angle) * outer, cy + Math.sin(angle) * outer);
        ctx.stroke();

        if (major && deg !== 0) {
          const label = Math.abs(deg).toString();
          ctx.fillText(label, cx + Math.cos(angle) * (radius + 22), cy + Math.sin(angle) * (radius + 22));
        }
      }

      // Bank pointer (fixed at the top), plus a rotating index along the scale.
      ctx.fillStyle = "rgba(70,216,255,0.95)";
      ctx.beginPath();
      ctx.moveTo(cx, cy - radius - 1);
      ctx.lineTo(cx - 5, cy - radius - 11);
      ctx.lineTo(cx + 5, cy - radius - 11);
      ctx.closePath();
      ctx.fill();

      const bank = -roll * DEG - Math.PI / 2;
      ctx.strokeStyle = "rgba(255,184,107,0.9)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(bank) * (radius + 2), cy + Math.sin(bank) * (radius + 2));
      ctx.lineTo(cx + Math.cos(bank) * (radius + 8), cy + Math.sin(bank) * (radius + 8));
      ctx.stroke();

      ctx.restore();
    }

    drawAircraft(ctx, cx, cy, radius) {
      ctx.save();
      ctx.translate(cx, cy);

      const wing = radius * 0.42;
      const gap = radius * 0.055;

      ctx.strokeStyle = "rgba(255,196,80,0.96)";
      ctx.lineWidth = Math.max(2, radius * 0.015);
      ctx.lineCap = "round";

      // Wings, split at the centre
      ctx.beginPath();
      ctx.moveTo(-wing, 0);
      ctx.lineTo(-gap, 0);
      ctx.moveTo(gap, 0);
      ctx.lineTo(wing, 0);
      ctx.stroke();

      // Wing tips
      ctx.lineWidth = Math.max(1.6, radius * 0.012);
      ctx.beginPath();
      ctx.moveTo(-wing, 0);
      ctx.lineTo(-wing, radius * 0.05);
      ctx.moveTo(wing, 0);
      ctx.lineTo(wing, radius * 0.05);
      ctx.stroke();

      // Centre dot
      ctx.fillStyle = "rgba(255,196,80,1)";
      ctx.beginPath();
      ctx.arc(0, 0, Math.max(2.2, radius * 0.015), 0, Math.PI * 2);
      ctx.fill();

      // Nose chevron
      ctx.strokeStyle = "rgba(255,255,255,0.7)";
      ctx.lineWidth = 1.3;
      ctx.beginPath();
      ctx.moveTo(-radius * 0.06, -radius * 0.06);
      ctx.lineTo(0, -radius * 0.085);
      ctx.lineTo(radius * 0.06, -radius * 0.06);
      ctx.stroke();

      ctx.restore();
    }

    drawYawTape(ctx, cx, cy, radius, yaw) {
      const tapeWidth = Math.min(radius * 1.7, this.width - 40);
      const x0 = cx - tapeWidth / 2;
      const y = Math.max(4, cy - radius - 31);
      const height = 18;
      const yawWrapped = wrap360(yaw);
      const pixelsPerDegree = tapeWidth / 110;

      ctx.save();
      ctx.beginPath();
      ctx.rect(x0, y, tapeWidth, height + 10);
      ctx.clip();

      ctx.fillStyle = "rgba(6,12,22,0.74)";
      ctx.fillRect(x0, y, tapeWidth, height);
      ctx.strokeStyle = "rgba(70,216,255,0.14)";
      ctx.lineWidth = 1;
      ctx.strokeRect(x0, y, tapeWidth, height);

      const baseX = cx;
      const start = Math.floor((yawWrapped - 60) / 5) * 5;
      const end = Math.ceil((yawWrapped + 60) / 5) * 5;

      ctx.font = '8px "Cascadia Code", Consolas, monospace';
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";

      for (let value = start; value <= end; value += 5) {
        let delta = value - yawWrapped;
        if (delta > 180) delta -= 360;
        if (delta < -180) delta += 360;
        const x = baseX + delta * pixelsPerDegree;
        if (x < x0 || x > x0 + tapeWidth) continue;

        const major = value % 30 === 0;
        ctx.strokeStyle = major ? "rgba(220,236,255,0.65)" : "rgba(220,236,255,0.2)";
        ctx.beginPath();
        ctx.moveTo(x, y + height - (major ? 9 : 4));
        ctx.lineTo(x, y + height);
        ctx.stroke();

        if (major) {
          const label = String(wrap360(value)).padStart(3, "0");
          ctx.fillStyle = "rgba(220,236,255,0.8)";
          ctx.fillText(label, x, y + 6);
        }
      }

      // Fixed centre index
      ctx.fillStyle = "rgba(255,196,80,0.95)";
      ctx.beginPath();
      ctx.moveTo(cx, y + height + 1);
      ctx.lineTo(cx - 4, y + height + 7);
      ctx.lineTo(cx + 4, y + height + 7);
      ctx.closePath();
      ctx.fill();

      ctx.restore();
    }
  }

  window.Horizon = Horizon;
})();
