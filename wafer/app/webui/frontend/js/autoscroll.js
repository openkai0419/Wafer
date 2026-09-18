import { load, save } from './store.js';

export const SPEED_DEFAULT = 50;
export const SPEED_MIN = 5;
export const SPEED_MAX = 500;
export const SPEED_STEPS = buildSpeedSteps();

function buildSpeedSteps() {
  const steps = [];
  for (const [limit, increment] of [
    [20, 1],
    [50, 2],
    [100, 5],
    [200, 10],
    [SPEED_MAX, 25],
  ]) {
    for (let value = steps.length ? steps.at(-1) + increment : SPEED_MIN; value <= limit; value += increment) steps.push(value);
  }
  return steps;
}

export function nearestSpeedIndex(speed) {
  let nearest = 0;
  for (let i = 1; i < SPEED_STEPS.length; i++) {
    if (Math.abs(SPEED_STEPS[i] - speed) < Math.abs(SPEED_STEPS[nearest] - speed)) nearest = i;
  }
  return nearest;
}

const CANCEL_KEYS = new Set(['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' ']);
const CANCEL_EVENTS = ['wheel', 'pointerdown', 'touchstart'];

export class AutoScroll {
  constructor(scrollEl, canvasEl, onRunningChange) {
    this.scroll = scrollEl;
    this.canvas = canvasEl;
    this.onRunningChange = onRunningChange;
    this.speed = load('autoScrollSpeed', SPEED_DEFAULT);
    this.frame = null;
    this.offset = 0;
    this.lastTime = 0;
    for (const type of CANCEL_EVENTS) {
      scrollEl.addEventListener(type, () => this.stop(), { passive: true });
    }
    document.addEventListener('keydown', (e) => {
      if (e.target instanceof Element && e.target.closest('input, textarea, select')) return;
      if (CANCEL_KEYS.has(e.key)) this.stop();
    });
  }

  get running() {
    return this.frame !== null;
  }

  setSpeed(speed) {
    this.speed = Math.min(SPEED_MAX, Math.max(SPEED_MIN, Math.round(speed)));
    save('autoScrollSpeed', this.speed);
  }

  toggle() {
    this.running ? this.stop() : this.start();
  }

  start() {
    if (this.running) return;
    this.offset = this.scroll.scrollTop;
    this.lastTime = performance.now();
    this.frame = requestAnimationFrame((now) => this.step(now));
    this.onRunningChange(true);
  }

  stop() {
    if (!this.running) return;
    cancelAnimationFrame(this.frame);
    this.frame = null;
    this.canvas.style.transform = '';
    this.onRunningChange(false);
  }

  step(now) {
    const limit = this.scroll.scrollHeight - this.scroll.clientHeight;
    if (limit <= 0) {
      this.stop();
      return;
    }
    this.offset += (this.speed * (now - this.lastTime)) / 1000;
    this.lastTime = now;
    if (this.offset >= limit) this.offset = 0;
    const whole = Math.floor(this.offset);
    this.scroll.scrollTop = whole;
    this.canvas.style.transform = `translateY(${whole - this.offset}px)`;
    this.frame = requestAnimationFrame((next) => this.step(next));
  }
}
