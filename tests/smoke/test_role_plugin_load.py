import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

from wafer.plugin.kinds import PLUGIN_KIND_COLLECTOR, PLUGIN_KIND_IMAGE_LOADER, PLUGIN_KIND_PARSER

TIMEOUT = 25
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PRELUDE = """
import json, sys
def modules(*names):
    return {n: any(m == n or m.startswith(n + '.') for m in sys.modules) for n in names}
def names(registry):
    return sorted(c.NAME for c in registry.list_all())
"""


def run_in_fresh_process(appdata, body, *args):
    env = {**os.environ, "WIN_PD_OVERRIDE_LOCAL_APPDATA": str(appdata)}
    result = subprocess.run(
        [sys.executable, "-c", PRELUDE + body, *args],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


BUILD_INDEX = """
from wafer.plugin.loader import load_plugins
from wafer.plugin.plugin_index import index_path, read_index
load_plugins(write_index=True)
records = read_index()
from wafer.plugin.settings import PluginSettings
PluginSettings().set_enabled_overrides({
    f'{p.kind}:{p.class_name}': True
    for r in records.values() for p in r.plugins
    if p.kind in ('collector', 'parser')
})
print(json.dumps({
    'path': index_path(),
    'plugins': [[p.kind, p.name] for r in records.values() for p in r.plugins],
}))
"""

_built = {}


def built_index():
    if not _built:
        appdata = tempfile.mkdtemp(prefix="wafer_role_smoke_")
        _built["appdata"] = appdata
        _built.update(run_in_fresh_process(appdata, BUILD_INDEX))
    return _built


def names_of(kind):
    return sorted({name for k, name in built_index()["plugins"] if k == kind})


COLLECTORS = [(PLUGIN_KIND_COLLECTOR, n) for n in names_of(PLUGIN_KIND_COLLECTOR)]
PARSERS = [(PLUGIN_KIND_PARSER, n) for n in names_of(PLUGIN_KIND_PARSER)]
WORKERS = COLLECTORS + PARSERS

WORKER_BODY = """
from wafer.plugin.loader import load_worker_plugins
kind, name = sys.argv[1], sys.argv[2]
load_worker_plugins(kind, name)
from wafer.plugin.collector.handler import collector_resolver
from wafer.plugin.parser.handler import parser_resolver
from wafer.plugin.imageloader.handler import image_loader_resolver
print(json.dumps({
    'collectors': names(collector_resolver.registry),
    'parsers': names(parser_resolver.registry),
    'loaders': names(image_loader_resolver.registry),
    'modules': modules('PySide6', 'numpy', 'cv2'),
}))
"""


@pytest.fixture(scope="module")
def index():
    return built_index()


def run_worker(index, kind, name):
    return run_in_fresh_process(index["appdata"], WORKER_BODY, kind, name)


def test_index_is_written(index):
    assert os.path.isfile(index["path"])
    assert WORKERS


@pytest.mark.parametrize("kind,name", WORKERS)
def test_worker_has_no_qt(index, kind, name):
    out = run_worker(index, kind, name)
    own = out["collectors"] if kind == PLUGIN_KIND_COLLECTOR else out["parsers"]
    other = out["parsers"] if kind == PLUGIN_KIND_COLLECTOR else out["collectors"]
    assert name in own
    assert not other
    assert set(names_of(PLUGIN_KIND_IMAGE_LOADER)) <= set(out["loaders"])
    assert not out["modules"]["PySide6"]


@pytest.mark.parametrize("kind,name", [w for w in WORKERS if w[1] != "mapping"])
def test_worker_has_no_numpy_until_it_decodes(index, kind, name):
    out = run_worker(index, kind, name)
    assert not out["modules"]["numpy"]
    assert not out["modules"]["cv2"]


def test_indexer_has_no_qt_and_every_worker_class(index):
    body = """
from wafer.plugin.loader import load_indexer_plugins
load_indexer_plugins()
from wafer.plugin.collector.handler import collector_resolver
from wafer.plugin.parser.handler import parser_resolver
print(json.dumps({
    'collectors': names(collector_resolver.registry),
    'parsers': names(parser_resolver.registry),
    'modules': modules('PySide6'),
}))
"""
    out = run_in_fresh_process(index["appdata"], body)
    assert set(out["collectors"]) == {n for _, n in COLLECTORS}
    assert set(out["parsers"]) == {n for _, n in PARSERS}
    assert not out["modules"]["PySide6"]


def make_png(path):
    from PIL import Image

    Image.new("RGB", (64, 48), (200, 30, 90)).save(path)
    return str(path)


def test_color_worker_decodes_without_qt(index, tmp_path):
    body = """
from wafer.plugin.loader import load_worker_plugins
load_worker_plugins('collector', 'color')
from wafer.plugin.imageloader.handler import image_loader_resolver
img = image_loader_resolver.load_pil(sys.argv[1])
print(json.dumps({'size': list(img.size), 'modules': modules('PySide6', 'numpy', 'cv2')}))
"""
    out = run_in_fresh_process(index["appdata"], body, make_png(tmp_path / "a.png"))
    assert out["size"] == [64, 48]
    assert out["modules"]["numpy"]
    assert out["modules"]["cv2"]
    assert not out["modules"]["PySide6"]


def test_first_decode_is_safe_from_many_threads(index, tmp_path):
    body = """
import threading
from wafer.plugin.loader import load_worker_plugins
load_worker_plugins('collector', 'color')
from wafer.plugin.imageloader.handler import image_loader_resolver
path = sys.argv[1]
results, errors = [], []
start = threading.Barrier(4)
def work():
    start.wait()
    for _ in range(5):
        try:
            results.append(image_loader_resolver.load_pil(path) is not None)
        except BaseException as exc:
            errors.append(repr(exc))
threads = [threading.Thread(target=work) for _ in range(4)]
[t.start() for t in threads]
[t.join() for t in threads]
print(json.dumps({'results': results, 'errors': errors}))
"""
    out = run_in_fresh_process(index["appdata"], body, make_png(tmp_path / "a.png"))
    assert out["errors"] == []
    assert out["results"] == [True] * 20


def test_full_load_has_no_requests_webengine_or_cv2(index):
    body = """
from wafer.plugin.loader import load_plugins
load_plugins()
print(json.dumps(modules('requests', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'cv2')))
"""
    out = run_in_fresh_process(index["appdata"], body)
    assert out == {k: False for k in out}


def test_preload_brings_cv2(index):
    body = """
from wafer.plugin.loader import load_worker_plugins
load_worker_plugins('collector', 'color')
before = modules('cv2')['cv2']
from wafer.plugin.imageloader.handler import image_loader_resolver
image_loader_resolver.preload()
print(json.dumps({'before': before, 'after': modules('cv2')['cv2']}))
"""
    out = run_in_fresh_process(index["appdata"], body)
    assert out == {"before": False, "after": True}


@pytest.mark.parametrize("kind,name", COLLECTORS[:1] + PARSERS[:1])
def test_stale_index_still_registers_the_worker(index, tmp_path, kind, name):
    body = """
import os
from wafer.plugin.plugin_index import index_path
os.makedirs(os.path.dirname(index_path()), exist_ok=True)
with open(index_path(), 'w', encoding='utf-8') as f:
    f.write('{broken')
from wafer.plugin.loader import load_worker_plugins
load_worker_plugins(sys.argv[1], sys.argv[2])
from wafer.plugin.collector.handler import collector_resolver
from wafer.plugin.parser.handler import parser_resolver
print(json.dumps({'collectors': names(collector_resolver.registry), 'parsers': names(parser_resolver.registry)}))
"""
    appdata = tmp_path / "appdata"
    shutil.copytree(index["appdata"], appdata)
    out = run_in_fresh_process(appdata, body, kind, name)
    assert name in (out["collectors"] if kind == PLUGIN_KIND_COLLECTOR else out["parsers"])
