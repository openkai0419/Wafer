import { getJson } from './api.js';
import { groupEntriesByPrefix, stripPrefix } from './keygroups.js';

export const DEFAULT_LABELS = {
  loading: 'loading...',
  noPrefix: '(no prefix)',
  fileSection: 'File',
  sourceSection: 'Source',
  collectedBy: 'collected by',
  loadError: (message) => `failed to load metadata: ${message}`,
};

const CACHE_LIMIT = 20;

export class MetaPanel {
  constructor(labels = {}) {
    this.labels = { ...DEFAULT_LABELS, ...labels };
    this.el = document.getElementById('meta-panel');
    this.content = document.getElementById('meta-content');
    this.token = 0;
    this.cache = new Map();
  }

  async load(key, db, path) {
    const data = this.cache.get(key) ?? (await getJson('/api/meta', { db, path }));
    this.remember(key, data);
    return data;
  }

  async show(db, item) {
    this.el.classList.remove('hidden');
    const token = ++this.token;
    const key = `${db}:${item.path}`;
    if (!this.cache.has(key)) {
      if (!this.content.hasChildNodes()) this.content.textContent = this.labels.loading;
      this.el.classList.add('pending');
    }
    try {
      const data = await this.load(key, db, item.path);
      if (token !== this.token) return;
      this.el.classList.remove('pending');
      const entries = [...valueEntries(data.meta), ...valueEntries(data.tags)];
      const source = [...data.source];
      if (data.collectors.length) source.push([this.labels.collectedBy, collectorList(data.collectors)]);
      const fileEntries = data.file.length ? data.file : [['name', item.name], ['path', item.path]];
      const sections = [section(this.labels.fileSection, fileEntries)];
      if (source.length) sections.push(section(this.labels.sourceSection, source));
      for (const [prefix, group] of groupEntriesByPrefix(entries)) sections.push(section(`${prefix || this.labels.noPrefix} (${group.length})`, group));
      this.content.replaceChildren(...sections);
    } catch (e) {
      if (token !== this.token) return;
      this.el.classList.remove('pending');
      this.content.textContent = this.labels.loadError(e.message);
    }
  }

  remember(key, data) {
    this.cache.delete(key);
    this.cache.set(key, data);
    if (this.cache.size > CACHE_LIMIT) this.cache.delete(this.cache.keys().next().value);
  }

  invalidate() {
    this.cache.clear();
  }

  hide() {
    this.token++;
    this.el.classList.remove('pending');
    this.el.classList.add('hidden');
  }

  get isOpen() {
    return !this.el.classList.contains('hidden');
  }
}

function section(title, entries) {
  const box = document.createElement('section');
  const heading = document.createElement('h3');
  heading.textContent = title;
  box.append(heading, definitionList(entries));
  return box;
}

function definitionList(entries) {
  const dl = document.createElement('dl');
  for (const [key, value] of entries) {
    const dt = document.createElement('dt');
    dt.textContent = stripPrefix(key);
    dt.title = key;
    const dd = document.createElement('dd');
    if (value instanceof Node) dd.append(value);
    else dd.textContent = String(value ?? '');
    dl.append(dt, dd);
  }
  return dl;
}

function collectorList(collectors) {
  const box = document.createElement('span');
  box.className = 'collectors';
  for (const [name, status] of collectors) {
    const chip = document.createElement('span');
    chip.className = `collector ${status}`;
    chip.textContent = name;
    box.append(chip);
  }
  return box;
}

function valueEntries(obj) {
  return Object.entries(obj || {}).map(([key, entry]) => [key, entry.value]);
}
