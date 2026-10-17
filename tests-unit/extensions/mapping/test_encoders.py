import pickle

import numpy as np
import pytest

from extensions.mapping.encoders import (
    ENCODERS,
    PALETTE_KEY,
    PALETTE_MAX_SLOTS,
    CategoryEncoder,
    NumericEncoder,
    PaletteEncoder,
    SUMMARY_DIMS,
    TEXT_MAX_CHARS,
    PathEncoder,
    TextEncoder,
    TokenSetEncoder,
    auto_encoders,
    detect_encoder,
    detect_separator,
    expand_group_keys,
    feature_input,
    folder_prefixes,
    group_values,
    normalize_token,
    rgb_to_lab,
)
from extensions.mapping.params import MapParams
from wafer.core.db.path_values import PathValue
from wafer.core.logs import AppLogger

PARAMS = MapParams()


def values(*texts):
    return [PathValue(t) for t in texts]


def packed(r, g, b):
    return float((r << 16) | (g << 8) | b)


def palette(*colors):
    return [PathValue(str(int(packed(*c))), packed(*c)) for c in colors]


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


def test_folder_prefixes_ignore_the_file_name_and_mixed_separators():
    assert folder_prefixes(r"c:\a/b\x.png") ==("c:", "c:/a", "c:/a/b")
    assert folder_prefixes("//server/share/x.png") == ("server", "server/share")
    assert folder_prefixes("x.png") == ()


def test_path_places_files_by_folder_distance():
    encoder = PathEncoder()
    matrix = encoder.fit_transform(values("c:/a/b/1.png", "c:/a/b/2.png", "c:/a/c/3.png", "d:/x/4.png"), PARAMS).toarray()
    distance = lambda i, j: np.linalg.norm(matrix[i] - matrix[j])
    assert distance(0, 1) == pytest.approx(0.0)
    assert distance(0, 1) < distance(0, 2) < distance(0, 3)


def test_path_labels_show_the_deepest_shared_folder():
    encoder = PathEncoder()
    encoder.fit_transform(values("c:/root/a/b/1.png", "c:/root/a/b/2.png", "c:/root/a/c/3.png", "d:/x/4.png"), PARAMS)
    assert encoder.describe(np.array([0, 1]), MapParams(label_terms=3)) == ["a/b"]


def test_path_is_detected_for_paths_but_not_tag_lists():
    assert detect_encoder([PathValue(f"c:/pics/{i}/x.png") for i in range(10)]) == "path"
    assert detect_encoder([PathValue("cat, sky/blue, sea") for _ in range(10)]) == "token_set"


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
        (PathEncoder(), values("c:/a/1.png", "c:/b/2.png")),
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
    (PathEncoder(), values("c:/a/1.png", "c:/b/2.png", "c:/a/3.png")),
    (TextEncoder(), values("青い髪の少女", "夜の街", "猫が寝ている")),
    (CategoryEncoder(), values("a", "b", "a")),
    (PaletteEncoder(), [palette((250, 10, 10), (20, 20, 20)), palette((10, 10, 250)), None]),
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


def test_group_values_orders_slots_and_skips_missing():
    entry = {
        "color.palette.2": PathValue("x", packed(0, 0, 255)),
        "color.palette.1": PathValue("y", packed(255, 0, 0)),
        "color.palette.3": PathValue(""),
        "color.palette.x": PathValue("w", packed(1, 1, 1)),
        "other": PathValue("z", 1.0),
    }
    slots = group_values(entry, PALETTE_KEY)
    assert [v.number for v in slots] == [packed(255, 0, 0), packed(0, 0, 255)]
    assert group_values({}, PALETTE_KEY) is None
    assert feature_input(entry, PALETTE_KEY, PaletteEncoder) == slots
    assert feature_input(entry, "other", NumericEncoder) == entry["other"]


def test_group_values_sorts_numerically_and_skips_non_finite():
    entry = {f"color.palette.{n}": PathValue(str(n), float(n)) for n in (10, 2, 1)}
    entry["color.palette.4"] = PathValue("nan", float("nan"))
    assert [v.number for v in group_values(entry, PALETTE_KEY)] == [1.0, 2.0, 10.0]


def test_expand_group_keys():
    keys = expand_group_keys(PALETTE_KEY)
    assert keys[0] == "color.palette.1" and keys[-1] == f"color.palette.{PALETTE_MAX_SLOTS}"
    assert len(keys) == PALETTE_MAX_SLOTS


def test_palette_distances_follow_dominant_colors():
    encoder = PaletteEncoder()
    inputs = [palette((250, 10, 10), (20, 20, 20)), palette((240, 20, 20), (20, 20, 20)), palette((10, 10, 250), (20, 20, 20)), None]
    matrix = encoder.fit_transform(inputs, MapParams())
    assert np.linalg.norm(matrix[0] - matrix[1]) < np.linalg.norm(matrix[0] - matrix[2])
    assert encoder.present(inputs).tolist() == [True, True, True, False]
    assert np.allclose(encoder.transform(inputs[:2]), matrix[:2])
    assert not matrix[3].any()


def test_palette_rank_weighting():
    encoder = PaletteEncoder()
    red_first = palette((250, 0, 0), (0, 0, 250))
    blue_first = palette((0, 0, 250), (250, 0, 0))
    red_only = palette((250, 0, 0))
    matrix = encoder.fit_transform([red_first, blue_first, red_only], MapParams())
    assert np.linalg.norm(matrix[0] - matrix[2]) < np.linalg.norm(matrix[1] - matrix[2])


