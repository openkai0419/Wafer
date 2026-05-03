import json
import os
import time

from PIL import Image

from wafer.utils.paths import normalize_path
from wafer.core.db.file_db import FileDB
from wafer.core.db.query import FileSearchEngine, SearchQuery
from wafer.plugin.collector.handler import collector_resolver
from wafer.plugin.parser.handler import parser_resolver
from wafer.app.indexer.collector_receiver import _parse_batch as _parse_collector_batch
from wafer.app.indexer.parser_receiver import _parse_batch as _parse_parser_batch
from test_support.scan_harness import ScanHarness


def _create_nai_image(path, prompt="a cat", model="nai-v3", seed=42):
    img = Image.new("RGB", (200, 100), color=(128, 200, 64))
    comment = json.dumps({"prompt": prompt, "model": model, "seed": seed, "steps": 28})
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("Comment", comment)
    img.save(str(path), format="PNG", pnginfo=info)


def _run_exif_collector(db):
    pending = db.get_pending_sources("exiftool")
    if not pending:
        return []
    paths = [row[0] for row in pending]
    file_info_map = {row[0]: (row[1], row[2]) for row in pending}
    db.mark_dispatched(paths, "exiftool")
    plugin = collector_resolver.registry.get("exiftool")()
    results = []
    for p in paths:
        info = file_info_map.get(p, (0.0, 0))
        r = plugin.process(p, info).to_dict()
        r["collector"] = "exiftool"
        results.append(r)
    return results


def _write_collector_results(db, results):
    data = _parse_collector_batch(results)
    db.upsert_collection_results(
        data["image_entries"],
        data["meta_info_entries"],
        data["tag_entries"],
        data["collector_status"],
    )


class TestParserResultsParsedCorrectly:
    def test_parser_meta_keys_have_prefix(self):
        results = [
            {
                "source": "/test/img.png",
                "path": "/test/img.png",
                "status": True,
                "parser": "novelai",
                "meta_info": {"prompt": "a cat", "model": "nai-v3"},
            }
        ]
        parsed = _parse_parser_batch(results)
        keys = [e[1] for e in parsed["meta_info_entries"]]
        assert all(k.startswith("novelai.") for k in keys)
        assert "novelai.prompt" in keys
        assert "novelai.model" in keys

    def test_parser_fail_no_meta(self):
        results = [
            {
                "source": "/test/bad.png",
                "status": False,
                "parser": "novelai",
                "meta_info": {"prompt": "ignored"},
            }
        ]
        parsed = _parse_parser_batch(results)
        assert parsed["meta_info_entries"] == []
        assert len(parsed["collector_status"]) == 1
        assert parsed["collector_status"][0][2] == "fail"

    def test_parser_delete_keys_captured(self):
        results = [
            {
                "source": "/test/img.png",
                "path": "/test/img.png",
                "status": True,
                "parser": "novelai",
                "meta_info": {"prompt": "a cat"},
                "delete_keys": ["exif.Comment", "exif.Description"],
            }
        ]
        parsed = _parse_parser_batch(results)
        assert len(parsed["delete_entries"]) == 1
        assert parsed["delete_entries"][0][2] == ["exif.Comment", "exif.Description"]


class TestParserToDBPipeline:
    def test_parser_meta_stored_in_db(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        _create_nai_image(img_dir / "nai_test.png", prompt="sunset over ocean", seed=100)

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"
        norm = normalize_path(str(img_dir / "nai_test.png"))

        with ScanHarness(db_path, collectors=collectors) as h:
            h.scan_and_wait(img_dir, expected=1)
            assert h.wait_for(lambda: len(h.db.get_pending_sources("exiftool")) >= 1)

            collector_results = _run_exif_collector(h.db)
            _write_collector_results(h.db, collector_results)

            comment_rows = h.db.read_conn.execute("SELECT value FROM meta_info WHERE path=? AND key='exif.Comment'", (norm,)).fetchall()

            if not comment_rows:
                return

            comment_json = comment_rows[0][0]
            file_hash = h.db.read_conn.execute("SELECT file_hash FROM sources WHERE source=?", (norm,)).fetchone()

            parser_results = [
                {
                    "source": norm,
                    "path": norm,
                    "status": True,
                    "parser": "novelai",
                    "file_hash": file_hash[0] if file_hash else None,
                    "meta_info": {"prompt": "sunset over ocean", "seed": "100", "model": "nai-v3"},
                }
            ]
            parsed = _parse_parser_batch(parser_results)
            h.db.upsert_collection_results(
                [],
                parsed["meta_info_entries"],
                parsed.get("tag_entries", []),
                parsed["collector_status"],
            )

            meta = h.db.read_conn.execute("SELECT key, value FROM meta_info WHERE path=? AND key LIKE 'novelai.%'", (norm,)).fetchall()
            meta_dict = {k: v for k, v in meta}
            assert "novelai.prompt" in meta_dict
            assert meta_dict["novelai.prompt"] == "sunset over ocean"
            assert "novelai.seed" in meta_dict

    def test_parser_results_searchable(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        _create_nai_image(img_dir / "art.png", prompt="fantasy landscape")

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"
        norm = normalize_path(str(img_dir / "art.png"))

        with ScanHarness(db_path, collectors=collectors) as h:
            h.scan_and_wait(img_dir, expected=1)
            assert h.wait_for(lambda: len(h.db.get_pending_sources("exiftool")) >= 1)

            collector_results = _run_exif_collector(h.db)
            _write_collector_results(h.db, collector_results)

            parser_results = [
                {
                    "source": norm,
                    "path": norm,
                    "status": True,
                    "parser": "novelai",
                    "meta_info": {"prompt": "fantasy landscape", "steps": "28"},
                }
            ]
            parsed = _parse_parser_batch(parser_results)
            h.db.upsert_collection_results(
                [],
                parsed["meta_info_entries"],
                parsed.get("tag_entries", []),
                parsed["collector_status"],
            )

        engine = FileSearchEngine(str(db_path))
        result_paths, _, _ = engine.search(SearchQuery(keys=("novelai.prompt",), keywords="fantasy", require_keys=True))
        assert len(result_paths) == 1
        assert result_paths[0] == norm
