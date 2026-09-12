import { getJson, THUMB_SIZE_DEFAULT } from './api.js';
import { QueryClient } from './query.js';
import { FolderTree } from './foldertree.js';
import { Grid } from './grid.js';
import { KeyPicker } from './keypicker.js';
import { MetaPanel } from './meta.js';
import { Viewer } from './viewer.js';
import { connectEvents } from './ws.js';
import { load, save } from './store.js';
import { setIcon } from './icons.js';

const state = {
  db: load('db', ''),
  folder: load('folder', null),
  keywords: load('keywords', ''),
  keys: load('searchKeys', []),
  sort: load('sort', 'name'),
  ascending: load('ascending', true),
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
  (item) => selectFolderOf(item),
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
const keyPicker = new KeyPicker(document.getElementById('key-picker'), document.getElementById('key-popup'), (keys) => {
  state.keys = keys;
  runQuery();
});

async function selectFolderOf(item) {
  const source = (item.source || item.path).replace(/\\/g, '/');
  const dir = source.slice(0, source.lastIndexOf('/'));
  viewer.close();
  if (!dir || !(await tree.reveal(dir))) status.textContent = 'folder not in tree';
}

function buildFilters() {
  const filters = [];
  if (state.folder) {
    filters.push({ name: 'directory', params: { directories: [state.folder], include_subfolders: true } });
  }
  if (state.keywords || state.keys.length) {
    const params = { keywords: state.keywords, keyword_separator: ' ', require_keys: !state.keywords };
    if (state.keys.length) params.keys = state.keys;
    filters.push({ name: 'text', params });
  }
  return filters;
}

let queryToken = 0;
async function runQuery() {
  if (!state.db) return;
  const token = ++queryToken;
  status.textContent = 'searching...';
  try {
    const client = new QueryClient();
    const result = await client.run(state.db, buildFilters(), state.sort, state.ascending);
    if (token !== queryToken) return;
    const aspects = await client.aspects();
    if (token !== queryToken) return;
    grid.setQuery(client, aspects);
    viewer.setQuery(client, result.total);
    status.textContent = `${result.total} files`;
  } catch (e) {
    if (token === queryToken) status.textContent = `error: ${e.message}`;
  }
}

async function switchDb(db, restoreFolder = false) {
  state.db = db;
  save('db', db);
  keyPicker.setDb(db);
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
  setOrderIcon();
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
  setOrderIcon();
  runQuery();
});
searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    state.keywords = searchInput.value.trim();
    save('keywords', state.keywords);
    runQuery();
  }
});

function setOrderIcon() {
  setIcon(orderToggle, state.ascending ? 'chevron-up' : 'chevron-down');
  orderToggle.setAttribute('aria-label', state.ascending ? 'sort ascending' : 'sort descending');
}

setupSidebar();
setupSettings();

function setupSidebar() {
  const sidebar = document.getElementById('sidebar');
  const toggle = document.getElementById('sidebar-toggle');

  const setCollapsed = (collapsed) => {
    sidebar.classList.toggle('collapsed', collapsed);
    setIcon(toggle, collapsed ? 'chevron-right' : 'chevron-left');
    toggle.setAttribute('aria-label', collapsed ? 'show sidebar' : 'hide sidebar');
    save('sidebarCollapsed', collapsed);
  };

  setCollapsed(load('sidebarCollapsed', false));
  toggle.addEventListener('click', () => setCollapsed(sidebar.classList.contains('collapsed') === false));
}

function setupSettings() {
  const button = document.getElementById('settings-btn');
  const modal = document.getElementById('settings-modal');
  const thumbSelect = document.getElementById('thumb-size');
  setIcon(button, 'menu');
  for (const px of [128, 192, 256, 384, 512, 768, 1024]) {
    const opt = document.createElement('option');
    opt.value = String(px);
    opt.textContent = String(px);
    thumbSelect.appendChild(opt);
  }
  thumbSelect.value = String(load('thumbSize', THUMB_SIZE_DEFAULT));
  thumbSelect.addEventListener('change', () => {
    save('thumbSize', Number(thumbSelect.value));
    grid.relayout();
  });
  button.addEventListener('click', () => modal.classList.remove('hidden'));
  modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.classList.add('hidden');
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') modal.classList.add('hidden');
  });
}

const connBanner = document.getElementById('conn-banner');

let refreshTimer = null;
connectEvents(
  (event) => {
    if (event.topic === 'update' && event.db === state.db) {
      keyPicker.invalidate();
      clearTimeout(refreshTimer);
      refreshTimer = setTimeout(runQuery, 1500);
    } else if (event.topic === 'db.created' || event.topic === 'db.deleted') {
      location.reload();
    }
  },
  (status) => {
    connBanner.classList.toggle('hidden', status !== 'closed');
  },
);

init();
