import { fileUrl } from './api.js';
import { load, save } from './store.js';
import { setIcon } from './icons.js';

const MIN_SLIDESHOW_INTERVAL = 0.5;

export const DEFAULT_LABELS = {
  selectFolder: 'move to folder',
  interval: 'slideshow interval (s)',
  slideshowStart: 'start slideshow',
  slideshowStop: 'stop slideshow',
  notFound: 'error: item not found',
  loadError: (message) => `error: ${message}`,
  mediaError: (name) => `error: failed to load ${name}`,
  download: (name) => `download: ${name}`,
};

function loaded(element) {
  const done = element instanceof HTMLVideoElement ? 'loadeddata' : 'load';
  if (!(element instanceof HTMLImageElement || element instanceof HTMLVideoElement)) return Promise.resolve();
  return new Promise((resolve, reject) => {
    element.addEventListener(done, resolve, { once: true });
    element.addEventListener('error', reject, { once: true });
  });
}

export class Viewer {
  constructor(onIndexChange, onInfo, onSelectFolder, labels = {}) {
    this.labels = { ...DEFAULT_LABELS, ...labels };
    this.el = document.getElementById('viewer');
    this.stage = document.getElementById('viewer-stage');
    this.caption = document.getElementById('viewer-caption');
    this.onIndexChange = onIndexChange;
    this.onSelectFolder = onSelectFolder;
    this.index = -1;
    this.item = null;
    this.total = 0;
    this.client = null;
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
    selectFolder.textContent = this.labels.selectFolder;
    selectFolder.addEventListener('click', () => {
      this.menu.classList.add('hidden');
      if (this.item) this.onSelectFolder(this.item);
    });

    this.slideshowToggle = document.createElement('button');
    this.slideshowToggle.className = 'menu-item';
    this.slideshowToggle.addEventListener('click', () => this.toggleSlideshow());

    const intervalRow = document.createElement('label');
    intervalRow.className = 'menu-item';
    intervalRow.textContent = this.labels.interval;
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
    this.slideshowToggle.textContent = this.slideshow ? this.labels.slideshowStop : this.labels.slideshowStart;
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

  setQuery(client, total) {
    this.client = client;
    this.total = total;
    this.close();
  }

  async open(index, item) {
    if (index < 0 || index >= this.total) return;
    this.clearTimer();
    const token = ++this.token;
    this.index = index;
    this.item = null;
    this.stage.replaceChildren();
    this.caption.textContent = `${index + 1}/${this.total}`;
    this.el.classList.remove('hidden');
    this.el.classList.add('loading');
    const settle = (message) => {
      this.el.classList.remove('loading');
      if (message !== undefined) this.caption.textContent = message;
    };
    if (!item) {
      try {
        const data = await this.client.items(index, 1);
        item = data.items[0];
      } catch (e) {
        if (token === this.token) settle(this.labels.loadError(e.message));
        return;
      }
      if (!item) {
        if (token === this.token) settle(this.labels.notFound);
        return;
      }
    }
    if (token !== this.token) return;
    const url = fileUrl(this.client.db, item.path);
    const media = this.render(item, url);
    this.caption.textContent = `${index + 1}/${this.total}  ${item.name}`;
    this.item = item;
    this.stage.replaceChildren(media);
    this.onIndexChange(index, item);
    this.armSlideshow();
    loaded(media).then(
      () => token === this.token && settle(),
      () => token === this.token && settle(this.labels.mediaError(item.name)),
    );
  }

  render(item, url) {
    if (item.kind === 'image') {
      const img = document.createElement('img');
      img.src = url;
      return img;
    }
    if (item.kind === 'video') {
      const video = document.createElement('video');
      video.src = url;
      video.controls = true;
      video.autoplay = true;
      video.volume = load('volume', 1);
      video.addEventListener('volumechange', () => save('volume', video.volume));
      return video;
    }
    const link = document.createElement('a');
    link.href = url;
    link.textContent = this.labels.download(item.name);
    link.download = item.name;
    return link;
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
    this.el.classList.remove('loading');
    this.stage.replaceChildren();
    this.caption.textContent = '';
    this.index = -1;
    this.item = null;
  }

  get isOpen() {
    return !this.el.classList.contains('hidden');
  }
}
