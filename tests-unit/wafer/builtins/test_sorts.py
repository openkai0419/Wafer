from wafer.builtins.sorts import NaturalPathSort, RandomSort


def test_natural_path_sort():
    rows = [{"path": "img10.png"}, {"path": "img2.png"}, {"path": "img1.png"}]
    result = NaturalPathSort.sort_rows(rows, ascending=True)
    assert [r["path"] for r in result] == ["img1.png", "img2.png", "img10.png"]


def test_random_sort_returns_all():
    rows = [{"path": f"{i}.png"} for i in range(20)]
    result = RandomSort.sort_rows(list(rows), ascending=True)
    assert len(result) == 20
