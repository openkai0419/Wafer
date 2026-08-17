import { getAspects, getJson, postQuery } from './api.js';
import { FolderTree } from './foldertree.js';
import { Grid } from './grid.js';
import { MetaPanel } from './meta.js';
import { Viewer } from './viewer.js';
import { connectEvents } from './ws.js';
import { load, save } from './store.js';

const state = {
  db: load('db', ''),
  folder: load('folder', null),
  keywords: load('keywords', ''),
  sort: load('sort', 'name'),
  ascending: load('ascending', true),
  queryId: '',
  total: 0,
};

const status = document.getElementById('status');
const dbSelect = document.getElementById('db-select');
const sortSelect = document.getElementById('sort-select');
const orderToggle = document.getElementById('order-toggle');
const searchInput = document.getElementById('search-input');

const meta = new MetaPanel();
const viewer = new Viewer(
  (index, item) => {
    if (meta.isOpen && item) meta.show(state.db, item);
  },
  () => {
    const item = grid.item(viewer.index);
    if (item) meta.isOpen ? meta.hide() : meta.show(state.db, item);
  },
);
const grid = new Grid(
  document.getElementById('grid-scroll'),
  document.getElementById('grid-canvas'),
  (index) => viewer.open(index, grid.item(index)),
);
const tree = new FolderTree(document.getElementById('folder-tree'), (path) => {
  state.folder = path;
  save('folder', path);
  runQuery();
});

function buildFilters() {
  const filters = [];
  if (state.folder) {
    filters.push({ name: 'directory', params: { directories: [state.folder], include_subfolders: true } });
  }
  if (state.keywords) {
    filters.push({ name: 'text', params: { keywords: state.keywords, keyword_separator: ' ', require_keys: false } });
  }
  return filters;
}

let queryToken = 0;
async function runQuery() {
  if (!state.db) return;
  const token = ++queryToken;
  status.textContent = 'searching...';
  try {
    const result = await postQuery(state.db, buildFilters(), state.sort, state.ascending);
    if (token !== queryToken) return;
    const aspects = await getAspects(result.query_id);
    if (token !== queryToken) return;
    state.queryId = result.query_id;
    state.total = result.total;
    grid.setQuery(state.db, result.query_id, aspects);
    viewer.setQuery(state.db, result.query_id, result.total);
    status.textContent = `${result.total} files`;
  } catch (e) {
    if (token === queryToken) status.textContent = `error: ${e.message}`;
  }
}

async function switchDb(db, restoreFolder = false) {
  state.db = db;
  save('db', db);
  if (!restoreFolder) {
    state.folder = null;
    save('folder', null);
  }
  await tree.load(db, restoreFolder ? state.folder : null);
  await runQuery();
}

async function fetchDbs(retries = 10) {
  for (let attempt = 0; ; attempt++) {
    const data = await getJson('/api/dbs');
    if (data.dbs.length > 0 || attempt >= retries) return data.dbs;
    status.textContent = 'waiting for database...';
    await new Promise((r) => setTimeout(r, 500));
  }
}

async function init() {
  const sorts = await getJson('/api/sorts');
  for (const name of sorts.sorts) {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    sortSelect.appendChild(opt);
  }
  if (!sorts.sorts.includes(state.sort)) state.sort = sorts.sorts[0] || 'name';
  sortSelect.value = state.sort;
  orderToggle.textContent = state.ascending ? '↑' : '↓';
  searchInput.value = state.keywords;
  const dbs = await fetchDbs();
  for (const name of dbs) {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    dbSelect.appendChild(opt);
  }
  if (dbs.length === 0) {
    status.textContent = 'no database found';
    return;
  }
  const saved = dbs.includes(state.db) ? state.db : dbs[0];
  dbSelect.value = saved;
  await switchDb(saved, saved === state.db);
}

dbSelect.addEventListener('change', () => switchDb(dbSelect.value));
sortSelect.addEventListener('change', () => {
  state.sort = sortSelect.value;
  save('sort', state.sort);
  runQuery();
});
orderToggle.addEventListener('click', () => {
  state.ascending = !state.ascending;
  save('ascending', state.ascending);
  orderToggle.textContent = state.ascending ? '↑' : '↓';
  runQuery();
});
searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    state.keywords = searchInput.value.trim();
    save('keywords', state.keywords);
    runQuery();
  }
});

setupSidebar();

function setupSidebar() {
  const sidebar = document.getElementById('sidebar');
  const resizer = document.getElementById('sidebar-resizer');
  const toggle = document.getElementById('sidebar-toggle');

  const setCollapsed = (collapsed) => {
    sidebar.classList.toggle('collapsed', collapsed);
    resizer.classList.toggle('hidden', collapsed);
    toggle.classList.toggle('hidden', !collapsed);
    save('sidebarCollapsed', collapsed);
  };

  setCollapsed(load('sidebarCollapsed', false));
  resizer.addEventListener('click', () => setCollapsed(true));
  toggle.addEventListener('click', () => setCollapsed(false));
}

let refreshTimer = null;
connectEvents((event) => {
  if (event.topic === 'update' && event.db === state.db) {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(runQuery, 1500);
  } else if (event.topic === 'db.created' || event.topic === 'db.deleted') {
    location.reload();
  }
});

init();
