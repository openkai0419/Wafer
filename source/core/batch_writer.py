import time
import queue
import threading
from .batch_utils import (
    process_image, CHUNK, INITIAL_BATCH_SIZE, BASE_DURATION,
    MAX_BATCH_SIZE, MIN_BATCH_SIZE, executor
)
from ..profiling import init_env
logger, profiler = init_env()

class BatchWriter:
    def __init__(self, db_manager):
        self.db = db_manager
        self.indexer = None

    @profiler.profile
    def batch_process_images(self, batch, file_info):
        results = list(executor.map(lambda p: process_image(p, file_info), batch))
        image_entries, meta_entries, meta_info_entries, failed_entries = [], [], [], []
        for p, aspect, mtime, fsize, ctime, collected_at, meta_info, status in results:
            if status == 'fail':
                failed_entries.append((str(p), mtime, fsize))
                continue
            image_entries.append((str(p), mtime, fsize))
            meta_entries.append((str(p), aspect, mtime, fsize, ctime, collected_at))
            meta_info_entries.extend(meta_info)
        return image_entries, meta_entries, meta_info_entries, failed_entries

    @profiler.profile
    def write_batch_to_db(self, image_entries, meta_entries, meta_info_entries, failed_entries):
        with self.db.conn:
            cur = self.db.conn.cursor()
            if failed_entries:
                cur.executemany("""
                    INSERT INTO images (path, mtime, size, status)
                    VALUES (?, ?, ?, 'fail')
                    ON CONFLICT(path) DO UPDATE SET mtime = excluded.mtime, size = excluded.size, status = 'fail'
                """, failed_entries)
            if image_entries:
                cur.executemany("""
                    INSERT INTO images (path, mtime, size, status)
                    VALUES (?, ?, ?, 'ok')
                    ON CONFLICT(path) DO UPDATE SET mtime = excluded.mtime, size = excluded.size, status = 'ok'
                """, image_entries)
            if meta_entries:
                cur.executemany("""
                    INSERT INTO meta (path, aspect_ratio, mtime, size, created, collected_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        aspect_ratio = excluded.aspect_ratio,
                        mtime = excluded.mtime,
                        size = excluded.size,
                        created = excluded.created,
                        collected_at = excluded.collected_at
                """, meta_entries)
            if meta_info_entries:
                cur.executemany("""
                    INSERT INTO meta_info (path, key, value)
                    VALUES (?, ?, ?)
                    ON CONFLICT(path, key) DO UPDATE SET value = excluded.value
                """, meta_info_entries)
            cur.close()

    @profiler.profile
    def update_meta_and_image(self, paths, file_info):
        total = len(paths)
        batch_size = INITIAL_BATCH_SIZE
        temp_duration = BASE_DURATION
        i = 0
        write_queue = queue.Queue(maxsize=4)

        def writer_thread_func():
            while True:
                item = write_queue.get()
                if item is None:
                    break
                try:
                    img_e, meta_e, info_e, failed_e = item
                    self.write_batch_to_db(img_e, meta_e, info_e, failed_e)
                except Exception as e:
                    logger.error(f"[WriterThread] Error in write_batch_to_db: {e}")
                finally:
                    write_queue.task_done()

        writer_thread = threading.Thread(target=writer_thread_func, daemon=True)
        writer_thread.start()

        while i < total:
            batch = paths[i:i + batch_size]
            t0 = time.monotonic()
            img_e, meta_e, info_e, failed_e = self.batch_process_images(batch, file_info)
            t1 = time.monotonic()
            while True:
                try:
                    write_queue.put_nowait((img_e, meta_e, info_e, failed_e))
                    break
                except queue.Full:
                    temp_duration *= 1.5
                    logger.info(f"[WriterQueue] Full, waiting... {temp_duration}")
                    time.sleep(temp_duration)
            duration = t1 - t0
            if duration < temp_duration:
                batch_size = min(MAX_BATCH_SIZE, int(batch_size * 1.5))
            elif duration > (temp_duration + (temp_duration / 2.0)):
                batch_size = max(MIN_BATCH_SIZE, int(batch_size / 2.0))
            logger.debug(f"temp_duration {temp_duration}, {temp_duration + (temp_duration / 2)}")
            i += len(batch)
            if self.indexer:
                self.indexer._emit_progress(len(batch), 0)
                self.indexer.emit_update()
            logger.info(f"[Adaptive Commit] {i}/{total} processed (batch={batch_size}, {duration:.2f}s)")

        write_queue.join()
        write_queue.put(None)
        writer_thread.join()
