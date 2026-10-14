import pickle

import numpy as np
import pytest

from extensions.mapping.encoders import (
    ENCODERS,
    CategoryEncoder,
    NumericEncoder,
    TextEncoder,
    TokenSetEncoder,
    auto_encoders,
    detect_encoder,
    detect_separator,
    normalize_token,
    rgb_to_lab,
)
from extensions.mapping.params import MapParams
from wafer.core.db.path_values import PathValue
from wafer.core.logs import AppLogger

PARAMS = MapParams()


def values(*texts):
    return [PathValue(t) for t in texts]


def test_every_encoder_and_option_has_description():
    for cls in ENCODERS.values():
        assert cls.DISPLAY_NAME and cls.DESCRIPTION, cls.NAME
        for option in cls.OPTIONS:
            assert option.label and option.description, (cls.NAME, option.name)


@pytest.mark.parametrize(
    "items, expected",
    [
        ([PathValue("1", 1.0), PathValue("2", 2.0), PathValue("3", 3.0)], "numeric"),
        (values("1girl, solo, blue hair", "1girl, smile", "sky, cloud"), "token_set"),
        (values("青い髪の少女が立っている", "夜の街と雨", "猫が寝ている"), "text"),
        (values("sdxl", "sdxl", "sd15", "sdxl", "sd15", "sdxl", "sdxl", "sd15", "sdxl", "sdxl", "sd15"), "category"),
    ],
)
def test_detect_encoder(items, expected):
    assert detect_encoder(items) == expected


def test_detect_separator():
    assert detect_separator(["a, b", "c, d"]) == "comma"
    assert detect_separator(["a\nb", "c\nd"]) == "newline"
    assert detect_separator(["a b", "c d"]) == "space"
    assert detect_separator([]) == "space"


def test_normalize_token():
    assert normalize_token(" Blue_Hair ") == ("blue hair", 1.0)
    assert normalize_token("(smile:1.3)") == ("smile", pytest.approx(1.3))
    assert normalize_token("{{sky}}")[1] == pytest.approx(1.05**2)
    assert normalize_token("[night]")[1] == pytest.approx(1 / 1.05)
    assert normalize_token("  ") == ("", 1.0)


def test_numeric_rank_and_missing():
    encoder = NumericEncoder()
    inputs = [PathValue("10", 10.0), PathValue("1000", 1000.0), None, PathValue("x")]
    matrix = encoder.fit_transform(inputs, PARAMS)
    assert encoder.present(inputs).tolist() == [True, True, False, False]
    assert matrix[0, 0] == 0.0 and matrix[1, 0] == 1.0


def test_numeric_linear_and_log():
    inputs = [PathValue("1", 1.0), PathValue("10", 10.0), PathValue("100", 100.0)]
    linear = NumericEncoder({"scale": "linear"}).fit_transform(inputs, PARAMS)[:, 0]
    log = NumericEncoder({"scale": "log"}).fit_transform(inputs, PARAMS)[:, 0]
    assert linear[1] == pytest.approx(9 / 99)
    assert log[1] == pytest.approx((np.log1p(10) - np.log1p(1)) / (np.log1p(100) - np.log1p(1)), abs=1e-4)


def test_numeric_describe_timestamps_and_plain():
    encoder = NumericEncoder()
    encoder.fit_transform([PathValue("", 1700000000.0), PathValue("", 1700090000.0)], PARAMS)
    assert encoder.describe(np.array([0, 1]), PARAMS)[0].count("-") == 4
    encoder.fit_transform([PathValue("", 2.0), PathValue("", 5.0)], PARAMS)
    assert encoder.describe(np.array([0, 1]), PARAMS) == ["2 \u2013 5"]


def test_token_set_overlap_and_describe():
    encoder = TokenSetEncoder()
    inputs = values("cat, sky, common", "cat, sky, common", "dog, sea, common", "dog, sea, common")
    matrix = encoder.fit_transform(inputs, PARAMS).toarray()
    same = np.linalg.norm(matrix[0] - matrix[1])
    different = np.linalg.norm(matrix[0] - matrix[2])
    assert same < different
    assert set(encoder.describe(np.array([0, 1]), MapParams(label_terms=2))) == {"cat", "sky"}


