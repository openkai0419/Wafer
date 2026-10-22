import json

import pytest

from extensions.wd14 import _models
from extensions.wd14._downloader import DEFAULT_MODEL
from extensions.wd14._models import list_models, load_spec, load_tags, model_dir, normalize_category, normalize_rating

WD_CSV = "tag_id,name,category,count\n9999999,general,9,1\n9999998,sensitive,9,1\n1,1girl,0,1\n2,hatsune_miku,4,1\n3,vocaloid,3,1\n4,highres,5,1\n"


@pytest.fixture
def models_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(_models, "MODELS_DIR", tmp_path)
    return tmp_path


def make_model(root, name, tags=WD_CSV, tags_name="selected_tags.csv", spec=None):
    folder = root / name
    folder.mkdir()
    (folder / "model.onnx").write_bytes(b"")
    (folder / tags_name).write_text(tags, encoding="utf-8")
    if spec is not None:
        (folder / "tagger.json").write_text(json.dumps(spec), encoding="utf-8")
    return folder


class TestListModels:
    def test_default_model_always_listed(self, models_dir):
        assert list_models() == [DEFAULT_MODEL]

    def test_lists_folders_with_model_or_spec(self, models_dir):
        make_model(models_dir, "b-tagger")
        (models_dir / "a-tagger").mkdir()
        (models_dir / "a-tagger" / "tagger.json").write_text("{}", encoding="utf-8")
        (models_dir / "empty").mkdir()
        assert list_models() == sorted(["a-tagger", "b-tagger", DEFAULT_MODEL])


class TestModelDir:
    def test_rejects_path_escape(self, models_dir):
        with pytest.raises(ValueError):
            model_dir("../outside")
        with pytest.raises(ValueError):
            model_dir("a/b")


class TestLoadSpec:
    def test_defaults_are_wd_v3(self, models_dir):
        make_model(models_dir, "wd")
        spec = load_spec("wd")
        assert spec.channels == "BGR"
        assert spec.mean is None and spec.std is None
        assert spec.pad == (255, 255, 255)
        assert spec.size is None

    def test_tagger_json_overrides(self, models_dir):
        make_model(
            models_dir,
            "pixai",
            spec={"channels": "rgb", "mean": [0.5, 0.5, 0.5], "std": [0.5, 0.5, 0.5], "pad": "black", "resample": "bilinear", "size": 1008, "categories": {"5": "general", "7": "meta"}},
        )
        spec = load_spec("pixai")
        assert spec.channels == "RGB"
        assert spec.mean == (0.5, 0.5, 0.5)
        assert spec.pad == (0, 0, 0)
        assert spec.size == 1008
        assert spec.resample == "bilinear"
        assert spec.category_ids[5] == "general"
        assert spec.category_ids[7] == "meta"
        assert spec.category_ids[4] == "character"

    def test_no_pad_and_custom_color(self, models_dir):
        make_model(models_dir, "a", spec={"pad": None})
        make_model(models_dir, "b", spec={"pad": [1, 2, 3]})
        assert load_spec("a").pad is None
        assert load_spec("b").pad == (1, 2, 3)

    def test_custom_file_names(self, models_dir):
        folder = make_model(models_dir, "t", tags='{"idx2tag": []}', tags_name="vocab.json", spec={"tags": "vocab.json"})
        assert load_spec("t").tags_path == folder / "vocab.json"

    def test_missing_tags_raises_with_hint(self, models_dir):
        folder = models_dir / "broken"
        folder.mkdir()
        (folder / "model.onnx").write_bytes(b"")
        with pytest.raises(FileNotFoundError, match="selected_tags.csv"):
            load_spec("broken")


class TestNormalize:
    def test_category_ids_and_names(self):
        assert normalize_category("9") == "rating"
        assert normalize_category(4) == "character"
        assert normalize_category("-1") == "general"
        assert normalize_category(42) == "general"
        assert normalize_category("Style") == "artist"
        assert normalize_category("copyright") == "copyright"
        assert normalize_category("unknown") == "general"

    def test_rating_names(self):
        assert normalize_rating("rating:g") == "general"
        assert normalize_rating("rating_explicit") == "explicit"
        assert normalize_rating("sensitive") == "sensitive"


class TestLoadTags:
    def test_csv(self, models_dir):
        make_model(models_dir, "wd")
        names, categories = load_tags(load_spec("wd"))
        assert names == ["general", "sensitive", "1girl", "hatsune_miku", "vocaloid", "highres"]
        assert categories == ["rating", "rating", "general", "character", "copyright", "meta"]

    def test_csv_without_category_column(self, models_dir):
        make_model(models_dir, "names", tags="name\n1girl\nsolo\n")
        assert load_tags(load_spec("names")) == (["1girl", "solo"], ["general", "general"])

    def test_csv_rating_aliases(self, models_dir):
        make_model(models_dir, "pixai", tags="tag_id,name,category,count\n0,rating:g,9,0\n1,rating:e,9,0\n")
        assert load_tags(load_spec("pixai"))[0] == ["general", "explicit"]

    def test_json_vocab_with_category_override(self, models_dir):
        vocab = {"idx2tag": ["long hair", "some artist", "fox", "hi res"], "tag2category": {"long hair": 0, "some artist": 1, "fox": 5, "hi res": 7}}
        make_model(models_dir, "e621", tags=json.dumps(vocab), tags_name="vocab.json", spec={"tags": "vocab.json", "categories": {"5": "general", "7": "meta"}})
        names, categories = load_tags(load_spec("e621"))
        assert names == ["long_hair", "some_artist", "fox", "hi_res"]
        assert categories == ["general", "artist", "general", "meta"]
