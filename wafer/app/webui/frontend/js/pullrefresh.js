import { icon } from './icons.js';

const PULL_THRESHOLD = 80;
const PULL_RESISTANCE = 0.5;

export class PullRefresh {
  constructor(scrollEl, onRefresh) {
    this.scroll = scrollEl;
    this.onRefresh = onRefresh;
    this.startY = null;
    this.refreshing = false;
    this.indicator = document.createElement('div');
    this.indicator.id = 'pull-indicator';
    this.indicator.className = 'hidden';
    this.indicator.innerHTML = icon('refresh');
    scrollEl.appendChild(this.indicator);
    scrollEl.addEventListener('touchstart', (e) => this.onStart(e), { passive: true });
    scrollEl.addEventListener('touchmove', (e) => this.onMove(e), { passive: false });
    scrollEl.addEventListener('touchend', () => this.onEnd());
    scrollEl.addEventListener('touchcancel', () => {
      if (!this.refreshing) this.reset();
    });
  }

  get armed() {
    return this.indicator.classList.contains('armed');
  }

  onStart(e) {
    if (this.refreshing) return;
    this.reset();
    if (e.touches.length === 1 && this.scroll.scrollTop === 0) this.startY = e.touches[0].clientY;
  }

  onMove(e) {
    if (this.startY === null) return;
    if (e.touches.length > 1 || this.scroll.scrollTop !== 0) {
      this.reset();
      return;
    }
    const pull = (e.touches[0].clientY - this.startY) * PULL_RESISTANCE;
    if (pull <= 0) {
      this.indicator.className = 'hidden';
      return;
    }
    e.preventDefault();
    this.indicator.style.setProperty('--pull', pull);
    this.indicator.className = pull >= PULL_THRESHOLD ? 'armed' : '';
  }

  async onEnd() {
    if (this.startY === null) return;
    if (!this.armed) {
      this.reset();
      return;
    }
    this.startY = null;
    this.refreshing = true;
    this.indicator.className = 'refreshing';
    this.indicator.style.setProperty('--pull', PULL_THRESHOLD);
    try {
      await this.onRefresh();
    } finally {
      this.refreshing = false;
      this.reset();
    }
  }

  reset() {
    this.startY = null;
    this.indicator.className = 'hidden';
  }
}
