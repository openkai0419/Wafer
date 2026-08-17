import io

from PIL import Image

DB = "testdb"


def test_thumb(client, dataset):
    path = dataset["files"][0][0]
    resp, body = client.get("/api/thumb", params={"db": DB, "path": path, "size": "64"})
    assert resp.status == 200
    img = Image.open(io.BytesIO(body))
    assert img.format == "WEBP"
    assert max(img.size) <= 64


def test_thumb_cached_second_request(client, dataset):
    path = dataset["files"][1][0]
    resp1, body1 = client.get("/api/thumb", params={"db": DB, "path": path})
    resp2, body2 = client.get("/api/thumb", params={"db": DB, "path": path})
    assert resp1.status == 200
    assert resp2.status == 200
    assert body1 == body2


def test_thumb_unregistered_path(client, tmp_path):
    outside = tmp_path / "outside.png"
    Image.new("RGB", (10, 10)).save(outside)
    resp, _ = client.get("/api/thumb", params={"db": DB, "path": str(outside)})
    assert resp.status == 404


def test_thumb_zip_virtual_path(client, dataset):
    resp, body = client.get("/api/thumb", params={"db": DB, "path": dataset["virtual"], "size": "64"})
    assert resp.status == 200
    img = Image.open(io.BytesIO(body))
    assert img.format == "WEBP"
    assert max(img.size) <= 64


def test_file_zip_virtual_path(client, dataset):
    resp, body = client.get("/api/file", params={"db": DB, "path": dataset["virtual"]})
    assert resp.status == 200
    assert Image.open(io.BytesIO(body)).format == "PNG"


def test_thumb_non_image(client, dataset):
    text_path = dataset["files"][3][0]
    resp, _ = client.get("/api/thumb", params={"db": DB, "path": text_path})
    assert resp.status in (200, 422)


def test_thumb_missing_params(client):
    resp, _ = client.get("/api/thumb", params={"db": DB})
    assert resp.status == 400


def test_thumb_invalid_size(client, dataset):
    resp, _ = client.get("/api/thumb", params={"db": DB, "path": dataset["files"][0][0], "size": "abc"})
    assert resp.status == 400


def test_file_full(client, dataset):
    path = dataset["files"][0][0]
    resp, body = client.get("/api/file", params={"db": DB, "path": path})
    assert resp.status == 200
    with open(path, "rb") as f:
        assert body == f.read()


def test_file_range(client, dataset):
    path = dataset["files"][0][0]
    resp, body = client.get("/api/file", params={"db": DB, "path": path}, headers={"Range": "bytes=0-9"})
    assert resp.status == 206
    assert len(body) == 10
    with open(path, "rb") as f:
        assert body == f.read(10)


def test_file_unregistered(client):
    resp, _ = client.get("/api/file", params={"db": DB, "path": "C:/nope.png"})
    assert resp.status == 404


def test_file_unknown_db(client, dataset):
    resp, _ = client.get("/api/file", params={"db": "nope", "path": dataset["files"][0][0]})
    assert resp.status == 404
