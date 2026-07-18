from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


MANIFEST_SCHEMA = 1


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_version(raw: str) -> str:
    match = re.match(r"^v?(\d+(?:\.\d+)*)", raw.strip())
    if not match:
        raise ValueError(f"invalid version: {raw!r}")
    return match.group(1)


def make_manifest(zip_path: Path, version: str) -> dict:
    return {
        "schema": MANIFEST_SCHEMA,
        "version": normalize_version(version),
        "assets": [
            {
                "name": zip_path.name,
                "kind": "full",
                "sha256": sha256_of(zip_path),
                "size": zip_path.stat().st_size,
            }
        ],
    }


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: make_update_manifest.py <zip_path> <version> <out_path>", file=sys.stderr)
        return 2
    zip_path = Path(argv[1])
    if not zip_path.is_file():
        print(f"zip not found: {zip_path}", file=sys.stderr)
        return 1
    manifest = make_manifest(zip_path, argv[2])
    Path(argv[3]).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"manifest written: {argv[3]} (version {manifest['version']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
