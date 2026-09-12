import { getItems, thumbUrl, THUMB_SIZE_DEFAULT } from './api.js';
import { load } from './store.js';

const GAP = 4;
const PAGE = 200;
const OVERSCAN = 600;

export class Grid {
  constructor(scrollEl, canvasEl, onOpen) {
    this.scroll = scrollEl;
    this.canvas = canvasEl;
    this.onOpen = onOpen;
    this.db = '';
    this.queryId = '';
    this.total = 0;
    this.rows = [];
    this.items = new Map();
    this.pending = new Set();
    this.cells = new Map();
    this.scroll.addEventListener('scroll', () => this.render());
    new ResizeObserver(() => this.relayout()).observe(this.scroll);
    this.canvas.addEventListener('click', (e) => {
      const cell = e.target.closest('.cell');
      if (cell) this.onOpen(Number(cell.dataset.i));
    });
  }

  setQuery(db, queryId, aspects) {
    this.db = db;
    this.queryId = queryId;
    this.aspects = aspects;
    this.total = aspects.length;
    this.items.clear();
    this.pending.clear();
    this.scroll.scrollTop = 0;
    this.relayout();
  }

  relayout() {
    if (!this.aspects) return;
    const width = this.scroll.clientWidth - GAP;
    if (width <= 0) return;
    const rowHeight = load('thumbSize', THUMB_SIZE_DEFAULT);
    this.rows = [];
    let start = 0, sum = 0, y = GAP;
    for (let i = 0; i < this.total; i++) {
      const a = Math.min(Math.max(this.aspects[i] || 1, 0.2), 5);
      sum += a;
      const rowWidth = sum * rowHeight + (i - start) * GAP;
      if (rowWidth >= width || i === this.total - 1) {
        const scale = rowWidth >= width ? (width - (i - start) * GAP) / (sum * rowHeight) : 1;
        const h = Math.round(rowHeight * Math.min(scale, 1.5));
        this.rows.push({ start, end: i, y, h });
        y += h + GAP;
        start = i + 1;
        sum = 0;
      }
    }
    this.canvas.style.height = `${y}px`;
    this.cells.clear();
    this.canvas.textContent = '';
    this.render();
  }

  visibleRows() {
    const top = this.scroll.scrollTop - OVERSCAN;
    const bottom = this.scroll.scrollTop + this.scroll.clientHeight + OVERSCAN;
    return this.rows.filter((r) => r.y + r.h >= top && r.y <= bottom);
  }

  render() {
    if (!this.aspects) return;
    const visible = this.visibleRows();
    const wanted = new Set();
    for (const row of visible) {
      for (let i = row.start; i <= row.end; i++) wanted.add(i);
    }
    for (const [i, el] of this.cells) {
      if (!wanted.has(i)) {
        el.remove();
        this.cells.delete(i);
      }
    }
    for (const row of visible) this.renderRow(row);
    this.fetchMissing(wanted);
  }

  renderRow(row) {
    const width = this.scroll.clientWidth - GAP;
    let sum = 0;
    for (let i = row.start; i <= row.end; i++) sum += Math.min(Math.max(this.aspects[i] || 1, 0.2), 5);
    const avail = width - (row.end - row.start) * GAP;
    let x = GAP;
    for (let i = row.start; i <= row.end; i++) {
      const a = Math.min(Math.max(this.aspects[i] || 1, 0.2), 5);
      const w = Math.round((a / sum) * avail);
      let cell = this.cells.get(i);
      if (!cell) {
        cell = document.createElement('div');
        cell.className = 'cell';
        cell.dataset.i = i;
        this.canvas.appendChild(cell);
        this.cells.set(i, cell);
      }
      cell.style.cssText = `left:${x}px;top:${row.y}px;width:${w}px;height:${row.h}px`;
      this.fillCell(cell, i);
      x += w + GAP;
    }
  }

  fillCell(cell, i) {
    const item = this.items.get(i);
    if (!item || cell.dataset.filled === this.queryId + i) return;
    cell.dataset.filled = this.queryId + i;
    cell.title = item.name;
    const img = document.createElement('img');
    img.loading = 'lazy';
    img.src = thumbUrl(this.db, item.path);
    img.onerror = () => {
      const label = document.createElement('div');
      label.className = `placeholder ${item.kind}`;
      label.textContent = item.name;
      cell.replaceChildren(label);
    };
    cell.replaceChildren(img);
  }

  async fetchMissing(wanted) {
    const pages = new Set();
    for (const i of wanted) {
      if (!this.items.has(i)) pages.add(Math.floor(i / PAGE));
    }
    for (const page of pages) {
      if (this.pending.has(page)) continue;
      this.pending.add(page);
      const queryId = this.queryId;
      try {
        const data = await getItems(queryId, page * PAGE, PAGE);
        if (queryId !== this.queryId) continue;
        for (const item of data.items) this.items.set(item.i, item);
        this.render();
      } catch (e) {
        console.error(e);
      } finally {
        this.pending.delete(page);
      }
    }
  }

  item(i) {
    return this.items.get(i);
  }
}
