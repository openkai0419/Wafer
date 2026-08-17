import asyncio
import io
import os
import zipfile

import pytest
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from wafer.core.db.file_db import FileDB
from wafer.core.db.setting_db import SettingDB
from wafer.utils.paths import normalize_path
from wafer.utils.virtual_paths import build_virtual_path

DB_NAME = "testdb"


@pytest.fixture(scope="session")
def dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp("webui")
    images = root / "images"
    (images / "sub").mkdir(parents=True)
    specs = [
        ("a_cat.png", (100, 50), "cat"),
        ("b_dog.png", (50, 100), "dog"),
        ("sub/c_cat.png", (80, 80), "cat"),
    ]
    files = []
    for rel, size, animal in specs:
        p = images / rel
        Image.new("RGB", size, "red").save(p)
        files.append((normalize_path(p), size[0] / size[1], animal))
    note = images / "note.txt"
    note.write_text("hello")
    files.append((normalize_path(note), 1.0, "none"))

    zip_path = images / "archive.zip"
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "blue").save(buf, format="PNG")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("inner.png", buf.getvalue())
    zip_source = normalize_path(zip_path)
    virtual = build_virtual_path(zip_source, "inner.png")

    (root / "data").mkdir()
    (root / "dirs").mkdir()
    db = FileDB(root / "data" / f"{DB_NAME}.db")
    db.start()
    db.initialize_database()
    sources, imgs, metas, tags = [], [], [], []
    for i, (path, aspect, animal) in enumerate(files):
        stat = os.stat(path)
        sources.append((path, f"hash{i}", stat.st_size, stat.st_mtime))
        imgs.append((path, path, aspect))
        metas.append((path, "prompt", f"a {animal} picture", None))
        tags.append((f"hash{i}", "animal", animal, None))
    zip_stat = os.stat(zip_path)
    sources.append((zip_source, "hashzip", zip_stat.st_size, zip_stat.st_mtime))
    imgs.append((virtual, zip_source, 1.5))
    db.upsert_batches(sources, imgs, metas, tags)
    db.close()

    setting = SettingDB(str(root / "dirs" / f"{DB_NAME}.db"))
    setting.add_parent_folder(normalize_path(images))
    setting.add_ignore_folder(normalize_path(images / "ignored"))

    return {"root": root, "images": normalize_path(images), "files": files, "virtual": virtual, "zip_source": zip_source}


@pytest.fixture
def app(dataset, monkeypatch, tmp_path):
    root = dataset["root"]
    monkeypatch.setattr("wafer.app.webui.backend.session.data_db_path", lambda name: str(root / "data" / f"{name}.db"))
    monkeypatch.setattr("wafer.app.webui.backend.session.list_data_db_names", lambda: [DB_NAME])
    monkeypatch.setattr("wafer.app.webui.backend.api.setting_db_path", lambda name: str(root / "dirs" / f"{name}.db"))
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    monkeypatch.setattr("wafer.app.webui.backend.media.thumb_cache_dir", lambda: str(thumbs))
    from wafer.app.webui.backend.media import MEDIA_EXECUTOR
    from wafer.app.webui.backend.server import create_app
    from wafer.app.webui.backend.session import QUERY_SERVICE
    from wafer.plugin.imageloader.handler import image_loader_resolver
    from extensions.image.loader import ImageFileLoader
    from extensions.zip.resolver import ZipImageLoader

    image_loader_resolver.registry.register(ImageFileLoader)
    image_loader_resolver.registry.register(ZipImageLoader)

    application = create_app(with_events=False)
    yield application
    application[QUERY_SERVICE].close()
    application[MEDIA_EXECUTOR].shutdown(wait=True, cancel_futures=True)


@pytest.fixture
def client(app):
    loop = asyncio.new_event_loop()

    async def start():
        c = TestClient(TestServer(app))
        await c.start_server()
        return c

    test_client = loop.run_until_complete(start())

    class SyncClient:
        def __init__(self):
            self.loop = loop
            self.raw = test_client

        def request(self, method, path, **kwargs):
            return loop.run_until_complete(self._request(method, path, **kwargs))

        async def _request(self, method, path, **kwargs):
            resp = await test_client.request(method, path, **kwargs)
            body = await resp.read()
            return resp, body

        def get(self, path, **kwargs):
            return self.request("GET", path, **kwargs)

        def post(self, path, **kwargs):
            return self.request("POST", path, **kwargs)

    yield SyncClient()
    loop.run_until_complete(test_client.close())
    loop.close()


@pytest.fixture
def query(client):
    import json

    def _query(db, filters=None, sort="none", ascending=True):
        resp, body = client.post("/api/query", json={"db": db, "filters": filters or [], "sort": sort, "ascending": ascending})
        assert resp.status == 200, body
        data = json.loads(body)
        return data["query_id"], data["total"]

    return _query
