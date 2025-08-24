import os
import cv2
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from PIL import Image
from .exif_parser import ExifParser 

from ..common.profiling import logger
from ..common.hashes import fast_sig_hash
from .manager import BaseLoader, BaseReader

class ImageReader(BaseReader):
    ext = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')

    @classmethod
    def is_readable(cls, path: str) -> bool:
        return os.path.splitext(path)[-1].lower() in cls.ext
    
    def read(self, p, size=None):
        try:
            with Image.open(p) as img:
                width, height = img.size
                orientation = 1
                exif_for_orient = img.getexif()
                if exif_for_orient:
                    try:
                        orientation = int(exif_for_orient.get(274, 1))
                    except Exception:
                        orientation = 1
                if orientation in (5, 6, 7, 8):
                    width, height = height, width
                aspect = (width / height) if height else 1.0

                parser = ExifParser()
                res = parser.parse_img(img)
                if res["error"]:
                    raise RuntimeError(res["error"])
                exif_dict = res["exif"]
                info_items = res["info_items"]

            meta_info = {}
            meta_info.update(exif_dict)
            meta_info.update(info_items)

            # 基本情報
            info = {
                    "source" : str(p),
                    "path" : str(p),
                    "name" : str(os.path.basename(p)),
                    "aspect": aspect,
                    "file_hash": fast_sig_hash(p),
                    }
            
            # 追加情報
            tags = {
                "Width": str(width),
                "Height": str(height),
            }

            return (info, meta_info, tags, None)

        except Exception as e:
            from ..common.profiling import logger
            logger.warning(f'Failed to process {p}: {e}')
            info = {
            "source" : p,
            "path" : p,
            "name" : os.path.basename(p),
            "aspect": None,
            }
            return (info, {}, {}, 'fail')
        

