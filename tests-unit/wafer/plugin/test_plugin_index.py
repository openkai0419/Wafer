import builtins
import json
import os
import subprocess
import sys
from pathlib import Path

from wafer._version import __version__
from wafer.plugin.plugin_index import (
    INDEX_SCHEMA,
    ExtensionRecord,
    PluginEntry,
    extension_fingerprint,
    read_index,
    write_index,
)

ROOT = Path(__file__).resolve().parents[3]


def make_ext(tmp_path):
    folder = tmp_path / "ext"
    folder.mkdir()
    (folder / "a.py").write_text("x = 1\n")
    return folder


def test_fingerprint_changes_when_a_py_file_changes(tmp_path):
    folder = make_ext(tmp_path)
    before = extension_fingerprint(str(folder))
    (folder / "a.py").write_text("x = 12345\n")
    assert extension_fingerprint(str(folder)) != before


def test_fingerprint_changes_when_mtime_changes(tmp_path):
    folder = make_ext(tmp_path)
    before = extension_fingerprint(str(folder))
    stat = (folder / "a.py").stat()
    os.utime(folder / "a.py", ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert extension_fingerprint(str(folder)) != before


def test_fingerprint_changes_when_a_py_file_is_added_or_removed(tmp_path):
    folder = make_ext(tmp_path)
    before = extension_fingerprint(str(folder))
    (folder / "b.py").write_text("")
    added = extension_fingerprint(str(folder))
    assert added != before
    (folder / "b.py").unlink()
    (folder / "a.py").unlink()
    assert extension_fingerprint(str(folder)) not in (before, added)


def test_fingerprint_includes_underscore_files_and_subfolders(tmp_path):
    folder = make_ext(tmp_path)
    before = extension_fingerprint(str(folder))
    (folder / "_helpers.py").write_text("")
    with_underscore = extension_fingerprint(str(folder))
    assert with_underscore != before
    (folder / "sub").mkdir()
    (folder / "sub" / "c.py").write_text("")
    assert extension_fingerprint(str(folder)) != with_underscore


def test_fingerprint_ignores_lib_pycache_and_non_py(tmp_path):
    folder = make_ext(tmp_path)
    before = extension_fingerprint(str(folder))
    (folder / "lib").mkdir()
    (folder / "lib" / "dep.py").write_text("")
    (folder / "__pycache__").mkdir()
    (folder / "__pycache__" / "a.cpython-312.pyc").write_text("")
    (folder / "__pycache__" / "z.py").write_text("")
    (folder / "README.md").write_text("")
    (folder / "data.json").write_text("{}")
    assert extension_fingerprint(str(folder)) == before


def test_fingerprint_does_not_read_contents(tmp_path, monkeypatch):
    folder = make_ext(tmp_path)

    def fail(*args, **kwargs):
        raise AssertionError("open called")

    monkeypatch.setattr(builtins, "open", fail)
    assert extension_fingerprint(str(folder))


def sample_records():
    return {
        "alpha": ExtensionRecord(
            fingerprint="abc",
            plugins=(
                PluginEntry(kind="collector", module="collector", class_name="AlphaCollector", name="alpha"),
                PluginEntry(kind="viewer", module="_helpers", class_name="AlphaViewer", name="alpha_viewer"),
            ),
        ),
        "empty": ExtensionRecord(fingerprint="def", plugins=()),
    }


def test_round_trip(tmp_path):
    path = str(tmp_path / "index.json")
    records = sample_records()
    assert write_index(records, path) is True
    assert read_index(path) == records
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    assert raw["schema"] == INDEX_SCHEMA
    assert raw["wafer_version"] == __version__
    assert raw["extensions"]["alpha"]["plugins"][0]["class"] == "AlphaCollector"


def test_read_index_rejects_missing_file(tmp_path):
    assert read_index(str(tmp_path / "none.json")) == {}


def test_read_index_rejects_truncated_json(tmp_path):
    path = tmp_path / "index.json"
    write_index(sample_records(), str(path))
    text = path.read_text(encoding="utf-8")
    path.write_text(text[: len(text) // 2], encoding="utf-8")
    assert read_index(str(path)) == {}


def write_raw(tmp_path, **overrides):
    data = {"schema": INDEX_SCHEMA, "wafer_version": __version__, "extensions": {}}
    data.update(overrides)
    path = tmp_path / "index.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_read_index_rejects_other_schema(tmp_path):
    ext = {"a": {"fingerprint": "x", "plugins": []}}
    assert read_index(write_raw(tmp_path, extensions=ext)) != {}
    assert read_index(write_raw(tmp_path, schema=INDEX_SCHEMA + 1, extensions=ext)) == {}


def test_read_index_rejects_other_wafer_version(tmp_path):
    ext = {"a": {"fingerprint": "x", "plugins": []}}
    assert read_index(write_raw(tmp_path, wafer_version="0.0.0-other", extensions=ext)) == {}


def test_read_index_rejects_wrong_shape(tmp_path):
    entry = {"kind": "k", "module": "m", "class": "C", "name": "n"}
    bad = [
        {"a": {"fingerprint": "x", "plugins": "nope"}},
        {"a": {"fingerprint": 1, "plugins": []}},
        {"a": {"plugins": []}},
        {"a": {"fingerprint": "x", "plugins": [{"kind": "k"}]}},
        {"a": {"fingerprint": "x", "plugins": [{**entry, "class": 3}]}},
        {"a": {"fingerprint": "x", "plugins": ["str"]}},
        {"a": []},
        [],
    ]
    for ext in bad:
        assert read_index(write_raw(tmp_path, extensions=ext)) == {}, ext
    path = tmp_path / "list.json"
    path.write_text("[]", encoding="utf-8")
    assert read_index(str(path)) == {}


def test_write_index_skips_when_unchanged(tmp_path):
    path = tmp_path / "index.json"
    records = sample_records()
    assert write_index(records, str(path)) is True
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    assert write_index(records, str(path)) is False
    assert path.stat().st_mtime_ns == 1_000_000_000
    records["new"] = ExtensionRecord(fingerprint="n", plugins=())
    assert write_index(records, str(path)) is True


def test_write_leaves_no_temp_file(tmp_path):
    path = tmp_path / "sub" / "index.json"
    write_index(sample_records(), str(path))
    write_index({}, str(path))
    assert [p.name for p in path.parent.iterdir()] == ["index.json"]


def test_import_does_not_pull_qt():
    code = (
        "import sys;import wafer.plugin.plugin_index;"
        "hit = sorted(m for m in sys.modules if m.split('.')[0] == 'PySide6');"
        "print(hit);sys.exit(1 if hit else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, f"pulled {result.stdout}\n{result.stderr}"
