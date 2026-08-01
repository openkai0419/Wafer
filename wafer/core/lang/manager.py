from ...utils.paths import get_resource_path
from ...utils.logs import AppLogger
from ...utils.json_io import read_json_file, write_json_file

_t_instance = None


def init_translator(json_path, default_locale="en"):
    global _t_instance
    _t_instance = TranslationManager(json_path, default_locale)


def get_translator():
    if _t_instance is None:
        raise RuntimeError("TranslationManager is not initialized. Call init_translator() first.")
    return _t_instance


class TranslationManager:
    def __init__(self, json_path, default_locale="en"):
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
        if translated == "":
            return english_text
        return translated

    def tr_format(self, english_text, **kwargs):
        template = self.tr(english_text)
        try:
            return template.format(**kwargs)
        except KeyError as e:
            AppLogger.warning(f"Missing format key: {e}")
            return template

    def set_locale(self, locale):
        self.current_locale = locale

    def dump_missing_keys(self, output_path=None):
        output_path = output_path or self.json_path
        existing = read_json_file(output_path, {})

        keys = sorted(set(self.missing_keys) | set(existing))
        if not keys:
            return
        out = {k: existing.get(k, {}) for k in keys}

        write_json_file(output_path, out, indent=2, ensure_ascii=False)
        AppLogger.info(f"Missing keys written to: {output_path}")


init_translator(get_resource_path() / "translations.json")
translator = get_translator()
t = translator
