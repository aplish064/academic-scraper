/**
 * Ambient particle field — a small canvas layer that drifts soft, twinkling
 * dots across the screen. Intended to sit behind the knowledge-graph SVG
 * as a background, not to compete with it.
 *
 * Design notes:
 *   - Additive blending (composite "lighter") so overlapping particles bloom.
 *   - Per-particle radial gradient gives each dot a soft halo instead of
 *     a hard edge.
 *   - Sine-phase "twinkle" modulates alpha so the field feels alive even
 *     while individual velocities are nearly still.
 *   - Positions wrap around the viewport.
 */

const PALETTE = [
  [180, 190, 254], // lavender
  [137, 180, 250], // blue
  [203, 166, 247], // mauve
  [148, 226, 213], // teal
  [245, 194, 231], // pink
  [116, 199, 236], // sapphire
];

export class ParticleField {
  constructor(canvas, count = 90) {
    this.canvas = canvas;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("2d context not available");
    this.ctx = ctx;
    this.count = count;
    this.particles = [];
    this.raf = null;
    this.lastTime = 0;
    this.w = 0;
    this.h = 0;
    this.running = false;
    this.resizeHandler = () => this.resize();
    this.resize();
    this.spawn(count);
  }

  start() {
    if (this.running) return;
    this.running = true;
    window.addEventListener("resize", this.resizeHandler);
    this.lastTime = performance.now();
    const loop = (t) => {
      if (!this.running) return;
      const dt = Math.min(64, t - this.lastTime);
      this.lastTime = t;
      this.tick(dt);
      this.draw();
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  stop() {
    this.running = false;
    if (this.raf != null) {
      cancelAnimationFrame(this.raf);
      this.raf = null;
    }
    window.removeEventListener("resize", this.resizeHandler);
  }

  resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.w = this.canvas.clientWidth || this.canvas.parentElement?.clientWidth || 1;
    this.h = this.canvas.clientHeight || this.canvas.parentElement?.clientHeight || 1;
    this.canvas.width = Math.max(1, Math.floor(this.w * dpr));
    this.canvas.height = Math.max(1, Math.floor(this.h * dpr));
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  spawn(count) {
    this.particles = [];
    for (let i = 0; i < count; i++) {
      this.particles.push(this.makeParticle());
    }
  }

  makeParticle() {
    return {
      x: Math.random() * this.w,
      y: Math.random() * this.h,
      vx: (Math.random() - 0.5) * 0.18,
      vy: (Math.random() - 0.5) * 0.18,
      r: 0.5 + Math.random() * 1.6,
      baseAlpha: 0.16 + Math.random() * 0.34,
      phase: Math.random() * Math.PI * 2,
      phaseSpeed: 0.0005 + Math.random() * 0.0014,
      color: PALETTE[Math.floor(Math.random() * PALETTE.length)],
    };
  }

  tick(dt) {
    for (const p of this.particles) {
      p.x += p.vx * dt * 0.6;
      p.y += p.vy * dt * 0.6;
      p.phase += p.phaseSpeed * dt;
      // wrap around
      if (p.x < -12) p.x = this.w + 12;
      if (p.x > this.w + 12) p.x = -12;
      if (p.y < -12) p.y = this.h + 12;
      if (p.y > this.h + 12) p.y = -12;
    }
  }

  draw() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.w, this.h);
    ctx.globalCompositeOperation = "lighter";
    for (const p of this.particles) {
      const twinkle = (Math.sin(p.phase) + 1) * 0.5; // 0..1
      const alpha = p.baseAlpha * (0.55 + twinkle * 0.45);
      const [r, g, b] = p.color;
      const gradR = p.r * 7;
      const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, gradR);
      grad.addColorStop(0, `rgba(${r},${g},${b},${alpha})`);
      grad.addColorStop(0.4, `rgba(${r},${g},${b},${alpha * 0.3})`);
      grad.addColorStop(1, `rgba(${r},${g},${b},0)`);
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(p.x, p.y, gradR, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalCompositeOperation = "source-over";
  }
}
