"""
Dataset downloader for visual debugging and stress testing.

Downloads/generates sample files from permissive-license sources.
Files are tracked by manifest.json for idempotent downloads and clean removal.

Sources:
  Images    -- Lorem Picsum (Unsplash License, free for any use)
  Animated  -- Programmatically generated GIF / APNG / animated WebP
  Videos    -- Blender Open Movies (CC BY 3.0 / 4.0)
  COCO      -- Manual download detection (.sample/coco/)

Presets:
  minimal   -- Quick setup for CI / fast iteration (30 images, 2 videos, 5 animated)
  standard  -- Normal development (200 images, 5 videos, 30 animated)
  large     -- Comprehensive visual testing (993 images, 5 videos, 100 animated)

Usage:
    python tests/dataset_downloader.py download [--preset standard] [--images N] [--videos N] [--animated N]
    python tests/dataset_downloader.py clean   [--dest PATH]
    python tests/dataset_downloader.py status  [--dest PATH]
"""

import argparse
import json
import math
import random
import struct
import sys
import zlib
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

PRESETS = {
    'minimal': {'images': 30, 'videos': 2, 'animated': 5},
    'standard': {'images': 200, 'videos': 5, 'animated': 30},
    'large': {'images': 993, 'videos': 5, 'animated': 100},
}

_IMAGE_SIZES = [
    (640, 480),
    (800, 600),
    (1024, 768),
    (1280, 720),
    (1920, 1080),
    (2560, 1440),
]

_IMAGE_FORMATS = ['jpg', 'webp', 'png']

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

_ANIMATED_SIZES = [
    (160, 120),
    (320, 240),
    (480, 360),
    (640, 480),
]


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
# Picsum ID fetching
# ---------------------------------------------------------------------------

def _fetch_picsum_ids(dest: Path) -> list[int]:
    cache_path = dest / '_picsum_ids.json'
    if cache_path.exists():
        with open(cache_path, encoding='utf-8') as f:
            cached = json.load(f)
        if cached.get('ids'):
            return cached['ids']

    import requests

    print('  Fetching available Picsum IDs...')
    ids: list[int] = []
    page = 1
    while True:
        r = requests.get(
            f'https://picsum.photos/v2/list?page={page}&limit=100',
            timeout=30,
        )
        if not _is_trusted_host(r.url):
            break
        data = r.json()
        if not data:
            break
        ids.extend(int(item['id']) for item in data)
        page += 1

    if ids:
        dest.mkdir(parents=True, exist_ok=True)
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump({'ids': sorted(ids), 'fetched_at': datetime.now(timezone.utc).isoformat()}, f)
        print(f'  Found {len(ids)} Picsum IDs (cached)')

    return sorted(ids)


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


def _entry(dest: Path, file_path: Path, source: str, lic: str, ftype: str) -> dict:
    return {
        'path': file_path.relative_to(dest).as_posix(),
        'source': source,
        'license': lic,
        'type': ftype,
    }


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
# Image downloader (Picsum)
# ---------------------------------------------------------------------------

def _download_images(dest: Path, count: int, new_files: list):
    from PIL import Image
    import io

    print(f'\n=== Images ({count} files) ===')
    img_dir = dest / 'image'
    img_dir.mkdir(parents=True, exist_ok=True)

    all_ids = _fetch_picsum_ids(dest)
    if not all_ids:
        print('  ERROR: Could not fetch Picsum IDs')
        return

    n_sizes = len(_IMAGE_SIZES)
    n_fmts = len(_IMAGE_FORMATS)

    combos: list[tuple[int, tuple[int, int], str]] = []
    for idx, pid in enumerate(all_ids):
        size = _IMAGE_SIZES[idx % n_sizes]
        fmt = _IMAGE_FORMATS[idx % n_fmts]
        combos.append((pid, size, fmt))

    if count > len(all_ids):
        extra_needed = count - len(all_ids)
        used = set((c[0], c[1], c[2]) for c in combos)
        extra_combos: list[tuple[int, tuple[int, int], str]] = []
        for pid in all_ids:
            for size in _IMAGE_SIZES:
                for fmt in _IMAGE_FORMATS:
                    key = (pid, size, fmt)
                    if key not in used:
                        extra_combos.append(key)
        rng = random.Random(42)
        rng.shuffle(extra_combos)
        combos.extend(extra_combos[:extra_needed])

    downloaded = 0
    for pid, (w, h), fmt in combos[:count]:
        stem = f'picsum_{pid}_{w}x{h}'
        url = f'https://picsum.photos/id/{pid}/{w}/{h}'

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


