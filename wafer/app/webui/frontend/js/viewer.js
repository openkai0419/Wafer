import { fileUrl, getItems } from './api.js';
import { load, save } from './store.js';
import { setIcon } from './icons.js';

const MIN_SLIDESHOW_INTERVAL = 0.5;

export class Viewer {
  constructor(onIndexChange, onInfo, onSelectFolder) {
    this.el = document.getElementById('viewer');
    this.stage = document.getElementById('viewer-stage');
    this.caption = document.getElementById('viewer-caption');
    this.onIndexChange = onIndexChange;
    this.onSelectFolder = onSelectFolder;
    this.index = -1;
    this.item = null;
    this.total = 0;
    this.db = '';
    this.queryId = '';
    this.slideshow = false;
    this.interval = load('slideshowInterval', 3);
    this.timer = null;
    this.token = 0;
    const close = document.getElementById('viewer-close');
    const prev = document.getElementById('viewer-prev');
    const next = document.getElementById('viewer-next');
    const info = document.getElementById('viewer-info');
    setIcon(close, 'close');
    setIcon(prev, 'chevron-left');
    setIcon(next, 'chevron-right');
    setIcon(info, 'info');
    close.addEventListener('click', () => this.close());
    prev.addEventListener('click', () => this.step(-1));
    next.addEventListener('click', () => this.step(1));
    info.addEventListener('click', () => onInfo());
    this.setupMenu();
    this.el.addEventListener('click', (e) => {
      if (e.target === this.el || e.target === this.stage) this.close();
    });
    document.addEventListener('keydown', (e) => {
      if (this.el.classList.contains('hidden')) return;
      if (e.key === 'Escape') this.close();
      else if (e.key === 'ArrowLeft') this.step(-1);
      else if (e.key === 'ArrowRight') this.step(1);
    });
  }

  setupMenu() {
    this.menu = document.getElementById('viewer-menu-popup');
    const button = document.getElementById('viewer-menu');
    setIcon(button, 'menu');
    button.addEventListener('click', (e) => {
      e.stopPropagation();
      this.menu.classList.toggle('hidden');
    });
    document.addEventListener('click', (e) => {
      if (e.target !== button && !this.menu.contains(e.target)) this.menu.classList.add('hidden');
    });

    const selectFolder = document.createElement('button');
    selectFolder.className = 'menu-item';
    selectFolder.textContent = 'select folder';
    selectFolder.addEventListener('click', () => {
      this.menu.classList.add('hidden');
      if (this.item) this.onSelectFolder(this.item);
    });

    this.slideshowToggle = document.createElement('button');
    this.slideshowToggle.className = 'menu-item';
    this.slideshowToggle.addEventListener('click', () => this.toggleSlideshow());

    const intervalRow = document.createElement('label');
    intervalRow.className = 'menu-item';
    intervalRow.textContent = 'interval (s)';
    const input = document.createElement('input');
    input.type = 'number';
    input.min = String(MIN_SLIDESHOW_INTERVAL);
    input.step = '0.5';
    input.value = String(this.interval);
    const apply = () => {
      const value = Number(input.value);
      if (!Number.isFinite(value) || value < MIN_SLIDESHOW_INTERVAL) {
        input.value = String(this.interval);
        return;
      }
      this.interval = value;
      save('slideshowInterval', this.interval);
      if (this.slideshow) this.armSlideshow();
    };
    input.addEventListener('change', apply);
    intervalRow.appendChild(input);

    this.menu.append(selectFolder, this.slideshowToggle, intervalRow);
    this.updateMenu();
  }

  updateMenu() {
    this.slideshowToggle.textContent = this.slideshow ? 'stop slideshow' : 'start slideshow';
  }

  toggleSlideshow() {
    this.slideshow = !this.slideshow;
    this.updateMenu();
    this.menu.classList.add('hidden');
    if (this.slideshow) this.armSlideshow();
    else this.clearTimer();
  }

  clearTimer() {
    clearTimeout(this.timer);
    this.timer = null;
  }

  armSlideshow() {
    this.clearTimer();
    if (!this.slideshow) return;
    const token = this.token;
    const video = this.stage.querySelector('video');
    if (video) {
      video.loop = false;
      video.addEventListener('ended', () => this.advance(token), { once: true });
      return;
    }
    const startTimer = () => {
      if (token !== this.token) return;
      this.timer = setTimeout(() => this.advance(token), this.interval * 1000);
    };
    const img = this.stage.querySelector('img');
    if (img && !img.complete) {
      img.addEventListener('load', startTimer, { once: true });
      img.addEventListener('error', startTimer, { once: true });
    } else {
      startTimer();
    }
  }

  advance(token) {
    if (!this.slideshow || token !== this.token) return;
    const next = this.index + 1 >= this.total ? 0 : this.index + 1;
    this.open(next);
  }

  setQuery(db, queryId, total) {
    this.db = db;
    this.queryId = queryId;
    this.total = total;
    this.close();
  }

  async open(index, item) {
    if (index < 0 || index >= this.total) return;
    this.clearTimer();
    this.token++;
    this.index = index;
    this.el.classList.remove('hidden');
    if (!item) {
      const data = await getItems(this.queryId, index, 1);
      item = data.items[0];
    }
    if (!item || this.index !== index) return;
    this.item = item;
    this.caption.textContent = `${index + 1}/${this.total}  ${item.name}`;
    const url = fileUrl(this.db, item.path);
    if (item.kind === 'image') {
      const img = document.createElement('img');
      img.src = url;
      this.stage.replaceChildren(img);
    } else if (item.kind === 'video') {
      const video = document.createElement('video');
      video.src = url;
      video.controls = true;
      video.autoplay = true;
      video.volume = load('volume', 1);
      video.addEventListener('volumechange', () => save('volume', video.volume));
      this.stage.replaceChildren(video);
    } else {
      const link = document.createElement('a');
      link.href = url;
      link.textContent = `download: ${item.name}`;
      link.download = item.name;
      this.stage.replaceChildren(link);
    }
    this.onIndexChange(index, item);
    this.armSlideshow();
  }

  step(delta) {
    this.open(this.index + delta);
  }

  close() {
    this.slideshow = false;
    this.token++;
    this.clearTimer();
    if (this.slideshowToggle) this.updateMenu();
    if (this.menu) this.menu.classList.add('hidden');
    this.el.classList.add('hidden');
    this.stage.replaceChildren();
    this.index = -1;
    this.item = null;
  }

  get isOpen() {
    return !this.el.classList.contains('hidden');
  }
}
