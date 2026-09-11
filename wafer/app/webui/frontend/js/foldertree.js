import { getJson } from './api.js';
import { load, save } from './store.js';
import { setIcon } from './icons.js';

export class FolderTree {
  constructor(el, onSelect) {
    this.el = el;
    this.onSelect = onSelect;
    this.db = '';
    this.selected = null;
    this.expanded = new Set(load('expanded', []));
    this.branches = new Map();
  }

  async load(db, restorePath) {
    this.db = db;
    this.selected = null;
    this.branches.clear();
    this.el.textContent = '';
    const all = this.makeNode('(all files)', null, 0);
    this.el.appendChild(all);
    if (restorePath == null) {
      all.classList.add('selected');
      this.selected = all;
    }
    const data = await getJson('/api/folders', { db });
    for (const path of data.folders) this.el.appendChild(this.makeBranch(path, 0));
    if (restorePath != null) await this.restore(restorePath);
  }

  async restore(path) {
    const parts = path.split('/');
    for (let i = 1; i < parts.length; i++) {
      const branch = this.branches.get(parts.slice(0, i).join('/'));
      if (branch) await branch.expand(true);
    }
    const target = this.branches.get(path);
    if (target) this.select(target.node, path);
  }

  makeBranch(path, depth) {
    const wrap = document.createElement('div');
    const node = this.makeNode(path.split('/').pop() || path, path, depth);
    wrap.appendChild(node);
    const children = document.createElement('div');
    children.className = 'children hidden';
    wrap.appendChild(children);
    const expand = async (open) => {
      const nowOpen = open === undefined ? children.classList.contains('hidden') : open;
      children.classList.toggle('hidden', !nowOpen);
      node.querySelector('.expander').classList.toggle('open', nowOpen);
      nowOpen ? this.expanded.add(path) : this.expanded.delete(path);
      save('expanded', [...this.expanded]);
      if (nowOpen && children.childElementCount === 0) {
        const data = await getJson('/api/folders', { db: this.db, path });
        for (const child of data.folders) children.appendChild(this.makeBranch(child, depth + 1));
      }
    };
    node.querySelector('.expander').addEventListener('click', (e) => {
      e.stopPropagation();
      expand();
    });
    this.branches.set(path, { node, expand });
    return wrap;
  }

  select(node, path) {
    if (this.selected) this.selected.classList.remove('selected');
    node.classList.add('selected');
    this.selected = node;
    this.onSelect(path);
  }

  makeNode(label, path, depth) {
    const node = document.createElement('div');
    node.className = 'folder-node';
    node.style.paddingLeft = `${depth * 14 + 4}px`;
    const expander = document.createElement('span');
    expander.className = 'expander';
    if (path !== null) setIcon(expander, 'chevron-right');
    const name = document.createElement('span');
    name.textContent = label;
    node.append(expander, name);
    node.addEventListener('click', () => this.select(node, path));
    return node;
  }
}
