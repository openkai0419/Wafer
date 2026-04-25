import os
import re

from ...utils.logs import AppLogger

_README_NAMES = ("README.md", "readme.md", "Readme.md")
_MAX_BYTES = 8192
_EMPHASIS_RE = re.compile(r"(\*\*|\*|`|__|_)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def extract_readme_summary(folder_path: str) -> str:
    path = _find_readme(folder_path)
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read(_MAX_BYTES)
    except OSError as exc:
        AppLogger.warning(f"readme_summary: failed to read {path}: {exc}")
        return ""
    return _first_paragraph(text)


def _find_readme(folder_path: str) -> str:
    for name in _README_NAMES:
        candidate = os.path.join(folder_path, name)
        if os.path.isfile(candidate):
            return candidate
    return ""


def _first_paragraph(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if lines:
                break
            continue
        if line.startswith("#") or line.startswith(">") or line.startswith("- ") or line.startswith("* ") or line.startswith("```"):
            if lines:
                break
            continue
        lines.append(line)
    if not lines:
        return ""
    joined = " ".join(lines)
    joined = _LINK_RE.sub(r"\1", joined)
    joined = _EMPHASIS_RE.sub("", joined)
    return joined.strip()