def test_token_set_space_and_custom_separator():
    space = TokenSetEncoder({"separator": "space"})
    space.fit_transform(values("blue hair", "red hair"), PARAMS)
    assert space.describe(np.array([0]), MapParams(label_terms=1)) == ["blue"]
    custom = TokenSetEncoder({"separator": "custom", "pattern": r"\s*/\s*"})
    assert custom.fit_transform(values("a / b", "b / c"), PARAMS).shape[1] == 3


@pytest.mark.parametrize("pattern", ["(", ""])
def test_token_set_invalid_or_empty_pattern_falls_back_to_auto(pattern):
    encoder = TokenSetEncoder({"separator": "custom", "pattern": pattern})
    assert encoder.fit_transform(values("a, b", "b, c"), PARAMS).shape[1] == 3


def test_token_set_all_empty():
    encoder = TokenSetEncoder()
    matrix = encoder.fit_transform([None, None, None], PARAMS)
    assert matrix.shape[0] == 3
    assert encoder.describe(np.array([0, 1]), PARAMS) == []


def test_text_handles_japanese_variants():
    encoder = TextEncoder()
    matrix = encoder.fit_transform(values("青い髪の少女", "青髪の少女", "夜の街と雨"), PARAMS).toarray()
    assert np.linalg.norm(matrix[0] - matrix[1]) < np.linalg.norm(matrix[0] - matrix[2])
    assert encoder.describe(np.array([2]), PARAMS)


def test_text_without_words_logs_once_and_returns_no_terms(monkeypatch):
    warnings = []
    monkeypatch.setattr(AppLogger, "warning", lambda message, **kwargs: warnings.append(message))
    encoder = TextEncoder()
    encoder.fit_transform(values("a b", "c d", "e"), PARAMS)
    assert encoder.describe(np.array([0]), PARAMS) == []
    assert encoder.describe(np.array([1, 2]), PARAMS) == []
    assert [w for w in warnings if "no words" in w] == ["[Mapping] Text key has no words to label groups"]


def test_token_set_custom_regex_with_capture_group_drops_empty_pieces():
    encoder = TokenSetEncoder({"separator": "custom", "pattern": r",|(;)"})
    matrix = encoder.fit_transform(values("a,b;c", "b;c,d"), PARAMS)
    assert matrix.shape[1] == 5


def test_category_one_hot_and_describe():
    encoder = CategoryEncoder()
    matrix = encoder.fit_transform(values("a", "a", "b"), PARAMS).toarray()
    assert (matrix[0] == matrix[1]).all() and not (matrix[0] == matrix[2]).all()
    assert encoder.describe(np.array([0, 1, 2]), PARAMS) == ["a"]


def test_rgb_to_lab_reference_points():
    assert rgb_to_lab(np.array([[255, 255, 255]], dtype=np.uint8))[0] == pytest.approx([100, 0, 0], abs=0.5)
    assert rgb_to_lab(np.array([[0, 0, 0]], dtype=np.uint8))[0] == pytest.approx([0, 0, 0], abs=0.5)


@pytest.mark.parametrize(
    "encoder, fit_inputs, new_inputs",
    [
        (NumericEncoder(), [PathValue("1", 1.0), PathValue("5", 5.0), PathValue("9", 9.0)], [PathValue("5", 5.0), PathValue("100", 100.0), None]),
        (NumericEncoder({"scale": "log"}), [PathValue("1", 1.0), PathValue("10", 10.0)], [PathValue("10", 10.0)]),
        (TokenSetEncoder(), values("cat, sky", "dog, sea", "cat, sea"), values("cat, sky", "unseen, tokens")),
        (TextEncoder(), values("青い髪の少女", "夜の街"), values("青い髪の少女", "まったく別の文章")),
        (CategoryEncoder(), values("a", "b"), values("a", "zzz")),
    ],
)
def test_transform_matches_fit_columns_and_values(encoder, fit_inputs, new_inputs):
    fitted = encoder.fit_transform(fit_inputs, PARAMS)
    again = encoder.transform(fit_inputs)
    assert np.allclose(dense(fitted), dense(again))
    assert dense(encoder.transform(new_inputs)).shape == (len(new_inputs), dense(fitted).shape[1])


