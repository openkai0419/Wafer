const KEY = 'wafer.ui';

let cache = null;

function read() {
  if (cache) return cache;
  try {
    cache = JSON.parse(localStorage.getItem(KEY)) || {};
  } catch {
    cache = {};
  }
  return cache;
}

export function load(key, fallback) {
  const value = read()[key];
  return value === undefined ? fallback : value;
}

export function save(key, value) {
  const data = read();
  data[key] = value;
  try {
    localStorage.setItem(KEY, JSON.stringify(data));
  } catch (e) {
    console.warn(`failed to persist UI state: ${e.message}`);
  }
}
