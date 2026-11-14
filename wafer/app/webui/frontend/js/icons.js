function gear({ teeth = 8, outer = 10, inner = 6.3, hole = 2.6 } = {}) {
  const corners = teeth * 4;
  const points = Array.from({ length: corners }, (_, i) => {
    const angle = (2 * Math.PI * i) / corners - Math.PI / 2;
    const radius = i % 4 === 0 || i % 4 === 3 ? inner : outer;
    return `${(12 + radius * Math.cos(angle)).toFixed(2)} ${(12 + radius * Math.sin(angle)).toFixed(2)}`;
  });
  const circle = `M${12 + hole} 12a${hole} ${hole} 0 1 0 ${-2 * hole} 0a${hole} ${hole} 0 1 0 ${2 * hole} 0Z`;
  return `<path fill="currentColor" stroke="none" fill-rule="evenodd" d="M${points.join('L')}Z${circle}"/>`;
}

const PATHS = {
  gear: gear(),
  'chevron-left': '<polyline points="15 18 9 12 15 6"/>',
  'chevron-right': '<polyline points="9 18 15 12 9 6"/>',
  'chevron-up': '<polyline points="18 15 12 9 6 15"/>',
  'chevron-down': '<polyline points="6 9 12 15 18 9"/>',
  menu: '<line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/>',
  close: '<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>',
  info: '<circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16"/><line x1="12" y1="8" x2="12" y2="8"/>',
  refresh: '<path d="M20 12a8 8 0 1 1-2.34-5.66"/><polyline points="20 4 20 9 15 9"/>',
  filter: '<polygon points="3 5 21 5 14 13 14 19 10 21 10 13"/>',
};

export function icon(name) {
  return `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${PATHS[name]}</svg>`;
}

export function setIcon(el, name) {
  el.innerHTML = icon(name);
}

export function setTip(el, text) {
  el.title = text;
  el.setAttribute('aria-label', text);
}
