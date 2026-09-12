import { load } from './store.js';

export async function getJson(path, params) {
  const url = params ? `${path}?${new URLSearchParams(params)}` : path;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

export async function postQuery(db, filters, sort, ascending) {
  const res = await fetch('/api/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ db, filters, sort, ascending }),
  });
  if (!res.ok) throw new Error(`query: ${res.status}`);
  return res.json();
}

export async function getAspects(queryId) {
  const res = await fetch(`/api/query/${queryId}/aspects`);
  if (!res.ok) throw new Error(`aspects: ${res.status}`);
  return new Float32Array(await res.arrayBuffer());
}

export function getItems(queryId, offset, limit) {
  return getJson(`/api/query/${queryId}/items`, { offset, limit });
}

export function fileUrl(db, path) {
  return `/api/file?${new URLSearchParams({ db, path })}`;
}

export const THUMB_SIZE_DEFAULT = 256;

export function thumbUrl(db, path, size = load('thumbSize', THUMB_SIZE_DEFAULT)) {
  return `/api/thumb?${new URLSearchParams({ db, path, size })}`;
}

export function getKeys(db) {
  return getJson('/api/keys', { db });
}
