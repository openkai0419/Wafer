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


def test_dump_noop_when_nothing_missing(tmp_path):
    path = tmp_path / "translations.json"
    tm = TranslationManager(str(path), "en")

    tm.dump_missing_keys()

    assert not path.exists()


def test_dump_keeps_an_unreadable_file(tmp_path):
    path = tmp_path / "translations.json"
    tm = TranslationManager(str(path), "en")
    path.write_text('{"Hello": {"ja": ', encoding="utf-8")
    tm("World")

    tm.dump_missing_keys()

    assert path.read_text(encoding="utf-8") == '{"Hello": {"ja": '


def test_dump_skips_writing_when_every_missing_key_is_already_listed(tmp_path):
    path = tmp_path / "translations.json"
    path.write_text('{"Hello": {}}', encoding="utf-8")
    tm = TranslationManager(str(path), "en")
    tm("Hello")

    tm.dump_missing_keys()

    assert path.read_text(encoding="utf-8") == '{"Hello": {}}'


def test_dump_merges_keys_another_process_wrote_meanwhile(tmp_path):
    path = tmp_path / "translations.json"
    path.write_text("{}", encoding="utf-8")
    first = TranslationManager(str(path), "en")
    second = TranslationManager(str(path), "en")
    first("A")
    second("B")

    first.dump_missing_keys()
    second.dump_missing_keys()

    assert _read(path) == {"A": {}, "B": {}}
