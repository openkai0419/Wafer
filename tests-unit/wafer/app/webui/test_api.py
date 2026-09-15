import json
import struct

import pytest

DB = "testdb"


def jbody(body):
    return json.loads(body)


def test_dbs(client):
    resp, body = client.get("/api/dbs")
    assert resp.status == 200
    assert jbody(body)["dbs"] == [DB]


def test_favicon(client):
    resp, body = client.get("/favicon.ico")
    assert resp.status == 200
    assert resp.content_type in ("image/vnd.microsoft.icon", "image/x-icon")
    assert len(body) > 0


def test_query_all(client):
    resp, body = client.post("/api/query", json={"db": DB})
    assert resp.status == 200
    data = jbody(body)
    assert data["total"] == 5
    assert data["query_id"]


def test_query_unknown_db(client):
    resp, _ = client.post("/api/query", json={"db": "nope"})
    assert resp.status == 404


def test_query_unknown_filter(client):
    resp, _ = client.post("/api/query", json={"db": DB, "filters": [{"name": "nope"}]})
    assert resp.status == 400


def test_query_invalid_json(client):
    resp, _ = client.post("/api/query", data=b"not json", headers={"Content-Type": "application/json"})
    assert resp.status == 400


def test_query_text_filter(client, query):
    qid, total = query(DB, filters=[{"name": "text", "params": {"keys": ["prompt"], "keywords": "cat"}}])
    assert total == 2


def test_query_keys_only(client, query):
    qid, total = query(DB, filters=[{"name": "text", "params": {"keys": ["prompt"], "keywords": "", "require_keys": True}}])
    assert total == 4


def test_query_directory_filter(client, dataset, query):
    qid, total = query(DB, filters=[{"name": "directory", "params": {"directories": [dataset["images"] + "/sub"], "include_subfolders": True}}])
    assert total == 1


def test_items(client, dataset, query):
    qid, total = query(DB, sort="name", ascending=True)
    resp, body = client.get(f"/api/query/{qid}/items?offset=0&limit=2")
    assert resp.status == 200
    items = jbody(body)["items"]
    assert len(items) == 2
    assert items[0]["i"] == 0
    assert items[0]["name"] == "a_cat.png"
    assert items[0]["kind"] == "image"
    assert items[1]["name"] == "b_dog.png"
    resp, body = client.get(f"/api/query/{qid}/items?offset=4&limit=10")
    items = jbody(body)["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "other"


def test_items_invalid_offset(client, query):
    qid, _ = query(DB)
    resp, _ = client.get(f"/api/query/{qid}/items?offset=x")
    assert resp.status == 400


def test_aspects_binary(client, query):
    qid, total = query(DB, sort="name", ascending=True)
    resp, body = client.get(f"/api/query/{qid}/aspects")
    assert resp.status == 200
    assert resp.content_type == "application/octet-stream"
    assert len(body) == total * 4
    values = struct.unpack(f"<{total}f", body)
    assert abs(values[0] - 2.0) < 1e-6
    assert abs(values[1] - 0.5) < 1e-6


def test_query_session_not_found(client):
    resp, _ = client.get("/api/query/deadbeef/items")
    assert resp.status == 404


def test_meta(client, dataset):
    path = dataset["files"][0][0]
    resp, body = client.get("/api/meta", params={"db": DB, "path": path})
    assert resp.status == 200
    data = jbody(body)
    assert data["meta"]["prompt"]["value"] == "a cat picture"
    assert data["tags"]["animal"]["value"] == "cat"
    assert data["file_hash"] == "hash0"


def test_folders_roots(client, dataset):
    resp, body = client.get("/api/folders", params={"db": DB})
    assert resp.status == 200
    assert jbody(body)["folders"] == [dataset["images"]]


def test_folders_children(client, dataset):
    resp, body = client.get("/api/folders", params={"db": DB, "path": dataset["images"]})
    assert resp.status == 200
    assert jbody(body)["folders"] == [dataset["images"] + "/sub"]


def test_folders_outside_root(client):
    resp, _ = client.get("/api/folders", params={"db": DB, "path": "C:/Windows"})
    assert resp.status == 403


def test_filters_exclude_internal(client):
    resp, body = client.get("/api/filters")
    names = [f["name"] for f in jbody(body)["filters"]]
    assert "text" in names
    assert "directory" in names
    assert "contained_files" not in names
    assert "source_children" not in names


def test_keys(client):
    resp, body = client.get("/api/keys", params={"db": DB})
    assert resp.status == 200
    keys = jbody(body)["keys"]
    assert all(isinstance(k, str) and isinstance(n, int) for k, n in keys)
    names = [k for k, _ in keys]
    assert "prompt" in names
    assert "path" in names
    freqs = [n for _, n in keys]
    assert freqs == sorted(freqs, reverse=True)


def test_keys_unknown_db(client):
    resp, _ = client.get("/api/keys", params={"db": "nope"})
    assert resp.status == 404


def test_keys_missing_db(client):
    resp, _ = client.get("/api/keys")
    assert resp.status == 400


def test_sorts(client):
    resp, body = client.get("/api/sorts")
    sorts = jbody(body)["sorts"]
    assert "name" in sorts
    assert "path" in sorts
    assert "none" in sorts


def test_origin_mismatch_rejected(client):
    resp, _ = client.get("/api/dbs", headers={"Origin": "http://evil.example"})
    assert resp.status == 403


def test_cross_site_fetch_rejected(client):
    resp, _ = client.get("/api/dbs", headers={"Sec-Fetch-Site": "cross-site"})
    assert resp.status == 403


def test_same_origin_allowed(client, app):
    resp, _ = client.get("/api/dbs", headers={"Sec-Fetch-Site": "same-origin"})
    assert resp.status == 200


def test_allowed_hosts_for_loopback_and_lan():
    from wafer.app.webui.backend.server import allowed_hosts_for

    hosts = allowed_hosts_for("127.0.0.1", 8787)
    assert hosts is not None
    assert "127.0.0.1:8787" in hosts and "localhost:8787" in hosts
    assert allowed_hosts_for("0.0.0.0", 8787) is None


def test_disallowed_host_rejected():
    import asyncio

    from aiohttp import web

    from wafer.app.webui.backend.server import ALLOWED_HOSTS, same_origin_middleware

    class FakeApp(dict):
        pass

    app = FakeApp()
    app[ALLOWED_HOSTS] = frozenset({"127.0.0.1:1"})

    class FakeRequest:
        host = "rebind.evil:80"
        headers: dict = {}

        def __init__(self):
            self.app = app

    async def handler(_req):
        return web.Response()

    async def run():
        return await same_origin_middleware(FakeRequest(), handler)

    with pytest.raises(web.HTTPForbidden):
        asyncio.new_event_loop().run_until_complete(run())


def test_query_body_not_object_rejected(client):
    resp, _ = client.post("/api/query", json=["not", "an", "object"])
    assert resp.status == 400


def test_query_sort_not_string_rejected(client):
    resp, _ = client.post("/api/query", json={"db": DB, "sort": []})
    assert resp.status == 400


def test_query_filter_name_not_string_rejected(client):
    resp, _ = client.post("/api/query", json={"db": DB, "filters": [{"name": []}]})
    assert resp.status == 400


def test_folders_unknown_db(client):
    resp, _ = client.get("/api/folders", params={"db": "nope"})
    assert resp.status == 404
