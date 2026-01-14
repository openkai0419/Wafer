from __future__ import annotations

from pathlib import Path


def test_execute_paste_overwrite_same_path_is_noop(tmp_path):
    from source.os.paste import ClipboardFilePaster, PasteDecision, PastePlanItem

    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")

    item = PastePlanItem(
        index=0,
        src=Path(src),
        is_dir=False,
        action="copy",
        dst_default=Path(src),
        conflict=True,
        suggested_dst=None,
    )

    res = ClipboardFilePaster().execute_paste([item], {0: PasteDecision(mode="overwrite")})
    assert src.exists()
    assert src.read_text(encoding="utf-8") == "x"
    assert res and res[0]["status"] == "skipped"


def test_execute_paste_overwrite_replaces_existing_file(tmp_path):
    from source.os.paste import ClipboardFilePaster, PasteDecision, PastePlanItem

    src = tmp_path / "src.txt"
    src.write_text("new", encoding="utf-8")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    dst = dst_dir / "src.txt"
    dst.write_text("old", encoding="utf-8")

    item = PastePlanItem(
        index=0,
        src=Path(src),
        is_dir=False,
        action="copy",
        dst_default=Path(dst),
        conflict=True,
        suggested_dst=None,
    )

    res = ClipboardFilePaster().execute_paste([item], {0: PasteDecision(mode="overwrite")})
    assert dst.read_text(encoding="utf-8") == "new"
    assert res and res[0]["status"] == "ok"
