from pathlib import Path
from PySide6 import QtCore
from source.utils.paths import get_resource_path
from source.utils.logs import AppLogger
from source.utils.json_io import read_json_file, write_json_file
_t_instance = None

def init_translator(json_path, default_locale='en'):
    global _t_instance
    _t_instance = TranslationManager(json_path, default_locale)

def get_translator():
    if _t_instance is None:
        raise RuntimeError('TranslationManager is not initialized. Call init_translator() first.')
    return _t_instance

class TranslationManager(QtCore.QObject):
    languageChanged = QtCore.Signal()

    def __init__(self, json_path, default_locale='en'):
        super().__init__()
        self.current_locale = default_locale
        self.json_path = json_path
        self.translations = {}
        self.missing_keys = set()
        self.load_translations()

    def __call__(self, english_text: str, **kwargs):
        if kwargs:
            return self.tr_format(english_text, **kwargs)
        return self.tr(english_text)
    
    def load_translations(self):
        self.translations = read_json_file(self.json_path, {})

    def tr(self, english_text):
        entry = self.translations.get(english_text)
        if not entry:
            self.missing_keys.add(english_text)
            return english_text
        translated = entry.get(self.current_locale, english_text)
        if translated == '':
            return english_text
        return translated

    def tr_format(self, english_text, **kwargs):
        template = self.tr(english_text)
        try:
            return template.format(**kwargs)
        except KeyError as e:
            AppLogger.warning(f'Missing format key: {e}')
            return template

    def set_locale(self, locale):
        if locale != self.current_locale:
            self.current_locale = locale
            self.languageChanged.emit()

    def dump_missing_keys(self, output_path=None, languages=None):
        if languages is None:
            languages = sorted({self.current_locale, 'en'})

        output_path = output_path or self.json_path
        existing = read_json_file(output_path, {})
        for v in existing.values():
            if isinstance(v, dict):
                languages = sorted(set(languages) | set(v.keys()))

        out = {}
        for k in sorted(self.missing_keys):
            out[k] = {lang: (k if lang == 'en' else '') for lang in languages}

        for k, v in existing.items():
            if k in out and isinstance(v, dict):
                out[k].update(v)
            else:
                out[k] = v

        write_json_file(output_path, out, indent=2, ensure_ascii=False)
        msg = f'Missing keys written to: {output_path}'
        AppLogger.info(msg)


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
                AppLogger.warning(f'method {method_name} not defined in {self}')
        return translator

    def set_translation_method(self, method_name):
        self._translation_method_name = method_name

init_translator(get_resource_path() / 'translations.json')
translator = get_translator()