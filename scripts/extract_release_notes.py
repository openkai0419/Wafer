from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


SECTION_RE = re.compile(r"^##\s+\[?v?(\d+\.\d+\.\d+)\]?\s*$", re.IGNORECASE | re.MULTILINE)


def normalize_tag(value: str) -> str:
    text = str(value or "").strip()
    return text[1:] if text[:1].lower() == "v" else text


def extract_release_notes(text: str, tag: str) -> str:
    target = normalize_tag(tag)
    if not target:
        raise ValueError("release tag is empty")

    matches = list(SECTION_RE.finditer(text))
    for index, match in enumerate(matches):
        if normalize_tag(match.group(1)) != target:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        return text[match.start() : end].strip() + "\n"
    raise ValueError(f"release notes section not found for {tag}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract one version section from RELEASE_NOTES.md")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("tag")
    args = parser.parse_args(argv)

    try:
        notes = extract_release_notes(args.source.read_text(encoding="utf-8"), args.tag)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(notes, encoding="utf-8")
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
