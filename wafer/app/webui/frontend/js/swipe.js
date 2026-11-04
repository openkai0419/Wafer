const SWIPE_START_PX = 10;
const COMMIT_RATIO = 0.25;
const FLICK_PX_PER_MS = 0.5;
const EDGE_RESISTANCE = 0.3;
const SETTLE_MS = 180;
const VELOCITY_WINDOW_MS = 100;
const MAX_PAGE_SCALE = 1.01;

export class Swipe {
  constructor(stage, { canStart, hasNeighbor, fillPane, onDragStart, onCancel, onCommit }) {
    this.stage = stage;
    this.canStart = canStart;
    this.hasNeighbor = hasNeighbor;
    this.fillPane = fillPane;
    this.onDragStart = onDragStart;
    this.onCancel = onCancel;
    this.onCommit = onCommit;
    this.drag = null;
    this.settling = null;
    this.swallowClick = false;
    window.visualViewport?.addEventListener('resize', () => {
      stage.style.touchAction = this.zoomed ? 'auto' : '';
    });
    stage.addEventListener('pointerdown', (e) => this.onDown(e));
    stage.addEventListener('pointermove', (e) => this.onMove(e));
    stage.addEventListener('pointerup', (e) => this.onUp(e));
    stage.addEventListener('pointercancel', (e) => this.onPointerCancel(e));
    stage.addEventListener(
      'click',
      (e) => {
        if (!this.swallowClick) return;
        this.swallowClick = false;
        e.stopPropagation();
      },
      true,
    );
  }

  get zoomed() {
    return (window.visualViewport?.scale ?? 1) > MAX_PAGE_SCALE;
  }

  abort() {
    if (this.settling) clearTimeout(this.settling.timer);
    if (this.drag && this.stage.hasPointerCapture(this.drag.id)) this.stage.releasePointerCapture(this.drag.id);
    this.drag = null;
    this.settling = null;
    this.clearPosition();
    this.stage.querySelectorAll('.swipe-pane').forEach((pane) => pane.remove());
  }

  clearPosition() {
    this.stage.classList.remove('swipe-settling');
    this.stage.style.removeProperty('--swipe-x');
  }

  setX(x) {
    this.stage.style.setProperty('--swipe-x', `${x}px`);
  }

  onDown(e) {
    const interrupted = this.settling !== null;
    this.swallowClick = interrupted;
    if (interrupted) this.finishSettling();
    if (this.drag) {
      if (e.pointerId !== this.drag.id) this.interrupt();
      return;
    }
    if (e.pointerType !== 'touch' || !e.isPrimary || this.zoomed || !this.canStart(e.target)) return;
    if (interrupted) this.stage.setPointerCapture(e.pointerId);
    this.drag = {
      id: e.pointerId,
      x0: e.clientX,
      y0: e.clientY,
      samples: [{ x: e.clientX, t: e.timeStamp }],
      swiping: false,
      delta: 0,
      neighbor: false,
      pane: null,
      x: 0,
    };
  }

  onMove(e) {
    const drag = this.drag;
    if (!drag || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.x0;
    const dy = e.clientY - drag.y0;
    if (!drag.swiping) {
      if (Math.abs(dy) > SWIPE_START_PX && Math.abs(dy) >= Math.abs(dx)) this.drag = null;
      else if (Math.abs(dx) > SWIPE_START_PX && Math.abs(dx) > Math.abs(dy)) this.begin(e, dx);
      if (!this.drag?.swiping) return;
    }
    this.sample(e);
    const inward = drag.delta > 0 ? Math.min(0, dx) : Math.max(0, dx);
    drag.x = drag.neighbor ? inward : inward * EDGE_RESISTANCE;
    this.setX(drag.x);
  }

  sample(e) {
    const { samples } = this.drag;
    samples.push({ x: e.clientX, t: e.timeStamp });
    const limit = e.timeStamp - VELOCITY_WINDOW_MS;
    while (samples.length > 2 && samples[1].t < limit) samples.shift();
  }

  begin(e, dx) {
    const drag = this.drag;
    drag.swiping = true;
    drag.delta = dx < 0 ? 1 : -1;
    this.swallowClick = true;
    this.stage.setPointerCapture(e.pointerId);
    this.onDragStart();
    drag.neighbor = this.hasNeighbor(drag.delta);
    if (!drag.neighbor) return;
    drag.pane = document.createElement('div');
    drag.pane.className = `swipe-pane ${drag.delta > 0 ? 'next' : 'prev'}`;
    this.stage.append(drag.pane);
    this.fillPane(drag.delta, drag.pane);
  }

  onUp(e) {
    const drag = this.drag;
    if (!drag || e.pointerId !== drag.id) return;
    if (!drag.swiping) {
      this.drag = null;
      return;
    }
    this.sample(e);
    const first = drag.samples[0];
    const last = drag.samples[drag.samples.length - 1];
    const elapsed = last.t - first.t;
    const toward = elapsed > 0 ? (-drag.delta * (last.x - first.x)) / elapsed : 0;
    const far = Math.abs(drag.x) >= this.stage.clientWidth * COMMIT_RATIO;
    this.settle(drag.neighbor && (far || toward >= FLICK_PX_PER_MS));
  }

  onPointerCancel(e) {
    const drag = this.drag;
    if (!drag || e.pointerId !== drag.id) return;
    this.interrupt();
  }

  interrupt() {
    if (this.drag.swiping) this.settle(false);
    else this.drag = null;
  }

  settle(commit) {
    const { delta, pane } = this.drag;
    this.drag = null;
    const wait = matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : SETTLE_MS;
    this.stage.classList.add('swipe-settling');
    this.setX(commit ? -delta * this.stage.clientWidth : 0);
    const timer = setTimeout(() => this.finishSettling(), wait);
    this.settling = { commit, delta, pane, timer };
  }

  finishSettling() {
    const { commit, delta, pane, timer } = this.settling;
    clearTimeout(timer);
    this.settling = null;
    this.clearPosition();
    if (commit) this.onCommit(delta, pane);
    else this.onCancel();
    pane?.remove();
  }
}
