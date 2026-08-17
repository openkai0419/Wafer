import { fileUrl, getItems } from './api.js';
import { load, save } from './store.js';

export class Viewer {
  constructor(onIndexChange, onInfo) {
    this.el = document.getElementById('viewer');
    this.stage = document.getElementById('viewer-stage');
    this.caption = document.getElementById('viewer-caption');
    this.onIndexChange = onIndexChange;
    this.index = -1;
    this.total = 0;
    this.db = '';
    this.queryId = '';
    document.getElementById('viewer-close').addEventListener('click', () => this.close());
    document.getElementById('viewer-prev').addEventListener('click', () => this.step(-1));
    document.getElementById('viewer-next').addEventListener('click', () => this.step(1));
    document.getElementById('viewer-info').addEventListener('click', () => onInfo());
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

  setQuery(db, queryId, total) {
    this.db = db;
    this.queryId = queryId;
    this.total = total;
    this.close();
  }

  async open(index, item) {
    if (index < 0 || index >= this.total) return;
    this.index = index;
    this.el.classList.remove('hidden');
    if (!item) {
      const data = await getItems(this.queryId, index, 1);
      item = data.items[0];
    }
    if (!item || this.index !== index) return;
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
  }

  step(delta) {
    this.open(this.index + delta);
  }

  close() {
    this.el.classList.add('hidden');
    this.stage.replaceChildren();
    this.index = -1;
  }

  get isOpen() {
    return !this.el.classList.contains('hidden');
  }
}
