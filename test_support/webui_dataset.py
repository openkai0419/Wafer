from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

from PIL import Image

from wafer.core.db.file_db import FileDB
from wafer.core.db.setting_db import SettingDB
from wafer.utils.paths import normalize_path
from wafer.utils.virtual_paths import build_virtual_path

DB_NAME = "testdb"


def build_webui_dataset(root: Path) -> dict:
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
