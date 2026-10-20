from extensions.text_generation._common import join_list_field, stringify_meta_info


class TestStringifyMetaInfo:
    def test_list_of_dicts_expanded_by_index(self):
        data = {"items": [{"name": "a", "tags": [{"v": 1}]}, "plain", {"name": "b"}]}
        assert stringify_meta_info(data) == {
            "items/0/name": "a",
            "items/0/tags/0/v": "1",
            "items/1": "plain",
            "items/2/name": "b",
        }

    def test_scalar_list_kept_as_string(self):
        assert stringify_meta_info({"strengths": [0.6, 0.6], "empty": []}) == {"strengths": "[0.6, 0.6]", "empty": "[]"}


class TestJoinListField:
    def test_joins_field_of_each_item_with_newlines(self):
        meta_info = stringify_meta_info({"chars": [{"caption": "a"}, {"other": "x"}, {"caption": "c"}]})
        join_list_field(meta_info, "chars", "caption")
        assert meta_info["chars"] == "a\nc"

    def test_ignores_nested_and_unrelated_keys(self):
        meta_info = {"chars/0/caption": "a", "chars/0/sub/caption": "nested", "charsx/0/caption": "other", "chars/x/caption": "bad"}
        join_list_field(meta_info, "chars", "caption")
        assert meta_info["chars"] == "a"

    def test_no_items_leaves_meta_info_unchanged(self):
        meta_info = {"chars": "[]"}
        join_list_field(meta_info, "chars", "caption")
        assert meta_info == {"chars": "[]"}
