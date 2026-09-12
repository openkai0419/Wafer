import { getKeys } from './api.js';
import { load, save } from './store.js';
import { setIcon } from './icons.js';

export class KeyPicker {
  constructor(button, popup, onChange) {
    this.button = button;
    this.popup = popup;
    this.onChange = onChange;
    this.active = load('searchKeys', []);
    this.pinned = load('pinnedKeys', []);
    for (const key of this.active) if (!this.pinned.includes(key)) this.pinned.push(key);
    this.db = '';
    this.catalog = null;
    this.loading = false;
    this.selectedEl = popup.querySelector('#key-selected');
    this.searchEl = popup.querySelector('#key-search');
    this.catalogEl = popup.querySelector('#key-catalog');
    this.updateButton();
    button.addEventListener('click', (e) => {
      e.stopPropagation();
      this.popup.classList.contains('hidden') ? this.openPopup() : this.popup.classList.add('hidden');
    });
    document.addEventListener('click', (e) => {
      if (!e.target.isConnected) return;
      if (!button.contains(e.target) && !this.popup.contains(e.target)) this.popup.classList.add('hidden');
    });
    this.searchEl.addEventListener('input', () => this.renderCatalog());
  }

  setDb(db) {
    if (db === this.db) return;
    this.db = db;
    this.catalog = null;
  }

  invalidate() {
    this.catalog = null;
  }

  async openPopup() {
    this.popup.classList.remove('hidden');
    this.renderSelected();
    this.searchEl.focus();
    if (this.catalog === null && !this.loading) {
      this.loading = true;
      this.catalogEl.textContent = 'loading...';
      try {
        const data = await getKeys(this.db);
        this.catalog = data.keys;
      } catch (e) {
        this.catalogEl.textContent = `error: ${e.message}`;
        return;
      } finally {
        this.loading = false;
      }
    }
    this.renderCatalog();
  }

  toggle(key) {
    if (!this.pinned.includes(key)) this.pinned = [...this.pinned, key];
    this.active = this.active.includes(key) ? this.active.filter((k) => k !== key) : [...this.active, key];
    this.commit();
  }

  unpin(key) {
    const wasActive = this.active.includes(key);
    this.pinned = this.pinned.filter((k) => k !== key);
    this.active = this.active.filter((k) => k !== key);
    this.commit(wasActive);
  }

  commit(notify = true) {
    save('searchKeys', this.active);
    save('pinnedKeys', this.pinned);
    this.updateButton();
    this.renderSelected();
    this.renderCatalog();
    if (notify) this.onChange(this.active);
  }

  updateButton() {
    setIcon(this.button, 'key');
    this.button.classList.toggle('active', this.active.length > 0);
    if (this.active.length) {
      const badge = document.createElement('span');
      badge.className = 'key-badge';
      badge.textContent = this.active.length;
      this.button.appendChild(badge);
    }
  }

  renderSelected() {
    this.selectedEl.replaceChildren();
    for (const key of this.pinned) {
      const chip = document.createElement('span');
      chip.className = 'key-chip';
      chip.classList.toggle('active', this.active.includes(key));
      const name = document.createElement('button');
      name.className = 'key-chip-name';
      name.textContent = key;
      name.title = this.active.includes(key) ? 'disable' : 'enable';
      name.addEventListener('click', () => this.toggle(key));
      const remove = document.createElement('button');
      remove.className = 'key-chip-x';
      remove.title = 'remove';
      remove.setAttribute('aria-label', `remove ${key}`);
      setIcon(remove, 'close');
      remove.addEventListener('click', () => this.unpin(key));
      chip.append(name, remove);
      this.selectedEl.appendChild(chip);
    }
    this.selectedEl.classList.toggle('hidden', this.pinned.length === 0);
  }

  renderCatalog() {
    if (this.catalog === null) return;
    const needle = this.searchEl.value.trim().toLowerCase();
    this.catalogEl.replaceChildren();
    for (const [key, count] of this.catalog) {
      if (needle && !key.toLowerCase().includes(needle)) continue;
      const row = document.createElement('div');
      row.className = 'key-row';
      row.classList.toggle('selected', this.active.includes(key));
      const name = document.createElement('span');
      name.textContent = key;
      const freq = document.createElement('span');
      freq.className = 'key-count';
      freq.textContent = count;
      row.append(name, freq);
      row.addEventListener('click', () => this.toggle(key));
      this.catalogEl.appendChild(row);
    }
    if (this.catalogEl.childElementCount === 0) this.catalogEl.textContent = 'no keys';
  }
}
