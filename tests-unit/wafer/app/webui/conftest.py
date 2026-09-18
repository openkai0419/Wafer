import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from test_support.webui_dataset import DB_NAME, build_webui_dataset


@pytest.fixture(scope="session")
def dataset(tmp_path_factory):
    return build_webui_dataset(tmp_path_factory.mktemp("webui"))


@pytest.fixture
def app(dataset, monkeypatch, tmp_path):
    root = dataset["root"]
    monkeypatch.setattr("wafer.app.webui.backend.session.data_db_path", lambda name: str(root / "data" / f"{name}.db"))
    monkeypatch.setattr("wafer.app.webui.backend.session.list_data_db_names", lambda: [DB_NAME])
    monkeypatch.setattr("wafer.app.webui.backend.api.setting_db_path", lambda name: str(root / "dirs" / f"{name}.db"))
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    monkeypatch.setattr("wafer.web.media.thumb_cache_dir", lambda: str(thumbs))
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
    asyncio.run(application[QUERY_SERVICE].close())
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
