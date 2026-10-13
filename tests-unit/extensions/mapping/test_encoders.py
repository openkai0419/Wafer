import numpy as np
import pytest

from extensions.mapping.encoders import (
    CategoryEncoder,
    NumericEncoder,
    TextEncoder,
    TokenSetEncoder,
    ENCODERS,
    detect_encoder,
    detect_separator,
    normalize_token,
)
from extensions.mapping.params import MapParams
from wafer.core.db.path_values import PathValue

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
    matrix = encoder.encode(inputs, PARAMS)
    assert encoder.present(inputs).tolist() == [True, True, False, False]
    assert matrix[0, 0] == 0.0 and matrix[1, 0] == 1.0


def test_numeric_linear_and_log():
    inputs = [PathValue("1", 1.0), PathValue("10", 10.0), PathValue("100", 100.0)]
    linear = NumericEncoder({"scale": "linear"}).encode(inputs, PARAMS)[:, 0]
    log = NumericEncoder({"scale": "log"}).encode(inputs, PARAMS)[:, 0]
    assert linear[1] == pytest.approx(9 / 99)
    assert log[1] == pytest.approx((np.log1p(10) - np.log1p(1)) / (np.log1p(100) - np.log1p(1)), abs=1e-4)


def test_numeric_describe_timestamps_and_plain():
    encoder = NumericEncoder()
    encoder.encode([PathValue("", 1700000000.0), PathValue("", 1700090000.0)], PARAMS)
    assert encoder.describe(np.array([0, 1]), PARAMS)[0].count("-") == 4
    encoder.encode([PathValue("", 2.0), PathValue("", 5.0)], PARAMS)
    assert encoder.describe(np.array([0, 1]), PARAMS) == ["2 \u2013 5"]


def test_token_set_overlap_and_describe():
    encoder = TokenSetEncoder()
    inputs = values("cat, sky, common", "cat, sky, common", "dog, sea, common", "dog, sea, common")
    matrix = encoder.encode(inputs, PARAMS).toarray()
    same = np.linalg.norm(matrix[0] - matrix[1])
    different = np.linalg.norm(matrix[0] - matrix[2])
    assert same < different
    assert set(encoder.describe(np.array([0, 1]), MapParams(label_terms=2))) == {"cat", "sky"}


def test_token_set_space_and_custom_separator():
    space = TokenSetEncoder({"separator": "space"})
    space.encode(values("blue hair", "red hair"), PARAMS)
    assert space.describe(np.array([0]), MapParams(label_terms=1)) == ["blue"]
    custom = TokenSetEncoder({"separator": "custom", "pattern": r"\s*/\s*"})
    assert custom.encode(values("a / b", "b / c"), PARAMS).shape[1] == 3


@pytest.mark.parametrize("pattern", ["(", ""])
def test_token_set_invalid_or_empty_pattern_falls_back_to_auto(pattern):
    encoder = TokenSetEncoder({"separator": "custom", "pattern": pattern})
    assert encoder.encode(values("a, b", "b, c"), PARAMS).shape[1] == 3


def test_token_set_all_empty():
    encoder = TokenSetEncoder()
    matrix = encoder.encode([None, None, None], PARAMS)
    assert matrix.shape[0] == 3
    assert encoder.describe(np.array([0, 1]), PARAMS) == []


def test_text_handles_japanese_variants():
    encoder = TextEncoder()
    matrix = encoder.encode(values("青い髪の少女", "青髪の少女", "夜の街と雨"), PARAMS).toarray()
    assert np.linalg.norm(matrix[0] - matrix[1]) < np.linalg.norm(matrix[0] - matrix[2])
    assert encoder.describe(np.array([2]), PARAMS)


def test_category_one_hot_and_describe():
    encoder = CategoryEncoder()
    matrix = encoder.encode(values("a", "a", "b"), PARAMS).toarray()
    assert (matrix[0] == matrix[1]).all() and not (matrix[0] == matrix[2]).all()
    assert encoder.describe(np.array([0, 1, 2]), PARAMS) == ["a"]
