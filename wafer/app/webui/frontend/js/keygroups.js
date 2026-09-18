export function keyPrefix(key) {
  const dot = key.indexOf('.');
  return dot > 0 ? key.slice(0, dot) : '';
}

export function stripPrefix(key) {
  const dot = key.indexOf('.');
  return dot > 0 ? key.slice(dot + 1) : key;
}

export function groupEntriesByPrefix(entries) {
  const groups = new Map();
  for (const entry of entries) {
    const prefix = keyPrefix(entry[0]);
    if (!groups.has(prefix)) groups.set(prefix, []);
    groups.get(prefix).push(entry);
  }
  return [...groups].sort(([a], [b]) => (a === '' || b === '' ? (a === '' ? -1 : 1) : a.localeCompare(b)));
}
