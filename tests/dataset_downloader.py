"""
Dataset downloader for testing.

Downloads sample files from permissive-license sources for integration tests.
Files are tracked by manifest.json for idempotent downloads and clean removal.

Sources:
  Images  — Lorem Picsum  (Unsplash License, free for any use)
  Videos  — Blender Open Movies  (CC BY 3.0 / 4.0)
  Audio   — Programmatically generated WAV (no external source)
  Archive — ZIP bundles built from the above

Usage:
    python tests/dataset_downloader.py download [--types image,video,audio,archive] [--count N] [--dest PATH]
    python tests/dataset_downloader.py clean   [--dest PATH]
    python tests/dataset_downloader.py status  [--dest PATH]
"""

import argparse
import array
import io
import json
import math
import os
import sys
import wave
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEST = PROJECT_ROOT / '.sample'
MANIFEST_NAME = 'manifest.json'

_ALLOWED_HOST_SUFFIXES = (
    'picsum.photos',
    'download.blender.org',
)

_PICSUM_IDS = list(range(10, 85))

_IMAGE_SIZES = [
    (640, 480),
    (800, 600),
    (1280, 720),
    (1920, 1080),
    (2560, 1440),
    (3840, 2160),
]

_IMAGE_FORMATS = ['jpg', 'png', 'webp']

_VIDEO_SOURCES = [
    ('BigBuckBunny_320x180.mp4',
     'https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4',
     'CC BY 3.0'),
    ('sintel_trailer-480p.mp4',
     'https://download.blender.org/durian/trailer/sintel_trailer-480p.mp4',
     'CC BY 3.0'),
    ('big_buck_bunny_720p_h264.mov',
     'https://download.blender.org/peach/bigbuckbunny_movies/big_buck_bunny_720p_h264.mov',
     'CC BY 3.0'),
    ('sintel_trailer-720p.mp4',
     'https://download.blender.org/durian/trailer/sintel_trailer-720p.mp4',
     'CC BY 3.0'),
    ('big_buck_bunny_1080p_h264.mov',
     'https://download.blender.org/peach/bigbuckbunny_movies/big_buck_bunny_1080p_h264.mov',
     'CC BY 3.0'),
]

_AUDIO_FREQUENCIES = [220, 330, 440, 550, 660, 880, 1000, 1200]
_AUDIO_DURATIONS = [3, 5, 10, 15, 30, 60, 120]


# ---------------------------------------------------------------------------
# Host validation
# ---------------------------------------------------------------------------

def _is_trusted_host(url: str) -> bool:
    hostname = urlparse(url).hostname
    if not hostname:
        return False
    return any(
        hostname == s or hostname.endswith('.' + s)
        for s in _ALLOWED_HOST_SUFFIXES
    )


# ---------------------------------------------------------------------------
# Download helper
# ---------------------------------------------------------------------------

