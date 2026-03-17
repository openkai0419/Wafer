from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from queue import Empty, PriorityQueue
from typing import Callable

from ...utils.logs import AppLogger
from .task import Task, TaskPriority

_QUEUE_POLL_INTERVAL = 1.0
_IDLE_THRESHOLD = 5 * 60.0
_STOP_PRIORITY = 999


@dataclass
class PeriodicTask:
    name: str
    interval: float
    create_task: Callable[[], Task]
    idle_only: bool = False
    last_run: float = field(default=0.0)

    def should_run(self, now: float, is_idle: bool) -> bool:
        if self.idle_only and not is_idle:
            return False
        return (now - self.last_run) >= self.interval


class TaskScheduler:

    def __init__(self):
        self._queue: PriorityQueue[Task] = PriorityQueue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_active_time = time.monotonic()
        self._idle_threshold = _IDLE_THRESHOLD
        self._periodic_tasks: list[PeriodicTask] = []

    def submit(self, task: Task):
        self._queue.put(task)

    def add_periodic_task(self, periodic: PeriodicTask):
        self._periodic_tasks.append(periodic)

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.submit(Task.create('__stop__', priority=_STOP_PRIORITY, run=lambda: None))
        if self._thread:
            self._thread.join(timeout=10.0)
        self._stop.set()

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
            if task.priority <= TaskPriority.SCAN:
                self._last_active_time = time.monotonic()

    def _check_periodic_tasks(self):
        now = time.monotonic()
        is_idle = (now - self._last_active_time) >= self._idle_threshold
        for periodic in self._periodic_tasks:
            if periodic.should_run(now, is_idle):
                self.submit(periodic.create_task())
                periodic.last_run = now
