from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from queue import Empty, PriorityQueue
from typing import Callable

from ...utils.logs import AppLogger
from .task import CancelToken, Task, TaskPriority

_QUEUE_POLL_INTERVAL = 1.0
_STOP_PRIORITY = 999


@dataclass
class PeriodicTask:
    name: str
    interval: float
    create_task: Callable[[], Task]
    idle_delay: float = 0.0
    once_per_idle: bool = False
    last_run: float = field(default=0.0)
    _idle_done: bool = field(default=False, repr=False)

    def should_run(self, now: float, idle_duration: float) -> bool:
        if idle_duration < self.idle_delay:
            return False
        if self.once_per_idle and self._idle_done:
            return False
        return (now - self.last_run) >= self.interval


class TaskScheduler:

    def __init__(self):
        self._queue: PriorityQueue[Task] = PriorityQueue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_active_time = time.monotonic()
        self._periodic_tasks: list[PeriodicTask] = []
        self._tokens: set[CancelToken] = set()
        self._tokens_lock = threading.Lock()

    def submit(self, task: Task):
        if task.cancel_token:
            with self._tokens_lock:
                self._tokens.add(task.cancel_token)
        self._queue.put(task)

    def cancel_all(self):
        with self._tokens_lock:
            for token in self._tokens:
                token.cancel()
            self._tokens.clear()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Empty:
                break

    def add_periodic_task(self, periodic: PeriodicTask):
        self._periodic_tasks.append(periodic)

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.submit(Task.create('__stop__', priority=_STOP_PRIORITY, run=lambda: None))
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=10.0)

    def _loop(self):
        while not self._stop.is_set():
            self._check_periodic_tasks()
            try:
                task = self._queue.get(timeout=_QUEUE_POLL_INTERVAL)
            except Empty:
                continue
            if task.name == '__stop__':
                break
            if task.cancel_token and task.cancel_token.is_cancelled:
                continue
            try:
                task.run()
            except Exception as e:
                AppLogger.error(f'[Scheduler] task failed: {task.name}: {e}', exc=e)
            if task.on_complete:
                try:
                    task.on_complete()
                except Exception as e:
                    AppLogger.warning(
                        f'[Scheduler] on_complete failed: {task.name}: {e}', exc=e,
                    )
            if task.priority <= TaskPriority.DISPATCH:
                self._last_active_time = time.monotonic()
                self._reset_once_per_idle_flags()

    def _reset_once_per_idle_flags(self):
        for periodic in self._periodic_tasks:
            if periodic.once_per_idle:
                periodic._idle_done = False

    def _check_periodic_tasks(self):
        now = time.monotonic()
        idle_duration = now - self._last_active_time
        for periodic in self._periodic_tasks:
            if periodic.should_run(now, idle_duration):
                self.submit(periodic.create_task())
                periodic.last_run = now
                if periodic.once_per_idle:
                    periodic._idle_done = True
