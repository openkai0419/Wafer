import json

from wafer.core.lang.manager import TranslationManager


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_dump_writes_empty_dict_for_new_keys(tmp_path):
    path = tmp_path / "translations.json"
    path.write_text("{}", encoding="utf-8")
    tm = TranslationManager(str(path), "en")
    tm("Hello")
    tm("World")

    tm.dump_missing_keys()

    assert _read(path) == {"Hello": {}, "World": {}}


def test_dump_preserves_existing_translations(tmp_path):
    path = tmp_path / "translations.json"
    path.write_text(json.dumps({"Hello": {"ja": "こんにちは"}}), encoding="utf-8")
    tm = TranslationManager(str(path), "en")
    tm("World")

    tm.dump_missing_keys()

    assert _read(path) == {"Hello": {"ja": "こんにちは"}, "World": {}}


def test_dump_works_in_english_session(tmp_path):
    path = tmp_path / "translations.json"
    path.write_text("{}", encoding="utf-8")
    tm = TranslationManager(str(path), "en")
    tm("Only key")

    tm.dump_missing_keys()

    assert _read(path) == {"Only key": {}}


def test_dump_noop_when_nothing_missing(tmp_path):
    path = tmp_path / "translations.json"
    tm = TranslationManager(str(path), "en")

    tm.dump_missing_keys()

    assert not path.exists()
