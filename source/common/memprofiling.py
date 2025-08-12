# mem_watch.py
from __future__ import annotations
import sys, time, threading, contextlib, gc, tracemalloc
from typing import Any, Iterable, Optional, Dict

try:
    import psutil  # 任意
except Exception:
    psutil = None


# ===== メモリ基礎 =====
def start_tracemalloc(frames: int = 25) -> None:
    if not tracemalloc.is_tracing():
        tracemalloc.start(frames)

def rss_bytes() -> Optional[int]:
    if psutil is None:
        return None
    try:
        return psutil.Process().memory_info().rss
    except Exception:
        return None

def log_mem(prefix: str = "", *, extra: Optional[Dict[str, Any]] = None, logger=None) -> None:
    cur, peak = (tracemalloc.get_traced_memory() if tracemalloc.is_tracing() else (None, None))
    rss = rss_bytes()
    line = f"[MEM]{prefix} RSS={rss} heap={cur} peak={peak}"
    if extra:
        tail = " " + " ".join(f"{k}={v}" for k, v in extra.items())
        line += tail
    (logger.info if logger else print)(line, file=sys.stderr)  # loggerがあればinfoで出す

class _Snap:
    last = None

def take_snap_diff(label: str = "", *, key: str = "lineno", limit: int = 10, logger=None) -> None:
    if not tracemalloc.is_tracing():
        return
    snap = tracemalloc.take_snapshot()
    if _Snap.last is None:
        stats = snap.statistics(key)[:limit]
        head = f"[MEM_SNAP]{label} top {key}"
    else:
        stats = snap.compare_to(_Snap.last, key)[:limit]
        head = f"[MEM_DIFF]{label} top {key}"
    _Snap.last = snap
    (logger.info if logger else print)(head, file=sys.stderr)
    for s in stats:
        (logger.info if logger else print)(f"  {s}", file=sys.stderr)

def malloc_trim_if_possible() -> None:
    # Linuxで断片化を戻せるなら使える（任意）
    try:
        import ctypes
        gc.collect()
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


# ===== Framesサイズ計測 =====
def _len_like(x: Any) -> int:
    # zmq.Frame / bytes / bytearray / memoryview を安全にlen()
    try:
        return len(x)
    except TypeError:
        try:
            return len(memoryview(x))
        except Exception:
            return 0

def frames_size(frames: Iterable[Any]) -> int:
    total = 0
    for f in frames:
        total += _len_like(getattr(f, "buffer", f))  # zmq.Frame.buffer or raw
    return total

def item_size_default(item: Any) -> int:
    # Queueに入る可能性のあるアイテムのサイズ推定
    # - (ident, frames)   -> frames_size(frames)
    # - frames(tuple/list)-> frames_size(frames)
    # - bytes/bytearray   -> len()
    # - sentinel/object   -> 0
    try:
        # (ident, frames)
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], (tuple, list)):
            return frames_size(item[1])
        # framesのみ
        if isinstance(item, (tuple, list)) and item and hasattr(item[0], "__len__"):
            return frames_size(item)
        # bytes系
        return _len_like(item)
    except Exception:
        return 0


# ===== キューメータ =====
class QueueMeter:
    def __init__(self, name: str):
        self.name = name
        self._lock = threading.Lock()
        self.cur_items = 0
        self.cur_bytes = 0
        self.enq_items = 0
        self.enq_bytes = 0
        self.deq_items = 0
        self.deq_bytes = 0
        self.drop_items = 0
        self.drop_bytes = 0

    def on_enqueue(self, size: int) -> None:
        with self._lock:
            self.cur_items += 1
            self.cur_bytes += size
            self.enq_items += 1
            self.enq_bytes += size

    def on_dequeue(self, size: int) -> None:
        with self._lock:
            self.cur_items = max(0, self.cur_items - 1)
            self.cur_bytes = max(0, self.cur_bytes - size)
            self.deq_items += 1
            self.deq_bytes += size

    def on_drop(self, size: int) -> None:
        with self._lock:
            self.drop_items += 1
            self.drop_bytes += size
            # cur_* はもともと減っている（getで捨てる想定）ので弄らない

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return dict(
                name=self.name,
                cur_items=self.cur_items,
                cur_bytes=self.cur_bytes,
                enq_items=self.enq_items,
                enq_bytes=self.enq_bytes,
                deq_items=self.deq_items,
                deq_bytes=self.deq_bytes,
                drop_items=self.drop_items,
                drop_bytes=self.drop_bytes,
            )


# ===== 監視付き put =====
def try_put_monitored(q, item, meter: QueueMeter, *, size_fn=item_size_default) -> bool:
    size = size_fn(item)
    try:
        q.put_nowait(item)
        meter.on_enqueue(size)
        return True
    except Exception:
        # 古い1件をドロップ（latest-wins）
        with contextlib.suppress(Exception):
            old = q.get_nowait()
            meter.on_drop(size_fn(old))
        try:
            q.put_nowait(item)
            meter.on_enqueue(size)
            return True
        except Exception:
            meter.on_drop(size)  # 入れ直しにも失敗
            return False

def force_put_monitored(q, item, meter: QueueMeter, *, size_fn=item_size_default) -> None:
    while not try_put_monitored(q, item, meter, size_fn=size_fn):
        time.sleep(0.001)


# ===== 定期サンプリング =====
class PeriodicSampler:
    def __init__(self, fn, *, interval: float = 5.0, name: str = "sampler"):
        self.fn = fn
        self.interval = interval
        self.name = name
        self._stop = threading.Event()
        self._th: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._th:
            return
        self._th = threading.Thread(target=self._loop, name=self.name, daemon=True)
        self._th.start()

    def stop(self) -> None:
        self._stop.set()
        if self._th:
            self._th.join(timeout=2.0)

    def _loop(self):
        while not self._stop.is_set():
            with contextlib.suppress(Exception):
                self.fn()
            self._stop.wait(self.interval)