def dense(matrix):
    return matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)


def test_numeric_rank_transform_interpolates_new_values():
    encoder = NumericEncoder()
    encoder.fit_transform([PathValue("", 0.0), PathValue("", 10.0), PathValue("", 20.0)], PARAMS)
    assert encoder.transform([PathValue("", 5.0)])[0, 0] == pytest.approx(0.25)
    assert encoder.transform([PathValue("", 99.0)])[0, 0] == pytest.approx(1.0)


def test_image_encoder_is_gone_and_auto_encoders_exclude_non_auto():
    assert "image_color" not in ENCODERS
    assert all(cls.AUTO_DETECT for cls in auto_encoders())


@pytest.mark.parametrize(
    "encoder, fit_inputs",
    [
        (NumericEncoder(), [PathValue("1", 1.0), PathValue("5", 5.0)]),
        (TokenSetEncoder(), values("cat, sky", "dog, sea")),
        (TextEncoder(), values("青い髪の少女", "夜の街")),
        (CategoryEncoder(), values("a", "b")),
    ],
)
def test_fitted_encoders_are_picklable(encoder, fit_inputs):
    encoder.fit_transform(fit_inputs, PARAMS)
    restored = pickle.loads(pickle.dumps(encoder))
    assert np.allclose(dense(restored.transform(fit_inputs)), dense(encoder.transform(fit_inputs)))
    assert restored.describe(np.array([0]), PARAMS) == encoder.describe(np.array([0]), PARAMS)


def test_numeric_rank_ties_use_average_rank():
    encoder = NumericEncoder()
    fitted = encoder.fit_transform([PathValue("", 1.0), PathValue("", 1.0), PathValue("", 1.0), PathValue("", 5.0)], PARAMS)[:, 0]
    assert fitted == pytest.approx([1 / 3, 1 / 3, 1 / 3, 1.0])
    assert encoder.transform([PathValue("", 1.0), PathValue("", 5.0)])[:, 0] == pytest.approx([1 / 3, 1.0])


def test_numeric_rank_matches_scipy_rankdata_with_ties():
    from scipy.stats import rankdata

    numbers = [3.0, 1.0, 3.0, 2.0, 2.0, 2.0, 9.0]
    fitted = NumericEncoder().fit_transform([PathValue("", n) for n in numbers], PARAMS)[:, 0]
    assert fitted == pytest.approx((rankdata(numbers) - 1) / (len(numbers) - 1))


COMPACT_CASES = [
    (NumericEncoder(), [PathValue("1", 1.0), PathValue("5", 5.0), PathValue("9", 9.0)]),
    (NumericEncoder({"scale": "log"}), [PathValue("1", 1.0), PathValue("10", 10.0)]),
    (TokenSetEncoder(), values("cat, sky", "dog, sea", "cat, sea")),
    (TextEncoder(), values("青い髪の少女", "夜の街", "猫が寝ている")),
    (CategoryEncoder(), values("a", "b", "a")),
]


@pytest.mark.parametrize("encoder, fit_inputs", COMPACT_CASES)
def test_compact_keeps_transform_and_describe_is_safe(encoder, fit_inputs):
    encoder.fit_transform(fit_inputs, PARAMS)
    before = dense(encoder.transform(fit_inputs))
    encoder.compact()
    assert np.allclose(before, dense(encoder.transform(fit_inputs)))
    assert encoder.describe(np.array([0, 1]), PARAMS) == []
    assert np.allclose(before, dense(pickle.loads(pickle.dumps(encoder)).transform(fit_inputs)))


def test_compact_shrinks_pickled_text_encoder():
    texts = values(*[f"sample prompt number {i} with some words about subject {i % 17}" for i in range(200)])
    encoder = TextEncoder()
    encoder.fit_transform(texts, PARAMS)
    encoder.describe(np.array([0, 1]), PARAMS)
    before = len(pickle.dumps(encoder))
    encoder.compact()
    assert len(pickle.dumps(encoder)) < before
