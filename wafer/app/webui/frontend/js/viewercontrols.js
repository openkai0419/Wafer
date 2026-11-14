const HIDE_DELAY_MS = 3000;
const HIDDEN_CLASS = 'controls-hidden';
const OVERLAP_TOLERANCE_PX = 1;

function drawnRect(img, box) {
  const scale = Math.min(box.width / img.naturalWidth, box.height / img.naturalHeight);
  const width = img.naturalWidth * scale;
  const height = img.naturalHeight * scale;
  const left = box.left + (box.width - width) / 2;
  const top = box.top + (box.height - height) / 2;
  return { left, top, right: left + width, bottom: top + height };
}

function untransformedBox(el) {
  const parent = el.offsetParent.getBoundingClientRect();
  return { left: parent.left + el.offsetLeft, top: parent.top + el.offsetTop, width: el.offsetWidth, height: el.offsetHeight };
}

function overlaps(a, b) {
  const width = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  return width > OVERLAP_TOLERANCE_PX && height > OVERLAP_TOLERANCE_PX;
}

export function isInsideDrawnImage(img, x, y) {
  if (!img.naturalWidth || !img.naturalHeight) return true;
  const rect = drawnRect(img, img.getBoundingClientRect());
  return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
}

export class ViewerControls {
  constructor(viewerEl) {
    this.el = viewerEl;
    this.main = viewerEl.querySelector('#viewer-main');
    this.stage = viewerEl.querySelector('#viewer-stage');
    this.parts = [...this.main.querySelectorAll(':scope > button'), viewerEl.querySelector('#viewer-caption')];
    this.active = false;
    this.hideable = true;
    this.autoHide = true;
    this.timer = null;
    const restart = () => this.restart();
    viewerEl.addEventListener('pointerdown', restart);
    viewerEl.addEventListener('pointermove', restart);
    document.addEventListener('keydown', restart);
    this.main.addEventListener('focusin', (e) => {
      if (this.active && e.target.parentElement === this.main && e.target instanceof HTMLButtonElement) this.show();
    });
    new ResizeObserver(() => this.revealIfClear()).observe(this.main);
  }

  get hidden() {
    return this.el.classList.contains(HIDDEN_CLASS);
  }

  get popupOpen() {
    return this.el.querySelector('[id$="-popup"]:not(.hidden)') !== null;
  }

  get coversContent() {
    const img = this.stage.querySelector(':scope > img');
    if (!img?.naturalWidth || !img.offsetParent) return false;
    const drawn = drawnRect(img, untransformedBox(img));
    return this.parts.some((part) => overlaps(part.getBoundingClientRect(), drawn));
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
    else if (this.coversContent) this.hide();
  }

  setHideable(value) {
    this.hideable = value;
    if (!value && this.hidden) this.show();
  }

  setAutoHide(value) {
    this.autoHide = value;
    if (this.active && !this.hidden) this.arm();
  }

  revealIfClear() {
    if (this.active && this.hidden && !this.coversContent) this.show();
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
    if (this.autoHide) this.timer = setTimeout(() => this.expire(), HIDE_DELAY_MS);
  }

  expire() {
    this.timer = null;
    if (this.popupOpen || !this.hideable || !this.coversContent) this.arm();
    else this.hide();
  }

  clearTimer() {
    clearTimeout(this.timer);
    this.timer = null;
  }
}
