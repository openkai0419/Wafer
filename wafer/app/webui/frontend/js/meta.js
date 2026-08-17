import { getJson } from './api.js';

export class MetaPanel {
  constructor() {
    this.el = document.getElementById('meta-panel');
    this.content = document.getElementById('meta-content');
  }

  async show(db, item) {
    this.el.classList.remove('hidden');
    this.content.textContent = 'loading...';
    try {
      const data = await getJson('/api/meta', { db, path: item.path });
      this.content.replaceChildren(
        this.section('File', { name: item.name, path: item.path, hash: data.file_hash || '' }),
        this.section('Metadata', mapValues(data.meta)),
        this.section('Tags', mapValues(data.tags)),
      );
    } catch (e) {
      this.content.textContent = `failed to load metadata: ${e.message}`;
    }
  }

  section(title, entries) {
    const box = document.createElement('section');
    const h = document.createElement('h3');
    h.textContent = title;
    box.appendChild(h);
    const dl = document.createElement('dl');
    for (const [key, value] of Object.entries(entries)) {
      const dt = document.createElement('dt');
      dt.textContent = key;
      const dd = document.createElement('dd');
      dd.textContent = String(value ?? '');
      dl.append(dt, dd);
    }
    box.appendChild(dl);
    return box;
  }

  hide() {
    this.el.classList.add('hidden');
  }

  get isOpen() {
    return !this.el.classList.contains('hidden');
  }
}

function mapValues(obj) {
  const out = {};
  for (const [key, entry] of Object.entries(obj || {})) out[key] = entry.value;
  return out;
}