# ---------------------------------------------------------------------------
# Video downloader (Blender)
# ---------------------------------------------------------------------------

def _download_videos(dest: Path, count: int, new_files: list):
    actual = min(count, len(_VIDEO_SOURCES))
    print(f'\n=== Videos ({actual} files) ===')
    vid_dir = dest / 'video'
    vid_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    for name, url, lic in _VIDEO_SOURCES[:actual]:
        file_path = vid_dir / name
        if file_path.exists():
            print(f'  EXISTS: {name}')
            downloaded += 1
            continue
        if _download_file(url, file_path):
            new_files.append(_entry(dest, file_path, url, lic, 'video'))
            downloaded += 1

    print(f'  Videos completed: {downloaded}/{actual}')


# ---------------------------------------------------------------------------
# Animated image generator
# ---------------------------------------------------------------------------

def _generate_animated_gif(path: Path, w: int, h: int, n_frames: int, seed: int):
    from PIL import Image, ImageDraw

    rng = random.Random(seed)
    frames: list[Image.Image] = []

    bg_r, bg_g, bg_b = rng.randint(20, 80), rng.randint(20, 80), rng.randint(20, 80)
    shape_colors = [
        (rng.randint(100, 255), rng.randint(100, 255), rng.randint(100, 255))
        for _ in range(3)
    ]
    shapes = []
    for color in shape_colors:
        cx, cy = rng.randint(0, w), rng.randint(0, h)
        dx, dy = rng.randint(-8, 8), rng.randint(-8, 8)
        radius = rng.randint(min(w, h) // 10, min(w, h) // 4)
        shapes.append((cx, cy, dx, dy, radius, color))

    for frame_i in range(n_frames):
        img = Image.new('RGB', (w, h), (bg_r, bg_g, bg_b))
        draw = ImageDraw.Draw(img)
        for j, (cx, cy, dx, dy, radius, color) in enumerate(shapes):
            x = (cx + dx * frame_i) % w
            y = (cy + dy * frame_i) % h
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=color)
        frames.append(img)

    frames[0].save(
        path, save_all=True, append_images=frames[1:],
        duration=80, loop=0, optimize=False,
    )


def _generate_apng(path: Path, w: int, h: int, n_frames: int, seed: int):
    rng = random.Random(seed)

    def _make_frame_rgba(frame_i: int) -> bytes:
        pixels = bytearray(w * h * 4)
        for y_pos in range(h):
            for x_pos in range(w):
                offset = (y_pos * w + x_pos) * 4
                t = frame_i / max(n_frames - 1, 1)
                r_val = int(127 + 127 * math.sin(2 * math.pi * (x_pos / w + t)))
                g_val = int(127 + 127 * math.sin(2 * math.pi * (y_pos / h + t * 0.7)))
                b_val = int(127 + 127 * math.sin(2 * math.pi * ((x_pos + y_pos) / (w + h) + t * 1.3)))
                pixels[offset] = r_val & 0xFF
                pixels[offset + 1] = g_val & 0xFF
                pixels[offset + 2] = b_val & 0xFF
                pixels[offset + 3] = 255
        return bytes(pixels)

    def _make_idat(raw_data: bytes) -> bytes:
        filtered = bytearray()
        stride = w * 4
        for y_pos in range(h):
            filtered.append(0)
            filtered.extend(raw_data[y_pos * stride:(y_pos + 1) * stride])
        return zlib.compress(bytes(filtered))

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = zlib.crc32(c) & 0xFFFFFFFF
        return struct.pack('>I', len(data)) + c + struct.pack('>I', crc)

    sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)
    actl_data = struct.pack('>II', n_frames, 0)

    chunks = [sig, _chunk(b'IHDR', ihdr_data), _chunk(b'acTL', actl_data)]

    seq_num = 0
    for i in range(n_frames):
        rgba = _make_frame_rgba(i)
        compressed = _make_idat(rgba)

        fctl_data = struct.pack('>IIIIIHHBB',
                                seq_num, w, h, 0, 0,
                                80, 1000, 0, 0)
        chunks.append(_chunk(b'fcTL', fctl_data))
        seq_num += 1

        if i == 0:
            chunks.append(_chunk(b'IDAT', compressed))
        else:
            fdat_data = struct.pack('>I', seq_num) + compressed
            chunks.append(_chunk(b'fdAT', fdat_data))
            seq_num += 1

    chunks.append(_chunk(b'IEND', b''))
    path.write_bytes(b''.join(chunks))


