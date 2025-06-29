import time
import os
import concurrent.futures
from PIL import Image
from PySide6 import QtGui
from ..profiling import init_env
from ..common import normalize_path

logger, profiler = init_env()

extensions = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")
CHUNK = 900
BASE_DURATION = 10.0
MIN_BATCH_SIZE = 100
MAX_BATCH_SIZE = 100000
INITIAL_BATCH_SIZE = 5000
executor = concurrent.futures.ThreadPoolExecutor()


def get_file_ctime(path):
    try:
        stat = os.stat(path)
        if hasattr(stat, 'st_birthtime'):
            return stat.st_birthtime
        else:
            return stat.st_ctime
    except Exception as e:
        logger.warning(f"Failed to get ctime for {path}: {e}")
        return None


def read_info(path):
    try:
        with Image.open(path) as img:
            return dict(img.info)
    except Exception as e:
        logger.warning(f"Failed to read image info for {path}: {e}")
    return {}


def get_aspect(p):
    reader = QtGui.QImageReader(p)
    reader.setAutoTransform(True)
    size = reader.size()
    aspect = size.width() / size.height() if size.isValid() and size.height() > 0 else 1.0
    return aspect


def process_image(p, file_info):
    try:
        mtime, fsize = file_info.get(p, (None, None))
        ctime = get_file_ctime(p)
        collected_at = time.time()
        aspect = get_aspect(p)
        info = read_info(p)
        meta_info = [(str(p), str(k), str(v)) for k, v in info.items()]
        meta_info.append((str(p), "__filepath__", str(p)))
        return (p, aspect, mtime, fsize, ctime, collected_at, meta_info, None)
    except Exception as e:
        logger.warning(f"Failed to process {p}: {e}")
        mtime, fsize = file_info.get(p, (None, None))
        return (p, None, mtime, fsize, None, time.time(), [], 'fail')