class ImageLoader(BaseLoader):
    ext = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
    
    @classmethod
    def is_loadable(cls, path):
        return os.path.splitext(path)[-1].lower() in cls.ext

    # --- 変更点1: Qt側での縮小をデコーダにやらせる ---
    def _qt_read(self, path, size: QtCore.QSize | None, keep_aspect: bool) -> QtGui.QImage | None:
        reader = QtGui.QImageReader(path)
        reader.setAutoTransform(True)
        if size is not None:
            if keep_aspect:
                sz = self._approx_aspect_keep_size(reader, size)
                reader.setScaledSize(sz)
            else:
                reader.setScaledSize(size)
        image = reader.read()
        if image.isNull():
            return None
        return image

    def _approx_aspect_keep_size(self, reader: QtGui.QImageReader, target: QtCore.QSize) -> QtCore.QSize:
        # 原寸が読めない場合もあるため、ヘッダだけ先に読む
        sz = reader.size()
        if not sz.isValid():
            return target  # 情報が無ければそのまま
        tw, th = target.width(), target.height()
        rw, rh = sz.width(), sz.height()
        if rw <= 0 or rh <= 0 or tw <= 0 or th <= 0:
            return target
        # 長辺合わせ
        if rw >= rh:
            scale = tw / rw
        else:
            scale = th / rh
        sw, sh = max(1, int(rw * scale)), max(1, int(rh * scale))
        return QtCore.QSize(sw, sh)

    # --- 変更点2: JPEGはIMREAD_REDUCED_*で軽量デコード ---
    def _imread_flags_for_size(self, ext: str, size: QtCore.QSize | None):
        # 既定
        flags = cv2.IMREAD_UNCHANGED
        if size is None:
            return flags
        if ext in ('.jpg', '.jpeg'):
            # 長辺から粗い縮小率を選ぶ
            try:
                # ファイルヘッダから大きさを取れないので、いったん通常デコードしてしまうのは本末転倒。
                # そこで目安としてターゲットが小さければ強めに縮小。
                longest = max(size.width(), size.height())
                if longest <= 256:
                    flags = cv2.IMREAD_REDUCED_COLOR_8
                elif longest <= 512:
                    flags = cv2.IMREAD_REDUCED_COLOR_4
                elif longest <= 1024:
                    flags = cv2.IMREAD_REDUCED_COLOR_2
                else:
                    flags = cv2.IMREAD_COLOR  # ほぼ原寸
            except Exception:
                pass
        return flags

    # --- 変更点3: QImageコピー削減（numpyバッファを保持） ---
    def _numpy_to_qimage(self, img: np.ndarray) -> QtGui.QImage:
        # 16bit→8bit（内部統一）
        if img.dtype == np.uint16:
            img = (img >> 8).astype(np.uint8)

        if img.ndim == 2:
            buf = np.ascontiguousarray(img)
            q = QtGui.QImage(buf.data, buf.shape[1], buf.shape[0], buf.strides[0],
                             QtGui.QImage.Format_Grayscale8)
            q._buf = buf  # バッファ寿命をQImageと同調
            return q

        if img.ndim == 3:
            h, w, c = img.shape
            if c == 2:
                g, a = cv2.split(img)
                rgb = cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)
                rgba = np.ascontiguousarray(np.dstack([rgb, a]))
                q = QtGui.QImage(rgba.data, w, h, rgba.strides[0],
                                 QtGui.QImage.Format_RGBA8888)
                q._buf = rgba
                return q
            if c == 3:
                # BGR→RGB（ascontiguousでコピー1回のみ）
                rgb = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                q = QtGui.QImage(rgb.data, w, h, rgb.strides[0],
                                 QtGui.QImage.Format_RGB888)
                q._buf = rgb
                return q
            if c == 4:
                rgba = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA))
                q = QtGui.QImage(rgba.data, w, h, rgba.strides[0],
                                 QtGui.QImage.Format_RGBA8888)
                q._buf = rgba
                return q

        raise ValueError('Unsupported image dimensions/channels')

    # --- 変更点4: 分類は据え置き（但しOpenCV優先度をやや上げる） ---
    def _classify_opencv_array(self, arr: np.ndarray, ext: str) -> str:
        if arr is None:
            return 'qt'
        if arr.ndim not in (2, 3):
            return 'qt'
        if arr.dtype in (np.float16, np.float32, np.float64):
            return 'qt'
        if arr.ndim == 3:
            c = arr.shape[2]
            if c not in (2, 3, 4):
                return 'qt'
            if ext in ('.jpg', '.jpeg') and c == 4:
                return 'qt'
            if ext == '.png' and (c == 2 or arr.dtype == np.uint16):
                return 'qt'
        if arr.dtype not in (np.uint8, np.uint16):
            return 'qt'
        return 'opencv'

    def load(self, path, *args, **kwargs):
        return self._load(path, *args, **kwargs)

    def _load(self, path, size: QtCore.QSize | None = None) -> QtGui.QImage | None:
        ext = os.path.splitext(path)[-1].lower()
        try:
            # 1) GIFは既存仕様：Qt + 比率維持
            if ext == '.gif':
                try:
                    with Image.open(path) as im:
                        im.seek(0)
                        if size is not None:
                            im.thumbnail((size.width(), size.height()), Image.LANCZOS)
                        arr = np.array(im.convert('RGBA'))
                        arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGRA)
                        return self._numpy_to_qimage(arr)
                except Exception:
                    return self._qt_read(path, size, keep_aspect=True)

            # 2) OpenCVで先に高速経路を試す
            flags = self._imread_flags_for_size(ext, size)
            try:
                data = np.fromfile(path, dtype=np.uint8)
            except Exception:
                # fromfileが遅い/失敗する環境向けフォールバック
                with open(path, 'rb') as f:
                    data = np.frombuffer(f.read(), dtype=np.uint8)
            arr = cv2.imdecode(data, flags)

            route = self._classify_opencv_array(arr, ext)
            if route != 'opencv':
                # Qt優先（既存仕様：GIF以外はサイズ指定時は比率無視）
                img = self._qt_read(path, size, keep_aspect=False)
                if img is not None:
                    return img
                # Qt失敗 → OpenCV継続

            if arr is None:
                # どちらも失敗気味 → 最終的にQtで再挑戦
                return self._qt_read(path, size, keep_aspect=(ext == '.gif'))

            # 3) 必要な時だけリサイズ（既に近ければスキップ）
            if size is not None:
                h, w = arr.shape[:2]
                if (abs(w - size.width()) + abs(h - size.height())) > 2:
                    interp = cv2.INTER_AREA if (size.width() < w or size.height() < h) else cv2.INTER_LANCZOS4
                    arr = cv2.resize(arr, (size.width(), size.height()), interpolation=interp)

            # 4) NumPy -> QImage（コピー最小化）
            qimg = self._numpy_to_qimage(arr)
            return qimg

        except Exception as e:
            # 最終フォールバック: Qt
            try:
                img = self._qt_read(path, size, keep_aspect=(ext == '.gif'))
                if img is not None:
                    return img
            except Exception:
                pass
            logger.warning(f'[ImageLoader] Failed to load image: {path} ({e})')
            return None
