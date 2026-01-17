from pathlib import Path


def test_unique_path_generates_increment(tmp_path):
    from source.os.file_transfer_utils import unique_path

    d = tmp_path
    (d / 'a.txt').write_text('x', encoding='utf-8')
    p = Path(unique_path(d, 'a.txt'))
    assert p.name.startswith('a (') and p.suffix == '.txt'


def test_check_copy_conflict_same_path(tmp_path):
    from source.os.file_transfer_utils import check_copy_conflict

    p = tmp_path / 'x.txt'
    p.write_text('x', encoding='utf-8')
    assert check_copy_conflict(p, p) == 'same_path'


def test_sanitize_filename_windows_invalid_chars():
    from source.os.file_transfer_utils import sanitize_filename

    assert sanitize_filename('a<b>c.txt') == 'a_b_c.txt'
