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

export class MetaPanel {
  constructor(labels = {}) {
    this.labels = { ...DEFAULT_LABELS, ...labels };
    this.el = document.getElementById('meta-panel');
    this.content = document.getElementById('meta-content');
  }

  async show(db, item) {
    this.el.classList.remove('hidden');
    this.content.textContent = this.labels.loading;
    try {
      const data = await getJson('/api/meta', { db, path: item.path });
      const entries = [...valueEntries(data.meta), ...valueEntries(data.tags)];
      const source = [...data.source];
      if (data.collectors.length) source.push([this.labels.collectedBy, collectorList(data.collectors)]);
      const fileEntries = data.file.length ? data.file : [['name', item.name], ['path', item.path]];
      const sections = [section(this.labels.fileSection, fileEntries)];
      if (source.length) sections.push(section(this.labels.sourceSection, source));
      for (const [prefix, group] of groupEntriesByPrefix(entries)) sections.push(section(`${prefix || this.labels.noPrefix} (${group.length})`, group));
      this.content.replaceChildren(...sections);
    } catch (e) {
      this.content.textContent = this.labels.loadError(e.message);
    }
  }

  hide() {
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
