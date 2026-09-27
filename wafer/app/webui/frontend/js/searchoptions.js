import { load, save } from './store.js';

export const KEYWORD_MODE_DEFAULT = 'AND';
export const KEYWORD_SEPARATOR_DEFAULT = ',';

export class SearchOptions {
  constructor(popup, onChange, directOnly = false) {
    this.onChange = onChange;
    this.mode = load('keywordMode', KEYWORD_MODE_DEFAULT);
    this.separator = load('keywordSeparator', KEYWORD_SEPARATOR_DEFAULT);
    this.modeButtons = [...popup.querySelectorAll('#keyword-mode button')];
    this.separatorInput = popup.querySelector('#keyword-separator');
    this.separatorInput.value = this.separator;
    this.directOnly = directOnly;
    this.directOnlyInput = popup.querySelector('#direct-only');
    this.directOnlyInput.checked = directOnly;
    this.renderMode();
    for (const button of this.modeButtons) {
      button.addEventListener('click', () => this.setMode(button.dataset.mode));
    }
    this.separatorInput.addEventListener('change', () => this.setSeparator(this.separatorInput.value));
    this.directOnlyInput.addEventListener('change', () => this.setDirectOnly(this.directOnlyInput.checked));
  }

  setMode(mode) {
    if (mode === this.mode) return;
    this.mode = mode;
    save('keywordMode', mode);
    this.renderMode();
    this.onChange();
  }

  setSeparator(value) {
    const separator = value || KEYWORD_SEPARATOR_DEFAULT;
    this.separatorInput.value = separator;
    if (separator === this.separator) return;
    this.separator = separator;
    save('keywordSeparator', separator);
    this.onChange();
  }

  setDirectOnly(value, notify = true) {
    this.directOnlyInput.checked = value;
    if (value === this.directOnly) return;
    this.directOnly = value;
    if (notify) this.onChange();
  }

  renderMode() {
    for (const button of this.modeButtons) {
      button.classList.toggle('active', button.dataset.mode === this.mode);
    }
  }
}
