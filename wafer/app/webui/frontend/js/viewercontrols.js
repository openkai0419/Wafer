const HIDE_DELAY_MS = 3000;
const HIDDEN_CLASS = 'controls-hidden';

export function isInsideDrawnImage(img, x, y) {
  const box = img.getBoundingClientRect();
  if (!img.naturalWidth || !img.naturalHeight) return true;
  const scale = Math.min(box.width / img.naturalWidth, box.height / img.naturalHeight);
  const width = img.naturalWidth * scale;
  const height = img.naturalHeight * scale;
  const left = box.left + (box.width - width) / 2;
  const top = box.top + (box.height - height) / 2;
  return x >= left && x <= left + width && y >= top && y <= top + height;
}

export class ViewerControls {
  constructor(viewerEl) {
    this.el = viewerEl;
    this.main = viewerEl.querySelector('#viewer-main');
    this.active = false;
    this.hideable = true;
    this.timer = null;
    const restart = () => this.restart();
    viewerEl.addEventListener('pointerdown', restart);
    viewerEl.addEventListener('pointermove', restart);
    document.addEventListener('keydown', restart);
    this.main.addEventListener('focusin', (e) => {
      if (this.active && e.target.parentElement === this.main && e.target instanceof HTMLButtonElement) this.show();
    });
  }

  get hidden() {
    return this.el.classList.contains(HIDDEN_CLASS);
  }

  get popupOpen() {
    return this.el.querySelector('[id$="-popup"]:not(.hidden)') !== null;
  }

  start() {
    this.active = true;
    this.hideable = true;
    this.show();
  }

  stop() {
    this.active = false;
    this.clearTimer();
    this.el.classList.remove(HIDDEN_CLASS);
  }

  toggle() {
    if (!this.active || !this.hideable || this.popupOpen) return;
    if (this.hidden) this.show();
    else this.hide();
  }

  setHideable(value) {
    this.hideable = value;
    if (!value) this.el.classList.remove(HIDDEN_CLASS);
  }

  show() {
    this.el.classList.remove(HIDDEN_CLASS);
    this.arm();
  }

  hide() {
    this.clearTimer();
    this.el.classList.add(HIDDEN_CLASS);
  }

  restart() {
    if (this.active && !this.hidden) this.arm();
  }

  arm() {
    this.clearTimer();
    this.timer = setTimeout(() => this.expire(), HIDE_DELAY_MS);
  }

  expire() {
    this.timer = null;
    if (this.popupOpen || !this.hideable) this.arm();
    else this.hide();
  }

  clearTimer() {
    clearTimeout(this.timer);
    this.timer = null;
  }
}
