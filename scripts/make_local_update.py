from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build as build_mod
from make_update_manifest import make_manifest


def load_dev():
    dev_path = ROOT / "wafer" / "_dev.py"
    spec = importlib.util.spec_from_file_location("wafer_update_dev", dev_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def zip_dist(dist_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(dist_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(dist_dir).as_posix())


def make_latest_json(version: str, zip_name: str) -> dict:
    return {
        "tag_name": f"v{version}",
        "name": f"Wafer v{version}",
        "html_url": "https://github.com/openkai0419/Wafer/releases/latest",
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "body": "Local test update",
        "assets": [{"name": "manifest.json"}, {"name": zip_name}],
    }


def main(argv: list[str]) -> int:
    dev = load_dev()
    out_dir = dev.source_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    version = build_mod.get_git_version() or build_mod.read_fallback_version()
    print(f"[local-update] Building portable package v{version}")
    build_mod.build()

    dist_dir = ROOT / "dist" / build_mod.DIST_NAME
    zip_name = f"Wafer-v{version}.zip"
    zip_path = out_dir / zip_name
    print(f"[local-update] Zipping {dist_dir} -> {zip_path}")
    zip_dist(dist_dir, zip_path)

    manifest = make_manifest(zip_path, version)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out_dir / "latest.json").write_text(json.dumps(make_latest_json(version, zip_name), indent=2) + "\n", encoding="utf-8")

    print(f"[local-update] Update source ready: {out_dir}")
    print("[local-update] Set wafer/_dev.py FORCE_UPDATE_ENABLED = True, then run dist/Wafer/Wafer.exe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
