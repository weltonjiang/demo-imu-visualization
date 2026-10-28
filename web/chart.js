/* Scrolling attitude history: three stacked sparkline rows, each with its own
 * auto-scaled range so small tilts stay readable while a large yaw sweep still
 * fits. */
(function () {
  "use strict";

  const DEG = Math.PI / 180;

  function clamp(value, low, high) {
    return value < low ? low : value > high ? high : value;
  }

  function niceRange(maxAbs) {
    const steps = [30, 45, 60, 90, 120, 180, 360];
    const wanted = Math.max(12, maxAbs);
    for (const step of steps) {
      if (wanted <= step) return step;
    }
    return 360;
  }

  class AttitudeChart {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.points = [];
      this.windowSeconds = 20;
      this.width = 1;
      this.height = 1;
      this.dpr = 1;
      this.series = [
        { key: "roll", label: "R", color: "#7fa5ff" },
        { key: "pitch", label: "P", color: "#7ee787" },
        { key: "yaw", label: "Y", color: "#46d8ff" },
      ];
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

    push(t, roll, pitch, yaw) {
      const time = Number(t);
      if (!Number.isFinite(time)) return;
      this.points.push({
        t: time,
        roll: Number(roll) || 0,
        pitch: Number(pitch) || 0,
        yaw: Number(yaw) || 0,
      });
      const cutoff = time - this.windowSeconds - 2.5;
      while (this.points.length > 2 && this.points[0].t < cutoff) {
        this.points.shift();
      }
      if (this.points.length > 1600) this.points.splice(0, this.points.length - 1600);
    }

    latestTime() {
      return this.points.length ? this.points[this.points.length - 1].t : 0;
    }

    draw() {
      const ctx = this.ctx;
      const w = this.width;
      const h = this.height;
      if (w < 30 || h < 30) return;

      ctx.clearRect(0, 0, w, h);

      const padLeft = 38;
      const padRight = 6;
      const padTop = 1;
      const padBottom = 12;
      const gap = 4;
      const rowHeight = Math.max(8, (h - padTop - padBottom - gap * 2) / 3);
      const plotWidth = Math.max(1, w - padLeft - padRight);
      const latest = this.latestTime();
      const start = latest - this.windowSeconds;
      const xOf = (t) => padLeft + ((t - start) / this.windowSeconds) * plotWidth;

      ctx.font = '8px "Cascadia Code", Consolas, monospace';
      ctx.textBaseline = "middle";

      // Shared vertical time grid.
      for (let offset = 0; offset <= this.windowSeconds; offset += 5) {
        const x = xOf(start + offset);
        ctx.strokeStyle = "rgba(120,150,185,0.07)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, padTop);
        ctx.lineTo(x, padTop + rowHeight * 3 + gap * 2);
        ctx.stroke();
      }

      if (this.points.length < 2) {
        ctx.fillStyle = "rgba(100,122,150,0.75)";
        ctx.font = '10px "Segoe UI", sans-serif';
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("Waiting for samples", padLeft + plotWidth / 2, h / 2);
        return;
      }

      const visible = this.points.filter((point) => point.t >= start - 1);
      if (visible.length < 2) return;

      this.series.forEach((series, index) => {
        const rowTop = padTop + index * (rowHeight + gap);
        const rowBottom = rowTop + rowHeight;
        const isYaw = series.key === "yaw";
        let range = 360;
        let yOf;
        if (isYaw) {
          // Compass heading: 0 at the bottom, 360 at the top.
          yOf = (value) =>
            rowTop + ((360 - clamp(value, 0, 360)) / 360) * rowHeight;
        } else {
          let maxAbs = 0;
          for (const point of visible) {
            maxAbs = Math.max(maxAbs, Math.abs(point[series.key]));
          }
          range = niceRange(maxAbs);
          yOf = (value) =>
            rowTop + ((range - clamp(value, -range, range)) / (range * 2)) * rowHeight;
        }

        // Row background and zero line.
        ctx.fillStyle = "rgba(255,255,255,0.014)";
        ctx.fillRect(padLeft, rowTop, plotWidth, rowHeight);

        ctx.strokeStyle = "rgba(140,170,205,0.13)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padLeft, yOf(0));
        ctx.lineTo(w - padRight, yOf(0));
        ctx.stroke();

        // Top/bottom bounds.
        ctx.strokeStyle = "rgba(120,150,185,0.06)";
        ctx.beginPath();
        ctx.moveTo(padLeft, rowTop + 0.5);
        ctx.lineTo(w - padRight, rowTop + 0.5);
        ctx.moveTo(padLeft, rowBottom - 0.5);
        ctx.lineTo(w - padRight, rowBottom - 0.5);
        ctx.stroke();

        // Label + range.
        ctx.textAlign = "left";
        ctx.fillStyle = series.color;
        ctx.globalAlpha = 0.9;
        ctx.fillText(series.label, 6, rowTop + rowHeight / 2);
        ctx.globalAlpha = 1;
        ctx.fillStyle = "rgba(100,122,150,0.75)";
        ctx.textAlign = "right";
        ctx.fillText(isYaw ? "0-360" : `±${range}`, padLeft - 6, rowTop + rowHeight / 2);

        // Clip the row so the glow never leaves it.
        ctx.save();
        ctx.beginPath();
        ctx.rect(padLeft, rowTop, plotWidth, rowHeight);
        ctx.clip();

        // Soft area fill down to zero.
        ctx.beginPath();
        let started = false;
        let previous = null;
        for (const point of visible) {
          const value = point[series.key];
          const x = xOf(point.t);
          const y = yOf(value);
          if (!started || (series.key === "yaw" && Math.abs(value - previous) > 180)) {
            if (started) {
              ctx.lineTo(x, yOf(0));
              ctx.closePath();
              ctx.fillStyle = series.color;
              ctx.globalAlpha = 0.08;
              ctx.fill();
              ctx.beginPath();
            }
            ctx.moveTo(x, yOf(0));
            ctx.lineTo(x, y);
            started = true;
          } else {
            ctx.lineTo(x, y);
          }
          previous = value;
        }
        if (started) {
          const last = visible[visible.length - 1];
          ctx.lineTo(xOf(last.t), yOf(0));
          ctx.closePath();
          ctx.fillStyle = series.color;
          ctx.globalAlpha = 0.08;
          ctx.fill();
        }
        ctx.globalAlpha = 1;

        // Line with a slight glow.
        ctx.beginPath();
        started = false;
        previous = null;
        for (const point of visible) {
          const value = point[series.key];
          const x = xOf(point.t);
          const y = yOf(value);
          if (!started || (series.key === "yaw" && Math.abs(value - previous) > 180)) {
            ctx.moveTo(x, y);
            started = true;
          } else {
            ctx.lineTo(x, y);
          }
          previous = value;
        }
        ctx.strokeStyle = series.color;
        ctx.lineWidth = series.key === "yaw" ? 1.5 : 1.3;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.shadowColor = series.color;
        ctx.shadowBlur = 5;
        ctx.stroke();
        ctx.shadowBlur = 0;

        ctx.restore();
      });

      // Time labels under the last row.
      ctx.font = '7.5px "Cascadia Code", Consolas, monospace';
      ctx.fillStyle = "rgba(100,122,150,0.55)";
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillText(`${this.windowSeconds}s`, padLeft, h - padBottom + 2);
      ctx.textAlign = "right";
      ctx.fillText("now", w - padRight, h - padBottom + 2);
    }
  }

  window.AttitudeChart = AttitudeChart;
})();
