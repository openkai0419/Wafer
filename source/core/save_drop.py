import os
import shutil
import platform
import requests  # using requests for downloading, install it if not available
from PySide6.QtCore import QMimeData, QByteArray
from PySide6.QtGui import QImage

def get_unique_filename(directory: str, name: str) -> str:
    """If 'name' exists in 'directory', generate a new name to avoid overwriting."""
    base, ext = os.path.splitext(name)
    candidate = name
    counter = 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{base} ({counter}){ext}"
        counter += 1
    return candidate

def save_dropped_data(mime: QMimeData, dest_dir: str):
    os.makedirs(dest_dir, exist_ok=True)  # ensure destination exists

    # 1. Check for direct image data
    if mime.hasImage():
        # Retrieve QImage from mime data
        qimage = QImage(mime.imageData())  # convert QVariant to QImage
        # Determine file extension/format
        fmt = "png"
        ext = ".png"
        for fmt_name in mime.formats():
            if fmt_name.lower().startswith("image/"):
                if "png" in fmt_name:
                    fmt, ext = "png", ".png"
                elif "jpeg" in fmt_name or "jpg" in fmt_name:
                    fmt, ext = "jpg", ".jpg"
                elif "bmp" in fmt_name:
                    fmt, ext = "bmp", ".bmp"
                # (additional image formats can be added here)
        # Determine base filename
        base_name = "image"
        if mime.hasUrls():
            # if an URL is provided, use its filename part if possible
            first_url = mime.urls()[0]
            fname = first_url.fileName()
            if fname:
                base_name = os.path.splitext(fname)[0]
        filename = get_unique_filename(dest_dir, base_name + ext)
        file_path = os.path.join(dest_dir, filename)
        qimage.save(file_path, fmt.upper())
        print(f"Saved image to {file_path}")
        return  # done

        # 3. Check for URLs (file paths or web URLs)
    if mime.hasUrls():
        for url in mime.urls():
            if url.isLocalFile():
                src_path = url.toLocalFile()
                if os.path.exists(src_path):
                    fname = os.path.basename(src_path)
                    dest_name = get_unique_filename(dest_dir, fname)
                    dest_path = os.path.join(dest_dir, dest_name)
                    try:
                        shutil.copy2(src_path, dest_path)
                        print(f"Copied file {src_path} to {dest_path}")
                    except Exception as e:
                        print(f"Failed to copy {src_path}: {e}")
                else:
                    print(f"Local file not found: {src_path}")
            else:
                url_str = url.toString()
                if url_str.startswith("blob:"):
                    print(f"Encountered blob URL: {url_str}")
                    continue
                base_name = url.fileName() or url.host() or "link"
                if url_str.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                    try:
                        resp = requests.get(url_str, timeout=10)
                        ct = resp.headers.get("Content-Type", "")
                        if resp.status_code == 200 and ct.lower().startswith("image/"):
                            ext = "." + ct.split("/")[-1] if "/" in ct else ""
                            image_name = get_unique_filename(dest_dir, base_name + ext)
                            image_path = os.path.join(dest_dir, image_name)
                            with open(image_path, 'wb') as f:
                                f.write(resp.content)
                            print(f"Downloaded image to {image_path}")
                    except Exception as e:
                        print(f"Failed to download {url_str}: {e}")

    system = platform.system()
    if system == "Windows":
        for fmt in mime.formats():
            if fmt.startswith("application/x-qt-windows-mime") and "FileGroupDescriptor" in fmt:
                raw_data = mime.data(fmt)
                data = bytes(raw_data)

                if len(data) < 4:
                    print("Invalid descriptor data")
                    return

                count = int.from_bytes(data[0:4], byteorder='little')
                offset = 4
                filenames = []

                for i in range(count):
                    # デコードパターンの候補を順に試す
                    patterns = [
                        # (size, start, end, codec)
                        (592, 72, 72+260, 'utf-16le'),
                        (592, 72, 72+260, 'mbcs'),
                        (852, 332, 332+520, 'utf-16le'),
                    ]

                    filename = None

                    for size, start, end, codec in patterns:
                        name_bytes = data[offset+start : offset+end]
                        try:
                            decoded = name_bytes.decode(codec).split('\x00', 1)[0].strip()
                            name, ext = os.path.splitext(decoded)
                            if ext:  # 拡張子が見つかればOK
                                filename = decoded
                                break
                        except Exception:
                            continue  # 次のパターンへ

                    if not filename:
                        raise Exception(f"Failed to extract filename at index {i}")

                    filenames.append(filename)
                    offset += size

                for idx, name in enumerate(filenames):
                    content_fmt = f'application/x-qt-windows-mime;value="FileContents";index={idx}'
                    if mime.hasFormat(content_fmt):
                        content_data = mime.data(content_fmt)
                    else:
                        content_data = mime.data('application/x-qt-windows-mime;value="FileContents"')
                    if content_data is None:
                        print(f"No content data for {name}")
                        continue
                    safe_name = get_unique_filename(dest_dir, name)
                    file_path = os.path.join(dest_dir, safe_name)
                    with open(file_path, 'wb') as f:
                        f.write(bytes(content_data))
                    print(f"Saved file to {file_path}")
                return

        return

    print("No supported data in drop.")
