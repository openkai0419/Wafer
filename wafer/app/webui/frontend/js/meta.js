import { getJson } from './api.js';
import { groupEntriesByPrefix, stripPrefix } from './keygroups.js';

const UNPREFIXED_TITLE = 'general';

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
      const entries = [...valueEntries(data.meta), ...valueEntries(data.tags)];
      this.content.replaceChildren(
        section('File', [
          ['name', item.name],
          ['path', item.path],
          ['hash', data.file_hash || ''],
        ]),
        ...groupEntriesByPrefix(entries).map(([prefix, group]) => section(`${prefix || UNPREFIXED_TITLE} (${group.length})`, group)),
      );
    } catch (e) {
      this.content.textContent = `failed to load metadata: ${e.message}`;
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
    dd.textContent = String(value ?? '');
    dl.append(dt, dd);
  }
  return dl;
}

function valueEntries(obj) {
  return Object.entries(obj || {}).map(([key, entry]) => [key, entry.value]);
}
