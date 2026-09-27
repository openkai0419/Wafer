import { load, save } from './store.js';

export const KEYWORD_MODE_DEFAULT = 'AND';
export const KEYWORD_SEPARATOR_DEFAULT = ',';

export class SearchOptions {
  constructor(popup, onChange) {
    this.onChange = onChange;
    this.mode = load('keywordMode', KEYWORD_MODE_DEFAULT);
    this.separator = load('keywordSeparator', KEYWORD_SEPARATOR_DEFAULT);
    this.modeButtons = [...popup.querySelectorAll('#keyword-mode button')];
    this.separatorInput = popup.querySelector('#keyword-separator');
    this.separatorInput.value = this.separator;
    this.renderMode();
    for (const button of this.modeButtons) {
      button.addEventListener('click', () => this.setMode(button.dataset.mode));
    }
    this.separatorInput.addEventListener('change', () => this.setSeparator(this.separatorInput.value));
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

  renderMode() {
    for (const button of this.modeButtons) {
      button.classList.toggle('active', button.dataset.mode === this.mode);
    }
  }
}