def _generate_animated_webp(path: Path, w: int, h: int, n_frames: int, seed: int):
    from PIL import Image, ImageDraw

    rng = random.Random(seed)
    frames: list[Image.Image] = []

    for frame_i in range(n_frames):
        img = Image.new('RGBA', (w, h), (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)

        stripe_w = max(w // 6, 1)
        offset = int(frame_i * stripe_w * 0.5) % (stripe_w * 2)

        for x_start in range(-offset, w + stripe_w, stripe_w * 2):
            hue_shift = (seed * 53 + frame_i * 20 + x_start) % 360
            r = int(127 + 127 * math.sin(math.radians(hue_shift)))
            g = int(127 + 127 * math.sin(math.radians(hue_shift + 120)))
            b = int(127 + 127 * math.sin(math.radians(hue_shift + 240)))
            draw.rectangle([x_start, 0, x_start + stripe_w - 1, h - 1], fill=(r, g, b, 255))

        n_circles = rng.randint(2, 5)
        for _ in range(n_circles):
            cx = rng.randint(0, w)
            cy = rng.randint(0, h)
            cr = rng.randint(5, min(w, h) // 3)
            alpha = rng.randint(100, 200)
            color = (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255), alpha)
            draw.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=color)

        frames.append(img)

    frames[0].save(
        path, save_all=True, append_images=frames[1:],
        duration=80, loop=0, format='WEBP',
    )


def _generate_animated(dest: Path, count: int, new_files: list):
    print(f'\n=== Animated ({count} files, generated) ===')
    anim_dir = dest / 'animated'
    anim_dir.mkdir(parents=True, exist_ok=True)

    formats = ['gif', 'apng', 'webp']
    frame_counts = [4, 8, 12, 16, 24]
    generated = 0

    for i in range(count):
        fmt = formats[i % len(formats)]
        w, h = _ANIMATED_SIZES[i % len(_ANIMATED_SIZES)]
        n_frames = frame_counts[i % len(frame_counts)]
        seed = i * 7 + 13

        ext = fmt if fmt != 'apng' else 'png'
        name = f'anim_{i:04d}_{w}x{h}_{n_frames}f.{ext}'
        file_path = anim_dir / name

        if file_path.exists():
            print(f'  EXISTS: {name}')
            generated += 1
            continue

        try:
            if fmt == 'gif':
                _generate_animated_gif(file_path, w, h, n_frames, seed)
            elif fmt == 'apng':
                _generate_apng(file_path, w, h, n_frames, seed)
            elif fmt == 'webp':
                _generate_animated_webp(file_path, w, h, n_frames, seed)

            size_kb = file_path.stat().st_size / 1024
            print(f'  {name}: {size_kb:.0f} KB')
            new_files.append(_entry(dest, file_path, 'generated', 'N/A', 'animated'))
            generated += 1
        except Exception as e:
            print(f'  FAIL ({name}): {e}')

    print(f'  Animated completed: {generated}/{count}')


# ---------------------------------------------------------------------------
# COCO detection (manual download)
# ---------------------------------------------------------------------------

def _detect_coco(dest: Path) -> dict[str, int]:
    coco_dir = dest / 'coco'
    result: dict[str, int] = {}
    if not coco_dir.exists():
        return result
    for sub in sorted(coco_dir.iterdir()):
        if sub.is_dir():
            count = sum(1 for f in sub.iterdir() if f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png'))
            if count:
                result[sub.name] = count
    return result


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

_TYPE_HANDLERS = {
    'images': _download_images,
    'videos': _download_videos,
    'animated': _generate_animated,
}


def cmd_download(dest: Path, counts: dict[str, int]):
    print(f'Destination : {dest}')
    for t, c in counts.items():
        print(f'  {t:10s}: {c}')

    manifest = load_manifest(dest)
    existing = {e['path'] for e in manifest['files']}
    new_files: list[dict] = []

    for t in ('images', 'videos', 'animated'):
        c = counts.get(t, 0)
        if c <= 0:
            continue
        handler = _TYPE_HANDLERS.get(t)
        if handler:
            handler(dest, c, new_files)

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

    for sub in ('image', 'video', 'animated'):
        d = dest / sub
        if d.exists() and not any(d.iterdir()):
            d.rmdir()

    for cache in (dest / '_picsum_ids.json',):
        if cache.exists():
            cache.unlink()

    mf = dest / MANIFEST_NAME
    if mf.exists():
        mf.unlink()

    if dest.exists() and not any(dest.iterdir()):
        dest.rmdir()

    print(f'Removed {removed} files from {dest}')


def cmd_status(dest: Path):
    manifest = load_manifest(dest)

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
    total_files = len(manifest['files'])

    coco = _detect_coco(dest)
    coco_total = sum(coco.values())

    print(f'Total       : {total_files + coco_total} files ({total_files} managed + {coco_total} COCO), {total_size / (1024 * 1024):.1f} MB (managed)')

    for t, files in sorted(by_type.items()):
        t_size = sum(s for _, s, _ in files)
        missing = sum(1 for _, _, e in files if not e)
        line = f'  {t:10s}: {len(files)} files ({t_size / (1024 * 1024):.1f} MB)'
        if missing:
            line += f'  [{missing} missing]'
        print(line)

    if coco:
        for name, count in sorted(coco.items()):
            print(f'  coco/{name:5s}: {count} files (manual)')
    elif not manifest['files']:
        print(f'No dataset at {dest}')
        print(f'Run: python {Path(__file__).name} download')

    print()
    print('Presets:')
    for name, cfg in PRESETS.items():
        parts = ', '.join(f'{k}={v}' for k, v in cfg.items())
        print(f'  {name:10s}: {parts}')

    if not coco:
        print()
        print('COCO (manual download for large-scale testing):')
        print('  val2017     (5,000 images, ~1GB):   http://images.cocodataset.org/zips/val2017.zip')
        print('  train2017   (118k images, ~18GB):    http://images.cocodataset.org/zips/train2017.zip')
        print('  unlabeled   (123k images, ~19GB):    http://images.cocodataset.org/zips/unlabeled2017.zip')
        print(f'  Extract to: {dest / "coco" / "<set_name>"}/')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Dataset downloader for testing')
    parser.add_argument('--dest', default=str(DEFAULT_DEST),
                        help='Download destination (default: .sample/)')
    sub = parser.add_subparsers(dest='command', required=True)

    dl = sub.add_parser('download', help='Download / generate sample files')
    dl.add_argument('--preset', default='standard', choices=PRESETS.keys(),
                    help='Preset configuration (default: standard)')
    dl.add_argument('--images', type=int, default=None,
                    help='Override image count')
    dl.add_argument('--videos', type=int, default=None,
                    help='Override video count')
    dl.add_argument('--animated', type=int, default=None,
                    help='Override animated count')

    sub.add_parser('clean', help='Remove all tracked files')
    sub.add_parser('status', help='Show dataset summary')

    args = parser.parse_args()
    dest = Path(args.dest).resolve()

    if args.command == 'download':
        counts = dict(PRESETS[args.preset])
        if args.images is not None:
            counts['images'] = args.images
        if args.videos is not None:
            counts['videos'] = args.videos
        if args.animated is not None:
            counts['animated'] = args.animated
        cmd_download(dest, counts)
    elif args.command == 'clean':
        cmd_clean(dest)
    elif args.command == 'status':
        cmd_status(dest)


if __name__ == '__main__':
    main()
