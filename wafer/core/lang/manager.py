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

    def dump_missing_keys(self, output_path=None, languages=None):
        if languages is None:
            languages = sorted({self.current_locale, "en"})

        output_path = output_path or self.json_path
        existing = read_json_file(output_path, {})
        for v in existing.values():
            if isinstance(v, dict):
                languages = sorted(set(languages) | set(v.keys()))

        out = {}
        for k in sorted(self.missing_keys):
            out[k] = {lang: (k if lang == "en" else "") for lang in languages}

        for k, v in existing.items():
            if k in out and isinstance(v, dict):
                out[k].update(v)
            else:
                out[k] = v

        write_json_file(output_path, out, indent=2, ensure_ascii=False)
        msg = f"Missing keys written to: {output_path}"
        AppLogger.info(msg)


init_translator(get_resource_path() / "translations.json")
translator = get_translator()
t = translator