def test_palette_describe_names_dominant_color():
    encoder = PaletteEncoder()
    encoder.fit_transform([palette((20, 40, 230)), palette((240, 240, 240))], MapParams())
    assert encoder.describe(np.array([0]), MapParams())[0] == "blue"
    assert encoder.describe(np.array([1]), MapParams()) == ["white", "bright"]


def test_palette_is_not_auto_detected_and_is_the_only_key_group():
    assert "palette" in ENCODERS and PaletteEncoder not in auto_encoders()
    assert [cls.NAME for cls in ENCODERS.values() if cls.KEY_GROUP] == ["palette"]


DESCRIBE_CASES = [
    (NumericEncoder, [PathValue("1", 1.0), PathValue("5", 5.0), None, PathValue("9", 9.0)]),
    (TokenSetEncoder, values("cat, sky", "dog, sea", "cat, sea", "(cat:1.2), [sky]")),
    (TextEncoder, values("blue hair girl", "night city street", "blue sky", "")),
    (CategoryEncoder, values("a", "b", "a", "")),
    (PaletteEncoder, [palette((250, 10, 10), (20, 20, 20)), palette((10, 10, 250)), None, palette((240, 240, 240))]),
]


@pytest.mark.parametrize("encoder_cls, inputs", DESCRIBE_CASES)
def test_fit_describe_labels_match_fit_transform(encoder_cls, inputs):
    params = MapParams(label_terms=3)
    fitted, described = encoder_cls(), encoder_cls()
    fitted.fit_transform(inputs, params)
    assert described.fit_describe(inputs, params) is None
    for members in ([0], [1], [0, 2], [1, 3], [0, 1, 2, 3]):
        assert described.describe(np.array(members), params) == fitted.describe(np.array(members), params)


def test_palette_first_colors_match_per_row_lab():
    inputs = [palette((250, 10, 10), (20, 20, 20)), None, palette((0, 128, 255)), []]
    encoder = PaletteEncoder()
    encoder.fit_describe(inputs, PARAMS)
    expected = rgb_to_lab(np.array([[250, 10, 10], [0, 128, 255]], dtype=np.uint8))
    assert np.allclose(encoder.first_colors[[0, 2]], expected)
    assert np.isnan(encoder.first_colors[[1, 3]]).all()


def test_normalize_token_is_memoised():
    normalize_token.cache_clear()
    assert normalize_token("(Cat_Ears:1.2)") == normalize_token("(Cat_Ears:1.2)")
    assert normalize_token.cache_info().hits == 1


def test_text_chunk_sizes_are_per_key_options():
    texts = values("blue hair girl", "blue eyes girl", "red car")
    short = TextEncoder({"min_chars": "2", "max_chars": "2"})
    long = TextEncoder({"min_chars": "5", "max_chars": "3"})
    assert short.ngram_range() == (2, 2) and long.ngram_range() == (3, 5)
    short.fit_transform(texts, PARAMS)
    long.fit_transform(texts, PARAMS)
    assert set(short.vectorizer.get_feature_names_out()) != set(long.vectorizer.get_feature_names_out())


def test_number_options_are_clamped_and_fall_back_on_bad_values():
    assert TextEncoder.number_option({"max_chars": "999"}, "max_chars") == TEXT_MAX_CHARS
    assert TokenSetEncoder.summary_dims({"summary": "bad"}) == SUMMARY_DIMS
    assert PathEncoder.summary_dims({"summary": "1"}) == 2
    assert NumericEncoder.summary_dims({}) == SUMMARY_DIMS


@pytest.mark.parametrize("encoder", [TokenSetEncoder, PathEncoder, TextEncoder, CategoryEncoder])
def test_sparse_encoders_offer_a_detail_option(encoder):
    assert any(option.name == "summary" and option.numeric for option in encoder.OPTIONS)
    assert encoder.summary_dims({"summary": "120"}) == 120


def slow_palette_reference(inputs):
    import math

    from extensions.mapping.encoders import PALETTE_BINS, PALETTE_RANGE, rgb_to_lab

    def unpack_rgb(value):
        number = int(value) & 0xFFFFFF
        return (number >> 16) & 0xFF, (number >> 8) & 0xFF, number & 0xFF

    def soft_bin_weights(lab):
        coords = []
        for value, (low, high), bins in zip(lab, PALETTE_RANGE, PALETTE_BINS):
            position = (min(max(float(value), low), high) - low) / (high - low) * bins - 0.5
            base = math.floor(position)
            fraction = position - base
            coords.append([(min(max(base, 0), bins - 1), 1.0 - fraction), (min(max(base + 1, 0), bins - 1), fraction)])
        return [((i * PALETTE_BINS[1] + j) * PALETTE_BINS[2] + k, wi * wj * wk) for i, wi in coords[0] for j, wj in coords[1] for k, wk in coords[2]]

    output = np.zeros((len(inputs), int(np.prod(PALETTE_BINS))), dtype=np.float64)
    for row, slots in enumerate(inputs):
        if not slots:
            continue
        ranks = np.array([1.0 / (i + 1) for i in range(len(slots))])
        ranks /= ranks.sum()
        labs = rgb_to_lab(np.array([unpack_rgb(slot.number) for slot in slots], dtype=np.uint8))
        for lab, weight in zip(labs, ranks):
            for index, share in soft_bin_weights(lab):
                output[row, index] += weight * share
    return np.sqrt(output)


def test_palette_transform_matches_the_per_color_definition():
    rng = np.random.default_rng(0)
    inputs = [None, []]
    for _ in range(60):
        inputs.append(palette(*[tuple(int(v) for v in rng.integers(0, 256, 3)) for _ in range(int(rng.integers(1, 8)))]))
    inputs.append(palette((0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255)))
    assert np.allclose(PaletteEncoder().transform(inputs), slow_palette_reference(inputs), atol=1e-6)
