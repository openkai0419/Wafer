from __future__ import annotations
from PySide6 import QtCore, QtGui
import os, sys, re, shutil, struct
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Literal

CutCopy = Tuple[Literal["copy","cut"], List[Path]]  # ("copy"|"cut", [paths...])

@dataclass
class PastePlanItem:
    index: int
    src: Path
    is_dir: bool
    action: Literal["copy","cut"]         # クリップボード由来
    dst_default: Path                     # 衝突が無ければここ
    conflict: bool                        # 既に存在するか
    suggested_dst: Path | None            # 衝突時のデフォルト案（" (2)" 的なリネーム）

@dataclass
class PasteDecision:
    # GUIが返す決定
    mode: Literal["overwrite","rename","skip"]
    # rename時のみ使用（ファイル名 or フルパスどちらでもOK）
    new_name_or_path: Optional[str] = None

class ClipboardFilePaster:
    def __init__(self):
        self.clipboard = QtGui.QGuiApplication.clipboard()

    def _extract_windows_drop_effect(self, md: QtCore.QMimeData) -> Optional[str]:
        if not sys.platform.startswith('win'):
            return None
        # Qt が Windows クリップボードをブリッジする際、どちらかの形式になる可能性がある
        keys = [
            'Preferred DropEffect',
            'application/x-qt-windows-mime;value="Preferred DropEffect"',
        ]
        for k in keys:
            if md.hasFormat(k):
                try:
                    data = bytes(md.data(k))
                    (effect,) = struct.unpack('<I', data[:4])
                    return 'cut' if effect == 2 else 'copy'
                except Exception:
                    pass
        return None
    
    def _extract_from_gnome_clipboard(self, md: QtCore.QMimeData) -> Optional[CutCopy]:
        fmt = 'x-special/gnome-copied-files'
        if not md.hasFormat(fmt):
            return None
        try:
            raw = bytes(md.data(fmt)).decode('utf-8', errors='replace')
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            if not lines:
                return None
            op = lines[0].lower()
            action = 'cut' if op == 'cut' else 'copy'
            paths: List[Path] = []
            for ln in lines[1:]:
                url = QtCore.QUrl(ln)
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.exists():
                        paths.append(p)
            return (action, paths) if paths else None
        except Exception:
            return None

    def _extract_from_nautilus_clipboard(self, md: QtCore.QMimeData) -> Optional[CutCopy]:
        fmt = 'x-special/nautilus-clipboard'
        if not md.hasFormat(fmt):
            return None
        try:
            raw = bytes(md.data(fmt)).decode('utf-8', errors='replace')
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            if not lines:
                return None
            mode = lines[0].lower()
            action = 'cut' if mode == 'cut' else 'copy'
            paths: List[Path] = []
            for ln in lines[1:]:
                url = QtCore.QUrl(ln)
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.exists():
                        paths.append(p)
            return (action, paths) if paths else None
        except Exception:
            return None

    def _parse_uri_list_text(self, text: str) -> List[Path]:
        paths: List[Path] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            try:
                url = QtCore.QUrl(line)
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.exists():
                        paths.append(p)
            except Exception:
                pass
        return paths

    def _parse_plain_text_paths(self, text: str) -> List[Path]:
        cand: List[str] = []
        cand.extend([s.strip('"') for s in re.split(r'[\r\n]+', text) if s.strip()])
        cand.extend(re.findall(r'"([^"]+)"', text))
        cand.extend(re.findall(r'(?:(?:[A-Za-z]:)?[\\/][^\s"\'<>|]+)', text))
        paths: List[Path] = []
        for s in cand:
            try:
                p = Path(s)
                if p.exists():
                    paths.append(p)
            except Exception:
                pass
        return list(dict.fromkeys(paths))

    def collect_clipboard_files(self) -> Optional[CutCopy]:
        md = self.clipboard.mimeData()
        if md is None:
            return None

        # GNOME 優先
        res = self._extract_from_gnome_clipboard(md)
        if res:
            return res

        # Nautilus
        res = self._extract_from_nautilus_clipboard(md)
        if res:
            return res

        # 汎用
        paths: List[Path] = []
        if md.hasUrls():
            for url in md.urls():
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.exists():
                        paths.append(p)
        if not paths and md.hasFormat('text/uri-list'):
            try:
                text = bytes(md.data('text/uri-list')).decode('utf-8', errors='replace')
                paths = self._parse_uri_list_text(text)
            except Exception:
                pass
        if not paths and md.hasText():
            paths = self._parse_plain_text_paths(md.text())

        if not paths:
            return None

        action = self._extract_windows_drop_effect(md) or 'copy'
        return (action, paths)

    # ---------- プラン層（ドライラン） ----------
    def _unique_path(self, dest_dir: Path, name: str) -> Path:
        stem = Path(name).stem
        suffix = Path(name).suffix
        candidate = dest_dir / name
        i = 2
        while candidate.exists():
            candidate = dest_dir / f"{stem} ({i}){suffix}"
            i += 1
        return candidate

    def build_paste_plan(self, destination_dir: Path | str) -> List[PastePlanItem]:
        dest_dir = Path(destination_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        extracted = self.collect_clipboard_files()
        if not extracted:
            return []

        action, paths = extracted
        plan: List[PastePlanItem] = []
        for i, src in enumerate(paths):
            dst_default = dest_dir / src.name
            conflict = dst_default.exists()
            suggested = self._unique_path(dest_dir, src.name) if conflict else None
            plan.append(PastePlanItem(
                index=i,
                src=src,
                is_dir=src.is_dir(),
                action=action,               # cut/copy
                dst_default=dst_default,
                conflict=conflict,
                suggested_dst=suggested
            ))
        return plan

    # ---------- 実行層（GUIの決定を受けて実際に処理） ----------
    def _copy_file(self, src: Path, dst: Path, follow_symlinks: bool) -> Path:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
        return dst

    def _copy_dir(self, src: Path, dst: Path, follow_symlinks: bool) -> Path:
        if dst.exists():
            raise FileExistsError(f"Destination exists: {dst}")
        shutil.copytree(src, dst, symlinks=not follow_symlinks, dirs_exist_ok=False)
        return dst

    def _move_any(self, src: Path, dst: Path) -> Path:
        dst.parent.mkdir(parents=True, exist_ok=True)
        return Path(shutil.move(str(src), str(dst)))

    def _is_subpath(self, child: Path, parent: Path) -> bool:
        """child が parent と同一 または その配下なら True"""
        try:
            child_r = child.resolve(strict=False)
            parent_r = parent.resolve(strict=False)
            return (child_r == parent_r) or (parent_r in child_r.parents)
        except Exception:
            # 解決不能なときは安全側で False（後段で例外として拾われる）
            return False

    def execute_paste(
        self,
        plan: List[PastePlanItem],
        decisions: Dict[int, PasteDecision],
        *,
        follow_symlinks: bool = True
    ) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []

        for item in plan:
            dec = decisions.get(item.index)
            if dec is None or dec.mode == "skip":
                results.append({
                    "action": "skip",
                    "src": str(item.src),
                    "dst": "",
                    "status": "skipped"
                })
                continue

            # --- 目的地の決定 ---
            if dec.mode == "overwrite":
                dst = item.dst_default
            elif dec.mode == "rename":
                if dec.new_name_or_path:
                    p = Path(dec.new_name_or_path)
                    dst = p if p.is_absolute() else (item.dst_default.parent / p)
                else:
                    dst = item.suggested_dst or item.dst_default
                # さらに衝突していればユニーク化
                if dst.exists():
                    dst = self._unique_path(dst.parent, dst.name)
            else:
                results.append({
                    "action": "unknown",
                    "src": str(item.src),
                    "dst": "",
                    "status": "error",
                    "error": f"unknown decision mode: {dec.mode}"
                })
                continue

            # --- 2) src と dst が実質同一パス問題への対処（自己消去防止） ---
            same_path = False
            try:
                same_path = (item.src.resolve(strict=False) == dst.resolve(strict=False))
            except Exception:
                same_path = False  # 解決不能でも通常フローへ

            if same_path:
                # cut: そのままは無意味/危険 -> ユニーク名に退避
                # copy: 自己上書きは危険 -> ユニーク名に複製
                dst = self._unique_path(dst.parent, dst.name)

            # --- 3) ディレクトリを自身の配下へ move しようとするケースを禁止 ---
            if item.action == "cut" and item.is_dir and self._is_subpath(dst, item.src):
                results.append({
                    "action": "move",
                    "src": str(item.src),
                    "dst": str(dst),
                    "status": "error",
                    "error": "cannot move a directory into itself or its subdirectory"
                })
                continue

            try:
                # --- 1) 上書き時の削除でシンボリックリンクを安全に扱う ---
                if dec.mode == "overwrite" and dst.exists():
                    # シンボリックリンクは unlink、それ以外は型に応じて削除
                    if dst.is_symlink():
                        dst.unlink()
                    elif dst.is_dir():
                        shutil.rmtree(dst)
                    else:
                        dst.unlink()

                # 実処理
                if item.action == "cut":
                    done = self._move_any(item.src, dst)
                    results.append({"action": "move", "src": str(item.src), "dst": str(done), "status": "ok"})
                else:
                    if item.is_dir:
                        done = self._copy_dir(item.src, dst, follow_symlinks)
                    else:
                        done = self._copy_file(item.src, dst, follow_symlinks)
                    results.append({"action": "copy", "src": str(item.src), "dst": str(done), "status": "ok"})

            except Exception as e:
                results.append({
                    "action": "move" if item.action == "cut" else "copy",
                    "src": str(item.src),
                    "dst": str(dst),
                    "status": "error",
                    "error": repr(e)
                })

        return results
