import json
from pathlib import Path
from PySide6 import QtCore
from ..common.funcs import get_resource_path

class TranslationManager(QtCore.QObject):
    languageChanged = QtCore.Signal()

    def __init__(self, json_path, default_locale='en'):
        super().__init__()
        self.current_locale = default_locale
        self.json_path = json_path
        self.translations = {}
        self.missing_keys = set()
        self.load_translations()

    def load_translations(self):
        if self.json_path.exists():
            with open(self.json_path, encoding='utf-8') as f:
                self.translations = json.load(f)
        else:
            self.translations = {}

    def tr(self, english_text):
        entry = self.translations.get(english_text)
        if not entry:
            self.missing_keys.add(english_text)
            return english_text
        translated = entry.get(self.current_locale, english_text)
        if translated == '':
            return english_text
        return translated

    def trf(self, english_text, **kwargs):
        template = self.tr(english_text)
        try:
            return template.format(**kwargs)
        except KeyError as e:
            print(f'[WARN] Missing format key: {e}')
            return template

    def set_locale(self, locale):
        if locale != self.current_locale:
            self.current_locale = locale
            self.languageChanged.emit()

    def dump_missing_keys(self, output_path=None, languages=None):
        if languages is None:
            languages = [self.current_locale] if self.current_locale != 'en' else ['ja']
        out = {k: {lang: '' for lang in languages} for k in sorted(self.missing_keys)}
        output_path = output_path or self.json_path
        if output_path.exists():
            with open(output_path, encoding='utf-8') as f:
                existing = json.load(f)
            for k, v in existing.items():
                if k in out:
                    v.update(out[k])
                    out[k] = v
                else:
                    out[k] = v
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print(f'Missing keys written to: {output_path}')
_t_instance = None

def init_translator(json_path, default_locale='en'):
    global _t_instance
    _t_instance = TranslationManager(json_path, default_locale)

def get_translator():
    if _t_instance is None:
        raise RuntimeError('TranslationManager is not initialized. Call init_translator() first.')
    return _t_instance

class TranslatorMixin:
    _default_update_method_name = 'update_translation'

    @property
    def t(self):
        translator = get_translator()
        if not hasattr(self, '_translator_connected'):
            self._translator_connected = True
            method_name = getattr(self, '_translation_method_name', self._default_update_method_name)
            if hasattr(self, method_name):
                getattr(translator.languageChanged, 'connect')(getattr(self, method_name))
            else:
                print(f'[WARN] method {method_name} not defined in {self}')
        return translator

    def set_translation_method(self, method_name):
        self._translation_method_name = method_name
init_translator(get_resource_path() / 'translations.json')
