from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ....core.platform.path_utils import validate_filename
from ....plugin.rename.base import BaseRenameSourcePlugin, SegmentInfo


@dataclass
class PostProcess:
    trim_start: int | None = None
    trim_end: int | None = None
    find: str = ''
    replace: str = ''
    find_regex: bool = False
    case_mode: str = ''
    prefix: str = ''
    suffix: str = ''

    def apply(self, text: str) -> str:
        s, e = self.trim_start, self.trim_end
        if s is not None or e is not None:
            text = text[s:e]
        if self.find:
            if self.find_regex:
                try:
                    text = re.sub(self.find, self.replace, text)
                except re.error:
                    pass
            else:
                text = text.replace(self.find, self.replace)
        if self.case_mode == 'upper':
            text = text.upper()
        elif self.case_mode == 'lower':
            text = text.lower()
        elif self.case_mode == 'title':
            text = text.title()
        return self.prefix + text + self.suffix


class RenameColumn:

    def __init__(
        self,
        source: BaseRenameSourcePlugin,
        post: PostProcess | None = None,
        enabled: bool = True,
    ):
        self.source = source
        self.post = post or PostProcess()
        self.enabled = enabled

    def evaluate(self, segment: SegmentInfo) -> str:
        return self.post.apply(self.source.evaluate(segment))


@dataclass
class RenameResult:
    original: str
    segments: list[str]
    new_name: str
    conflict: bool = False
    errors: list[str] = field(default_factory=list)
    missing: bool = False


class RenameEngine:

    @staticmethod
    def preview(
        paths: list[Path],
        columns: list[RenameColumn],
        ext_column: RenameColumn,
        metadata: dict[str, dict[str, str]] | None = None,
        keys: list[str] | None = None,
        initial_keys: list[str] | None = None,
    ) -> list[RenameResult]:
        metadata = metadata or {}
        total = len(paths)
        if keys is None:
            keys = [str(p).replace('\\', '/') for p in paths]
        seq_base = initial_keys if initial_keys is not None else keys
        seq_map = {k: i for i, k in enumerate(seq_base)}
        results: list[RenameResult] = []
        for i, (p, key) in enumerate(zip(paths, keys)):
            stem, ext = p.stem, p.suffix.lstrip('.')
            segment = SegmentInfo(
                index=seq_map.get(key, i),
                total=total,
                original_path=p,
                stem=stem,
                ext=ext,
                metadata=metadata.get(key, {}),
            )
            segs = [col.evaluate(segment) for col in columns]
            ext_part = ext_column.evaluate(segment)
            enabled_parts = [
                s for s, col in zip(segs, columns) if col.enabled
            ]
            results.append(
                RenameResult(
                    original=p.name,
                    segments=segs + [ext_part],
                    new_name=''.join(enabled_parts) + ext_part,
                )
            )
        seen: dict[str, list[int]] = {}
        for idx, r in enumerate(results):
            seen.setdefault(r.new_name.lower(), []).append(idx)
        for indices in seen.values():
            if len(indices) > 1:
                for idx in indices:
                    results[idx].conflict = True
        existing_names = {p.name.lower() for p in paths}
        for idx, (r, p) in enumerate(zip(results, paths)):
            issues = validate_filename(r.new_name)
            if issues:
                r.errors = issues
            if not r.conflict and r.new_name.lower() != p.name.lower():
                if r.new_name.lower() in existing_names:
                    r.conflict = True
        return results
