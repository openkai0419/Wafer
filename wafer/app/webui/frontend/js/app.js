import { getJson, THUMB_SIZE_DEFAULT, THUMB_STEPS } from './api.js';
import { QueryClient } from './query.js';
import { FolderTree } from './foldertree.js';
import { Grid } from './grid.js';
import { KeyPicker } from './keypicker.js';
import { SearchOptions, KEYWORD_MODE_DEFAULT, KEYWORD_SEPARATOR_DEFAULT } from './searchoptions.js';
import { MetaPanel } from './meta.js';
import { Viewer } from './viewer.js';
import { connectEvents } from './ws.js';
import { debounce } from './ratelimit.js';
import { AutoScroll, SPEED_STEPS, SPEED_DEFAULT, nearestSpeedIndex } from './autoscroll.js';
import { load, save } from './store.js';
import { setIcon } from './icons.js';

const SEARCH_DEBOUNCE_MS = 250;
const UPDATE_REFRESH_MS = 1500;

const state = {
  db: load('db', ''),
  folder: load('folder', null),
  keywords: load('keywords', ''),
  keys: load('searchKeys', []),
  keywordMode: load('keywordMode', KEYWORD_MODE_DEFAULT),
  separator: load('keywordSeparator', KEYWORD_SEPARATOR_DEFAULT),
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
const autoScroll = new AutoScroll(document.getElementById('grid-scroll'), document.getElementById('grid-canvas'), (running) => {
  const toggle = document.getElementById('auto-scroll-toggle');
  toggle.classList.toggle('active', running);
  toggle.textContent = running ? 'on' : 'off';
});
const tree = new FolderTree(document.getElementById('folder-tree'), (path) => {
  state.folder = path;
  save('folder', path);
  runQuery();
});
const searchPopup = document.getElementById('key-popup');
const keyPicker = new KeyPicker(document.getElementById('key-picker'), searchPopup, (keys) => {
  state.keys = keys;
  runQuery();
});
const searchOptions = new SearchOptions(searchPopup, () => {
  state.keywordMode = searchOptions.mode;
  state.separator = searchOptions.separator;
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
    const params = {
      keywords: state.keywords,
      keyword_separator: state.separator,
      keyword_mode: state.keywordMode,
      require_keys: !state.keywords,
    };
    if (state.keys.length) params.keys = state.keys;
    filters.push({ name: 'text', params });
  }
  return filters;
}

let queryToken = 0;
let lastSnapshot = '';
async function runQuery(force = false) {
  if (!state.db) return;
  const filters = buildFilters();
  const snapshot = JSON.stringify([state.db, filters, state.sort, state.ascending]);
  if (!force && snapshot === lastSnapshot) return;
  lastSnapshot = snapshot;
  const token = ++queryToken;
  status.textContent = 'searching...';
  status.classList.add('busy');
  try {
    const client = new QueryClient();
    const result = await client.run(state.db, filters, state.sort, state.ascending);
    if (token !== queryToken) return;
    const aspects = await client.aspects();
    if (token !== queryToken) return;
    grid.setQuery(client, aspects);
    viewer.setQuery(client, client.total);
    status.textContent = `${result.total} files`;
  } catch (e) {
    if (token === queryToken) {
      lastSnapshot = '';
      status.textContent = `error: ${e.message}`;
    }
  } finally {
    if (token === queryToken) status.classList.remove('busy');
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
  keyPicker.loadCatalog();
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
function commitKeywords() {
  state.keywords = searchInput.value.trim();
  save('keywords', state.keywords);
  runQuery();
}

const requestSearch = debounce(SEARCH_DEBOUNCE_MS, commitKeywords);
let composing = false;

searchInput.addEventListener('compositionstart', () => {
  composing = true;
});
searchInput.addEventListener('compositionend', () => {
  composing = false;
  requestSearch();
});
searchInput.addEventListener('blur', () => {
  composing = false;
});
searchInput.addEventListener('input', () => {
  if (!composing) requestSearch();
});
searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.isComposing) requestSearch.flush();
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
  for (const px of THUMB_STEPS) {
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
  const scrollToggle = document.getElementById('auto-scroll-toggle');
  const speedSlider = document.getElementById('auto-scroll-speed');
  const speedValue = document.getElementById('auto-scroll-speed-value');
  speedSlider.max = String(SPEED_STEPS.length - 1);
  const showSpeed = () => {
    speedSlider.value = String(nearestSpeedIndex(autoScroll.speed));
    speedValue.value = String(autoScroll.speed);
  };
  showSpeed();
  scrollToggle.addEventListener('click', () => autoScroll.toggle());
  speedSlider.addEventListener('input', () => {
    autoScroll.setSpeed(SPEED_STEPS[Number(speedSlider.value)]);
    showSpeed();
  });
  speedValue.addEventListener('change', () => {
    autoScroll.setSpeed(Number(speedValue.value) || SPEED_DEFAULT);
    showSpeed();
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

const refreshQuery = debounce(UPDATE_REFRESH_MS, () => runQuery(true));
connectEvents(
  (event) => {
    if (event.topic === 'update' && event.db === state.db) {
      keyPicker.invalidate();
      refreshQuery();
    } else if (event.topic === 'db.created' || event.topic === 'db.deleted') {
      location.reload();
    }
  },
  (connState) => {
    connBanner.classList.toggle('hidden', connState !== 'closed');
  },
);

init();