def _download_file(url: str, dest: Path, *, timeout: int = 300) -> bool:
    import requests

    if not _is_trusted_host(url):
        print(f'  SKIP (untrusted host): {urlparse(url).hostname}')
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + '.tmp')

    try:
        resp = requests.get(url, stream=True, timeout=timeout, allow_redirects=True)
        if not _is_trusted_host(resp.url):
            print(f'  SKIP (redirect to untrusted host): {urlparse(resp.url).hostname}')
            return False
        resp.raise_for_status()

        total = int(resp.headers.get('content-length', 0))
        done = 0

        with open(tmp, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
                done += len(chunk)
                if total:
                    mb = done / (1024 * 1024)
                    total_mb = total / (1024 * 1024)
                    print(f'\r  {dest.name}: {mb:.1f}/{total_mb:.1f} MB ({done * 100 // total}%)', end='', flush=True)
                else:
                    print(f'\r  {dest.name}: {done / (1024 * 1024):.1f} MB', end='', flush=True)

        print()
        tmp.rename(dest)
        return True

    except Exception as e:
        print(f'\n  FAIL ({dest.name}): {e}')
        if tmp.exists():
            tmp.unlink()
        return False


def _download_bytes(url: str, *, timeout: int = 120) -> bytes | None:
    import requests

    if not _is_trusted_host(url):
        return None
    resp = requests.get(url, timeout=timeout, allow_redirects=True)
    if not _is_trusted_host(resp.url):
        return None
    resp.raise_for_status()
    return resp.content


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def load_manifest(dest: Path | None = None) -> dict:
    if dest is None:
        dest = DEFAULT_DEST
    path = dest / MANIFEST_NAME
    if path.exists():
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return {'files': [], 'downloaded_at': None, 'dest': str(dest)}


def _save_manifest(dest: Path, manifest: dict):
    dest.mkdir(parents=True, exist_ok=True)
    with open(dest / MANIFEST_NAME, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Public helpers (for test imports)
# ---------------------------------------------------------------------------

def get_sample_files(dest: Path | None = None, file_type: str | None = None) -> list[Path]:
    if dest is None:
        dest = DEFAULT_DEST
    manifest = load_manifest(dest)
    result = []
    for entry in manifest['files']:
        if file_type and entry.get('type') != file_type:
            continue
        p = dest / entry['path']
        if p.exists():
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# Type handlers
# ---------------------------------------------------------------------------

def _download_images(dest: Path, count: int, new_files: list):
    from PIL import Image

    print(f'\n=== Images ({count} files) ===')
    img_dir = dest / 'image'
    img_dir.mkdir(parents=True, exist_ok=True)

    n_fmts = len(_IMAGE_FORMATS)
    n_sizes = len(_IMAGE_SIZES)
    downloaded = 0

    for i in range(count):
        pid = _PICSUM_IDS[i % len(_PICSUM_IDS)]
        w, h = _IMAGE_SIZES[i % n_sizes]
        fmt = _IMAGE_FORMATS[i % n_fmts]
        url = f'https://picsum.photos/id/{pid}/{w}/{h}'
        stem = f'picsum_{pid}_{w}x{h}'

        if fmt == 'jpg':
            file_path = img_dir / f'{stem}.jpg'
            if file_path.exists():
                print(f'  EXISTS: {file_path.name}')
                downloaded += 1
                continue
            if _download_file(url, file_path):
                new_files.append(_entry(dest, file_path, 'picsum.photos', 'Unsplash License', 'image'))
                downloaded += 1
        else:
            file_path = img_dir / f'{stem}.{fmt}'
            if file_path.exists():
                print(f'  EXISTS: {file_path.name}')
                downloaded += 1
                continue
            try:
                raw = _download_bytes(url)
                if raw is None:
                    continue
                img = Image.open(io.BytesIO(raw))
                save_fmt = 'PNG' if fmt == 'png' else 'WEBP'
                save_kw = {'quality': 90} if fmt == 'webp' else {}
                img.save(file_path, save_fmt, **save_kw)
                size_mb = file_path.stat().st_size / (1024 * 1024)
                print(f'  {file_path.name}: {size_mb:.1f} MB (converted)')
                new_files.append(_entry(dest, file_path, 'picsum.photos', 'Unsplash License', 'image'))
                downloaded += 1
            except Exception as e:
                print(f'  FAIL ({file_path.name}): {e}')

    print(f'  Images completed: {downloaded}/{count}')


def _download_videos(dest: Path, count: int, new_files: list):
    print(f'\n=== Videos (up to {count} files) ===')
    vid_dir = dest / 'video'
    vid_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    for name, url, lic in _VIDEO_SOURCES:
        if downloaded >= count:
            break
        file_path = vid_dir / name
        if file_path.exists():
            print(f'  EXISTS: {name}')
            downloaded += 1
            continue
        if _download_file(url, file_path):
            new_files.append(_entry(dest, file_path, url, lic, 'video'))
            downloaded += 1

    print(f'  Videos completed: {downloaded}/{min(count, len(_VIDEO_SOURCES))}')


def _generate_audio(dest: Path, count: int, new_files: list):
    print(f'\n=== Audio ({count} files, generated) ===')
    audio_dir = dest / 'audio'
    audio_dir.mkdir(parents=True, exist_ok=True)

    sample_rate = 44100
    generated = 0

    for i in range(count):
        freq = _AUDIO_FREQUENCIES[i % len(_AUDIO_FREQUENCIES)]
        duration = _AUDIO_DURATIONS[i % len(_AUDIO_DURATIONS)]
        name = f'tone_{freq}hz_{duration}s.wav'
        file_path = audio_dir / name

        if file_path.exists():
            print(f'  EXISTS: {name}')
            generated += 1
            continue

        n_frames = sample_rate * duration
        samples = array.array('h', bytes(n_frames * 4))
        two_pi = 2.0 * math.pi

        for n in range(n_frames):
            t = n / sample_rate
            samples[n * 2] = int(32767 * math.sin(two_pi * freq * t))
            samples[n * 2 + 1] = int(32767 * math.sin(two_pi * freq * 1.5 * t))

        with wave.open(str(file_path), 'w') as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(samples.tobytes())

        size_mb = file_path.stat().st_size / (1024 * 1024)
        print(f'  {name}: {size_mb:.1f} MB')
        new_files.append(_entry(dest, file_path, 'generated', 'N/A', 'audio'))
        generated += 1

    print(f'  Audio completed: {generated}/{count}')


def _generate_archives(dest: Path, count: int, new_files: list):
    print(f'\n=== Archives ({count} files, generated) ===')
    archive_dir = dest / 'archive'
    archive_dir.mkdir(parents=True, exist_ok=True)

    sources: list[Path] = []
    for sub in ('image', 'video', 'audio'):
        d = dest / sub
        if d.exists():
            sources.extend(f for f in d.iterdir() if f.is_file())

    if not sources:
        print('  SKIP: no source files to bundle')
        return

    per_zip = max(1, len(sources) // max(count, 1))
    generated = 0

    for i in range(count):
        name = f'mixed_bundle_{i + 1}.zip'
        file_path = archive_dir / name
        if file_path.exists():
            print(f'  EXISTS: {name}')
            generated += 1
            continue

        start = (i * per_zip) % len(sources)
        bundle = sources[start:start + per_zip] or sources[:per_zip]

        with zipfile.ZipFile(file_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in bundle:
                zf.write(f, f.name)

        size_mb = file_path.stat().st_size / (1024 * 1024)
        print(f'  {name}: {size_mb:.1f} MB ({len(bundle)} files)')
        new_files.append(_entry(dest, file_path, 'generated', 'N/A', 'archive'))
        generated += 1

    print(f'  Archives completed: {generated}/{count}')


def _entry(dest: Path, file_path: Path, source: str, lic: str, ftype: str) -> dict:
    return {
        'path': file_path.relative_to(dest).as_posix(),
        'source': source,
        'license': lic,
        'type': ftype,
    }


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

_TYPE_HANDLERS = {
    'image': _download_images,
    'video': _download_videos,
    'audio': _generate_audio,
}


def cmd_download(dest: Path, types: list[str], count: int):
    import requests  # noqa: F401  — fail-fast if missing

    print(f'Destination : {dest}')
    print(f'Types       : {", ".join(types)}')
    print(f'Count/type  : {count}')

    manifest = load_manifest(dest)
    existing = {e['path'] for e in manifest['files']}
    new_files: list[dict] = []

    for t in types:
        if t == 'archive':
            continue
        handler = _TYPE_HANDLERS.get(t)
        if handler:
            handler(dest, count, new_files)
        else:
            print(f'  Unknown type: {t}')

    if 'archive' in types:
        _generate_archives(dest, count, new_files)

    for f in new_files:
        if f['path'] not in existing:
            manifest['files'].append(f)

    manifest['downloaded_at'] = datetime.now(timezone.utc).isoformat()
    manifest['dest'] = str(dest)
    _save_manifest(dest, manifest)

    total = len(manifest['files'])
    print(f'\nDone. {len(new_files)} new, {total} total in manifest.')


def cmd_clean(dest: Path):
    manifest = load_manifest(dest)
    removed = 0
    for entry in manifest['files']:
        p = dest / entry['path']
        if p.exists():
            p.unlink()
            removed += 1

    for sub in ('image', 'video', 'audio', 'archive'):
        d = dest / sub
        if d.exists() and not any(d.iterdir()):
            d.rmdir()

    mf = dest / MANIFEST_NAME
    if mf.exists():
        mf.unlink()

    if dest.exists() and not any(dest.iterdir()):
        dest.rmdir()

    print(f'Removed {removed} files from {dest}')


def cmd_status(dest: Path):
    manifest = load_manifest(dest)
    if not manifest['files']:
        print(f'No dataset at {dest}')
        print(f'Run: python {Path(__file__).name} download')
        return

    by_type: dict[str, list[tuple[str, int, bool]]] = {}
    total_size = 0
    for entry in manifest['files']:
        t = entry.get('type', 'unknown')
        p = dest / entry['path']
        exists = p.exists()
        size = p.stat().st_size if exists else 0
        by_type.setdefault(t, []).append((entry['path'], size, exists))
        total_size += size

    print(f'Dataset     : {dest}')
    print(f'Downloaded  : {manifest.get("downloaded_at", "N/A")}')
    print(f'Total       : {len(manifest["files"])} files, {total_size / (1024 * 1024):.1f} MB')
    for t, files in sorted(by_type.items()):
        t_size = sum(s for _, s, _ in files)
        missing = sum(1 for _, _, e in files if not e)
        line = f'  {t:10s}: {len(files)} files ({t_size / (1024 * 1024):.1f} MB)'
        if missing:
            line += f'  [{missing} missing]'
        print(line)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Dataset downloader for testing')
    parser.add_argument('--dest', default=str(DEFAULT_DEST),
                        help=f'Download destination (default: .sample/)')
    sub = parser.add_subparsers(dest='command', required=True)

    dl = sub.add_parser('download', help='Download / generate sample files')
    dl.add_argument('--types', default='image,video,audio,archive',
                    help='Comma-separated types: image,video,audio,archive')
    dl.add_argument('--count', type=int, default=20,
                    help='Max files per type (default: 20)')

    sub.add_parser('clean', help='Remove all tracked files')
    sub.add_parser('status', help='Show dataset summary')

    args = parser.parse_args()
    dest = Path(args.dest).resolve()

    if args.command == 'download':
        types = [t.strip() for t in args.types.split(',')]
        cmd_download(dest, types, args.count)
    elif args.command == 'clean':
        cmd_clean(dest)
    elif args.command == 'status':
        cmd_status(dest)


if __name__ == '__main__':
    main()
